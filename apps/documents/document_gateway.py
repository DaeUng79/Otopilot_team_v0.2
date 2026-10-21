"""문서 조회·보관 어댑터 (DOC-02·05·06, PRO-03).

연결용 신규 파일 · 오대웅(DaeUng79) 문서 모듈 검토 대상.
설계(인계서 v2 §15 DOC 모듈)의 `list_uploads`·`view_source`·`archive_upload`를 구현한다.
삭제 사유와 파싱 이력은 보존한다. 원본 파일은 다른 등록 건에서 쓰지 않을 때 지운다.
제안서는 `project_proposal_uploads.status='ARCHIVED'`, 제안요청서는
`rfp_upload_visibility` 행으로 목록에서 제외한다.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hwpx_storage import connect

VISIBILITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS rfp_upload_visibility (
    project_id TEXT NOT NULL,
    upload_revision INTEGER NOT NULL,
    archived_at TEXT,
    archived_by TEXT,
    reason TEXT,
    PRIMARY KEY(project_id, upload_revision),
    FOREIGN KEY(project_id, upload_revision) REFERENCES project_rfp_uploads(project_id, revision)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_uploads(db_path: Path, project_id: str) -> list[dict[str, Any]]:
    """DOC-02: 제안요청서 업로드 이력(보관 처리 포함, 최신 먼저)."""
    if not Path(db_path).is_file():
        return []
    with connect(db_path) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_rfp_uploads'"
        ).fetchone():
            return []
        db.executescript(VISIBILITY_SCHEMA)
        rows = db.execute(
            "SELECT u.revision,u.document_id,u.filename,u.byte_size,u.uploaded_at,"
            "u.page_count,u.block_count,u.warning_count,b.parse_revision,v.archived_at,v.reason "
            "FROM project_rfp_uploads u "
            "LEFT JOIN rfp_snapshot_bindings b ON b.project_id=u.project_id AND b.upload_revision=u.revision "
            "LEFT JOIN rfp_upload_visibility v ON v.project_id=u.project_id AND v.upload_revision=u.revision "
            "WHERE u.project_id=? ORDER BY u.revision DESC", (project_id,)).fetchall()
    return [dict(r) for r in rows]


def view_source(db_path: Path, document_id: str) -> tuple[str, bytes] | None:
    """DOC-05: 원본 파일(파일명, 바이트)."""
    with connect(db_path) as db:
        row = db.execute("SELECT filename,data FROM source_files WHERE sha256=?",
                         (document_id,)).fetchone()
    return (row["filename"], bytes(row["data"])) if row else None


def parsed_blocks(db_path: Path, document_id: str, parse_revision: str) -> dict[str, Any]:
    """저장된 문단·표 텍스트(담당자 '원본 보기' 대체 표시)."""
    with connect(db_path) as db:
        record = db.execute(
            "SELECT document_json FROM parse_snapshots WHERE document_id=? AND revision=?",
            (document_id, parse_revision)).fetchone()
    if record is None:
        raise LookupError("파싱 원문을 찾을 수 없습니다.")
    document = json.loads(record[0])
    visible = []
    for block in document.get("blocks", []):
        if block.get("parent_block_id") or block.get("type") not in {"paragraph", "table"}:
            continue
        item = {"type": block["type"], "pages": block.get("physical_page_numbers", [])}
        if block["type"] == "paragraph":
            item["text"] = block.get("text", "")
        else:
            item["rows"] = [[{"text": cell.get("text", ""), "row_span": cell.get("row_span", 1),
                              "col_span": cell.get("col_span", 1)} for cell in cells]
                            for cells in block.get("table", {}).get("cells", [])]
        visible.append(item)
    return {"warnings": document.get("warnings", []), "blocks": visible}


def _delete_unused_source(db, document_id: str) -> bool:
    """다른 등록 건이나 결과 자료가 참조하지 않는 원본 BLOB만 제거한다."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"documents", "source_files"} <= tables:
        return False
    document = db.execute("SELECT source_sha256 FROM documents WHERE document_id=?",
                          (document_id,)).fetchone()
    if not document:
        return False
    sha256 = document[0]
    if "managed_result_files" in tables and db.execute(
        "SELECT 1 FROM managed_result_files WHERE source_sha256=? LIMIT 1", (sha256,)
    ).fetchone():
        return False
    for linked in db.execute("SELECT document_id FROM documents WHERE source_sha256=?", (sha256,)):
        linked_id = linked[0]
        rfp_exists = "project_rfp_uploads" in tables and db.execute(
            "SELECT 1 FROM project_rfp_uploads WHERE document_id=? LIMIT 1", (linked_id,)
        ).fetchone()
        proposal_exists = "project_proposal_uploads" in tables and db.execute(
            "SELECT 1 FROM project_proposal_uploads WHERE document_id=? LIMIT 1", (linked_id,)
        ).fetchone()
        if not rfp_exists and not proposal_exists:
            return False
        if rfp_exists and "rfp_upload_visibility" not in tables:
            return False
        if rfp_exists and db.execute(
            "SELECT 1 FROM project_rfp_uploads u "
            "LEFT JOIN rfp_upload_visibility v ON v.project_id=u.project_id "
            "AND v.upload_revision=u.revision "
            "WHERE u.document_id=? AND v.archived_at IS NULL LIMIT 1", (linked_id,)
        ).fetchone():
            return False
        if proposal_exists and db.execute(
            "SELECT 1 FROM project_proposal_uploads "
            "WHERE document_id=? AND status<>'ARCHIVED' LIMIT 1", (linked_id,)
        ).fetchone():
            return False
    return bool(db.execute("DELETE FROM source_files WHERE sha256=?", (sha256,)).rowcount)


