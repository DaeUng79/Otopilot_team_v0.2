"""The evaluator summary keeps proposal IDs and excludes grading claims."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[2] / "documents/proposal_item_summary.py"
SPEC = importlib.util.spec_from_file_location("proposal_item_summary_test", PATH)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


class ProposalItemSummaryTest(unittest.TestCase):
    def test_two_to_four_proposals_keep_ids_and_bound_input(self):
        for count in (2, 3, 4):
            with self.subTest(count=count):
                summary._summarize_cached.cache_clear()
                captured = []

                def create(**kwargs):
                    payload = json.loads(kwargs["messages"][1]["content"])
                    captured.append(payload)
                    values = {p["id"]: f"{p['id']} 제안 내용" for p in payload["proposals"]}
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                        content=json.dumps({"summaries": values}, ensure_ascii=False)))])

                client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                proposals = [{"id": f"p{i}", "evidence": [{"page": i + 1, "text": "근거" * 800}]}
                             for i in range(count)]
                with patch.object(summary, "_client", return_value=client):
                    result = summary.summarize_item("평가항목", "평가기준", proposals)
                    self.assertEqual(len(result), count)
                    self.assertTrue(all(len(p["evidence"][0]["text"]) <= 1200
                                        for p in captured[0]["proposals"]))
                    summary.summarize_item("평가항목", "평가기준", proposals)
                    self.assertEqual(len(captured), 1)

    def test_grading_claim_is_not_shown(self):
        summary._summarize_cached.cache_clear()
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"summaries":{"p1":"요구사항을 충족합니다."}}'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))
        with patch.object(summary, "_client", return_value=client):
            result = summary.summarize_item("항목", "기준", [{"id": "p1", "evidence": [{"page": 1, "text": "근거"}]}])
        self.assertEqual(result["p1"], "아래 페이지를 참고 하시기 바랍니다")


if __name__ == "__main__":
    unittest.main()
