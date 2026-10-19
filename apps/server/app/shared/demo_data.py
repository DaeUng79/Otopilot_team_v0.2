"""Explicit --demo only. Synthetic identities and approval fixture, isolated files."""

import hashlib
from pathlib import Path
from uuid import uuid4

from app.committee import committee_roster
from app.committee import committee_selection
from app.admin.admin_service import PERMISSIONS
from app.admin.auth_service import password_hash
from app.committee.committee_app.v2_core import Context, digest, now, packed
from app.committee.committee_app.v2_web_demo import seed_demo
from app.shared.db import DTO, Store, insert, rows
from app.shared.sync_service import deliver_outbox, receive_document_snapshot

DEMO_PASSWORD = "DemoOnly!2026"
DEMO_PROJECT = "demo-evaluation"


def samples(root: Path | None) -> list[DTO]:
    if root is None or not root.is_dir():
        return []
    hwpx = sorted(root.rglob("*.hwpx"))
    rfps = [p for p in hwpx if "제안요청서" in p.name]
    proposals = [p for p in hwpx if "식별정보" in p.name]
    pdfs = sorted(
        [
            p
            for p in root.rglob("*")
            if p.suffix.lower() == ".pdf" and "정성" in str(p.parent)
        ]
    )
    chosen = (
        ([("rfp", rfps[0])] if rfps else [])
        + ([("proposal-A", proposals[0])] if proposals else [])
        + ([("proposal-B", pdfs[0])] if pdfs else [])
    )
    return [
        {
            "id": key,
            "path": str(path.resolve()),
            "format": path.suffix[1:].upper(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for key, path in chosen
    ]


async def seed(s: Store, sample_root: Path | None = None) -> None:
    await seed_demo(s.runtime)
    with s.connect("admin", True) as c:
        if not c.execute(
            "SELECT 1 FROM admin_users WHERE username='super-demo'"
        ).fetchone():
            insert(
                c,
                "admin_users",
                {
                    "id": "super-demo",
                    "username": "super-demo",
                    "display_name": "가상 총괄관리자",
                    "role": "SUPER_ADMIN",
                    "password_hash": password_hash(DEMO_PASSWORD),
                    "active": 1,
                    "password_changed_at": now(),
                },
            )
            c.execute(
                "UPDATE admin_users SET password_hash=?,password_changed_at=? WHERE id=?",
                (password_hash(DEMO_PASSWORD), now(), "web-demo-admin"),
            )
            for permission in PERMISSIONS - {"MANAGE_ADMINS"}:
                insert(
                    c,
                    "admin_permissions",
                    {
                        "admin_id": "web-demo-admin",
                        "permission_code": permission,
                        "granted_by": "super-demo",
                    },
                )
            insert(
                c,
                "departments",
                {
                    "id": "other-dept",
                    "organization_name": "가상기관",
                    "name": "다른 부서",
                    "code": "OTHER",
                    "active": 1,
                },
            )
            insert(
                c,
                "admin_users",
                {
                    "id": "other-admin",
                    "department_id": "other-dept",
                    "username": "other-demo",
                    "display_name": "다른 부서 관리자",
                    "role": "DEPARTMENT_ADMIN",
                    "password_hash": password_hash(DEMO_PASSWORD),
                    "active": 1,
                    "password_changed_at": now(),
                },
            )
            for permission in PERMISSIONS - {"MANAGE_ADMINS"}:
                insert(
                    c,
                    "admin_permissions",
                    {
                        "admin_id": "other-admin",
                        "permission_code": permission,
                        "granted_by": "super-demo",
                    },
                )
        if not c.execute(
            "SELECT 1 FROM projects WHERE id=?", (DEMO_PROJECT,)
        ).fetchone():
            insert(
                c,
                "projects",
                {
                    "id": DEMO_PROJECT,
                    "department_id": "web-demo-dept",
                    "name": "가상사업 · 제안서 평가 통합 시연",
                    "contact_organization": "가상기관",
                    "contact_department": "시연 부서",
                    "contact_position": "담당",
                    "contact_name": "가상담당자",
                    "contact_phone_cipher": s.runtime.encrypt(
                        "01000000000", DEMO_PROJECT + ":phone"
                    ),
                    "status": "PREPARING",
                    "created_by": "web-demo-admin",
                },
            )
            for i in range(2):
                insert(
                    c,
                    "project_vendors",
                    {
                        "id": f"demo-vendor-{i}",
                        "project_id": DEMO_PROJECT,
                        "display_code": chr(65 + i),
                        "legal_name": f"가상업체 {chr(65 + i)}",
                        "sort_order": i,
                        "active": 1,
                    },
                )
    ctx = lambda: Context("web-demo-admin", str(uuid4()))
    with s.connect("admin") as c:
        roster = c.execute(
            "SELECT 1 FROM committee_rosters WHERE project_id=?", (DEMO_PROJECT,)
        ).fetchone()
    if not roster:
        rule = await committee_selection.save_rules(
            ctx(),
            {
                "project_id": DEMO_PROJECT,
                "selection_mode": "DIRECT",
                "target_count": 7,
                "reserve_count": 1,
                "quotas": [],
                "version": 0,
            },
            runtime=s.runtime,
        )
        with s.connect("admin") as c:
            candidates = rows(
                c,
                "SELECT id FROM evaluator_candidates WHERE department_id='web-demo-dept' AND pool_member=1 AND active=1 ORDER BY name LIMIT 8",
            )
        members = []
        for index, candidate in enumerate(candidates):
            nominee = await committee_roster.add_nominee(
                ctx(),
                {"project_id": DEMO_PROJECT, "candidate_id": candidate["id"]},
                runtime=s.runtime,
            )
            contacted = await committee_roster.save_contact(
                ctx(),
                {
                    "project_id": DEMO_PROJECT,
                    "nominee_id": nominee["id"],
                    "version": nominee["version"],
                    "contact_status": "AVAILABLE",
                    "contact_note": "가상 시연 연락 확인",
                },
                runtime=s.runtime,
            )
            members.append(
                {
                    "nominee_id": nominee["id"],
                    "version": contacted["version"],
                    "member_kind": "PRIMARY" if index < 7 else "RESERVE",
                    "reserve_order": 1 if index == 7 else None,
                }
            )
        await committee_roster.confirm_roster(
            ctx(),
            {
                "project_id": DEMO_PROJECT,
                "rule_version": rule["version"],
                "members": members,
            },
            runtime=s.runtime,
        )
    deliver_outbox(s)
    files = samples(sample_root)
    (s.evaluation_path.parent / "sample-manifest.json").write_text(
        packed(files), "utf8"
    )
    with s.connect() as c:
        if c.execute(
            "SELECT 1 FROM ref_approved_criteria_versions WHERE id='demo-criteria'"
        ).fetchone():
            return
    by_id = {f["id"]: f for f in files}
    rfp = by_id.get("rfp", {"sha256": digest("synthetic-rfp")})
    binding = {
        "id": "demo-rfp-binding",
        "project_id": DEMO_PROJECT,
        "upload_revision": 1,
        "document_id": rfp["sha256"],
        "parse_revision": "demo-fixture-v1",
    }
    criteria = {
        "id": "demo-criteria",
        "project_id": DEMO_PROJECT,
        "rfp_binding_id": binding["id"],
        "approval_no": 1,
        "total_max_score": 1000000,
        "status": "APPROVED",
        "approved_snapshot_json": packed(
            {
                "synthetic": True,
                "notice": "시연 전용 평가표. 원문 AI 추출 또는 실제 사람 승인 결과가 아닙니다.",
            }
        ),
        "approved_at": now(),
    }
    items = [
        {
            "id": f"demo-criterion-{i}",
            "project_id": DEMO_PROJECT,
            "approved_criteria_version_id": "demo-criteria",
            "parent_id": None,
            "code": f"C{i + 1}",
            "title": title,
            "description": "가상 기준 · 근거를 확인하고 배점 범위 내 입력",
            "is_scorable": 1,
            "max_score": score * 10000,
            "score_step": 10000,
            "sort_order": i,
        }
        for i, (title, score) in enumerate(
            [("사업 이해도", 30), ("수행 방법", 40), ("운영 및 지원", 30)]
        )
    ]
    proposals = [
        {
            "id": f"demo-proposal-{i}",
            "project_id": DEMO_PROJECT,
            "vendor_id": f"demo-vendor-{i}",
            "upload_revision": 1,
            "document_id": by_id.get(
                "proposal-" + chr(65 + i), {"sha256": digest(f"synthetic-proposal-{i}")}
            )["sha256"],
            "parse_revision": "demo-fixture-v1",
            "format": by_id.get("proposal-" + chr(65 + i), {}).get("format", "PDF"),
            "status": "READY",
        }
        for i in range(2)
    ]
    payload = {
        "binding": binding,
        "criteria": criteria,
        "items": items,
        "proposals": proposals,
    }
    receive_document_snapshot(
        s,
        {
            "event_id": "demo-approved-documents-v1",
            "contract_name": "documents.approved.snapshot",
            "schema_version": 2,
            "aggregate_id": DEMO_PROJECT,
            "aggregate_version": 1,
            "payload_json": packed(payload),
            "payload_sha256": digest(payload),
        },
    )
