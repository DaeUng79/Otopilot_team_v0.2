"""Repeated RFP codes are reviewed and normalized without changing source blocks."""

import unittest
from unittest.mock import patch

from apps.documents import step3_ai_requirements_extract_to_SQLite as step3
from apps.documents.step5_ai_proposal_analysis import extract_requirements


def fixture(second_detail="검색 결과 저장"):
    blocks = []
    roots = []
    for number, detail in enumerate(("검색 기능 제공", second_detail), 1):
        table_id = f"table-{number}"
        roots.append(table_id)
        table = {"block_id": table_id, "type": "table", "physical_page_number": number,
                 "table": {"cells": []}}
        blocks.append(table)
        for row, (label, value) in enumerate((
                ("요구사항 분류", "기능"), ("요구사항 번호", "FUN-1"),
                ("요구사항 명칭", "검색"), ("요구사항 상세설명", detail))):
            label_id, value_id = f"l-{number}-{row}", f"v-{number}-{row}"
            table["table"]["cells"].append([
                {"row": row, "col": 0, "text": label, "child_block_ids": [label_id]},
                {"row": row, "col": 1, "text": value, "child_block_ids": [value_id]}])
            blocks.extend([
                {"block_id": label_id, "type": "paragraph", "parent_block_id": table_id,
                 "text": label},
                {"block_id": value_id, "type": "paragraph", "parent_block_id": table_id,
                 "text": value}])
    return {"blocks": blocks}, {"block_ids": roots, "blocks": blocks}


class DuplicateRequirementCodesTest(unittest.TestCase):
    def test_unique_codes_skip_extra_ai_call(self):
        document, details = fixture()
        details["block_ids"] = details["block_ids"][:1]
        with patch.object(step3, "_response") as response:
            decisions, usage = step3._resolve_duplicate_codes(None, document, details, "model")
        self.assertEqual(decisions, [])
        self.assertEqual(usage["total_tokens"], 0)
        response.assert_not_called()

    def test_ai_merges_distinct_content_under_same_code(self):
        document, details = fixture()
        with patch.object(step3, "_response", return_value=(
                {"action": "merge", "keep_index": 0, "reason": "서로 다른 기능"},
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})):
            decisions, _ = step3._resolve_duplicate_codes(None, document, details, "model")
        self.assertEqual(decisions[0]["action"], "merge")
        result = {"details": details, "duplicate_code_resolutions": decisions,
                  "validation": {"list_codes": ["FUN-1"]}}
        requirements = extract_requirements(result)
        self.assertEqual(len(requirements), 1)
        self.assertIn("검색 기능 제공", requirements[0]["rfp_detail"])
        self.assertIn("검색 결과 저장", requirements[0]["rfp_detail"])
        self.assertEqual(len(details["block_ids"]), 2)

    def test_identical_content_keeps_one_item(self):
        document, details = fixture("검색 기능 제공")
        with patch.object(step3, "_response", return_value=(
                {"action": "remove_duplicate", "keep_index": 0, "reason": "같은 내용"},
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})):
            decisions, _ = step3._resolve_duplicate_codes(None, document, details, "model")
        requirements = extract_requirements({
            "details": details, "duplicate_code_resolutions": decisions,
            "validation": {"list_codes": ["FUN-1"]}})
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["rfp_detail"].count("검색 기능 제공"), 1)

    def test_missing_decision_does_not_silently_drop_content(self):
        _, details = fixture()
        with self.assertRaisesRegex(ValueError, "정리 결과가 없습니다"):
            extract_requirements({"details": details, "validation": {"list_codes": ["FUN-1"]}})


if __name__ == "__main__":
    unittest.main()
