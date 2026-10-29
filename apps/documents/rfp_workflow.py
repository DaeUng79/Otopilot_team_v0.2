"""제안요청서 요구사항 추출(DOC-03·04)·평가기준 초안 생성(CRT-01·02) 작업 큐.

연결용 신규 파일 · 오대웅(DaeUng79) 문서 모듈 검토 대상.
원본 `apps/documents_daeung/step0_documents_api.py`의 작업 큐 함수를 통합 서비스의
문서 DB(`project_rfp_uploads` + `rfp_snapshot_bindings`)에 맞춰 옮겼다. HTTP 서버는
두지 않고 `app/api/project_documents.py`가 이 함수들을 부른다.
AI 호출은 `requirements_extract`·`criteria_generate`가 그대로 담당한다.
"""

from __future__ import annotations

import sqlite3
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Iterator

from . import requirements_extract as requirements
from . import criteria_generate as criteria
from . import requirements_review as specs
from .document_gateway import VISIBILITY_SCHEMA

JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS requirement_jobs (
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    document_id TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, revision),
    FOREIGN KEY (project_id, revision)
        REFERENCES project_rfp_uploads(project_id, revision)
);
CREATE TABLE IF NOT EXISTS criteria_jobs (
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    document_id TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, revision),
    FOREIGN KEY (project_id, revision)
        REFERENCES project_rfp_uploads(project_id, revision)
);
"""
EXTRACTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rfp-ai")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _open(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_jobs(db_path: Path) -> None:
    """작업 표를 만들고 서버 재시작으로 끊긴 작업을 실패로 표시한다."""
    with _open(db_path) as connection:
        connection.executescript(JOB_SCHEMA)
        for table in ("requirement_jobs", "criteria_jobs"):
            connection.execute(
                f"UPDATE {table} SET status='failed', "
                "error='서버가 다시 시작되었습니다. 다시 시도해 주세요.', updated_at=? "
                "WHERE status IN ('queued', 'running')",
                (_now(),),
            )


def latest_rfp(db_path: Path, project_id: str) -> dict | None:
    """최신 제안요청서 업로드와 고정 파싱 버전."""
    if not Path(db_path).is_file():
        return None
    with _open(db_path) as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_rfp_uploads'"
        ).fetchone():
            return None
        connection.executescript(JOB_SCHEMA)
        connection.executescript(VISIBILITY_SCHEMA)
        row = connection.execute(
            "SELECT u.revision, u.document_id, u.filename, u.byte_size, u.uploaded_at, "
            "u.page_count, u.block_count, u.warning_count, b.parse_revision "
            "FROM project_rfp_uploads u LEFT JOIN rfp_snapshot_bindings b "
            "ON b.project_id=u.project_id AND b.upload_revision=u.revision "
            "LEFT JOIN rfp_upload_visibility v ON v.project_id=u.project_id "
            "AND v.upload_revision=u.revision "
            "WHERE u.project_id=? AND v.archived_at IS NULL "
            "ORDER BY u.revision DESC LIMIT 1", (project_id,)
        ).fetchone()
    return dict(row) if row else None


def _set_job(db_path: Path, table: str, project_id: str, revision: int,
             status: str, error: str | None = None) -> None:
    with _open(db_path) as connection:
        connection.execute(
            f"UPDATE {table} SET status=?, error=?, updated_at=? WHERE project_id=? AND revision=?",
            (status, error, _now(), project_id, revision),
        )


def _run_requirements(db_path: Path, project_id: str, revision: int, document_id: str,
                      *, force: bool = False, mode: str = "auto") -> None:
    try:
        _set_job(db_path, "requirement_jobs", project_id, revision, "running")
        result = requirements.extract_and_save_requirements(db_path, document_id, force=force)
        if isinstance(result, dict):
            specs.prepare(db_path, project_id, {"revision": revision, "document_id": document_id},
                          result, force=force, mode=mode)
        _set_job(db_path, "requirement_jobs", project_id, revision, "done")
    except requirements.RequirementsError as error:
        _set_job(db_path, "requirement_jobs", project_id, revision, "failed", str(error))
    except Exception:
        traceback.print_exc()
        _set_job(db_path, "requirement_jobs", project_id, revision, "failed",
                 "요구사항 추출에 실패했습니다. 서버 로그를 확인해 주세요.")


def _queue(db_path: Path, table: str, project_id: str, revision: int,
           document_id: str, worker) -> bool:
    """queued/running/done이면 그대로 두고, 아니면 새 작업을 넣는다. 넣었으면 True."""
    with _open(db_path) as connection:
        connection.executescript(JOB_SCHEMA)
        existing = connection.execute(
            f"SELECT status FROM {table} WHERE project_id=? AND revision=?",
            (project_id, revision),
        ).fetchone()
        if existing and existing[0] in {"queued", "running", "done"}:
            return False
        connection.execute(
            f"INSERT INTO {table} VALUES (?, ?, ?, 'queued', NULL, ?) "
            "ON CONFLICT(project_id, revision) DO UPDATE SET "
            "status='queued', error=NULL, updated_at=excluded.updated_at",
            (project_id, revision, document_id, _now()),
        )
    EXTRACTOR.submit(worker, db_path, project_id, revision, document_id)
    return True


def queue_requirements(db_path: Path, project_id: str, *, force: bool = False, mode: str = "auto") -> dict:
    """DOC-04: 최신 제안요청서의 요구사항 추출을 뒤에서 실행한다."""
    if mode not in {"auto", "numbered", "narrative"}:
        raise requirements.RequirementsError("분석 유형을 확인해 주세요.")
    latest = latest_rfp(db_path, project_id)
    if latest is None:
        raise requirements.RequirementsError("등록된 제안요청서가 없습니다.")
    with _open(db_path) as connection:
        connection.executescript(JOB_SCHEMA)
        running = connection.execute(
            "SELECT 1 FROM requirement_jobs WHERE project_id=? AND revision=? "
            "AND status IN ('queued', 'running')",
            (project_id, latest["revision"]),
        ).fetchone()
    if running:
        return requirement_status(db_path, project_id)
    if force:
        _set_job(db_path, "requirement_jobs", project_id, latest["revision"], "failed", None)
    _queue(db_path, "requirement_jobs", project_id, latest["revision"],
           latest["document_id"], partial(_run_requirements, force=force, **({"mode": mode} if mode != "auto" else {})))
    return requirement_status(db_path, project_id)


def requirement_status(db_path: Path, project_id: str) -> dict:
    """DOC-03: none / queued / running / done / failed."""
    latest = latest_rfp(db_path, project_id)
    if latest is None:
        return {"status": "none", "revision": None, "error": None, "summary": None}
    with _open(db_path) as connection:
        row = connection.execute(
            "SELECT status, error FROM requirement_jobs WHERE project_id=? AND revision=?",
            (project_id, latest["revision"]),
        ).fetchone()
    status, error = (row["status"], row["error"]) if row else ("none", None)
    summary = None
    ready = False
    review = None
    if status in {"none", "done"}:
        try:
            saved = requirements.load_saved_requirements(db_path, latest["document_id"])
        except requirements.RequirementsError:
            saved = None
        if saved is not None:
            status = "done"
            summary = {
                "created_at": str(saved.get("created_at")),
                "detail_count": len(saved.get("details", {}).get("block_ids", [])),
                "warning_count": len(saved.get("warnings", [])),
            }
            with _open(db_path) as connection:
                review = specs.latest(connection, project_id, latest["revision"], saved)
                effective = specs.effective(connection, project_id, latest["revision"], saved)
            ready = bool(specs.active_items(effective)) if effective.get("specification") else specs.numbered(saved)
            summary.update(analysis_type="narrative" if review else "numbered" if specs.numbered(saved) else "undetermined",
                           review_status=review["status"] if review else saved.get("status"),
                           specification_id=review["id"] if review else None)
            if review:
                summary["detail_count"] = len(review["items"])
            if not ready:
                status = "needs_review"

        elif status == "done":
            status, error = "failed", "저장된 요구사항 결과를 찾을 수 없습니다."
    return {"status": status, "revision": latest["revision"], "error": error, "summary": summary,
            "ready": ready, "preview_available": summary is not None}


def _run_criteria(db_path: Path, project_id: str, revision: int, document_id: str,
                  *, force: bool = False) -> None:
    try:
        _set_job(db_path, "criteria_jobs", project_id, revision, "running")
        criteria.extract_and_save_criteria(document_id, db_path=db_path, force=force,
                                            project_id=project_id, upload_revision=revision)
        _set_job(db_path, "criteria_jobs", project_id, revision, "done")
    except (criteria.CriteriaError, requirements.RequirementsError) as error:
        _set_job(db_path, "criteria_jobs", project_id, revision, "failed", str(error))
    except Exception:
        traceback.print_exc()
        _set_job(db_path, "criteria_jobs", project_id, revision, "failed",
                 "평가기준 생성에 실패했습니다. 서버 로그를 확인해 주세요.")


def queue_criteria(db_path: Path, project_id: str, *, force: bool = False) -> dict:
    """CRT-01: 요구사항이 준비된 최신 제안요청서로 평가기준 초안을 만든다."""
    latest = latest_rfp(db_path, project_id)
    if latest is None:
        raise criteria.CriteriaError("등록된 제안요청서가 없습니다.")
    if requirements.load_saved_requirements(db_path, latest["document_id"]) is None:
        raise criteria.CriteriaError("제안 요구사항 추출이 끝난 뒤 평가기준을 생성할 수 있습니다.")
    state = requirement_status(db_path, project_id)
    if state.get("status") == "needs_review":
        raise criteria.CriteriaError("문서 단계에서 요구사항 명세서를 검토·확정한 뒤 평가표를 생성해 주세요.")
    current = criteria_status(db_path, project_id)
    if current["status"] in {"queued", "running"}:
        return current
    if force:
        _set_job(db_path, "criteria_jobs", project_id, latest["revision"], "failed", None)
    _queue(db_path, "criteria_jobs", project_id, latest["revision"],
           latest["document_id"], partial(_run_criteria, force=force))
    return criteria_status(db_path, project_id)


def _run_pipeline(db_path: Path, project_id: str, revision: int, document_id: str) -> None:
    """요구사항 추출 → 평가기준 생성을 한 작업으로 이어서 실행한다."""
    _run_requirements(db_path, project_id, revision, document_id)
    with _open(db_path) as connection:
        done = connection.execute(
            "SELECT status FROM requirement_jobs WHERE project_id=? AND revision=?",
            (project_id, revision)).fetchone()
    if done and done[0] == "done":
        _run_criteria(db_path, project_id, revision, document_id)
    else:
        _set_job(db_path, "criteria_jobs", project_id, revision, "failed",
                 "요구사항 추출이 끝나지 않아 평가기준을 만들지 못했습니다.")


def queue_pipeline(db_path: Path, project_id: str, *, force: bool = False) -> dict:
    """CRT-01 한 번 클릭: 요구사항이 없으면 추출부터, 있으면 평가기준 생성만 뒤에서 실행한다."""
    latest = latest_rfp(db_path, project_id)
    if latest is None:
        raise criteria.CriteriaError("등록된 제안요청서가 없습니다.")
    try:
        ready = requirements.load_saved_requirements(db_path, latest["document_id"]) is not None
    except requirements.RequirementsError:
        ready = False
    if ready:
        return queue_criteria(db_path, project_id, force=force)
    revision, document_id = latest["revision"], latest["document_id"]
    with _open(db_path) as connection:
        connection.executescript(JOB_SCHEMA)
        running = connection.execute(
            "SELECT 1 FROM requirement_jobs WHERE project_id=? AND revision=? AND status IN ('queued','running')",
            (project_id, revision)).fetchone() or connection.execute(
            "SELECT 1 FROM criteria_jobs WHERE project_id=? AND revision=? AND status IN ('queued','running')",
            (project_id, revision)).fetchone()
        if running:
            return criteria_status(db_path, project_id)
        for table in ("requirement_jobs", "criteria_jobs"):
            connection.execute(
                f"INSERT INTO {table} VALUES (?, ?, ?, 'queued', NULL, ?) "
                "ON CONFLICT(project_id, revision) DO UPDATE SET "
                "status='queued', error=NULL, updated_at=excluded.updated_at",
                (project_id, revision, document_id, _now()))
    EXTRACTOR.submit(_run_pipeline, db_path, project_id, revision, document_id)
    return criteria_status(db_path, project_id)


def criteria_status(db_path: Path, project_id: str) -> dict:
    """CRT-02: 초안 상태와 저장된 AI 초안(행·배점·근거)."""
    latest = latest_rfp(db_path, project_id)
    if latest is None:
        return {"status": "none", "revision": None, "requirements_ready": False,
                "error": None, "result": None}
    try:
        requirements_ready = requirements.load_saved_requirements(
            db_path, latest["document_id"]) is not None
    except requirements.RequirementsError:
        requirements_ready = False
    with _open(db_path) as connection:
        row = connection.execute(
            "SELECT status, error FROM criteria_jobs WHERE project_id=? AND revision=?",
            (project_id, latest["revision"]),
        ).fetchone()
    status, error = (row["status"], row["error"]) if row else ("none", None)
    saved = None
    if requirements_ready and status in {"none", "done"}:
        try:
            saved = criteria.load_saved_criteria(db_path, latest["document_id"],
                project_id=project_id, upload_revision=latest["revision"])
        except (criteria.CriteriaError, requirements.RequirementsError) as exc:
            saved, error = None, str(exc)
    if saved is not None:
        status = "done"
    elif status == "done":
        status, error = "failed", error or "저장된 평가기준 결과를 찾을 수 없습니다."
    result = None
    if saved is not None:
        result = {key: saved.get(key) for key in (
            "created_at", "template_source", "reference_filename", "total_score",
            "rows", "selection_rationale", "supplemental_items", "guideline_url", "_id",
            "source_specification_id", "requirement_mapping", "unmapped_requirements",
        )}
        result["created_at"] = str(result["created_at"])
    return {"status": status, "revision": latest["revision"],
            "requirements_ready": requirements_ready, "error": error, "result": result}
