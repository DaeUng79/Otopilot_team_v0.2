"""ROS-01..06: contact decisions, final invitations and atomic evaluation handoff."""

import sqlite3
from collections import Counter
from uuid import uuid4

from app.committee.candidate_pool import _candidate, _nominee, _read
from app.committee.committee_app.v2_contracts import (
    AddNominee,
    ConfirmRoster,
    Contact,
    Exclude,
    ExportRoster,
    NomineeQuery,
)
from app.committee.committee_app.v2_core import (
    DTO,
    Context,
    ExportFile,
    ModuleError,
    Runtime,
    digest,
    now,
    packed,
    validate,
    version,
)
from app.committee.committee_app.v2_excel import export_xlsx


def _get(conn: sqlite3.Connection, project_id: str, nominee_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM project_nominees WHERE id=? AND project_id=?", (nominee_id, project_id)
    ).fetchone()
    if row is None:
        raise ModuleError("NOT_FOUND", "사업 후보를 찾을 수 없습니다.", 404)
    return row


async def list_nominees(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(NomineeQuery, command)

    def read(conn: sqlite3.Connection) -> DTO:
        runtime.project(conn, ctx, body.project_id)
        items = []
        for row in conn.execute(
            "SELECT * FROM project_nominees WHERE project_id=? ORDER BY created_at,id",
            (body.project_id,),
        ):
            candidate = _read(conn, runtime, _candidate(conn, ctx, runtime, row["candidate_id"]))
            if body.contact_status and row["contact_status"] != body.contact_status:
                continue
            if body.specialty_id and body.specialty_id not in candidate["specialty_ids"]:
                continue
            items.append(dict(row) | {"candidate": candidate})
        rule = conn.execute(
            "SELECT * FROM committee_rules WHERE project_id=?", (body.project_id,)
        ).fetchone()
        confirmed = conn.execute(
            "SELECT * FROM committee_rosters WHERE project_id=? AND status='CONFIRMED'",
            (body.project_id,),
        ).fetchone()
        return {
            "items": items,
            "total": len(items),
            "rule": dict(rule) if rule else None,
            "roster": dict(confirmed) if confirmed else None,
        }

    return await runtime.run(ctx, "ROS-01", body.model_dump(), read, write=False)


async def add_nominee(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(AddNominee, command)

    def add(conn: sqlite3.Connection) -> DTO:
        project = runtime.project(conn, ctx, body.project_id, edit=True)
        candidate = _candidate(conn, ctx, runtime, body.candidate_id)
        if candidate["department_id"] != project["department_id"]:
            raise ModuleError("FORBIDDEN", "사업과 후보의 부서가 다릅니다.", 403)
        if not candidate["active"] or candidate["deleted_at"]:
            raise ModuleError("CANDIDATE_INACTIVE", "활성 후보만 사업에 등록할 수 있습니다.")
        nid = _nominee(conn, runtime, body.project_id, body.candidate_id)
        runtime.audit(conn, ctx, "ROS-02", "project_nominees", nid, body.project_id)
        return dict(_get(conn, body.project_id, nid))

    return await runtime.run(ctx, "ROS-02", body.model_dump(), add)


async def save_contact(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(Contact, command)

    def save(conn: sqlite3.Connection) -> DTO:
        runtime.project(conn, ctx, body.project_id, edit=True)
        runtime.unlocked(conn, body.project_id)
        row = _get(conn, body.project_id, body.nominee_id)
        version(row, body.version)
        if row["exclusion_reason"]:
            raise ModuleError("NOMINEE_EXCLUDED", "제외된 후보의 연락 결과는 변경할 수 없습니다.")
        conn.execute(
            "UPDATE project_nominees SET "
            "contact_status=?,contact_note=?,contacted_at=?,contacted_by=?,"
            "updated_at=?,version=version+1 WHERE id=?",
            (body.contact_status, body.contact_note, now(), ctx.actor_id, now(), body.nominee_id),
        )
        runtime.audit(conn, ctx, "ROS-03", "project_nominees", body.nominee_id, body.project_id)
        return dict(_get(conn, body.project_id, body.nominee_id))

    return await runtime.run(ctx, "ROS-03", body.model_dump(), save)


async def exclude_nominee(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(Exclude, command)

    def exclude(conn: sqlite3.Connection) -> DTO:
        runtime.project(conn, ctx, body.project_id, edit=True)
        runtime.unlocked(conn, body.project_id)
        row = _get(conn, body.project_id, body.nominee_id)
        version(row, body.version)
        conn.execute(
            "UPDATE project_nominees SET "
            "exclusion_reason=?,updated_at=?,version=version+1 WHERE id=?",
            (body.reason, now(), body.nominee_id),
        )
        runtime.audit(conn, ctx, "ROS-04", "project_nominees", body.nominee_id, body.project_id)
        return dict(_get(conn, body.project_id, body.nominee_id))

    return await runtime.run(ctx, "ROS-04", body.model_dump(), exclude)


async def confirm_roster(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(ConfirmRoster, command)

    def confirm(conn: sqlite3.Connection) -> DTO:
        runtime.project(conn, ctx, body.project_id, edit=True)
        runtime.unlocked(conn, body.project_id)
        rule = conn.execute(
            "SELECT * FROM committee_rules WHERE project_id=?", (body.project_id,)
        ).fetchone()
        if rule is None:
            raise ModuleError("RULE_REQUIRED", "선정 규칙을 먼저 저장하세요.")
        version(rule, body.rule_version)
        primary = [m for m in body.members if m.member_kind == "PRIMARY"]
        reserves = [m for m in body.members if m.member_kind == "RESERVE"]
        reserve_count = rule["reserve_count"] if body.reserve_count is None else body.reserve_count
        if len(primary) != rule["target_count"] or len(reserves) != reserve_count:
            raise ModuleError("ROSTER_COUNT", "정위원·예비위원 수가 선정 규칙과 다릅니다.", 422)
        if len({m.nominee_id for m in body.members}) != len(body.members):
            raise ModuleError("DUPLICATE_MEMBER", "동일 후보를 중복 배정할 수 없습니다.", 422)
        if sorted(m.reserve_order for m in reserves if m.reserve_order is not None) != list(
            range(1, len(reserves) + 1)
        ):
            raise ModuleError("RESERVE_ORDER", "예비 순위는 1부터 연속이어야 합니다.", 422)
        rid, assignments, login_keys = str(uuid4()), [], set()
        primary_fields: Counter[str] = Counter()
        for member in body.members:
            nominee = _get(conn, body.project_id, member.nominee_id)
            version(nominee, member.version)
            candidate = _candidate(conn, ctx, runtime, nominee["candidate_id"])
            if (
                nominee["contact_status"] != "AVAILABLE"
                or nominee["exclusion_reason"]
                or not candidate["active"]
                or candidate["deleted_at"]
            ):
                raise ModuleError(
                    "MEMBER_NOT_READY", "참석 가능으로 확인된 활성 후보만 확정할 수 있습니다."
                )
            expected_source = "DIRECT" if rule["selection_mode"] == "DIRECT" else "POOL_DRAW"
            if nominee["source"] != expected_source:
                raise ModuleError("SOURCE_MISMATCH", "후보 등록 경로와 선정 방식이 다릅니다.")
            if expected_source == "POOL_DRAW" and member.member_kind == "PRIMARY":
                field = conn.execute(
                    "SELECT specialty_id FROM draw_members WHERE id=?", (nominee["draw_member_id"],)
                ).fetchone()[0]
                if not conn.execute(
                    "SELECT 1 FROM candidate_specialties cs JOIN specialties s ON "
                    "s.id=cs.specialty_id WHERE cs.candidate_id=? AND cs.specialty_id=? "
                    "AND s.active=1",
                    (candidate["id"], field),
                ).fetchone():
                    raise ModuleError(
                        "SPECIALTY_CHANGED", "추첨 이후 후보의 전문분야가 변경되었습니다."
                    )
                primary_fields[field] += 1
            phone = runtime.decrypt(candidate["phone_cipher"], candidate["id"] + ":phone")
            login = runtime.login_lookup_hmac(body.project_id, candidate["name"], phone[-4:])
            if login in login_keys:
                raise ModuleError(
                    "LOGIN_COLLISION",
                    "성명과 휴대전화 뒤 4자리가 중복됩니다. 로그인 식별 정책을 확인하세요.",
                )
            login_keys.add(login)
            assignments.append(
                {
                    "id": str(uuid4()),
                    "project_id": body.project_id,
                    "roster_id": rid,
                    "nominee_id": member.nominee_id,
                    "member_kind": member.member_kind,
                    "reserve_order": member.reserve_order,
                    "name_snapshot": candidate["name"],
                    "organization_snapshot": candidate["organization_name"],
                    "login_lookup_hmac": login,
                    "status": "INVITED",
                    "auth_key_version": runtime.auth_key_version,
                }
            )
        if rule["selection_mode"] == "POOL_RANDOM":
            quotas = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT specialty_id,final_count FROM field_quotas WHERE committee_rule_id=?",
                    (rule["id"],),
                )
            }
            if dict(primary_fields) != quotas:
                raise ModuleError(
                    "QUOTA_MISMATCH", "정위원의 추첨 배정 분야별 인원이 규칙과 다릅니다."
                )
        assignments.sort(key=lambda a: a["id"])
        projection = [{k: v for k, v in a.items() if k != "nominee_id"} for a in assignments]
        checksum = digest(projection)
        confirmed_at = now()
        if body.reserve_count is not None and reserve_count != rule["reserve_count"]:
            conn.execute(
                "UPDATE committee_rules SET reserve_count=?,version=version+1,"
                "updated_at=? WHERE id=?",
                (reserve_count, confirmed_at, rule["id"]),
            )
        runtime.insert(
            conn,
            "committee_rosters",
            {
                "id": rid,
                "project_id": body.project_id,
                "revision_no": 1,
                "status": "CONFIRMED",
                "roster_sha256": checksum,
                "confirmed_by": ctx.actor_id,
                "confirmed_at": confirmed_at,
            },
        )
        for item in assignments:
            runtime.insert(conn, "committee_assignments", item)
        payload = {
            "project_id": body.project_id,
            "roster_id": rid,
            "revision_no": 1,
            "roster_sha256": checksum,
            "assignments": projection,
            "status": "CONFIRMED",
            "confirmed_at": confirmed_at,
        }
        event_id = str(uuid4())
        runtime.insert(
            conn,
            "sync_outbox",
            {
                "event_id": event_id,
                "contract_name": "roster.confirmed",
                "schema_version": 2,
                "aggregate_id": rid,
                "aggregate_version": 1,
                "destination": "evaluation",
                "payload_json": packed(payload),
                "payload_sha256": digest(payload),
                "status": "PENDING",
                "retry_count": 0,
            },
        )
        runtime.audit(conn, ctx, "ROS-05", "committee_rosters", rid, body.project_id)
        return {
            "id": rid,
            "project_id": body.project_id,
            "version": 1,
            "roster_sha256": checksum,
            "assignments": [
                {k: v for k, v in a.items() if k != "login_lookup_hmac"} for a in assignments
            ],
            "event_id": event_id,
            "sync_status": "PENDING",
        }

    return await runtime.run(ctx, "ROS-05", body.model_dump(), confirm)


async def export_roster(ctx: Context, command: DTO, *, runtime: Runtime) -> ExportFile:
    body = validate(ExportRoster, command)

    def read(conn: sqlite3.Connection) -> DTO:
        runtime.project(conn, ctx, body.project_id)
        if not conn.execute(
            "SELECT 1 FROM committee_rosters WHERE id=? AND project_id=?",
            (body.roster_id, body.project_id),
        ).fetchone():
            raise ModuleError("NOT_FOUND", "확정 명단을 찾을 수 없습니다.", 404)
        rows = [
            list(r)
            for r in conn.execute(
                "SELECT member_kind,reserve_order,name_snapshot,organization_snapshot "
                "FROM committee_assignments WHERE roster_id=? ORDER BY "
                "member_kind,reserve_order,id",
                (body.roster_id,),
            )
        ]
        runtime.audit(conn, ctx, "ROS-06", "committee_rosters", body.roster_id, body.project_id)
        return {"rows": rows}

    result = await runtime.run(ctx, "ROS-06", body.model_dump(), read, write=False)
    return export_xlsx(
        "committee-roster.xlsx", ["구분", "예비 순위", "성명", "소속"], result["rows"]
    )
