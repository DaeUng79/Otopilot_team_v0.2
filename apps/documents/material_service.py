"""결과 자료 보관(MAT-01·02·03).

연결용 신규 파일 · 오대웅(DaeUng79) 문서 모듈 검토 대상.
설계(인계서 v2 §15 MATERIAL 모듈)의 `register_result_file`·`revise_result_file`와
목록 조회 `list_materials`(DASH 설계의 같은 이름)를 구현한다. 파일 원본은 기존
`source_files` BLOB 저장소를 재사용하고 메타데이터는 `managed_result_files`에 둔다.
수정은 항상 새 행(새 버전)이며 이전 행은 `archived_at`으로 목록에서만 뺀다.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .storage_documents import SCHEMA, connect

MATERIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS managed_result_files (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    source_sha256 TEXT NOT NULL REFERENCES source_files(sha256),
    title TEXT NOT NULL,
    description TEXT,
    revision_no INTEGER NOT NULL CHECK(revision_no > 0),
    previous_id TEXT REFERENCES managed_result_files(id),
    result_run_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('UPLOADED_RESULT','GENERATED_REPORT')),
    uploaded_by TEXT NOT NULL,
    archived_at TEXT
);
"""
MAX_FILE_SIZE = 50 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize(db_path: Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.executescript(SCHEMA + MATERIAL_SCHEMA)


def _store_blob(db, filename: str, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    db.execute("INSERT OR IGNORE INTO source_files VALUES (?,?,?,?)",
               (sha, filename, len(data), data))
    return sha


def _ensure_project(db, project_id: str, project_name: str) -> None:
    db.execute("INSERT INTO projects VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET name=excluded.name",
               (project_id, project_name, _now()))


def register_result_file(db_path: Path, *, project_id: str, project_name: str, filename: str,
                         data: bytes, title: str, description: str | None, uploaded_by: str,
                         kind: str = "UPLOADED_RESULT", result_run_id: str | None = None) -> dict[str, Any]:
    """MAT-02: 새 결과 자료(1판)."""
    if not title.strip():
        raise ValueError("제목을 적어 주세요.")
    if not data or len(data) > MAX_FILE_SIZE:
        raise ValueError("50MB 이하의 파일을 올려 주세요.")
    initialize(db_path)
    identity = str(uuid4())
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        _ensure_project(db, project_id, project_name)
        sha = _store_blob(db, filename, data)
        db.execute(
            "INSERT INTO managed_result_files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (identity, _now(), _now(), 1, project_id, sha, title.strip(), description,
             1, None, result_run_id, kind, uploaded_by))
    return get_result_file(db_path, project_id, identity)


def revise_result_file(db_path: Path, *, project_id: str, file_id: str, version: int,
                       uploaded_by: str, description: str | None, filename: str | None = None,
                       data: bytes | None = None, title: str | None = None) -> dict[str, Any]:
    """MAT-03: 설명·파일을 바꾼 새 버전을 만들고 이전 버전은 목록에서 뺀다."""
    initialize(db_path)
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM managed_result_files WHERE id=? AND project_id=?",
                         (file_id, project_id)).fetchone()
        if old is None:
            raise LookupError("자료를 찾을 수 없습니다.")
        if old["version"] != version:
            raise ValueError("다른 작업에서 변경했습니다. 다시 조회하세요.")
        if old["archived_at"]:
            raise ValueError("이미 새 버전이 있는 자료입니다. 최신 버전을 수정하세요.")
        if data is not None and old["kind"] == "GENERATED_REPORT":
            raise ValueError("시스템 취합본은 파일을 바꿀 수 없습니다. 설명만 고칠 수 있습니다.")
        if data is not None and (not data or len(data) > MAX_FILE_SIZE):
            raise ValueError("50MB 이하의 파일을 올려 주세요.")
        sha = _store_blob(db, filename or "", data) if data is not None else old["source_sha256"]
        identity = str(uuid4())
        db.execute(
            "INSERT INTO managed_result_files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (identity, _now(), _now(), 1, project_id, sha, (title or old["title"]).strip(),
             description, old["revision_no"] + 1, old["id"], old["result_run_id"], old["kind"],
             uploaded_by))
        db.execute("UPDATE managed_result_files SET archived_at=?,updated_at=?,version=version+1 WHERE id=?",
                   (_now(), _now(), old["id"]))
    return get_result_file(db_path, project_id, identity)


