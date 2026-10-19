"""Named v2 contracts from handoff section 08; internal adapters, not browser APIs."""

from __future__ import annotations

import json
import sqlite3

from app.committee.committee_app.v2_core import ModuleError, digest, now, packed
from app.shared.db import DTO, Store, insert, require, rows
from app.shared.sync_service import applied, inbox, publish, ref


def publish_admin_snapshots(c: sqlite3.Connection) -> None:
    snapshots = []
    for row in rows(
        c, "SELECT id,department_id,name,status,version,deleted_at FROM projects"
    ):
        payload = {
            k: row[k] for k in ("department_id", "name", "status", "version")
        } | {"project_id": row["id"], "is_deleted": int(row["deleted_at"] is not None)}
        snapshots.append(("project.snapshot", row["id"], row["version"], payload))
    for row in rows(
        c,
        "SELECT id,department_id,role,display_name,active,version,deleted_at FROM admin_users",
    ):
        payload = {k: v for k, v in row.items() if k != "deleted_at"} | {
            "is_deleted": int(row["deleted_at"] is not None),
            "permission_codes": [
                r[0]
                for r in c.execute(
                    "SELECT permission_code FROM admin_permissions WHERE admin_id=? ORDER BY permission_code",
                    (row["id"],),
                )
            ],
        }
        snapshots.append(("admin.projection", row["id"], row["version"], payload))
    for row in rows(
        c,
        "SELECT id,project_id,display_code,sort_order,active,version,deleted_at FROM project_vendors",
    ):
        payload = {k: v for k, v in row.items() if k != "deleted_at"} | {
            "is_deleted": int(row["deleted_at"] is not None)
        }
        snapshots.append(("vendor.snapshot", row["id"], row["version"], payload))
    for contract, identity, version, payload in snapshots:
        for destination in ("evaluation", "documents"):
            previous = c.execute(
                "SELECT payload_sha256,aggregate_version FROM sync_outbox WHERE contract_name=? AND aggregate_id=? AND destination=? ORDER BY aggregate_version DESC LIMIT 1",
                (contract, identity, destination),
            ).fetchone()
            if previous and previous["aggregate_version"] == version:
                require(
                    previous["payload_sha256"] == digest(payload),
                    "원본 버전 증가 없이 스냅샷이 변경되었습니다.",
                    "SOURCE_VERSION_CONFLICT",
                )
                continue
            if not previous or previous["aggregate_version"] < version:
                publish(c, contract, identity, version, payload, destination)


def normalize(envelope: DTO) -> DTO:
    event = {
        k: envelope[k]
        for k in (
            "event_id",
            "contract_name",
            "schema_version",
            "aggregate_id",
            "aggregate_version",
            "payload_sha256",
        )
    }
    event["payload_json"] = envelope.get("payload_json") or packed(envelope["payload"])
    require(
        event["schema_version"] == 2
        and type(event["aggregate_version"]) is int
        and event["aggregate_version"] > 0,
        "연계 스키마/버전을 확인하세요.",
        "CONTRACT_INVALID",
    )
    return event