def purge_archived_sources(db_path: Path) -> int:
    """이미 보관 처리된 등록 건에도 같은 원본 정리 규칙을 적용한다."""
    with connect(db_path) as db:
        db.execute("PRAGMA secure_delete=ON")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        document_ids = set()
        if {"rfp_upload_visibility", "project_rfp_uploads"} <= tables:
            document_ids.update(row[0] for row in db.execute(
                "SELECT u.document_id FROM project_rfp_uploads u "
                "JOIN rfp_upload_visibility v ON v.project_id=u.project_id "
                "AND v.upload_revision=u.revision WHERE v.archived_at IS NOT NULL"
            ))
        if "project_proposal_uploads" in tables:
            document_ids.update(row[0] for row in db.execute(
                "SELECT document_id FROM project_proposal_uploads WHERE status='ARCHIVED'"
            ))
        return sum(_delete_unused_source(db, document_id) for document_id in document_ids)


def archive_upload(db_path: Path, project_id: str, *, reason: str, actor_id: str,
                   proposal_upload_id: str | None = None,
                   upload_revision: int | None = None) -> dict[str, Any]:
    """DOC-06·PRO-03: 목록에서 빼고 사용하지 않는 원본 BLOB을 지운다."""
    if not reason.strip():
        raise ValueError("사유를 적어 주세요.")
    with connect(db_path) as db:
        db.executescript(VISIBILITY_SCHEMA)
        db.execute("PRAGMA secure_delete=ON")
        db.execute("BEGIN IMMEDIATE")
        if proposal_upload_id:
            changed = db.execute(
                "UPDATE project_proposal_uploads SET status='ARCHIVED',archive_reason=?,"
                "updated_at=?,version=version+1 WHERE id=? AND project_id=? AND status<>'ARCHIVED'",
                (reason.strip(), _now(), proposal_upload_id, project_id)).rowcount
            if not changed:
                raise LookupError("보관 처리할 제안서를 찾을 수 없습니다.")
            document_id = db.execute("SELECT document_id FROM project_proposal_uploads WHERE id=?",
                                     (proposal_upload_id,)).fetchone()[0]
            source_deleted = _delete_unused_source(db, document_id)
            return {"id": proposal_upload_id, "status": "ARCHIVED", "source_deleted": source_deleted}
        if upload_revision is None:
            raise ValueError("대상을 지정하세요.")
        upload = db.execute("SELECT document_id FROM project_rfp_uploads WHERE project_id=? AND revision=?",
                            (project_id, upload_revision)).fetchone()
        if not upload:
            raise LookupError("보관 처리할 제안요청서를 찾을 수 없습니다.")
        db.execute(
            "INSERT INTO rfp_upload_visibility VALUES (?,?,?,?,?) "
            "ON CONFLICT(project_id,upload_revision) DO UPDATE SET archived_at=excluded.archived_at,"
            "archived_by=excluded.archived_by,reason=excluded.reason",
            (project_id, upload_revision, _now(), actor_id, reason.strip()))
        source_deleted = _delete_unused_source(db, upload[0])
        return {"upload_revision": upload_revision, "status": "ARCHIVED", "source_deleted": source_deleted}


