"""행위 감사 기록. 전화번호·HMAC·비밀키·서명 이미지는 detail 에 넣지 않는다."""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import new_id, now, packed

FORBIDDEN_DETAIL_KEYS = {"phone", "last4", "login_lookup_hmac", "token", "image", "image_blob", "secret"}


def record(
    conn: sqlite3.Connection,
    *,
    actor_type: str,
    actor_id: str | None,
    project_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    detail: dict[str, Any] | None = None,
) -> str:
    safe = {k: v for k, v in (detail or {}).items() if k not in FORBIDDEN_DETAIL_KEYS}
    event_id = new_id()
    stamp = now()
    conn.execute(
        "INSERT INTO audit_events (id, created_at, updated_at, version, actor_type, actor_id, project_id, "
        "action, entity_type, entity_id, detail_json) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, stamp, stamp, actor_type, actor_id, project_id, action, entity_type, entity_id, packed(safe)),
    )
    return event_id