def apply_event(store: Store, envelope: DTO, source: str) -> DTO:
    event = normalize(envelope)
    allowed = {
        "admin": {
            "project.snapshot",
            "admin.projection",
            "vendor.snapshot",
            "roster.confirmed",
        },
        "documents": {"rfp.bound", "criteria.approved", "proposal.ready", "proposal.archived"},
    }
    require(
        event["contract_name"] in allowed.get(source, set()),
        "출처와 계약이 일치하지 않습니다.",
        "CONTRACT_INVALID",
    )
    result = {
        k: event[k]
        for k in ("event_id", "schema_version", "aggregate_version", "payload_sha256")
    }
    try:
        with store.connect(write=True) as c:
            if inbox(c, event, source):
                return result | {"status": "DUPLICATE"}
            p = json.loads(event["payload_json"])
            contract = event["contract_name"]
            version = event["aggregate_version"]
            pid = p.get("project_id")
            if (
                contract not in {"project.snapshot", "admin.projection"}
                and not c.execute(
                    "SELECT 1 FROM ref_projects WHERE id=?", (pid,)
                ).fetchone()
            ):
                return result | {"status": "PENDING_PARENT"}
            if contract == "project.snapshot":
                require(
                    p.get("version") == version,
                    "사업 버전이 다릅니다.",
                    "CONTRACT_INVALID",
                )
                ref(
                    c,
                    "ref_projects",
                    {k: p[k] for k in ("department_id", "name", "status")}
                    | {"id": pid, "is_deleted": p.get("is_deleted", 0)},
                    version,
                )
            elif contract == "admin.projection":
                require(
                    p.get("version") == version,
                    "관리자 버전이 다릅니다.",
                    "CONTRACT_INVALID",
                )
                ref(
                    c,
                    "ref_admin_users",
                    {
                        k: p[k]
                        for k in (
                            "id",
                            "department_id",
                            "role",
                            "display_name",
                            "active",
                        )
                    }
                    | {
                        "permission_codes_json": packed(p["permission_codes"]),
                        "is_deleted": p.get("is_deleted", 0),
                    },
                    version,
                )
            elif contract == "vendor.snapshot":
                require(
                    p.get("version") == version,
                    "업체 버전이 다릅니다.",
                    "CONTRACT_INVALID",
                )
                ref(
                    c,
                    "ref_project_vendors",
                    {
                        k: p[k]
                        for k in (
                            "id",
                            "project_id",
                            "display_code",
                            "sort_order",
                            "active",
                        )
                    }
                    | {"is_deleted": p.get("is_deleted", 0)},
                    version,
                )
            elif contract == "roster.confirmed":
                require(
                    digest(p["assignments"]) == p["roster_sha256"],
                    "명단 해시가 다릅니다.",
                    "PAYLOAD_CORRUPT",
                )
                require(
                    all(
                        a["project_id"] == pid and a["roster_id"] == p["roster_id"]
                        for a in p["assignments"]
                    ),
                    "명단 범위가 다릅니다.",
                    "SCOPE_CONFLICT",
                )
                ref(
                    c,
                    "ref_committee_rosters",
                    {
                        "id": p["roster_id"],
                        "project_id": pid,
                        "revision_no": p["revision_no"],
                        "status": p["status"],
                        "roster_sha256": p["roster_sha256"],
                    },
                    version,
                )
                for a in p["assignments"]:
                    ref(c, "ref_committee_assignments", a, version)
            elif contract == "rfp.bound":
                binding = {
                    k: p[k]
                    for k in (
                        "project_id",
                        "upload_revision",
                        "document_id",
                        "parse_revision",
                    )
                }
                ref(c, "ref_rfp_bindings", binding | {"id": digest(binding)}, version)
            elif contract in {"proposal.ready", "proposal.archived"}:
                if not c.execute(
                    "SELECT 1 FROM ref_project_vendors WHERE id=? AND project_id=?",
                    (p["vendor_id"], pid),
                ).fetchone():
                    return result | {"status": "PENDING_PARENT"}
                status = "READY" if contract == "proposal.ready" else "ARCHIVED"
                # 제안서 형식: 설계 HWPX/PDF + 샘플 자료의 HWP/PPTX (2026-10-18)
                require(
                    p.get("status") == status
                    and p["format"] in {"HWPX", "PDF", "HWP", "PPTX"},
                    "제안서 상태와 지원 형식을 확인하세요.",
                    "NOT_READY",
                )
                data = {
                    k: p[k]
                    for k in (
                        "project_id",
                        "vendor_id",
                        "upload_revision",
                        "document_id",
                        "parse_revision",
                        "format",
                    )
                }
                ref(
                    c,
                    "ref_proposal_uploads",
                    data | {"id": p["proposal_upload_id"], "status": status},
                    version,
                )
            else:
                require(
                    p.get("status") == "APPROVED",
                    "승인 평가표만 수신합니다.",
                    "NOT_APPROVED",
                )
                require(
                    p.get("snapshot_sha256") == digest(p["items"]),
                    "승인 항목 해시를 확인하세요.",
                    "PAYLOAD_CORRUPT",
                )
                pin = p["rfp_pin"]
                binding_id = digest(
                    {
                        k: pin[k]
                        for k in (
                            "project_id",
                            "upload_revision",
                            "document_id",
                            "parse_revision",
                        )
                    }
                )
                require(
                    pin["project_id"] == pid,
                    "고정 원문 사업이 다릅니다.",
                    "SCOPE_CONFLICT",
                )
                if not c.execute(
                    "SELECT 1 FROM ref_rfp_bindings WHERE id=? AND project_id=?",
                    (binding_id, pid),
                ).fetchone():
                    return result | {"status": "PENDING_PARENT"}
                items = p["items"]
                require(
                    items and len({i["id"] for i in items}) == len(items),
                    "항목 중복 또는 빈 평가표입니다.",
                    "CRITERIA_INVALID",
                )
                require(
                    all(
                        i["project_id"] == pid
                        and i["approved_criteria_version_id"] == p["id"]
                        for i in items
                    ),
                    "항목 범위가 다릅니다.",
                    "SCOPE_CONFLICT",
                )
                require(
                    sum(i["max_score"] for i in items if i["is_scorable"])
                    == p["total_max_score"],
                    "말단 배점 합계가 다릅니다.",
                    "CRITERIA_INVALID",
                )
                require(
                    not any(
                        i["is_scorable"]
                        and any(child.get("parent_id") == i["id"] for child in items)
                        for i in items
                    ),
                    "상위 항목은 채점할 수 없습니다.",
                    "CRITERIA_INVALID",
                )
                ref(
                    c,
                    "ref_approved_criteria_versions",
                    {
                        k: p[k]
                        for k in (
                            "id",
                            "project_id",
                            "approval_no",
                            "total_max_score",
                            "status",
                            "approved_at",
                        )
                    }
                    | {
                        "rfp_binding_id": binding_id,
                        "approved_snapshot_json": packed(p),
                    },
                    version,
                )
                pending = list(items)
                seen = set()
                while pending:
                    ready = [
                        i
                        for i in pending
                        if i.get("parent_id") is None or i["parent_id"] in seen
                    ]
                    require(ready, "항목 부모/순환을 확인하세요.", "CRITERIA_INVALID")
                    for item in ready:
                        require(
                            type(item["max_score"]) is int
                            and item["max_score"] >= 0
                            and type(item["score_step"]) is int
                            and item["score_step"] > 0,
                            "정수 배점/간격을 확인하세요.",
                            "CRITERIA_INVALID",
                        )
                        ref(c, "ref_approved_criteria_items", item, version)
                        seen.add(item["id"])
                        pending.remove(item)
            applied(c, event["event_id"])
            return result | {"status": "APPLIED"}
    except ModuleError as exc:
        with store.connect(write=True) as c:
            previous = c.execute(
                "SELECT payload_sha256,status FROM sync_inbox WHERE event_id=?",
                (event["event_id"],),
            ).fetchone()
            if previous is None:
                insert(
                    c,
                    "sync_inbox",
                    event
                    | {"source": source, "status": "REJECTED", "error_code": exc.code},
                )
            elif (
                previous["payload_sha256"] == event["payload_sha256"]
                and previous["status"] != "APPLIED"
            ):
                c.execute(
                    "UPDATE sync_inbox SET status='REJECTED',error_code=? WHERE event_id=?",
                    (exc.code, event["event_id"]),
                )
        raise


def deliver_admin(store: Store) -> int:
    with store.connect("admin", True) as c:
        publish_admin_snapshots(c)
    with store.connect("admin") as c:
        events = rows(
            c,
            "SELECT * FROM sync_outbox WHERE destination='evaluation' AND status<>'SENT' AND contract_name IN ('project.snapshot','admin.projection','vendor.snapshot','roster.confirmed') ORDER BY CASE contract_name WHEN 'project.snapshot' THEN 0 WHEN 'admin.projection' THEN 1 WHEN 'vendor.snapshot' THEN 2 ELSE 3 END,aggregate_version,created_at",
        )
    count = 0
    for event in events:
        result = apply_event(store, event, "admin")
        if result["status"] not in {"APPLIED", "DUPLICATE"}:
            continue
        with store.connect("admin", True) as c:
            c.execute(
                "UPDATE sync_outbox SET status='SENT',version=version+1,updated_at=? WHERE event_id=? AND payload_sha256=?",
                (now(), event["event_id"], result["payload_sha256"]),
            )
        count += 1
    return count
