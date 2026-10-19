"""Regression checks for the second-stage document integration."""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.project_documents import _proposal_counts
from app.documents.material_service import archive_result_file_in_transaction
from app.documents.rfp_toc import TOC_SCHEMA, load_toc, save_toc


class SecondStageMergeTest(unittest.TestCase):
    def test_rfp_move_rolls_back_when_result_row_changed(self):
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            db.executescript("""
                CREATE TABLE project_rfp_uploads (revision INTEGER);
                CREATE TABLE managed_result_files (
                    id TEXT, project_id TEXT, version INTEGER,
                    archived_at TEXT, updated_at TEXT);
                INSERT INTO managed_result_files VALUES ('result','project',2,NULL,'old');
            """)
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO project_rfp_uploads VALUES (1)")
            with self.assertRaises(ValueError):
                archive_result_file_in_transaction(
                    db, project_id="project", file_id="result", version=1)
            db.rollback()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM project_rfp_uploads").fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT archived_at FROM managed_result_files").fetchone()[0])

    def test_summary_counts_ready_vendors_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE project_proposal_uploads (project_id TEXT, vendor_id TEXT, status TEXT)")
                db.executemany(
                    "INSERT INTO project_proposal_uploads VALUES (?,?,?)",
                    [("p1", "a", "READY"), ("p1", "a", "READY"),
                     ("p1", "b", "ARCHIVED"), ("p1", "c", "READY"),
                     ("p2", "d", "ARCHIVED")],
                )
            self.assertEqual(_proposal_counts(path), [{"project_id": "p1", "vendor_count": 2}])

    def test_legacy_toc_snapshot_uses_updated_parser(self):
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            db.executescript("""
                CREATE TABLE parse_snapshots (document_id TEXT, revision TEXT,
                    PRIMARY KEY(document_id, revision));
                CREATE TABLE pages (document_id TEXT, revision TEXT,
                    physical_page_number INTEGER, page_number INTEGER);
                CREATE TABLE blocks (document_id TEXT, revision TEXT, type TEXT,
                    order_index INTEGER, text TEXT, physical_page_numbers_json TEXT,
                    parent_cell_id TEXT);
            """ + TOC_SCHEMA)
            db.execute("INSERT INTO parse_snapshots VALUES ('doc','rev')")
            db.execute("INSERT INTO pages VALUES ('doc','rev',2,1)")
            db.execute("INSERT INTO blocks VALUES ('doc','rev','paragraph',1,'Ⅰ. 사업 개요','[2]',NULL)")
            db.execute("INSERT INTO rfp_toc_snapshots(document_id,parse_revision,toc_json) VALUES ('doc','rev','[]')")
            pages = [{"n": 2, "label": 1}]
            toc = load_toc(db, "doc", "rev", pages)
            self.assertEqual([(item["t"], item["page"]) for item in toc], [("Ⅰ. 사업 개요", 2)])
            self.assertEqual(save_toc(db, "doc", "rev"), toc)
            saved = json.loads(db.execute("SELECT toc_json FROM rfp_toc_snapshots").fetchone()[0])
            self.assertEqual(saved["algorithm_version"], 2)
            self.assertEqual(load_toc(db, "doc", "rev", pages), toc)


if __name__ == "__main__":
    unittest.main()
