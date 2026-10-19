"""Regression checks for document archive state across document and evaluation DBs."""

import asyncio
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.project_documents import _latest_uploads
from app.committee.committee_app.v2_core import digest
from app.committee.committee_app.v2_web_demo import local_runtime
from app.documents.document_gateway import archive_upload
from app.documents.rfp_api import latest_rfp
from app.shared.db import Store
from app.shared.demo_data import seed
from app.shared.integration_contracts import apply_event


class DocumentArchiveSyncTest(unittest.TestCase):
    def test_proposal_archive_reaches_evaluation_projection(self):
        with tempfile.TemporaryDirectory(prefix="simsa-proposal-test-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            proposal_id = str(uuid4())
            payload = {
                "proposal_upload_id": proposal_id,
                "project_id": "demo-evaluation",
                "vendor_id": "demo-vendor-0",
                "upload_revision": 2,
                "document_id": "test-document",
                "parse_revision": "test-parse",
                "format": "PDF",
                "status": "READY",
            }

            def deliver(contract, version, body):
                return apply_event(store, {
                    "event_id": str(uuid4()), "contract_name": contract,
                    "schema_version": 2, "aggregate_id": proposal_id,
                    "aggregate_version": version, "payload": body,
                    "payload_sha256": digest(body),
                }, "documents")

            self.assertEqual(deliver("proposal.ready", 1, payload)["status"], "APPLIED")
            self.assertEqual(deliver("proposal.archived", 2, payload | {"status": "ARCHIVED"})["status"], "APPLIED")
            with store.connect() as db:
                row = db.execute(
                    "SELECT status,source_version FROM ref_proposal_uploads WHERE id=?", (proposal_id,)
                ).fetchone()
                self.assertEqual(tuple(row), ("ARCHIVED", 2))

    def test_archived_rfp_is_not_the_current_document(self):
        with tempfile.TemporaryDirectory(prefix="simsa-rfp-test-") as directory:
            db_path = Path(directory) / "documents.sqlite3"
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript("""
                    CREATE TABLE project_rfp_uploads (
                        project_id TEXT, revision INTEGER, document_id TEXT,
                        filename TEXT, byte_size INTEGER, uploaded_at TEXT,
                        page_count INTEGER, block_count INTEGER, warning_count INTEGER,
                        PRIMARY KEY(project_id, revision));
                    CREATE TABLE rfp_snapshot_bindings (
                        project_id TEXT, upload_revision INTEGER,
                        document_id TEXT, parse_revision TEXT);
                """)
                db.executemany(
                    "INSERT INTO project_rfp_uploads VALUES (?,?,?,?,?,?,?,?,?)",
                    [("project", n, f"doc-{n}", f"{n}.hwpx", 1, "now", 1, 1, 0)
                     for n in (1, 2)],
                )
                db.commit()
            self.assertEqual(latest_rfp(db_path, "project")["revision"], 2)
            archive_upload(db_path, "project", reason="test", actor_id="tester", upload_revision=2)
            self.assertEqual(latest_rfp(db_path, "project")["revision"], 1)
            self.assertEqual(_latest_uploads(db_path)[0]["revision"], 1)
            archive_upload(db_path, "project", reason="test", actor_id="tester", upload_revision=1)
            self.assertIsNone(latest_rfp(db_path, "project"))
            self.assertEqual(_latest_uploads(db_path), [])


if __name__ == "__main__":
    unittest.main()
