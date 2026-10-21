"""DRAW-01..03: field-constrained random matching, immutable draw evidence."""

import secrets
import sqlite3

from app.committee.candidate_pool import _specialties
from app.committee.committee_app.v2_contracts import Draw, ExportDraw, Rules
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


async def save_rules(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(Rules, command)

    def save(conn: sqlite3.Connection) -> DTO:
        runtime.project(conn, ctx, body.project_id, edit=True)
        runtime.unlocked(conn, body.project_id)
        active_draw = conn.execute(
            "SELECT id FROM committee_draws WHERE project_id=? AND status='CONFIRMED'",
            (body.project_id,),
        ).fetchone()
        if active_draw and not body.clear_nominees:
            raise ModuleError("DRAW_LOCKED", "기존 추첨을 취소한 뒤 선정 규칙을 변경하세요.")
        _specialties(conn, [q.specialty_id for q in body.quotas])
        old = conn.execute(
            "SELECT * FROM committee_rules WHERE project_id=?", (body.project_id,)
        ).fetchone()
        cleared = 0
        if active_draw:
            cleared = _clear_nominees(conn, ctx, runtime, body)
            conn.execute(
                "UPDATE committee_draws SET status='SUPERSEDED',updated_at=?,version=version+1 WHERE id=?",
                (now(), active_draw["id"]),
            )
            runtime.audit(conn, ctx, "DRAW-01", "committee_draws", active_draw["id"], body.project_id)
        if old:
            version(old, body.version)
            if old["selection_mode"] != body.selection_mode and not active_draw:
                cleared = _clear_nominees(conn, ctx, runtime, body)
            rid = old["id"]
            conn.execute(
                "UPDATE committee_rules SET "
                "selection_mode=?,target_count=?,reserve_count=?,policy_version=policy_version+1,"
                "approved_by=?,approved_at=?,version=version+1,updated_at=? WHERE id=?",
                (
                    body.selection_mode,
                    body.target_count,
                    body.reserve_count,
                    ctx.actor_id,
                    now(),
                    now(),
                    rid,
                ),
            )
            conn.execute("DELETE FROM field_quotas WHERE committee_rule_id=?", (rid,))
        else:
            if body.version != 0:
                raise ModuleError("VERSION_CONFLICT", "최초 규칙은 version=0으로 등록하세요.")
            rid = runtime.insert(
                conn,
                "committee_rules",
                {
                    "project_id": body.project_id,
                    "selection_mode": body.selection_mode,
                    "target_count": body.target_count,
                    "reserve_count": body.reserve_count,
                    "policy_version": 1,
                    "approved_by": ctx.actor_id,
                    "approved_at": now(),
                },
            )
        for q in body.quotas:
            runtime.insert(
                conn,
                "field_quotas",
                {
                    "project_id": body.project_id,
                    "committee_rule_id": rid,
                    "specialty_id": q.specialty_id,
                    "final_count": q.final_count,
                },
            )
        runtime.audit(conn, ctx, "DRAW-01", "committee_rules", rid, body.project_id)
        return dict(conn.execute("SELECT * FROM committee_rules WHERE id=?", (rid,)).fetchone()) | {
            "quotas": [q.model_dump() for q in body.quotas],
            "cleared_nominees": cleared,
        }

    return await runtime.run(ctx, "DRAW-01", body.model_dump(), save)


def _clear_nominees(conn: sqlite3.Connection, ctx: Context, runtime: Runtime, body: Rules) -> int:
    """선정 방식을 바꿀 때 이전 방식으로 등록한 사업 후보를 정리한다.

    명단 확정 전에는 이전 추첨을 SUPERSEDED로 보존하고 연결된 사업 후보를 정리한다.
    방식을 바꾸면 되돌아갈 길이 없는 막다른 상태가 되지 않도록, 담당자가 확인(clear_nominees)
    했을 때만 지우고 지운 후보마다 감사 기록을 남긴다. (2026-10-18)
    """
    nominees = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM project_nominees WHERE project_id=? ORDER BY created_at,id",
            (body.project_id,),
        )
    ]
    if not nominees:
        return 0
    if not body.clear_nominees:
        raise ModuleError(
            "MODE_LOCKED",
            "등록한 사업 후보가 있습니다. 후보를 정리하고 선정 방식을 바꾸려면 "
            "clear_nominees 확인이 필요합니다.",
        )
    if conn.execute(
        "SELECT 1 FROM committee_assignments WHERE project_id=?", (body.project_id,)
    ).fetchone():
        raise ModuleError("ROSTER_LOCKED", "초청명단에 오른 후보는 정리할 수 없습니다.")
    for nid in nominees:
        conn.execute("DELETE FROM project_nominees WHERE id=?", (nid,))
        runtime.audit(conn, ctx, "DRAW-01", "project_nominees", nid, body.project_id)
    return len(nominees)


def match_slots(eligible: list[DTO], quotas: list[DTO]) -> list[tuple[str, str]]:
    """Randomized augmenting paths: detects Hall shortages, never duplicates people.

    Random order is not a claim of uniform distribution over all feasible matchings.
    The persisted input and result, rather than a secret PRNG seed, are audit evidence.
    """
    rng = secrets.SystemRandom()
    slots = [q["specialty_id"] for q in quotas for _ in range(q["final_count"] * 3)]
    rng.shuffle(slots)
    adjacent = [[p["id"] for p in eligible if sid in p["specialty_ids"]] for sid in slots]
    for items in adjacent:
        rng.shuffle(items)
    assigned: dict[str, int] = {}

    def place(slot: int, visited: set[str]) -> bool:
        for cid in adjacent[slot]:
            if cid in visited:
                continue
            visited.add(cid)
            previous = assigned.get(cid)
            if previous is None or place(previous, visited):
                assigned[cid] = slot
                return True
        return False

    for slot in range(len(slots)):
        if not place(slot, set()):
            raise ModuleError("POOL_SHORTAGE", "분야별 3배수를 중복 없이 배정할 후보가 부족합니다.")
    return [(cid, slots[slot]) for cid, slot in sorted(assigned.items(), key=lambda pair: pair[1])]


