"""COM-01/05/06/07: department pool and project-specific candidate records."""

import sqlite3
from typing import Any
from uuid import uuid4

from app.committee.committee_app.errors import DomainError
from app.committee.committee_app.excel import email_of, phone_of
from app.committee.committee_app.v2_contracts import (
    CandidateCreate,
    CandidateDelete,
    CandidateQuery,
    CandidateUpdate,
)
from app.committee.committee_app.v2_core import DTO, Context, ModuleError, Runtime, now, validate, version


def _specialties(conn: sqlite3.Connection, ids: list[str]) -> None:
    if len(set(ids)) != len(ids):
        raise ModuleError("INPUT_INVALID", "전문분야가 중복됩니다.", 422)
    for sid in ids:
        if not conn.execute("SELECT 1 FROM specialties WHERE id=? AND active=1", (sid,)).fetchone():
            raise ModuleError("SPECIALTY_UNKNOWN", "등록된 전문분야 코드를 선택하세요.", 422)


def _contacts(phone: str, email: str | None) -> tuple[str, str | None]:
    try:
        return phone_of(phone), email_of(email or "") or None
    except DomainError as exc:
        raise ModuleError("INPUT_INVALID", "휴대전화 또는 이메일 형식을 확인하세요.", 422) from exc


def _read(conn: sqlite3.Connection, runtime: Runtime, row: sqlite3.Row) -> DTO:
    cid = row["id"]
    result = dict(row)
    result["phone"] = runtime.decrypt(result.pop("phone_cipher"), cid + ":phone")
    email = result.pop("email_cipher")
    result["email"] = runtime.decrypt(email, cid + ":email") if email else None
    result.pop("phone_lookup_hmac")
    result["specialty_ids"] = [
        r[0]
        for r in conn.execute(
            "SELECT specialty_id FROM candidate_specialties WHERE candidate_id=? "
            "ORDER BY specialty_id",
            (cid,),
        )
    ]
    return result


