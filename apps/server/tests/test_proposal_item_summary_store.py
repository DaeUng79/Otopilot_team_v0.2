"""Persist one item summary for all evaluators, including concurrent requests."""

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.documents.summary_store import get_or_generate


MIGRATION = Path(__file__).resolve().parents[1] / "migrations/evaluation/20261020_yujin_evaluation_005.sql"


class ProposalItemSummaryStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "evaluation.sqlite3"
        with sqlite3.connect(self.path) as conn:
            conn.executescript("""
                CREATE TABLE ref_projects(id TEXT PRIMARY KEY);
                CREATE TABLE evaluation_sessions(id TEXT PRIMARY KEY);
                CREATE TABLE ref_approved_criteria_items(id TEXT PRIMARY KEY);
                INSERT INTO ref_projects VALUES ('project');
                INSERT INTO evaluation_sessions VALUES ('session');
                INSERT INTO ref_approved_criteria_items VALUES ('criterion');
            """)
            conn.executescript(MIGRATION.read_text("utf8"))
        self.base = dict(project_id="project", session_id="session", criterion_id="criterion",
                         processor_version="v1", fingerprint={"document": "d1", "blocks": ["b1"]})

    def test_concurrent_evaluators_share_one_persisted_result(self):
        calls = 0
        lock = threading.Lock()

        def generate():
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.3)
            return {"proposal": "제안 내용"}

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: get_or_generate(self.path, **self.base, generate=generate), range(4)))
        self.assertEqual(calls, 1)
        self.assertEqual(results, [{"proposal": "제안 내용"}] * 4)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT status,summaries_json FROM proposal_item_summaries").fetchone(),
                             ("complete", json.dumps({"proposal": "제안 내용"}, ensure_ascii=False, sort_keys=True)))
        self.assertEqual(get_or_generate(self.path, **self.base,
                                         generate=lambda: self.fail("model should not run")), results[0])

    def test_changed_evidence_or_processor_version_generates_again(self):
        calls = []

        def generate():
            calls.append(1)
            return {"proposal": f"결과 {len(calls)}"}

        first = get_or_generate(self.path, **self.base, generate=generate)
        changed = {**self.base, "fingerprint": {"document": "d2", "blocks": ["b1"]}}
        second = get_or_generate(self.path, **changed, generate=generate)
        upgraded = {**changed, "processor_version": "v2"}
        third = get_or_generate(self.path, **upgraded, generate=generate)
        self.assertEqual([first, second, third], [
            {"proposal": "결과 1"}, {"proposal": "결과 2"}, {"proposal": "결과 3"}])

    def test_failed_generation_is_retryable(self):
        with self.assertRaisesRegex(RuntimeError, "model down"):
            get_or_generate(self.path, **self.base,
                            generate=lambda: (_ for _ in ()).throw(RuntimeError("model down")))
        result = get_or_generate(self.path, **self.base, generate=lambda: {"proposal": "재시도"})
        self.assertEqual(result, {"proposal": "재시도"})


if __name__ == "__main__":
    unittest.main()
