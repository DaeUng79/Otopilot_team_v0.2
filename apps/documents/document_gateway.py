"""문서 조회·보관 어댑터 (DOC-02·05·06, PRO-03).

연결용 신규 파일 · 오대웅(DaeUng79) 문서 모듈 검토 대상.
설계(인계서 v2 §15 DOC 모듈)의 `list_uploads`·`view_source`·`archive_upload`를 구현한다.
원본·스냅샷은 지우지 않는다. 제안서는 `project_proposal_uploads.status='ARCHIVED'`,
제안요청서는 `rfp_upload_visibility` 행으로 목록에서만 뺀다.
"""

from __future__ import annotations

import json
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


def archive_upload(db_path: Path, project_id: str, *, reason: str, actor_id: str,
                   proposal_upload_id: str | None = None,
                   upload_revision: int | None = None) -> dict[str, Any]:
    """DOC-06·PRO-03: 목록에서 뺀다. 원본·스냅샷·과거 평가 참조는 보존한다."""
    if not reason.strip():
        raise ValueError("사유를 적어 주세요.")
    with connect(db_path) as db:
        db.executescript(VISIBILITY_SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        if proposal_upload_id:
            changed = db.execute(
                "UPDATE project_proposal_uploads SET status='ARCHIVED',archive_reason=?,"
                "updated_at=?,version=version+1 WHERE id=? AND project_id=? AND status<>'ARCHIVED'",
                (reason.strip(), _now(), proposal_upload_id, project_id)).rowcount
            if not changed:
                raise LookupError("보관 처리할 제안서를 찾을 수 없습니다.")
            return {"id": proposal_upload_id, "status": "ARCHIVED"}
        if upload_revision is None:
            raise ValueError("대상을 지정하세요.")
        if not db.execute("SELECT 1 FROM project_rfp_uploads WHERE project_id=? AND revision=?",
                          (project_id, upload_revision)).fetchone():
            raise LookupError("보관 처리할 제안요청서를 찾을 수 없습니다.")
        db.execute(
            "INSERT INTO rfp_upload_visibility VALUES (?,?,?,?,?) "
            "ON CONFLICT(project_id,upload_revision) DO UPDATE SET archived_at=excluded.archived_at,"
            "archived_by=excluded.archived_by,reason=excluded.reason",
            (project_id, upload_revision, _now(), actor_id, reason.strip()))
        return {"upload_revision": upload_revision, "status": "ARCHIVED"}
