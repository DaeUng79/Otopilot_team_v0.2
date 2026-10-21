"""The comparison table accepts requirement IDs produced by the extractor."""

import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.documents.step5_ai_proposal_analysis import comparison_overview, extract_requirements


class ProposalComparisonFormatsTest(unittest.TestCase):
    def test_comparison_includes_saved_business_status(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "documents.sqlite3"
            status = {"current_status": [{"text": "현황 내용"}],
                      "background_and_need": [{"text": "필요성 내용"}],
                      "scope": [{"text": "범위 내용"}]}
            blocks = [{"block_id": "table", "type": "table", "table": {"cells": [
                [{"child_block_ids": ["label-code"]}, {"child_block_ids": ["value-code"]}],
                [{"child_block_ids": ["label-category"]}, {"child_block_ids": ["value-category"]}],
                [{"child_block_ids": ["label-title"]}, {"child_block_ids": ["value-title"]}],
            ]}}]
            blocks += [{"block_id": key, "text": value} for key, value in (
                ("label-code", "요구사항 번호"), ("value-code", "FUN-1"),
                ("label-category", "요구사항 분류"), ("value-category", "기능"),
                ("label-title", "요구사항 명칭"), ("value-title", "업무 분석"))]
            result = {"business_status": status,
                      "details": {"block_ids": ["table"], "blocks": blocks},
                      "validation": {"list_codes": [], "detail_codes": ["FUN-1"]}}
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE project_rfp_uploads
                      (project_id TEXT, revision INTEGER, document_id TEXT);
                    CREATE TABLE documents (document_id TEXT, active_revision TEXT);
                    CREATE TABLE requirement_results
                      (document_id TEXT, source_revision TEXT, result_id TEXT,
                       result_json TEXT, status TEXT, created_at TEXT);
                    CREATE TABLE project_proposal_uploads
                      (id TEXT, project_id TEXT, vendor_id TEXT, document_id TEXT,
                       parse_revision TEXT, filename TEXT, upload_revision INTEGER, status TEXT);
                    INSERT INTO project_rfp_uploads VALUES ('project', 1, 'rfp');
                    INSERT INTO documents VALUES ('rfp', 'parse');
                """)
                connection.execute("INSERT INTO requirement_results VALUES (?,?,?,?,?,?)",
                                   ("rfp", "parse", "result", json.dumps(result),
                                    "complete", "now"))
            overview = comparison_overview(database, "project")
            self.assertEqual(overview["status"], "ready")
            self.assertEqual(overview["business_status"], status)
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE requirement_jobs "
                                   "(project_id TEXT, revision INTEGER, status TEXT)")
                connection.execute("INSERT INTO requirement_jobs VALUES ('project',1,'running')")
            self.assertEqual(comparison_overview(database, "project")["status"],
                             "waiting_for_requirements")
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE requirement_jobs SET status='done'")
                connection.execute("UPDATE requirement_results SET result_json=?",
                                   (json.dumps(result | {"extractor_version": "requirements-sqlite-v5"}),))
            self.assertEqual(comparison_overview(database, "project")["status"],
                             "waiting_for_requirements")

    def test_requirement_number_with_short_code(self):
        pairs = [("요구사항 분류", "기능 요구사항"), ("요구사항 번호", "FUN-1"),
                 ("요구사항 명칭", "업무 분석"), ("요구사항 상세설명", "분석 범위"),
                 ("세부내용", "세부 작업")]
        blocks = [{"block_id": "table", "type": "table", "table": {"cells": []}}]
        for index, (label, value) in enumerate(pairs):
            label_id, value_id = f"label-{index}", f"value-{index}"
            blocks[0]["table"]["cells"].append(
                [{"child_block_ids": [label_id]}, {"child_block_ids": [value_id]}])
            blocks.extend([{"block_id": label_id, "text": label},
                           {"block_id": value_id, "text": value}])
        result = {"details": {"block_ids": ["table"], "blocks": blocks},
                  "validation": {"list_codes": ["FUN-1"]}}

        requirements = extract_requirements(result)

        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["code"], "FUN-1")
        self.assertIn("요구사항상세설명: 분석 범위", requirements[0]["rfp_detail"])
        self.assertIn("세부내용: 세부 작업", requirements[0]["rfp_detail"])


if __name__ == "__main__":
    unittest.main()
