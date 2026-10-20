"""Shared SQLite cache for one evaluation item's proposal summaries.

Only the worker holding a short lease calls the model. Other evaluator requests
wait for the committed result; a failed or abandoned lease can be retried.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Callable

from .db import connect, digest, now
from .envelope import ApiError

LEASE_SECONDS = 90
WAIT_SECONDS = 45


def get_or_generate(db_path: Path, *, project_id: str, session_id: str,
                    criterion_id: str, fingerprint: dict,
                    processor_version: str,
                    generate: Callable[[], dict[str, str]]) -> dict[str, str]:
    """Return a committed result shared by every evaluator in the session."""
    input_sha256 = digest({"processor_version": processor_version, **fingerprint})
    key = (session_id, criterion_id, input_sha256)
    owner = uuid.uuid4().hex
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        with connect(db_path, write=True) as conn:
            row = conn.execute(
                "SELECT status, owner_token, lease_until, summaries_json "
                "FROM proposal_item_summaries WHERE session_id=? AND criterion_id=? AND input_sha256=?",
                key).fetchone()
            if row and row["status"] == "complete":
                return json.loads(row["summaries_json"])
            current = time.time()
            if not row:
                stamp = now()
                conn.execute(
                    "INSERT INTO proposal_item_summaries "
                    "(project_id,session_id,criterion_id,input_sha256,processor_version,status,owner_token,lease_until,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,'generating',?,?,?,?)",
                    (project_id, session_id, criterion_id, input_sha256, processor_version,
                     owner, current + LEASE_SECONDS, stamp, stamp))
                claimed = True
            elif (row["lease_until"] or 0) < current:
                conn.execute(
                    "UPDATE proposal_item_summaries SET owner_token=?,lease_until=?,updated_at=? "
                    "WHERE session_id=? AND criterion_id=? AND input_sha256=?",
                    (owner, current + LEASE_SECONDS, now(), *key))
                claimed = True
            else:
                claimed = False
        if claimed:
            break
        if time.monotonic() >= deadline:
            raise ApiError("UPSTREAM_UNAVAILABLE", "AI 정리 결과를 기다리는 시간이 초과됐습니다.", 503, retryable=True)
        time.sleep(0.2)

    try:
        summaries = generate()
        with connect(db_path, write=True) as conn:
            changed = conn.execute(
                "UPDATE proposal_item_summaries SET status='complete',owner_token=NULL,lease_until=NULL," 
                "summaries_json=?,updated_at=? WHERE session_id=? AND criterion_id=? AND input_sha256=? "
                "AND owner_token=? AND status='generating'",
                (json.dumps(summaries, ensure_ascii=False, sort_keys=True), now(), *key, owner)).rowcount
        if changed:
            return summaries
        # A slow worker lost its lease. Use the replacement worker's result.
        return get_or_generate(db_path, project_id=project_id, session_id=session_id,
                               criterion_id=criterion_id, fingerprint=fingerprint,
                               processor_version=processor_version, generate=generate)
    except BaseException:
        with connect(db_path, write=True) as conn:
            conn.execute(
                "DELETE FROM proposal_item_summaries WHERE session_id=? AND criterion_id=? "
                "AND input_sha256=? AND owner_token=? AND status='generating'",
                (*key, owner))
        raise
