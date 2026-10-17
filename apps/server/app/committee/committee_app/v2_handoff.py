"""Internal dispatcher boundary. Never expose envelopes to public web clients.

SENT means an APPLIED/DUPLICATE acknowledgement was verified (v2 outbox enum).
The evaluation owner implements receiving refs/inbox; this module writes admin DB only.
"""

import asyncio
import json
import sqlite3

from .v2_core import DTO, Context, ModuleError, Runtime, digest, now


async def pending_events(ctx: Context, *, runtime: Runtime, limit: int = 100) -> list[DTO]:
    if not 1 <= limit <= 200:
        raise ModuleError("INPUT_INVALID", "전송 건수는 1~200이어야 합니다.", 422)

    def read(conn: sqlite3.Connection) -> DTO:
        actor = runtime.authorize(conn, ctx)
        # Filter before LIMIT so one department cannot starve another department's queue.
        rows = conn.execute(
            "SELECT o.*,r.project_id FROM sync_outbox o "
            "JOIN committee_rosters r ON r.id=o.aggregate_id "
            "JOIN projects p ON p.id=r.project_id "
            "WHERE o.contract_name='roster.confirmed' AND o.status IN ('PENDING','FAILED') "
            "AND p.deleted_at IS NULL AND (?='SUPER_ADMIN' OR p.department_id=?) "
            "ORDER BY o.created_at,o.id LIMIT ?",
            (actor["role"], actor["department_id"], limit),
        ).fetchall()
        items = []
        for row in rows:
            runtime.project(conn, ctx, row["project_id"])
            payload = json.loads(row["payload_json"])
            if digest(payload) != row["payload_sha256"]:
                raise ModuleError("PAYLOAD_CORRUPT", "연계 데이터 해시가 일치하지 않습니다.")
            items.append(
                {
                    k: row[k]
                    for k in (
                        "event_id",
                        "contract_name",
                        "schema_version",
                        "aggregate_id",
                        "aggregate_version",
                        "destination",
                        "payload_sha256",
                        "project_id",
                    )
                }
                | {"source": "admin", "payload": payload, "occurred_at": row["created_at"]}
            )
        return {"items": items}

    result = await runtime.run(ctx, "HANDOFF-READ", {}, read, write=False)
    return list(result["items"])


async def acknowledge_event(ctx: Context, acknowledgement: DTO, *, runtime: Runtime) -> DTO:
    """Call only with a trusted receiver's ACK; an arbitrary HTTP body is not proof."""
    required = {"event_id", "payload_sha256", "aggregate_version", "schema_version", "status"}
    if set(acknowledgement) != required or acknowledgement["status"] not in {
        "APPLIED",
        "DUPLICATE",
    }:
        raise ModuleError("ACK_INVALID", "평가 모듈의 반영 완료 응답이 필요합니다.", 422)

    def acknowledge() -> DTO:
        with runtime.connect(write=True) as conn:
            runtime.authorize(conn, ctx)
            row = conn.execute(
                "SELECT * FROM sync_outbox WHERE event_id=? AND contract_name='roster.confirmed'",
                (acknowledgement["event_id"],),
            ).fetchone()
            if row is None:
                raise ModuleError("NOT_FOUND", "연계 이벤트를 찾을 수 없습니다.", 404)
            roster = conn.execute(
                "SELECT project_id FROM committee_rosters WHERE id=?", (row["aggregate_id"],)
            ).fetchone()
            runtime.project(conn, ctx, roster[0])
            if any(
                row[key] != acknowledgement[key]
                for key in ("payload_sha256", "aggregate_version", "schema_version")
            ):
                raise ModuleError("ACK_CONFLICT", "수신 응답의 버전 또는 해시가 일치하지 않습니다.")
            if row["status"] != "SENT":
                conn.execute(
                    "UPDATE sync_outbox SET "
                    "status='SENT',updated_at=?,version=version+1,last_error_code=NULL "
                    "WHERE id=?",
                    (now(), row["id"]),
                )
                runtime.audit(conn, ctx, "HANDOFF-ACK", "sync_outbox", row["id"], roster[0])
            return {"event_id": row["event_id"], "sync_status": "SENT"}

    return await asyncio.to_thread(acknowledge)
