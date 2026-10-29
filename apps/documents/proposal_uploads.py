"""업체별 제안서 등록(PRO-01)·목록(PRO-02) 어댑터.

연결용 신규 파일 · 오대웅(DaeUng79) 문서 모듈 검토 대상.
설계(인계서 v2 §15 PROPOSAL 모듈)의 `register_proposal`·`list_proposals`를 구현한다.
파싱·저장은 기존 `parser_hwpx.parse_hwpx`·`storage_documents.save_to_sqlite`를
그대로 쓰고, PDF·PPTX는 같은 JSON 모양을 만드는 `parser_pdf`·`parser_pptx`를 부른다.
표 `project_proposal_uploads`는 schema_v2.json의 열을 따른다. 문서 DB에는
`ref_project_vendors`·`ref_admin_users` 사본이 없어 그 두 외래키는 선언하지 않고
서버(`app/api/project_documents.py`)가 관리 DB로 업체·관리자를 확인한다.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .parser_hwpx import parse_hwpx
from .storage_documents import SCHEMA, connect, save_to_sqlite

FORMATS = {".hwpx": "HWPX", ".pdf": "PDF", ".pptx": "PPTX"}
PROPOSAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_proposal_uploads (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    vendor_id TEXT NOT NULL,
    upload_revision INTEGER NOT NULL CHECK(upload_revision > 0),
    document_id TEXT NOT NULL,
    parse_revision TEXT NOT NULL,
    format TEXT NOT NULL CHECK(format IN ('HWPX','PDF','HWP','PPTX')),
    filename TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('READY','REVIEW_REQUIRED','ARCHIVED')),
    archive_reason TEXT,
    UNIQUE(project_id, vendor_id, upload_revision),
    UNIQUE(project_id, id),
    FOREIGN KEY(document_id, parse_revision) REFERENCES parse_snapshots(document_id, revision)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize(db_path: Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.executescript(SCHEMA + PROPOSAL_SCHEMA)


def format_of(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in FORMATS:
        raise ValueError("HWPX·PDF·PPTX 파일만 올릴 수 있습니다. HWP 파일은 등록할 수 없습니다.")
    return FORMATS[suffix]


def parse_proposal(path: Path, work_dir: Path) -> dict[str, Any]:
    """형식별 파서를 골라 저장 가능한 문서 JSON을 돌려준다."""
    kind = format_of(path.name)
    if kind == "HWPX":
        return parse_hwpx(path, output_dir=work_dir / "assets", strict_pagination=False)
    if kind == "PDF":
        from .parser_pdf import parse_pdf
        return parse_pdf(path)
    from .parser_pptx import parse_pptx
    return parse_pptx(path)


def _row(row) -> dict[str, Any]:
    return dict(row)


def register_proposal(db_path: Path, *, project_id: str, project_name: str, vendor_id: str,
                      filename: str, data: bytes, uploaded_by: str,
                      minimum_revision: int = 1) -> dict[str, Any]:
    """PRO-01: 파싱·원본 저장 후 업체별 새 업로드 차수(READY)를 만든다."""
    initialize(db_path)
    kind = format_of(filename)
    with tempfile.TemporaryDirectory(prefix="simsa-proposal-") as directory:
        work = Path(directory)
        source = work / filename
        source.write_bytes(data)
        parsed = parse_proposal(source, work)
        saved = save_to_sqlite(parsed, db_path, source_path=source,
                               project_id=project_id, project_name=project_name)
    identity = str(uuid4())
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        local_revision = db.execute(
            "SELECT COALESCE(MAX(upload_revision),0)+1 FROM project_proposal_uploads "
            "WHERE project_id=? AND vendor_id=?", (project_id, vendor_id)).fetchone()[0]
        revision = max(local_revision, minimum_revision)
        db.execute(
            "INSERT INTO project_proposal_uploads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (identity, _now(), _now(), 1, project_id, vendor_id, revision,
             saved["document_id"], saved["revision"], kind, filename, uploaded_by, "READY"),
        )
    result = get_proposal(db_path, project_id, identity)
    result.update(pages=saved["pages"], blocks=saved["blocks"],
                  warnings=len(parsed.get("warnings", [])))
    return result


def get_proposal(db_path: Path, project_id: str, proposal_upload_id: str) -> dict[str, Any]:
    with connect(db_path) as db:
        row = db.execute(
            "SELECT p.*, (SELECT byte_size FROM source_files s WHERE s.sha256=p.document_id) AS byte_size, "
            "(SELECT COUNT(*) FROM pages g WHERE g.document_id=p.document_id AND g.revision=p.parse_revision) AS page_count "
            "FROM project_proposal_uploads p WHERE p.id=? AND p.project_id=?",
            (proposal_upload_id, project_id)).fetchone()
    if row is None:
        raise LookupError("등록된 제안서를 찾을 수 없습니다.")
    return _row(row)


def list_proposals(db_path: Path, project_id: str, *, include_archived: bool = True) -> list[dict[str, Any]]:
    """PRO-02: 업체별 업로드 이력(최신 차수 먼저)."""
    if not Path(db_path).is_file():
        return []
    with connect(db_path) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_proposal_uploads'"
        ).fetchone():
            return []
        rows = db.execute(
            "SELECT p.*, (SELECT byte_size FROM source_files s WHERE s.sha256=p.document_id) AS byte_size, "
            "(SELECT COUNT(*) FROM pages g WHERE g.document_id=p.document_id AND g.revision=p.parse_revision) AS page_count "
            "FROM project_proposal_uploads p WHERE p.project_id=? "
            + ("" if include_archived else "AND p.status<>'ARCHIVED' ")
            + "ORDER BY p.vendor_id, p.upload_revision DESC", (project_id,)).fetchall()
    return [_row(r) for r in rows]


def latest_ready(db_path: Path, project_id: str) -> dict[str, dict[str, Any]]:
    """업체별 최신 READY 업로드."""
    result: dict[str, dict[str, Any]] = {}
    for row in list_proposals(db_path, project_id, include_archived=False):
        result.setdefault(row["vendor_id"], row)
    return result


def ready_event(upload: dict[str, Any]) -> dict[str, Any]:
    """평가 DB로 보내는 `proposal.ready` 계약 payload."""
    return {
        "proposal_upload_id": upload["id"], "project_id": upload["project_id"],
        "vendor_id": upload["vendor_id"], "upload_revision": upload["upload_revision"],
        "document_id": upload["document_id"], "parse_revision": upload["parse_revision"],
        "format": upload["format"], "status": upload["status"],
    }