def _candidate(conn: sqlite3.Connection, ctx: Context, runtime: Runtime, cid: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM evaluator_candidates WHERE id=?", (cid,)).fetchone()
    if row is None:
        raise ModuleError("NOT_FOUND", "후보를 찾을 수 없습니다.", 404)
    runtime.authorize(conn, ctx, row["department_id"])
    return row


def _unassigned(conn: sqlite3.Connection, cid: str) -> None:
    if conn.execute(
        "SELECT 1 FROM committee_assignments a JOIN project_nominees n ON n.id=a.nominee_id "
        "WHERE n.candidate_id=? AND a.status='INVITED'",
        (cid,),
    ).fetchone():
        raise ModuleError("ROSTER_LOCKED", "확정 위원 정보는 명단 변경 절차가 필요합니다.")


def _nominee(conn: sqlite3.Connection, runtime: Runtime, project_id: str, cid: str) -> str:
    runtime.unlocked(conn, project_id)
    rule = conn.execute(
        "SELECT selection_mode FROM committee_rules WHERE project_id=?", (project_id,)
    ).fetchone()
    if rule is None or rule[0] != "DIRECT":
        raise ModuleError("DIRECT_REQUIRED", "사업별 직접 등록 방식을 먼저 설정하세요.")
    return runtime.insert(
        conn,
        "project_nominees",
        {
            "project_id": project_id,
            "candidate_id": cid,
            "draw_member_id": None,
            "source": "DIRECT",
            "contact_status": "NOT_CONTACTED",
        },
    )


def _insert(
    conn: sqlite3.Connection,
    ctx: Context,
    runtime: Runtime,
    body: CandidateCreate,
    *,
    candidate_id: str | None = None,
) -> DTO:
    runtime.authorize(conn, ctx, body.department_id)
    if body.project_id:
        project = runtime.project(conn, ctx, body.project_id, edit=True)
        if project["department_id"] != body.department_id:
            raise ModuleError("FORBIDDEN", "사업과 등록 부서가 다릅니다.", 403)
    _specialties(conn, body.specialty_ids)
    phone, email = _contacts(body.phone, body.email)
    cid = candidate_id or str(uuid4())
    runtime.insert(
        conn,
        "evaluator_candidates",
        {
            "id": cid,
            "department_id": body.department_id,
            "pool_member": int(body.scope == "DEPARTMENT_POOL"),
            "organization_name": body.organization_name,
            "department_name": body.department_name,
            "name": body.name,
            "position": body.position,
            "phone_cipher": runtime.encrypt(phone, cid + ":phone"),
            "phone_lookup_hmac": runtime.lookup("phone", body.department_id, phone),
            "email_cipher": runtime.encrypt(email, cid + ":email") if email else None,
            "active": 1,
        },
    )
    for sid in body.specialty_ids:
        runtime.insert(conn, "candidate_specialties", {"candidate_id": cid, "specialty_id": sid})
    if body.project_id:
        _nominee(conn, runtime, body.project_id, cid)
    runtime.audit(conn, ctx, "COM-05", "evaluator_candidates", cid, body.project_id)
    return _read(conn, runtime, _candidate(conn, ctx, runtime, cid))


async def create_candidate(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(CandidateCreate, command)
    return await runtime.run(
        ctx, "COM-05", body.model_dump(), lambda c: _insert(c, ctx, runtime, body)
    )


async def search_candidates(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    query = validate(CandidateQuery, command)

    def query_rows(conn: sqlite3.Connection) -> DTO:
        runtime.authorize(conn, ctx, query.department_id)
        if query.project_id:
            runtime.project(conn, ctx, query.project_id)
        clauses = ["c.department_id=?"]
        params: list[Any] = [query.department_id]
        if query.scope == "DEPARTMENT_POOL":
            clauses.append("c.pool_member=1")
        else:
            clauses.append(
                "EXISTS(SELECT 1 FROM project_nominees n WHERE n.candidate_id=c.id "
                "AND n.project_id=?)"
            )
            params.append(query.project_id)
        if query.active is not False:
            clauses.append("c.deleted_at IS NULL")
        if query.active is not None:
            clauses.append("c.active=?")
            params.append(int(query.active))
        if query.search:
            clauses.append("(c.name LIKE ? ESCAPE '\\' OR c.organization_name LIKE ? ESCAPE '\\')")
            term = (
                "%"
                + query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            params.extend([term, term])
        if query.specialty_id:
            clauses.append(
                "EXISTS(SELECT 1 FROM candidate_specialties s WHERE "
                "s.candidate_id=c.id AND s.specialty_id=?)"
            )
            params.append(query.specialty_id)
        where = " AND ".join(clauses)
        total = conn.execute(
            "SELECT count(*) FROM evaluator_candidates c WHERE " + where, params
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT c.* FROM evaluator_candidates c WHERE "
            + where
            + " ORDER BY c.created_at,c.id LIMIT ? OFFSET ?",
            params + [query.page_size, (query.page - 1) * query.page_size],
        ).fetchall()
        return {
            "items": [_read(conn, runtime, row) for row in rows],
            "total": total,
            "page": query.page,
            "page_size": query.page_size,
        }

    return await runtime.run(ctx, "COM-01", query.model_dump(), query_rows, write=False)


async def update_candidate(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(CandidateUpdate, command)

    def update(conn: sqlite3.Connection) -> DTO:
        row = _candidate(conn, ctx, runtime, body.candidate_id)
        version(row, body.version)
        _unassigned(conn, body.candidate_id)
        if row["deleted_at"]:
            raise ModuleError("CANDIDATE_INACTIVE", "삭제된 후보는 수정할 수 없습니다.")
        _specialties(conn, body.specialty_ids)
        phone, email = _contacts(body.phone, body.email)
        cid = body.candidate_id
        conn.execute(
            "UPDATE evaluator_candidates SET "
            "name=?,organization_name=?,department_name=?,position=?,"
            "phone_cipher=?,phone_lookup_hmac=?,email_cipher=?,"
            "version=version+1,updated_at=? WHERE id=?",
            (
                body.name,
                body.organization_name,
                body.department_name,
                body.position,
                runtime.encrypt(phone, cid + ":phone"),
                runtime.lookup("phone", row["department_id"], phone),
                runtime.encrypt(email, cid + ":email") if email else None,
                now(),
                cid,
            ),
        )
        conn.execute("DELETE FROM candidate_specialties WHERE candidate_id=?", (cid,))
        for sid in body.specialty_ids:
            runtime.insert(
                conn, "candidate_specialties", {"candidate_id": cid, "specialty_id": sid}
            )
        conn.execute(
            "UPDATE project_nominees SET "
            "contact_status='NOT_CONTACTED',contacted_at=NULL,contacted_by=NULL,"
            "contact_note=NULL,version=version+1,updated_at=? WHERE candidate_id=?",
            (now(), cid),
        )
        runtime.audit(conn, ctx, "COM-06", "evaluator_candidates", cid)
        return _read(conn, runtime, _candidate(conn, ctx, runtime, cid))

    return await runtime.run(ctx, "COM-06", body.model_dump(), update)


async def deactivate_candidate(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(CandidateDelete, command)

    def deactivate(conn: sqlite3.Connection) -> DTO:
        row = _candidate(conn, ctx, runtime, body.candidate_id)
        version(row, body.version)
        _unassigned(conn, body.candidate_id)
        conn.execute(
            "UPDATE evaluator_candidates SET "
            "active=0,deleted_at=?,deleted_by=?,updated_at=?,version=version+1 "
            "WHERE id=?",
            (now(), ctx.actor_id, now(), body.candidate_id),
        )
        runtime.audit(conn, ctx, "COM-07", "evaluator_candidates", body.candidate_id)
        return {"id": body.candidate_id, "active": False, "version": body.version + 1}

    return await runtime.run(ctx, "COM-07", body.model_dump(), deactivate)


async def list_specialties(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    if command:
        raise ModuleError("INPUT_INVALID", "전문분야 조회에는 입력값이 필요하지 않습니다.", 422)

    def read(conn: sqlite3.Connection) -> DTO:
        return {
            "items": [
                dict(r)
                for r in conn.execute(
                    "SELECT id,code,name FROM specialties WHERE active=1 ORDER BY code"
                )
            ]
        }

    return await runtime.run(ctx, "COM-CATALOG", {}, read, write=False)
