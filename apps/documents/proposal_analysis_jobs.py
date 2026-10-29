"""제안서 2차 분석을 HTTP 요청과 분리해 실행한다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from . import proposal_analysis as analysis

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="proposal-analysis")
_lock = Lock()
_jobs: dict[str, dict] = {}


def status(project_id: str) -> dict:
    with _lock:
        return {"jobs": {upload_id: dict(job) for upload_id, job in _jobs.items()
                         if job["project_id"] == project_id}}


def queue(db: Path, project_id: str, proposal_upload_id: str) -> dict:
    # Validate sources before acknowledging the job. The worker rechecks them
    # before saving each item, so a changed upload cannot publish stale results.
    with closing(analysis._connect(db, readonly=True)) as conn:
        _, proposals = analysis._source(conn, project_id, None)
    if proposal_upload_id not in {proposal["id"] for proposal in proposals}:
        raise ValueError("현재 업체의 최신 READY 제안서를 선택해 주세요.")
    with _lock:
        current = _jobs.get(proposal_upload_id)
        if current and current["status"] in {"queued", "running"}:
            return dict(current)
        job = {"project_id": project_id, "proposal_upload_id": proposal_upload_id,
               "status": "queued", "error": None,
               "updated_at": datetime.now(timezone.utc).isoformat()}
        _jobs[proposal_upload_id] = job
        _executor.submit(_run, db, project_id, proposal_upload_id)
        return dict(job)


def _run(db: Path, project_id: str, proposal_upload_id: str) -> None:
    with _lock:
        _jobs[proposal_upload_id].update(status="running", updated_at=datetime.now(timezone.utc).isoformat())
    try:
        analysis.run(db, project_id, proposal_id=proposal_upload_id)
    except Exception as error:
        with _lock:
            _jobs[proposal_upload_id].update(status="failed", error=str(error),
                                             updated_at=datetime.now(timezone.utc).isoformat())
    else:
        with _lock:
            _jobs[proposal_upload_id].update(status="done", error=None,
                                             updated_at=datetime.now(timezone.utc).isoformat())
