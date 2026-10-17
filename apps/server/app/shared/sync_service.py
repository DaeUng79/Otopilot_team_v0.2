"""Trusted in-process delivery with durable inbox and ACK after local commit.

This receiver never accepts arbitrary browser envelopes. Documents owner can call
receive_document_snapshot from a trusted adapter after its approval transaction.
"""

import json
import sqlite3
from uuid import uuid4

from app.committee.committee_app.v2_core import digest, now, packed
from app.shared.db import DTO, Store, insert, require, rows


def ref(c: sqlite3.Connection, table: str, data: DTO, version: int) -> None:
    old = c.execute(f"SELECT * FROM {table} WHERE id=?", (data["id"],)).fetchone()
    checksum = digest(data)
    if old:
        require(
            old["source_version"] <= version, "역순 스냅샷입니다.", "STALE_SNAPSHOT"
        )
        if old["source_version"] == version:
            require(
                old["snapshot_sha256"] == checksum,
                "같은 버전의 내용이 다릅니다.",
                "SNAPSHOT_CONFLICT",
            )
            return
    values = {
        "source_version": version,
        "snapshot_sha256": checksum,
        "synced_at": now(),
        "is_deleted": 0,
    } | data
    if old:
        c.execute(
            f"UPDATE {table} SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
            (*values.values(), data["id"]),
        )
    else:
        insert(c, table, values)


def publish(
    c: sqlite3.Connection,
    contract: str,
    aggregate: str,
    version: int,
    payload: DTO,
    destination: str,
) -> str:
    event_id = str(uuid4())
    insert(
        c,
        "sync_outbox",
        {
            "event_id": event_id,
            "contract_name": contract,
            "schema_version": 2,
            "aggregate_id": aggregate,
            "aggregate_version": version,
            "destination": destination,
            "payload_json": packed(payload),
            "payload_sha256": digest(payload),
            "status": "PENDING",
            "retry_count": 0,
        },
    )
    return event_id


def inbox(c: sqlite3.Connection, event: DTO, source: str) -> bool:
    require(
        digest(json.loads(event["payload_json"])) == event["payload_sha256"],
        "연계 해시가 다릅니다.",
        "PAYLOAD_CORRUPT",
    )
    old = c.execute(
        "SELECT * FROM sync_inbox WHERE event_id=?", (event["event_id"],)
    ).fetchone()
    if old:
        require(
            old["payload_sha256"] == event["payload_sha256"],
            "이벤트 충돌입니다.",
            "EVENT_CONFLICT",
        )
        return old["status"] == "APPLIED"
    insert(
        c,
        "sync_inbox",
        {
            k: event[k]
            for k in (
                "event_id",
                "contract_name",
                "schema_version",
                "aggregate_id",
                "aggregate_version",
                "payload_json",
                "payload_sha256",
            )
        }
        | {"source": source, "status": "PENDING_PARENT"},
    )
    return False


def applied(c: sqlite3.Connection, event_id: str) -> None:
    c.execute(
        "UPDATE sync_inbox SET status='APPLIED',applied_at=?,error_code=NULL WHERE event_id=?",
        (now(), event_id),
    )


def publish_admin(c: sqlite3.Connection) -> None:
    from app.shared.integration_contracts import publish_admin_snapshots

    publish_admin_snapshots(c)


def deliver_outbox(s: Store) -> DTO:
    from app.shared.integration_contracts import deliver_admin

    delivered = deliver_admin(s)
    with s.connect() as e:
        finals = rows(
            e,
            "SELECT * FROM sync_outbox WHERE destination='admin' AND contract_name IN ('result.finalized','RESULT_FINALIZED','EVALUATION_OPENED') AND status<>'SENT' ORDER BY aggregate_version",
        )
    for event in finals:
        payload = json.loads(event["payload_json"])
        with s.connect("admin", True) as a:
            if not inbox(a, event, "evaluation"):
                status = (
                    "COMPLETED"
                    if event["contract_name"]
                    in {"result.finalized", "RESULT_FINALIZED"}
                    else "EVALUATING"
                )
                a.execute(
                    "UPDATE projects SET status=?,version=version+1,updated_at=? WHERE id=? AND status<>'COMPLETED'",
                    (status, now(), payload["project_id"]),
                )
                applied(a, event["event_id"])
        with s.connect(write=True) as e:
            e.execute(
                "UPDATE sync_outbox SET status='SENT',updated_at=?,version=version+1 WHERE event_id=?",
                (now(), event["event_id"]),
            )
    return {"delivered": delivered, "finalized": len(finals)}


def receive_document_snapshot(s: Store, event: DTO) -> DTO:
    """Internal integration contract: refs, whole approved tree and ready proposals."""
    require(
        event.get("contract_name") == "documents.approved.snapshot"
        and event.get("schema_version") == 2,
        "문서 계약 버전을 확인하세요.",
        "CONTRACT_INVALID",
    )
    p = json.loads(event["payload_json"])
    require(
        p["criteria"]["status"] == "APPROVED",
        "승인 평가표만 수신합니다.",
        "NOT_APPROVED",
    )
    pid = p["criteria"]["project_id"]
    require(
        all(
            r["project_id"] == pid for r in [p["binding"], *p["items"], *p["proposals"]]
        ),
        "문서 사업 범위가 다릅니다.",
        "SCOPE_CONFLICT",
    )
    require(
        all(
            r["approved_criteria_version_id"] == p["criteria"]["id"] for r in p["items"]
        ),
        "평가표 버전이 다릅니다.",
        "SCOPE_CONFLICT",
    )
    require(
        sum(i["max_score"] for i in p["items"] if i["is_scorable"])
        == p["criteria"]["total_max_score"],
        "평가표 배점 합계가 다릅니다.",
        "CRITERIA_INVALID",
    )
    with s.connect(write=True) as c:
        if inbox(c, event, "documents"):
            return {"status": "DUPLICATE", "event_id": event["event_id"]}
        if not c.execute("SELECT 1 FROM ref_projects WHERE id=?", (pid,)).fetchone():
            return {"status": "PENDING_PARENT", "event_id": event["event_id"]}
        ref(c, "ref_rfp_bindings", p["binding"], event["aggregate_version"])
        ref(
            c,
            "ref_approved_criteria_versions",
            p["criteria"],
            event["aggregate_version"],
        )
        remaining = list(p["items"])
        while remaining:
            ready = [
                i
                for i in remaining
                if i.get("parent_id") is None
                or c.execute(
                    "SELECT 1 FROM ref_approved_criteria_items WHERE id=?",
                    (i["parent_id"],),
                ).fetchone()
            ]
            require(
                ready, "평가항목 계층이 순환하거나 부모가 없습니다.", "CRITERIA_INVALID"
            )
            for item in ready:
                require(
                    item["score_step"] > 0 and item["max_score"] >= 0,
                    "평가항목 배점/간격을 확인하세요.",
                    "CRITERIA_INVALID",
                )
                ref(c, "ref_approved_criteria_items", item, event["aggregate_version"])
                remaining.remove(item)
        for proposal in p["proposals"]:
            ref(c, "ref_proposal_uploads", proposal, event["aggregate_version"])
        applied(c, event["event_id"])
    return {
        "status": "APPLIED",
        "event_id": event["event_id"],
        "payload_sha256": event["payload_sha256"],
    }