async def draw_shortlist(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(Draw, command)

    def draw(conn: sqlite3.Connection) -> DTO:
        project = runtime.project(conn, ctx, body.project_id, edit=True)
        runtime.unlocked(conn, body.project_id)
        rule = conn.execute(
            "SELECT * FROM committee_rules WHERE project_id=?", (body.project_id,)
        ).fetchone()
        if rule is None or rule["selection_mode"] != "POOL_RANDOM":
            raise ModuleError("RANDOM_REQUIRED", "부서 풀 무작위 선정 방식만 추첨할 수 있습니다.")
        version(rule, body.rule_version)
        if conn.execute(
            "SELECT 1 FROM committee_draws WHERE project_id=? AND status='CONFIRMED'", (body.project_id,)
        ).fetchone():
            raise ModuleError("ALREADY_DRAWN", "이미 추첨된 사업입니다.")
        quotas = [
            dict(q)
            for q in conn.execute(
                "SELECT specialty_id,final_count FROM field_quotas WHERE "
                "committee_rule_id=? ORDER BY specialty_id",
                (rule["id"],),
            )
        ]
        candidates = conn.execute(
            "SELECT id,version FROM evaluator_candidates WHERE department_id=? "
            "AND pool_member=1 AND active=1 AND deleted_at IS NULL ORDER BY id",
            (project["department_id"],),
        ).fetchall()
        eligible = [
            {
                "id": c["id"],
                "version": c["version"],
                "specialty_ids": [
                    r[0]
                    for r in conn.execute(
                        "SELECT cs.specialty_id FROM candidate_specialties cs JOIN "
                        "specialties s ON s.id=cs.specialty_id WHERE cs.candidate_id=? AND "
                        "s.active=1 ORDER BY cs.specialty_id",
                        (c["id"],),
                    )
                ],
            }
            for c in candidates
        ]
        result = match_slots(eligible, quotas)
        did = runtime.insert(
            conn,
            "committee_draws",
            {
                "project_id": body.project_id,
                "rule_id": rule["id"],
                "revision_no": conn.execute(
                    "SELECT COALESCE(MAX(revision_no),0)+1 FROM committee_draws WHERE project_id=?",
                    (body.project_id,),
                ).fetchone()[0],
                "policy_snapshot_json": packed(dict(rule) | {"quotas": quotas}),
                "eligible_pool_json": packed(eligible),
                "pool_sha256": digest(eligible),
                "algorithm_version": "randomized_matching_v1",
                "status": "CONFIRMED",
                "drawn_by": ctx.actor_id,
            },
        )
        members = []
        for order, (cid, sid) in enumerate(result, 1):
            mid = runtime.insert(
                conn,
                "draw_members",
                {
                    "project_id": body.project_id,
                    "draw_id": did,
                    "candidate_id": cid,
                    "specialty_id": sid,
                    "draw_order": order,
                },
            )
            nid = runtime.insert(
                conn,
                "project_nominees",
                {
                    "project_id": body.project_id,
                    "candidate_id": cid,
                    "draw_member_id": mid,
                    "source": "POOL_DRAW",
                    "contact_status": "NOT_CONTACTED",
                },
            )
            members.append(
                {
                    "id": mid,
                    "candidate_id": cid,
                    "specialty_id": sid,
                    "draw_order": order,
                    "nominee_id": nid,
                }
            )
        runtime.audit(conn, ctx, "DRAW-02", "committee_draws", did, body.project_id)
        return {
            "id": did,
            "project_id": body.project_id,
            "version": 1,
            "members": members,
            "pool_sha256": digest(eligible),
        }

    return await runtime.run(ctx, "DRAW-02", body.model_dump(), draw)


async def export_shortlist(ctx: Context, command: DTO, *, runtime: Runtime) -> ExportFile:
    from app.committee.committee_app.v2_excel import export_xlsx

    body = validate(ExportDraw, command)

    def read(conn: sqlite3.Connection) -> DTO:
        runtime.project(conn, ctx, body.project_id)
        draw = conn.execute(
            "SELECT * FROM committee_draws WHERE id=? AND project_id=?",
            (body.draw_id, body.project_id),
        ).fetchone()
        if draw is None:
            raise ModuleError("NOT_FOUND", "추첨 결과를 찾을 수 없습니다.", 404)
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT "
                "d.draw_order,c.id,c.name,c.organization_name,d.specialty_id,c.phone_cipher "
                "FROM draw_members d JOIN evaluator_candidates c ON c.id=d.candidate_id "
                "WHERE d.draw_id=? ORDER BY d.draw_order",
                (body.draw_id,),
            )
        ]
        runtime.audit(conn, ctx, "DRAW-03", "committee_draws", body.draw_id, body.project_id)
        return {
            "rows": [
                [
                    r["draw_order"],
                    r["name"],
                    r["organization_name"],
                    r["specialty_id"],
                    runtime.decrypt(r["phone_cipher"], r["id"] + ":phone"),
                ]
                for r in rows
            ]
        }

    result = await runtime.run(ctx, "DRAW-03", body.model_dump(), read, write=False)
    return export_xlsx(
        "committee-shortlist.xlsx", ["순서", "성명", "소속", "분야", "휴대전화"], result["rows"]
    )
