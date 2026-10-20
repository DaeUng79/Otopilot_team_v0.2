"""Regenerating criteria keeps the current review while creating a new one."""

import sys
import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.project_documents import _initialize
from app.documents import criteria_approval, rfp_api
from app.documents.hwpx_storage import connect


class CriteriaRegenerationTest(unittest.TestCase):
    def test_source_page_matches_each_scored_paragraph(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE blocks (document_id TEXT,revision TEXT,type TEXT,block_id TEXT,text TEXT,physical_page_numbers_json TEXT,order_index INTEGER)")
        for order, (title, page) in enumerate((("대상사업의 이해도", 41), ("사업추진전략의 창의성, 타당성", 42))):
            db.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?)",
                       ("rfp", "rev", "paragraph", f"p{order}", f"∘ {title} (5점)", json.dumps([page]), order))
        row = {"row_id": "R01", "evaluation_item":
               "∘ 대상사업의 이해도 (5점) ∘ 사업추진전략의 창의성, 타당성 (5점) ∘ 적용기술의 확장성, 실현가능성 (5점)", "score": 15}
        items = criteria_approval._rows_with_source_pages(
            db, {"document_id": "rfp", "parse_revision": "rev"}, [row])
        self.assertEqual([item.get("source_page") for item in items], [41, 42, None])
        self.assertEqual([item.get("source_block_id") for item in items], ["p0", "p1", None])
        db.close()

    def test_scored_bullets_become_separate_review_items(self):
        row = {"row_id": "R01", "evaluation_division": "전략 및 방법론",
               "evaluation_item": "∘ 대상사업의 이해도 (5점) ∘ 사업추진전략의 창의성, 타당성 (5점) ∘ 적용기술의 확장성, 실현가능성 (5점)",
               "evaluation_criteria": "사업 계획을 평가합니다.", "evaluation_elements": ["계획"], "score": 15}
        split = criteria_approval.split_scored_rows([row])
        self.assertEqual([item["evaluation_item"] for item in split], [
            "대상사업의 이해도", "사업추진전략의 창의성, 타당성", "적용기술의 확장성, 실현가능성"])
        self.assertEqual([item["score"] for item in split], [5, 5, 5])
        self.assertEqual([item["row_id"] for item in split], ["R01-01", "R01-02", "R01-03"])
        items = criteria_approval._items_from_ai([row], None)
        self.assertEqual([item["code"] for item in items], ["1", "1.1", "1.2", "1.3"])
        self.assertEqual([item["max_score"] for item in items], [0, 5, 5, 5])

    def test_mismatched_detail_scores_keep_original_row(self):
        row = {"evaluation_item": "∘ 이해도 (5점) ∘ 전략 (5점)", "score": 15}
        self.assertEqual(criteria_approval.split_scored_rows([row]), [row])

    def test_force_reaches_generator_without_reextracting_requirements(self):
        with patch.object(rfp_api, "latest_rfp", return_value={"revision": 1, "document_id": "rfp"}), \
             patch.object(rfp_api.requirements, "load_saved_requirements", return_value={"details": []}), \
             patch.object(rfp_api, "criteria_status", return_value={"status": "done"}), \
             patch.object(rfp_api, "_set_job") as set_job, \
             patch.object(rfp_api, "_queue") as queue:
            rfp_api.queue_pipeline(Path("unused"), "project", force=True)
            self.assertEqual(set_job.call_args.args[1], "criteria_jobs")
            worker = queue.call_args.args[-1]
            self.assertTrue(worker.keywords["force"])

        with patch.object(rfp_api, "_set_job"), \
             patch.object(rfp_api.criteria, "extract_and_save_criteria") as generate:
            rfp_api._run_criteria(Path("unused"), "project", 1, "rfp", force=True)
            generate.assert_called_once_with("rfp", db_path=Path("unused"), force=True)

    def test_new_ai_review_preserves_previous_working_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "documents.sqlite3"
            _initialize(database)
            criteria_approval.initialize(database)
            with connect(database) as db:
                db.execute("INSERT INTO projects VALUES (?,?,?)", ("project", "시험 사업", "now"))
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                           ("rfp", "rfp.hwpx", "hash", "rev", "now", "now"))
                db.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                           ("rfp", "rev", "parser", "schema", "{}", "now"))
                db.execute("INSERT INTO project_rfp_uploads VALUES (?,?,?,?,?,?,?,?,?)",
                           ("project", 1, "rfp", "rfp.hwpx", 1, "now", 1, 0, 0))
                db.execute("INSERT INTO rfp_snapshot_bindings VALUES (?,?,?,?,?,?)",
                           ("project", 1, "rfp", "rev", "now", "upload"))

            first = criteria_approval.open_draft(
                database, project_id="project", source="template", ai_result=None, actor_id="admin")
            ai = {"rows": [{"evaluation_division": "수행", "evaluation_item": "계획",
                            "evaluation_criteria": "계획의 적절성", "score": 80}],
                  "total_score": 80, "_id": "generated"}
            with self.assertRaisesRegex(criteria_approval.CriteriaApprovalError, "AI 초안 반영"):
                criteria_approval.open_draft(
                    database, project_id="project", source="ai", ai_result=ai, actor_id="admin")
            second = criteria_approval.open_draft(
                database, project_id="project", source="ai", ai_result=ai,
                actor_id="admin", restart=True)
            versions = criteria_approval.list_versions(database, "project")
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual([version["status"] for version in versions], ["RETIRED", "DRAFT"])
            self.assertEqual(versions[0]["items"][0]["title"], "사업 이해도")
            self.assertEqual(versions[1]["items"][1]["title"], "계획")


if __name__ == "__main__":
    unittest.main()
