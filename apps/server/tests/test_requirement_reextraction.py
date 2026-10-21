"""A repeated RFP upload and the manual retry must run extraction again."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.project_documents import _initialize
from app.documents import rfp_api
from app.documents.hwpx_storage import connect


class RequirementReextractionTest(unittest.TestCase):
    def test_reuploaded_same_document_queues_new_revision_and_forces_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "documents.sqlite3"
            _initialize(database)
            with connect(database) as db:
                db.execute("INSERT INTO projects VALUES (?,?,?)", ("project", "시험 사업", "now"))
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                           ("rfp", "rfp.hwpx", "rfp", "parse-rev", "now", "now"))
                db.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                           ("rfp", "parse-rev", "parser", "schema", "{}", "now"))
                for revision in (1, 2):
                    db.execute("INSERT INTO project_rfp_uploads VALUES (?,?,?,?,?,?,?,?,?)",
                               ("project", revision, "rfp", "rfp.hwpx", 1, "now", 1, 0, 0))
                    db.execute("INSERT INTO rfp_snapshot_bindings VALUES (?,?,?,?,?,?)",
                               ("project", revision, "rfp", "parse-rev", "now", "upload"))
            with patch.object(rfp_api.EXTRACTOR, "submit") as submit, \
                 patch.object(rfp_api.requirements, "load_saved_requirements", return_value={"details": []}):
                first = rfp_api.queue_requirements(database, "project", force=True)
                self.assertEqual(first["status"], "queued")
                self.assertEqual(first["revision"], 2)
                worker = submit.call_args.args[0]
                with patch.object(rfp_api.requirements, "extract_and_save_requirements") as extract:
                    worker(*submit.call_args.args[1:])
                    extract.assert_called_once_with(database, "rfp", force=True)
                self.assertEqual(rfp_api.requirement_status(database, "project")["status"], "done")

                second = rfp_api.queue_requirements(database, "project", force=True)
                self.assertEqual(second["status"], "queued")
                self.assertEqual(submit.call_count, 2)

    def test_running_job_is_not_requeued(self):
        with patch.object(rfp_api, "latest_rfp", return_value={"revision": 1, "document_id": "rfp"}), \
             patch.object(rfp_api, "_open") as opened, \
             patch.object(rfp_api, "requirement_status", return_value={"status": "running"}) as status, \
             patch.object(rfp_api, "_set_job") as set_job, \
             patch.object(rfp_api, "_queue") as queue:
            opened.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (1,)
            result = rfp_api.queue_requirements(Path("unused"), "project", force=True)
            self.assertEqual(result["status"], "running")
            status.assert_called_once()
            set_job.assert_not_called()
            queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
