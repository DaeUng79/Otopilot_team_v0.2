"""제안서 2차 분석에서 근거 없는 내용을 게시하지 않는지 확인한다."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import ValidationError

from apps.documents.step5_ai_proposal_analysis import (
    Evidence, Finding, _assemble, analyze_one, validate_finding, verify_summary,
)


class ProposalAnalysisSafetyTests(unittest.TestCase):
    def setUp(self):
        self.block = {"block_id": "p_001", "text": "프로젝트 수행계획서를 작성합니다.",
                      "physical_page_number": 7}
        self.offered = [{"blocks": [self.block]}]
        self.all_blocks = {"p_001": self.block}

    def test_exact_proposal_quote_is_kept_with_page(self):
        finding = Finding(status="확인됨", proposal_summary="수행계획서 작성 제안",
                          evidence=[Evidence(block_id="p_001")])
        item = validate_finding(finding, self.offered, self.all_blocks)
        self.assertEqual(item["evidence"][0]["page"], 7)
        self.assertEqual(item["evidence"][0]["quote"], self.block["text"])

    def test_unoffered_or_empty_block_is_rejected(self):
        for block_id in ("p_999", "p_empty"):
            with self.subTest(block_id=block_id):
                finding = Finding(status="확인됨", proposal_summary="허위 제안",
                                  evidence=[Evidence(block_id=block_id)])
                with self.assertRaises(ValueError):
                    validate_finding(finding, self.offered,
                                     {**self.all_blocks, "p_empty": {"text": ""}})

    def test_unconfirmed_cannot_contain_claim_or_evidence(self):
        for summary, evidence in [("추정되는 제안", []),
                                  ("확인되지 않음", [Evidence(block_id="p_001")])]:
            with self.subTest(summary=summary):
                with self.assertRaises(ValueError):
                    validate_finding(Finding(status="확인되지 않음", proposal_summary=summary,
                                             evidence=evidence), self.offered, self.all_blocks)

    def test_partial_result_cannot_be_published(self):
        requirements = [{"code": "CNR-001", "category": "컨설팅 요구사항"},
                        {"code": "CNR-002", "category": "컨설팅 요구사항"}]
        with self.assertRaises(ValueError):
            _assemble("project", {"result_id": "rfp", "document_id": "d", "source_revision": "v"},
                      {"id": "upload", "vendor_id": "vendor", "document_id": "pd", "parse_revision": "pv"},
                      "run", "gpt-4o", requirements,
                      {"CNR-001": {"status": "확인됨", "proposal_summary": "작성", "evidence": []}})

    def test_heading_alone_cannot_support_a_summary(self):
        item = verify_summary(None, "gpt-4o", {"status": "확인됨",
            "proposal_summary": "과업 변경 시 위원회를 개최합니다.",
            "evidence": [{"block_id": "p_001", "page": 7, "quote": "과업심의위원회 운영"}]})
        self.assertEqual(item["status"], "확인되지 않음")
        self.assertEqual(item["evidence"], [])

    def test_model_cannot_turn_a_finding_into_compliance_judgment(self):
        item = verify_summary(None, "gpt-4o", {"status": "확인됨",
            "proposal_summary": "이 제안은 요구사항을 충족합니다.",
            "evidence": [{"block_id": "p_001", "page": 7, "quote": self.block["text"]}]})
        self.assertEqual(item["status"], "확인되지 않음")

    def test_truncated_json_is_retried_with_bounded_output(self):
        error = None
        try:
            Finding.model_validate_json('{"status":"확인됨","proposal_summary":"잘린')
        except ValidationError as caught:
            error = caught
        response = SimpleNamespace(status="completed", output_parsed=Finding(
            status="확인됨", proposal_summary="수행계획서를 작성합니다.",
            evidence=[Evidence(block_id="p_001")]))
        client = SimpleNamespace(responses=SimpleNamespace(parse=Mock(side_effect=[error, response])))
        result = analyze_one(client, "gpt-4o",
                             {"code": "SFR-001", "category": "기능", "title": "수행계획",
                              "rfp_detail": "수행계획서 작성"},
                             [{"page": 7, "text": "[p_001] 프로젝트 수행계획서를 작성합니다.",
                               "blocks": [self.block]}], self.all_blocks)
        self.assertEqual(result["evidence"][0]["block_id"], "p_001")
        self.assertEqual(client.responses.parse.call_count, 2)
        self.assertEqual(client.responses.parse.call_args.kwargs["max_output_tokens"], 1600)


if __name__ == "__main__":
    unittest.main()
