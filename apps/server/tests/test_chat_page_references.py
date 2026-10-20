"""Chat answers keep usable page links even when the model omits its citation format."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.documents.chat_adapter import answer_one, pages_from_text, stream_answers


class ChatPageReferencesTest(unittest.TestCase):
    def test_common_page_formats(self):
        self.assertEqual(pages_from_text("[페이지번호 12쪽], 14~15페이지, p.18"), [12, 14, 15, 18])

    def test_missing_citation_uses_labeled_document_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "documents.sqlite3"
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE blocks (document_id TEXT, revision TEXT, block_id TEXT, "
                             "type TEXT, text TEXT, physical_page_numbers_json TEXT, order_index INTEGER)")
                conn.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?)",
                             ("doc", "rev", "block-1", "paragraph", "보안 대책과 접근 통제 방안", "[7]", 1))
            chatbot = SimpleNamespace(
                ChatbotError=ValueError,
                load_context=lambda *_: {"documents": [{"revision": "rev", "blocks": [
                    {"pages": [7], "type": "paragraph", "text": "보안 대책과 접근 통제 방안"}]}],
                    "content": "context", "source_tables": {}},
                build_messages=lambda *_: ([], 0, 1),
                stream_answer=lambda *_: iter(["접근 통제 방안을 제시합니다."]),
                answer_parts=lambda text, *_: (text, [], []),
            )
            result = answer_one(chatbot, None, database,
                                {"document_id": "doc", "parse_revision": "rev"}, "보안 대책", [])
            self.assertEqual(result["pages"], [7])
            self.assertEqual(result["page_source"], "candidate")

    def test_stream_emits_chunks_before_final_page_links(self):
        chatbot = SimpleNamespace(
            ChatbotError=ValueError,
            stream_answer=lambda *_: iter(["보안 대책은 ", "7쪽에 있습니다."]),
            answer_parts=lambda text, *_, **__: (text.strip(), [], []),
        )
        proposal = {"session_proposal_id": "vendor", "document_id": "doc", "parse_revision": "rev"}
        context = {"documents": [{"blocks": [{"pages": [7]}]}], "source_tables": {}}
        prepared = (chatbot, None, Path("unused"), "보안 대책", [(proposal, context, [], 0, 1, None)])
        events = list(stream_answers(prepared))
        self.assertEqual([event["type"] for event in events], ["delta", "delta", "answer", "done"])
        self.assertEqual(events[0]["text"], "보안 대책은")
        self.assertEqual(events[2]["answer"]["pages"], [7])


if __name__ == "__main__":
    unittest.main()
