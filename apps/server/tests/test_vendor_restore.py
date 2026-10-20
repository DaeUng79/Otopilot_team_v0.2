"""Re-registering an archived vendor keeps its identity and proposal history."""

import asyncio
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin.project_service import archive_vendor, create_project, save_vendor
from app.committee.committee_app.v2_web_demo import local_runtime
from app.documents import proposal_document_adapter as proposals
from app.shared.db import Actor, Store
from app.shared.demo_data import seed


class VendorRestoreTest(unittest.TestCase):
    def test_same_name_restores_vendor_and_next_proposal_revision(self):
        with tempfile.TemporaryDirectory(prefix="simsa-vendor-restore-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            actor = Actor("super-demo", "SUPER_ADMIN")

            def action(name, body, handler):
                return store.transact(actor, name, body, str(uuid4()), handler, database="admin")

            project = action("PRJ-02", {
                "department_id": "web-demo-dept", "name": "업체 복원 시험",
                "contact_organization": "시험 기관", "contact_department": "시험 부서",
                "contact_position": "주무관", "contact_name": "홍길동",
                "contact_phone": "010-1234-5678", "contact_email": "test@example.org",
                "evaluation_date": "2026-11-01",
            }, create_project)
            project_id = project["id"]
            original = action("PRJ-06", {
                "project_id": project_id, "display_code": "A사",
                "legal_name": "씨에스리", "sort_order": 1,
            }, save_vendor)
            action("PRJ-07", {
                "project_id": project_id, "vendor_id": original["id"],
                "version": original["version"],
            }, archive_vendor)
            restored = action("PRJ-06", {
                "project_id": project_id, "display_code": "B사",
                "legal_name": "씨에스리", "sort_order": 1,
            }, save_vendor)
            self.assertEqual(restored["id"], original["id"])
            self.assertEqual(restored["display_code"], "A사")
            self.assertTrue(restored["restored"])
            self.assertEqual(restored["active"], 1)
            self.assertIsNone(restored["deleted_at"])
            self.assertIsNone(restored["deleted_by"])
            with store.connect("admin") as connection:
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM project_vendors WHERE project_id=? AND legal_name=?",
                    (project_id, "씨에스리"),
                ).fetchone()[0], 1)

            documents = root / "documents.sqlite3"
            proposals.initialize(documents)
            with proposals.connect(documents) as connection:
                connection.execute("INSERT INTO projects VALUES (?,?,?)",
                                   (project_id, "업체 복원 시험", "now"))
                connection.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                                   ("old-doc", "old.pdf", "old-hash", "old-parse", "now", "now"))
                connection.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                                   ("old-doc", "old-parse", "test", "test", "{}", "now"))
                connection.execute(
                    "INSERT INTO project_proposal_uploads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("old-upload", "now", "now", 1, project_id, original["id"], 1,
                     "old-doc", "old-parse", "PDF", "old.pdf", actor.id, "ARCHIVED", "교체"),
                )

            def save_new(_parsed, _db_path, *, source_path, project_id, project_name):
                with proposals.connect(documents) as connection:
                    connection.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                                       ("new-doc", source_path.name, "new-hash", "new-parse", "now", "now"))
                    connection.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                                       ("new-doc", "new-parse", "test", "test", "{}", "now"))
                return {"document_id": "new-doc", "revision": "new-parse",
                        "pages": 1, "blocks": 1}

            with patch.object(proposals, "parse_proposal", return_value={"warnings": []}), \
                 patch.object(proposals, "save_to_sqlite", side_effect=save_new):
                upload = proposals.register_proposal(
                    documents, project_id=project_id, project_name="업체 복원 시험",
                    vendor_id=restored["id"], filename="new.pdf", data=b"%PDF-test",
                    uploaded_by=actor.id,
                )
            self.assertEqual(upload["upload_revision"], 2)
            self.assertEqual(upload["status"], "READY")
            with proposals.connect(documents) as connection:
                self.assertEqual(connection.execute(
                    "SELECT status FROM project_proposal_uploads WHERE id='old-upload'"
                ).fetchone()[0], "ARCHIVED")


if __name__ == "__main__":
    unittest.main()
