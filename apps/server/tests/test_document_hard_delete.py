"""Deleting an upload removes its data while retaining a shared source."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.project_documents import _initialize
from app.documents.document_gateway import delete_upload
from app.documents.hwpx_storage import connect
from app.documents.proposal_document_adapter import initialize as initialize_proposals
from app.documents.step5_ai_proposal_analysis import SCHEMA as ANALYSIS_SCHEMA
from app.documents.step3_ai_requirements_extract_to_SQLite import SCHEMA as REQUIREMENT_SCHEMA


class DocumentHardDeleteTest(unittest.TestCase):
    def test_deleting_rfp_removes_its_requirements_and_proposal_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.sqlite3"
            _initialize(path)
            initialize_proposals(path)
            with connect(path) as db:
                db.executescript(REQUIREMENT_SCHEMA + ANALYSIS_SCHEMA)
                db.execute("INSERT INTO projects VALUES (?,?,?)", ("project", "사업", "now"))
                for document_id in ("rfp", "proposal-doc"):
                    db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                               (document_id, "file.hwpx", document_id, "parse", "now", "now"))
                    db.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                               (document_id, "parse", "parser", "schema", "{}", "now"))
                    db.execute("INSERT INTO source_files VALUES (?,?,?,?)",
                               (document_id, "file.hwpx", 1, b"x"))
                db.execute("INSERT INTO project_rfp_uploads VALUES (?,?,?,?,?,?,?,?,?)",
                           ("project", 1, "rfp", "rfp.hwpx", 1, "now", 1, 0, 0))
                db.execute("INSERT INTO rfp_snapshot_bindings VALUES (?,?,?,?,?,?)",
                           ("project", 1, "rfp", "parse", "now", "upload"))
                db.execute("INSERT INTO project_proposal_uploads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("proposal", "now", "now", 1, "project", "vendor", 1,
                            "proposal-doc", "parse", "HWPX", "proposal.hwpx", "user", "READY", None))
                db.execute("INSERT INTO requirement_results VALUES (?,?,?,?,?,?,?,?,?)",
                           ("result", "rfp", "parse", "v", "model", "hash", "complete", "now", "{}"))
                db.execute("INSERT INTO proposal_analysis_items VALUES (?,?,?,?)",
                           ("run", "FUN-1", "{}", "now"))
                db.execute("INSERT INTO proposal_analysis_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           ("run", "project", "proposal", "result", "proposal-doc", "parse",
                            "processor", "model", "complete", "now", "{}"))
            delete_upload(path, "project", upload_revision=1)
            with connect(path) as db:
                for table in ("project_rfp_uploads", "requirement_results",
                              "proposal_analysis_results", "proposal_analysis_items"):
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM project_proposal_uploads").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM source_files").fetchone()[0], 1)

    def test_shared_file_survives_until_last_registration_is_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.sqlite3"
            _initialize(path)
            initialize_proposals(path)
            with connect(path) as db:
                db.executescript(ANALYSIS_SCHEMA)
                db.execute("INSERT INTO projects VALUES (?,?,?)", ("project", "사업", "now"))
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                           ("hash", "a.hwpx", "hash", "parse", "now", "now"))
                db.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                           ("hash", "parse", "parser", "schema", "{}", "now"))
                db.execute("INSERT INTO source_files VALUES (?,?,?,?)",
                           ("hash", "a.hwpx", 2, b"ab"))
                db.execute("INSERT INTO project_documents VALUES (?,?,?)", ("project", "hash", "now"))
                db.execute("INSERT INTO project_rfp_uploads VALUES (?,?,?,?,?,?,?,?,?)",
                           ("project", 1, "hash", "a.hwpx", 2, "now", 1, 0, 0))
                db.execute("INSERT INTO rfp_snapshot_bindings VALUES (?,?,?,?,?,?)",
                           ("project", 1, "hash", "parse", "now", "upload"))
                db.execute("INSERT INTO project_proposal_uploads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("proposal", "now", "now", 1, "project", "vendor", 1,
                            "hash", "parse", "HWPX", "a.hwpx", "user", "READY", None))
                db.execute("INSERT INTO proposal_analysis_items VALUES (?,?,?,?)",
                           ("run", "FUN-1", "{}", "now"))
                db.execute("INSERT INTO proposal_analysis_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           ("run", "project", "proposal", "result", "hash", "parse",
                            "processor", "model", "complete", "now", "{}"))
            deleted = delete_upload(path, "project", proposal_upload_id="proposal")
            self.assertTrue(deleted["shared_source_retained"])
            with connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM source_files").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM project_proposal_uploads").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM proposal_analysis_results").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM proposal_analysis_items").fetchone()[0], 0)
            deleted = delete_upload(path, "project", upload_revision=1)
            self.assertFalse(deleted["shared_source_retained"])
            with connect(path) as db:
                for table in ("project_rfp_uploads", "rfp_snapshot_bindings", "documents",
                              "parse_snapshots", "source_files", "project_documents"):
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
