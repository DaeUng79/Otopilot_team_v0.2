"""Deleting a draft project archives its snapshot and purges active project rows."""

import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin.project_service import (
    archive_project,
    backfill_deleted_projects,
    create_project,
    deleted_project_detail,
    list_deleted_projects,
    reclaim_document_space,
    search_projects,
)
from app.committee.committee_app.v2_core import ModuleError
from app.committee.committee_app.v2_web_demo import local_runtime
from app.documents.hwpx_storage import SCHEMA
from app.documents.rfp_toc import TOC_SCHEMA
from app.shared.db import Actor, Store
from app.shared.demo_data import seed


class ProjectDeleteArchiveTest(unittest.TestCase):
    def test_existing_soft_delete_is_backfilled_without_inventing_reason(self):
        with tempfile.TemporaryDirectory(prefix="simsa-delete-legacy-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            with store.connect("admin", True) as db:
                db.execute(
                    "UPDATE projects SET deleted_at='2026-10-17T00:00:00Z',"
                    "deleted_by='super-demo',status='CANCELLED' "
                    "WHERE id='demo-evaluation'"
                )
            self.assertEqual(backfill_deleted_projects(store), 1)
            self.assertEqual(backfill_deleted_projects(store), 0)
            with store.connect("admin") as db:
                detail = deleted_project_detail(
                    db, store, Actor("super-demo", "SUPER_ADMIN"),
                    {"deleted_project_id": "demo-evaluation"},
                )
            self.assertEqual(detail["status"], "UNKNOWN")
            self.assertIn("사유 미보관", detail["deletion_reason"])

    def test_draft_archive_purges_active_rows_and_filters_department(self):
        with tempfile.TemporaryDirectory(prefix="simsa-delete-test-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            admin = Actor("super-demo", "SUPER_ADMIN")
            project = store.transact(
                admin, "PRJ-02",
                {"department_id": "web-demo-dept", "name": "삭제 시험 사업",
                 "contact_organization": "시험 기관", "contact_department": "시험 부서",
                 "contact_position": "주무관", "contact_name": "홍길동",
                 "contact_phone": "010-1234-5678", "contact_email": "test@example.org",
                 "evaluation_date": "2026-11-01"},
                str(uuid4()), create_project, database="admin",
            )
            pid = project["id"]
            documents = root / "documents.sqlite3"
            store.documents_path = documents
            with sqlite3.connect(documents) as db:
                db.executescript("""
                    CREATE TABLE project_rfp_uploads (project_id TEXT,revision INTEGER,document_id TEXT);
                    CREATE TABLE rfp_snapshot_bindings (project_id TEXT,upload_revision INTEGER,parse_revision TEXT);
                    CREATE TABLE requirement_results (document_id TEXT,source_revision TEXT,created_at TEXT,result_json TEXT);
                    CREATE TABLE parse_snapshots (document_id TEXT,revision TEXT,document_json TEXT);
                """)
                db.execute("INSERT INTO project_rfp_uploads VALUES (?,?,?)", (pid, 1, "doc"))
                db.execute("INSERT INTO rfp_snapshot_bindings VALUES (?,?,?)", (pid, 1, "rev"))
                db.execute("INSERT INTO requirement_results VALUES (?,?,?,?)",
                           ("doc", "rev", "now", json.dumps({"business_status": {
                               "current_status": [{"text": "현황 요약", "source_block_ids": ["b1"]}]
                           }})))
                db.execute("INSERT INTO parse_snapshots VALUES (?,?,?)",
                           ("doc", "rev", json.dumps({"blocks": [{
                               "block_id": "b1", "physical_page_numbers": [3]
                           }]})))
            body = {"project_id": pid, "version": project["version"],
                    "reason": "사업 취소"}
            result = store.transact(
                admin, "PRJ-04", body, str(uuid4()), archive_project,
                database="admin",
            )
            self.assertEqual(result["status"], "CANCELLED")
            with store.connect("admin") as db:
                self.assertIsNone(db.execute(
                    "SELECT id FROM projects WHERE id=?", (pid,)
                ).fetchone())
                active = search_projects(db, store, admin, {"page": 1})
                archived = list_deleted_projects(db, store, admin, {"page": 1})
                detail = deleted_project_detail(db, store, admin,
                                                {"deleted_project_id": pid})
                other = list_deleted_projects(
                    db, store, Actor("other-admin", "DEPARTMENT_ADMIN"), {"page": 1}
                )
            self.assertNotIn(pid, [item["id"] for item in active["items"]])
            self.assertIn(pid, [item["id"] for item in archived["items"]])
            self.assertEqual(other["items"], [])
            self.assertEqual(detail["contact_phone"], "010-1234-5678")
            self.assertEqual(detail["deletion_reason"], "사업 취소")
            self.assertEqual(detail["business_summary"]["current_status"],
                             [{"text": "현황 요약", "pages": [3]}])
            archive = root / "projects_delete.sqlite3"
            with sqlite3.connect(archive) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_active_evaluation_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory(prefix="simsa-delete-locked-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            admin = Actor("super-demo", "SUPER_ADMIN")
            with store.connect("admin", True) as db:
                db.execute(
                    "UPDATE projects SET status='EVALUATING' WHERE id='demo-evaluation'"
                )
                version = db.execute(
                    "SELECT version FROM projects WHERE id='demo-evaluation'"
                ).fetchone()[0]
            with self.assertRaises(ModuleError):
                store.transact(
                    admin, "PRJ-04",
                    {"project_id": "demo-evaluation", "version": version,
                     "reason": "허용되지 않아야 함"},
                    str(uuid4()), archive_project, database="admin",
                )
            self.assertFalse((root / "projects_delete.sqlite3").exists())

    def test_unshared_document_bytes_are_removed_with_project(self):
        with tempfile.TemporaryDirectory(prefix="simsa-delete-document-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            actor = Actor("super-demo", "SUPER_ADMIN")
            project = store.transact(actor, "PRJ-02", {
                "department_id": "web-demo-dept", "name": "문서 삭제 시험",
                "contact_organization": "시험 기관", "contact_department": "시험 부서",
                "contact_position": "주무관", "contact_name": "홍길동",
                "contact_phone": "010-1234-5678", "contact_email": "test@example.org",
                "evaluation_date": "2026-11-01",
            }, str(uuid4()), create_project, database="admin")
            path = root / "documents.sqlite3"
            store.documents_path = path
            with sqlite3.connect(path) as db:
                db.executescript(SCHEMA + TOC_SCHEMA)
                db.execute("INSERT INTO projects VALUES (?,?,?)", (project["id"], project["name"], "now"))
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                           ("doc-test", "test.hwpx", "doc-test", "rev", "now", "now"))
                db.execute("INSERT INTO parse_snapshots VALUES (?,?,?,?,?,?)",
                           ("doc-test", "rev", "test", "2", '{"blocks":[]}', "now"))
                db.execute("INSERT INTO source_files VALUES (?,?,?,?)",
                           ("doc-test", "test.hwpx", 1048576, b"test" * 262144))
                db.execute("INSERT INTO project_documents VALUES (?,?,?)",
                           (project["id"], "doc-test", "now"))
                db.execute("INSERT INTO rfp_toc_snapshots(document_id,parse_revision,toc_json) "
                           "VALUES (?,?,?)", ("doc-test", "rev", "[]"))
            store.transact(actor, "PRJ-04", {"project_id": project["id"],
                           "version": project["version"], "reason": "테스트 삭제"},
                           str(uuid4()), archive_project, database="admin")
            with closing(sqlite3.connect(path)) as db:
                self.assertGreater(db.execute("PRAGMA freelist_count").fetchone()[0], 0)
            self.assertGreater(reclaim_document_space(store), 0)
            with sqlite3.connect(path) as db:
                for table in ("projects", "project_documents", "documents",
                              "parse_snapshots", "rfp_toc_snapshots", "source_files"):
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA freelist_count").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
