"""An unconfirmed shortlist may be superseded without losing its audit record."""

import asyncio
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.committee import committee_roster, committee_selection
from app.committee.committee_app.v2_core import Context, ModuleError
from app.committee.committee_app.v2_web_demo import local_runtime, seed_demo


class RedrawBeforeRosterTest(unittest.TestCase):
    def test_cancel_and_redraw_preserves_prior_draw(self):
        with tempfile.TemporaryDirectory(prefix="simsa-redraw-") as directory:
            runtime, _ = local_runtime(Path(directory))
            asyncio.run(seed_demo(runtime))
            ctx = lambda: Context("web-demo-admin", str(uuid4()))
            command = {
                "project_id": "p1", "selection_mode": "POOL_RANDOM",
                "target_count": 7, "reserve_count": 1,
                "quotas": [
                    {"specialty_id": "AI", "final_count": 3},
                    {"specialty_id": "SEC", "final_count": 3},
                    {"specialty_id": "SYS", "final_count": 1},
                ],
            }
            rule = asyncio.run(committee_selection.save_rules(ctx(), command | {"version": 0}, runtime=runtime))
            first = asyncio.run(committee_selection.draw_shortlist(
                ctx(), {"project_id": "p1", "rule_version": rule["version"]}, runtime=runtime))
            with self.assertRaises(ModuleError):
                asyncio.run(committee_selection.save_rules(
                    ctx(), command | {"version": rule["version"]}, runtime=runtime))
            revised = asyncio.run(committee_selection.save_rules(
                ctx(), command | {"version": rule["version"], "clear_nominees": True}, runtime=runtime))
            second = asyncio.run(committee_selection.draw_shortlist(
                ctx(), {"project_id": "p1", "rule_version": revised["version"]}, runtime=runtime))
            nominee_id = second["members"][0]["nominee_id"]
            excluded = asyncio.run(committee_roster.exclude_nominee(
                ctx(), {"project_id": "p1", "nominee_id": nominee_id, "version": 1,
                        "reason": "연락 불가"}, runtime=runtime))
            restored = asyncio.run(committee_roster.exclude_nominee(
                ctx(), {"project_id": "p1", "nominee_id": nominee_id,
                        "version": excluded["version"], "reason": None}, runtime=runtime))
            with runtime.connect() as conn:
                draws = conn.execute(
                    "SELECT id,revision_no,status FROM committee_draws WHERE project_id='p1' ORDER BY revision_no"
                ).fetchall()
                nominees = conn.execute("SELECT COUNT(*) FROM project_nominees WHERE project_id='p1'").fetchone()[0]
            self.assertEqual([(r["id"], r["revision_no"], r["status"]) for r in draws],
                             [(first["id"], 1, "SUPERSEDED"), (second["id"], 2, "CONFIRMED")])
            self.assertEqual(nominees, len(second["members"]))
            self.assertIsNone(restored["exclusion_reason"])
            with runtime.connect(write=True) as conn:
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("UPDATE committee_draws SET pool_sha256='changed' WHERE id=?", (first["id"],))


if __name__ == "__main__":
    unittest.main()
