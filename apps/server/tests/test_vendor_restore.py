"""Deleted vendors cannot restore old proposal data under the same name."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin.project_service import archive_vendor, create_project, save_vendor
from app.committee.committee_app.v2_web_demo import local_runtime
from app.documents import proposal_document_adapter as proposals
from app.documents.step5_ai_proposal_analysis import SCHEMA as ANALYSIS_SCHEMA
from app.shared.db import Actor, Store
from app.shared.demo_data import seed
from app.shared.sync_service import deliver_outbox


class VendorDeleteTest(unittest.TestCase):
    def test_deleting_vendor_removes_proposal_and_new_registration_gets_new_id(self):
        with tempfile.TemporaryDirectory(prefix="simsa-vendor-delete-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            documents = root / "documents.sqlite3"
            store.documents_path = documents
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            actor = Actor("super-demo", "SUPER_ADMIN")

            def action(name, body, handler):
                return store.transact(actor, name, body, str(uuid4()), handler, database="admin")

            project = action("PRJ-02", {
                "department_id": "web-demo-dept", "name": "업체 삭제 시험",
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
            deliver_outbox(store)

            proposals.initialize(documents)
            with proposals.connect(documents) as db:
                db.executescript(ANALYSIS_SCHEMA)
                db.execute("INSERT INTO projects VALUES (?,?,?)",
                           (project_id, "업체 삭제 시험", "now"))
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                           ("old-doc", "old.pdf", "old-hash", "old-parse", "now", "now"))
                db.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                           ("old-doc", "old-parse", "test", "test", "{}", "now"))
                db.execute("INSERT INTO source_files VALUES (?,?,?,?)",
                           ("old-hash", "old.pdf", 1, b"x"))
                db.execute("INSERT INTO project_proposal_uploads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("old-upload", "now", "now", 1, project_id, original["id"], 1,
                            "old-doc", "old-parse", "PDF", "old.pdf", actor.id, "READY", None))
                db.execute("INSERT INTO proposal_analysis_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           ("run", project_id, "old-upload", "rfp-result", "old-doc", "old-parse",
                            "processor", "model", "complete", "now", "{}"))
                db.execute("INSERT INTO proposal_analysis_items VALUES (?,?,?,?)",
                           ("run", "FUN-1", "{}", "now"))
            with store.connect(write=True) as db:
                db.execute("INSERT INTO ref_proposal_uploads "
                           "(id,source_version,snapshot_sha256,synced_at,is_deleted,project_id,"
                           "vendor_id,upload_revision,document_id,parse_revision,format,status) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("old-upload", 1, "hash", "now", 0, project_id, original["id"],
                            1, "old-doc", "old-parse", "PDF", "READY"))

            action("PRJ-07", {"project_id": project_id, "vendor_id": original["id"],
                              "version": original["version"]}, archive_vendor)
            with store.connect("admin") as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM project_vendors WHERE id=?",
                                            (original["id"],)).fetchone()[0], 0)
            with store.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM ref_project_vendors WHERE id=?",
                                            (original["id"],)).fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM ref_proposal_uploads WHERE vendor_id=?",
                                            (original["id"],)).fetchone()[0], 0)
            with proposals.connect(documents) as db:
                for table in ("project_proposal_uploads", "proposal_analysis_results",
                              "proposal_analysis_items", "documents", "parse_snapshots", "source_files"):
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

            replacement = action("PRJ-06", {
                "project_id": project_id, "display_code": "A사",
                "legal_name": "씨에스리", "sort_order": 1,
            }, save_vendor)
            self.assertNotEqual(replacement["id"], original["id"])
            self.assertEqual(replacement["display_code"], "A사")


if __name__ == "__main__":
    unittest.main()
