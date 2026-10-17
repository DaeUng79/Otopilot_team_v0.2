"""읽기·감사 기록용 SQLite 연결. 모든 연결은 PRAGMA foreign_keys=ON 이고 확인 결과가 1이 아니면 거절한다."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .envelope import ApiError


def now() -> str:
    return datetime.now(UTC).isoformat()


def later(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def new_id() -> str:
    return str(uuid.uuid4())


def packed(value: Any) -> str:
    """정규화 JSON: 재귀적 키 정렬·UTF-8·공백 없음 (위원 모듈 v2_core.packed 와 동일)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(packed(value).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=20)
    else:
        conn = sqlite3.connect(path, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA foreign_keys=ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        conn.close()
        raise RuntimeError("SQLite foreign_keys 를 켤 수 없습니다.")
    return conn


@contextmanager
def connect(path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """평가 DB 연결. write=True 면 BEGIN IMMEDIATE 로 시작하고 성공 시 commit, 예외 시 rollback."""
    with closing(_open(path)) as conn:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        else:
            conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


@contextmanager
def connect_documents(path: Path | None) -> Iterator[sqlite3.Connection]:
    """문서 DB(오대웅 모듈) 읽기 전용 연결. 쓰기는 step0 서버만 한다."""
    if path is None or not path.is_file():
        raise ApiError("UPSTREAM_UNAVAILABLE", "문서 DB 에 연결할 수 없어요.", 503, retryable=True)
    with closing(_open(path, readonly=True)) as conn:
        yield conn