def delete_upload(db_path: Path, project_id: str, *, proposal_upload_id: str | None = None,
                  upload_revision: int | None = None,
                  connection: sqlite3.Connection | None = None,
                  schema: str = "main") -> dict[str, Any]:
    """Permanently remove one registration and its unshared source/analysis data."""
    if schema not in {"main", "vendor_documents"}:
        raise ValueError("문서 DB 이름이 올바르지 않습니다.")
    with (connect(db_path) if connection is None else nullcontext(connection)) as db:
        db.execute(f"PRAGMA {schema}.secure_delete=ON")
        if connection is None:
            db.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in db.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'")}

        def remove_analyses(where: str, values: tuple) -> None:
            if "proposal_analysis_results" not in tables:
                return
            run_ids = [row[0] for row in db.execute(
                f"SELECT run_id FROM proposal_analysis_results WHERE {where}", values)]
            if "proposal_analysis_items" in tables:
                db.executemany("DELETE FROM proposal_analysis_items WHERE run_id=?",
                               ((run_id,) for run_id in run_ids))
            db.execute(f"DELETE FROM proposal_analysis_results WHERE {where}", values)

        def remove_partial_runs(rfp_document_ids: list[str], proposal_rows: list) -> None:
            if not {"requirement_results", "proposal_analysis_items"} <= tables:
                return
            from .step5_ai_proposal_analysis import DEFAULT_MODEL, _run_id
            models = {DEFAULT_MODEL}
            if "proposal_analysis_results" in tables:
                models.update(row[0] for row in db.execute(
                    "SELECT DISTINCT model FROM proposal_analysis_results WHERE project_id=?",
                    (project_id,)))
            for rfp_document_id in rfp_document_ids:
                for rfp in db.execute(
                    "SELECT result_id,result_json FROM requirement_results WHERE document_id=?",
                    (rfp_document_id,)):
                    for proposal in proposal_rows:
                        for model in models:
                            db.execute("DELETE FROM proposal_analysis_items WHERE run_id=?",
                                       (_run_id(rfp, proposal, model),))

        if proposal_upload_id is not None:
            row = db.execute(
                "SELECT document_id, vendor_id, upload_revision FROM project_proposal_uploads "
                "WHERE id=? AND project_id=?", (proposal_upload_id, project_id)).fetchone()
            if row is None:
                raise LookupError("삭제할 제안서를 찾을 수 없습니다.")
            document_id = row["document_id"]
            if "project_rfp_uploads" in tables:
                rfp_ids = [r[0] for r in db.execute(
                    "SELECT DISTINCT document_id FROM project_rfp_uploads WHERE project_id=?",
                    (project_id,))]
                remove_partial_runs(rfp_ids, [{"id": proposal_upload_id,
                    "document_id": document_id,
                    "parse_revision": db.execute(
                        "SELECT parse_revision FROM project_proposal_uploads WHERE id=?",
                        (proposal_upload_id,)).fetchone()[0]}])
            remove_analyses("proposal_upload_id=?", (proposal_upload_id,))
            db.execute("DELETE FROM project_proposal_uploads WHERE id=?", (proposal_upload_id,))
            result = {"id": proposal_upload_id, "status": "DELETED"}
        else:
            if upload_revision is None:
                raise ValueError("삭제할 문서를 지정해 주세요.")
            row = db.execute(
                "SELECT document_id FROM project_rfp_uploads WHERE project_id=? AND revision=?",
                (project_id, upload_revision)).fetchone()
            if row is None:
                raise LookupError("삭제할 제안요청서를 찾을 수 없습니다.")
            document_id = row["document_id"]
            if "project_proposal_uploads" in tables:
                remove_partial_runs([document_id], list(db.execute(
                    "SELECT id,document_id,parse_revision FROM project_proposal_uploads "
                    "WHERE project_id=?", (project_id,))))
            if "approved_criteria_versions" in tables:
                versions = [r[0] for r in db.execute(
                    "SELECT id FROM approved_criteria_versions WHERE project_id=? AND upload_revision=?",
                    (project_id, upload_revision))]
                if versions and "approved_criteria_items" in tables:
                    for version in versions:
                        while db.execute(
                            "DELETE FROM approved_criteria_items WHERE approved_criteria_version_id=? "
                            "AND id NOT IN (SELECT parent_id FROM approved_criteria_items "
                            "WHERE parent_id IS NOT NULL)", (version,)).rowcount:
                            pass
                db.execute("DELETE FROM approved_criteria_versions WHERE project_id=? AND upload_revision=?",
                           (project_id, upload_revision))
            for table, revision_column in (("requirement_jobs", "revision"),
                                           ("criteria_jobs", "revision"),
                                           ("rfp_upload_visibility", "upload_revision"),
                                           ("rfp_snapshot_bindings", "upload_revision")):
                if table in tables:
                    db.execute(f"DELETE FROM {table} WHERE project_id=? AND {revision_column}=?",
                               (project_id, upload_revision))
            db.execute("DELETE FROM project_rfp_uploads WHERE project_id=? AND revision=?",
                       (project_id, upload_revision))
            result = {"upload_revision": upload_revision, "status": "DELETED"}

        still_used = any(
            table in tables and db.execute(
                f"SELECT 1 FROM {table} WHERE document_id=? LIMIT 1", (document_id,)).fetchone()
            for table in ("project_rfp_uploads", "project_proposal_uploads"))
        if "project_documents" in tables and not any(
            table in tables and db.execute(
                f"SELECT 1 FROM {table} WHERE project_id=? AND document_id=? LIMIT 1",
                (project_id, document_id)).fetchone()
            for table in ("project_rfp_uploads", "project_proposal_uploads")):
            db.execute("DELETE FROM project_documents WHERE project_id=? AND document_id=?",
                       (project_id, document_id))
        if still_used:
            return result | {"shared_source_retained": True}

        if "requirement_results" in tables:
            result_ids = [r[0] for r in db.execute(
                "SELECT result_id FROM requirement_results WHERE document_id=?", (document_id,))]
            for result_id in result_ids:
                remove_analyses("rfp_result_id=?", (result_id,))
            db.execute("DELETE FROM requirement_results WHERE document_id=?", (document_id,))
        for table in ("criteria_results", "rfp_toc_snapshots"):
            if table in tables:
                db.execute(f"DELETE FROM {table} WHERE document_id=?", (document_id,))
        asset_ids = ([r[0] for r in db.execute(
            "SELECT DISTINCT sha256 FROM snapshot_assets WHERE document_id=?", (document_id,))]
            if "snapshot_assets" in tables else [])
        if "snapshot_assets" in tables:
            db.execute("DELETE FROM snapshot_assets WHERE document_id=?", (document_id,))
        for table in ("table_cells", "blocks", "pages", "parse_snapshots"):
            if table in tables:
                db.execute(f"DELETE FROM {table} WHERE document_id=?", (document_id,))
        if "assets" in tables and "snapshot_assets" in tables:
            db.executemany("DELETE FROM assets WHERE sha256=? AND NOT EXISTS "
                           "(SELECT 1 FROM snapshot_assets WHERE sha256=?)",
                           ((sha256, sha256) for sha256 in asset_ids))
        sha = db.execute("SELECT source_sha256 FROM documents WHERE document_id=?",
                         (document_id,)).fetchone()
        if "project_documents" in tables:
            db.execute("DELETE FROM project_documents WHERE document_id=?", (document_id,))
        db.execute("DELETE FROM documents WHERE document_id=?", (document_id,))
        if sha and "source_files" in tables and not (
                "managed_result_files" in tables and db.execute(
                    "SELECT 1 FROM managed_result_files WHERE source_sha256=?", (sha[0],)).fetchone()):
            db.execute("DELETE FROM source_files WHERE sha256=?", (sha[0],))
        return result | {"shared_source_retained": False}