def archive_result_file(db_path: Path, *, project_id: str, file_id: str, version: int) -> dict[str, Any]:
    """목록에서만 뺀다(archived_at). 행과 원본 BLOB은 남는다.

    결과 자료로 잘못 올라간 제안요청서를 제안요청서 차수로 옮긴 뒤 호출한다(2026-10-18).
    """
    initialize(db_path)
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        archive_result_file_in_transaction(
            db, project_id=project_id, file_id=file_id, version=version)
    return get_result_file(db_path, project_id, file_id)


def archive_result_file_in_transaction(
    db: sqlite3.Connection, *, project_id: str, file_id: str, version: int
) -> None:
    """Archive a result row inside the caller's document DB transaction."""
    old = db.execute("SELECT * FROM managed_result_files WHERE id=? AND project_id=?",
                     (file_id, project_id)).fetchone()
    if old is None:
        raise LookupError("자료를 찾을 수 없습니다.")
    if old["version"] != version:
        raise ValueError("다른 작업에서 변경했습니다. 다시 조회하세요.")
    if old["archived_at"]:
        raise ValueError("이미 목록에서 뺀 자료입니다.")
    stamp = _now()
    db.execute("UPDATE managed_result_files SET archived_at=?,updated_at=?,version=version+1 WHERE id=?",
               (stamp, stamp, file_id))


def _select(where: str) -> str:
    return ("SELECT m.*, s.filename, s.byte_size FROM managed_result_files m "
            "JOIN source_files s ON s.sha256=m.source_sha256 WHERE " + where)


def get_result_file(db_path: Path, project_id: str, file_id: str) -> dict[str, Any]:
    with connect(db_path) as db:
        row = db.execute(_select("m.id=? AND m.project_id=?"), (file_id, project_id)).fetchone()
    if row is None:
        raise LookupError("자료를 찾을 수 없습니다.")
    return dict(row)


def list_result_files(db_path: Path, project_id: str | None = None) -> list[dict[str, Any]]:
    """현재 버전(archived_at IS NULL)만."""
    if not Path(db_path).is_file():
        return []
    with connect(db_path) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_result_files'"
        ).fetchone():
            return []
        if project_id:
            rows = db.execute(_select("m.archived_at IS NULL AND m.project_id=? ORDER BY m.created_at DESC"),
                              (project_id,)).fetchall()
        else:
            rows = db.execute(_select("m.archived_at IS NULL ORDER BY m.created_at DESC")).fetchall()
    return [dict(r) for r in rows]


def list_materials(db_path: Path, project_ids: list[str]) -> list[dict[str, Any]]:
    """MAT-01: 사업별 제안요청서(최신)·제안서(업체별 최신 READY)·결과 자료를 한 목록으로."""
    from .document_gateway import list_uploads
    from .proposal_uploads import latest_ready

    items: list[dict[str, Any]] = []
    for pid in project_ids:
        uploads = [u for u in list_uploads(db_path, pid) if not u["archived_at"]]
        if uploads:
            u = uploads[0]
            items.append({"project_id": pid, "kind": "RFP", "label": "제안요청서", "vendor_id": None,
                          "filename": u["filename"], "byte_size": u["byte_size"],
                          "date": u["uploaded_at"], "revision": u["revision"],
                          "download": f"/api/v2/projects/{pid}/rfp/{u['revision']}/download"})
        for vendor_id, p in latest_ready(db_path, pid).items():
            items.append({"project_id": pid, "kind": "PROPOSAL", "label": "제안서", "vendor_id": vendor_id,
                          "filename": p["filename"], "byte_size": p["byte_size"],
                          "date": p["created_at"], "revision": p["upload_revision"],
                          "download": f"/api/v2/projects/{pid}/proposals/{p['id']}/download"})
        for f in list_result_files(db_path, pid):
            items.append({"project_id": pid, "kind": f["kind"], "label": "결과 자료", "vendor_id": None,
                          "filename": f["filename"], "byte_size": f["byte_size"], "date": f["created_at"],
                          "revision": f["revision_no"], "id": f["id"], "version": f["version"],
                          "title": f["title"], "description": f["description"],
                          "result_run_id": f["result_run_id"],
                          "download": f"/api/v2/projects/{pid}/result-files/{f['id']}/download"})
    return items
