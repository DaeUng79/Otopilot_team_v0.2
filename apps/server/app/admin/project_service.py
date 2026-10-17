"""PRJ-01..07. The admin database owns projects and vendor identities."""

import sqlite3
from datetime import date

from app.committee.committee_app.v2_core import now
from app.shared.db import (
    DTO,
    Actor,
    Store,
    insert,
    integer,
    one,
    paginate,
    require,
    rows,
    text,
    update,
)


def allowed(s: Store, a: Actor, b: DTO, edit: bool = False) -> DTO:
    pid = text(b, "project_id")
    s.admin(a, "MANAGE_PROJECTS", pid)
    with s.connect("admin") as c:
        row = one(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if edit:
        require(
            row["status"] in {"DRAFT", "PREPARING", "READY"},
            "평가 시작 후 사업과 업체를 변경할 수 없습니다.",
            "PROJECT_LOCKED",
        )
        with s.connect() as e:
            require(
                not e.execute(
                    "SELECT 1 FROM evaluation_sessions WHERE project_id=? AND status<>'CANCELLED'",
                    (pid,),
                ).fetchone(),
                "평가 회차가 준비되어 변경할 수 없습니다.",
                "PROJECT_LOCKED",
            )
    return row


def public(s: Store, r: DTO, detail: bool = False) -> DTO:
    result = {k: v for k, v in r.items() if not k.endswith("_cipher")}
    if detail:
        result["contact_phone"] = s.runtime.decrypt(
            r["contact_phone_cipher"], r["id"] + ":phone"
        )
        result["contact_email"] = (
            s.runtime.decrypt(r["contact_email_cipher"], r["id"] + ":email")
            if r["contact_email_cipher"]
            else ""
        )
    return result


def save_evaluation_date(c: sqlite3.Connection, pid: str, body: DTO) -> None:
    if "evaluation_date" not in body:
        return
    value = str(body.get("evaluation_date") or "").strip()
    if value:
        try:
            require(
                date.fromisoformat(value).isoformat() == value,
                "평가일을 확인하세요.",
                "INPUT_INVALID",
                422,
            )
        except ValueError:
            require(False, "평가일을 확인하세요.", "INPUT_INVALID", 422)
    c.execute(
        "INSERT INTO project_evaluation_dates(project_id,evaluation_date,updated_at) VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET evaluation_date=excluded.evaluation_date,updated_at=excluded.updated_at",
        (pid, value or None, now()),
    )


def dated(c: sqlite3.Connection, row: DTO) -> DTO:
    schedule = c.execute(
        "SELECT evaluation_date FROM project_evaluation_dates WHERE project_id=?",
        (row["id"],),
    ).fetchone()
    return row | {"evaluation_date": schedule[0] if schedule else None}


def progress(s: Store, pid: str) -> DTO:
    """Read evaluation-owned counts without cross-database SQL foreign keys."""
    with s.connect("admin") as admin:
        committee_started = bool(
            admin.execute(
                "SELECT 1 FROM committee_rules WHERE project_id=?", (pid,)
            ).fetchone()
        )
        invited = bool(
            admin.execute(
                "SELECT 1 FROM committee_rosters WHERE project_id=? AND status='CONFIRMED'",
                (pid,),
            ).fetchone()
        )
    with s.connect() as c:
        session = c.execute(
            "SELECT id,status FROM evaluation_sessions WHERE project_id=? AND status<>'CANCELLED' ORDER BY round_no DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if session is None:
            return {
                "participants": 0,
                "submitted": 0,
                "evaluation_status": None,
                "workflow_step": 5 if invited else 4 if committee_started else 1,
            }
        return {
            "participants": c.execute(
                "SELECT count(*) FROM session_participants WHERE session_id=?",
                (session["id"],),
            ).fetchone()[0],
            "submitted": c.execute(
                "SELECT count(*) FROM evaluation_submissions WHERE session_id=?",
                (session["id"],),
            ).fetchone()[0],
            "evaluation_status": session["status"],
            "workflow_step": 6
            if session["status"] in {"ALL_SUBMITTED", "FINALIZED"}
            else 5,
        }


def search_projects(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    s.admin(a, "MANAGE_PROJECTS")
    result = rows(
        c,
        "SELECT p.* FROM projects p JOIN departments d ON d.id=p.department_id WHERE p.deleted_at IS NULL AND d.active=1 AND p.name LIKE ? AND (?='SUPER_ADMIN' OR p.department_id=?) ORDER BY p.created_at DESC,p.id",
        ("%" + str(b.get("search", "")) + "%", a.role, a.department_id),
    )
    if b.get("department_id"):
        result = [r for r in result if r["department_id"] == b["department_id"]]
    if b.get("status"):
        result = [r for r in result if r["status"] == b["status"]]
    return {
        **paginate([dated(c, public(s, r)) | progress(s, r["id"]) for r in result], b),
        "departments": rows(
            c,
            "SELECT id,name,organization_name FROM departments WHERE active=1 AND deleted_at IS NULL AND (?='SUPER_ADMIN' OR id=?)",
            (a.role, a.department_id),
        ),
    }


def contacts(s: Store, b: DTO, pid: str) -> DTO:
    data: DTO = {
        k: text(b, k)
        for k in (
            "name",
            "contact_organization",
            "contact_department",
            "contact_position",
            "contact_name",
        )
    }
    phone = text(b, "contact_phone", 30)
    require(
        7 <= len("".join(x for x in phone if x.isdigit())) <= 15,
        "전화번호를 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    email = str(b.get("contact_email", "")).strip()
    require(
        not email or (len(email) <= 254 and "@" in email),
        "이메일을 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    data.update(
        contact_phone_cipher=s.runtime.encrypt(phone, pid + ":phone"),
        contact_email_cipher=s.runtime.encrypt(email, pid + ":email")
        if email
        else None,
    )
    return data


def create_project(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    from uuid import uuid4

    s.admin(a, "MANAGE_PROJECTS")
    if b.get("department_id"):
        dept = text(b, "department_id")
    else:
        # Free text on SA-03 still resolves to a real FK, in this transaction.
        require(
            a.role == "SUPER_ADMIN",
            "부서 등록은 총괄관리자만 할 수 있습니다.",
            "FORBIDDEN",
            403,
        )
        organization = text(b, "contact_organization")
        department = text(b, "contact_department")
        matches = rows(
            c,
            "SELECT id,active FROM departments WHERE organization_name=? AND name=? AND deleted_at IS NULL",
            (organization, department),
        )
        require(
            len(matches) <= 1,
            "같은 소속·부서명이 중복되어 있습니다. 부서 관리에서 정리하세요.",
            "DEPARTMENT_AMBIGUOUS",
        )
        if matches:
            require(
                matches[0]["active"] == 1,
                "비활성 부서입니다. 부서 관리에서 상태를 확인하세요.",
                "DEPARTMENT_INACTIVE",
            )
            dept = matches[0]["id"]
        else:
            from app.admin.department_service import save_department

            dept = save_department(
                c,
                s,
                a,
                {
                    "code": "D-" + uuid4().hex[:10].upper(),
                    "organization_name": organization,
                    "name": department,
                },
            )["id"]
    require(
        a.role == "SUPER_ADMIN" or dept == a.department_id,
        "소속 부서만 선택할 수 있습니다.",
        "FORBIDDEN",
        403,
    )
    require(
        c.execute(
            "SELECT 1 FROM departments WHERE id=? AND active=1 AND deleted_at IS NULL",
            (dept,),
        ).fetchone(),
        "활성 부서를 선택하세요.",
    )
    pid = str(uuid4())
    insert(
        c,
        "projects",
        contacts(s, b, pid)
        | {"id": pid, "department_id": dept, "status": "DRAFT", "created_by": a.id},
    )
    save_evaluation_date(c, pid, b)
    return dated(
        c, public(s, one(c, "SELECT * FROM projects WHERE id=?", (pid,)), True)
    )


def update_project(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    row = allowed(s, a, b)
    with s.connect() as evaluation:
        locked = row["status"] not in {"DRAFT", "PREPARING", "READY"} or bool(
            evaluation.execute(
                "SELECT 1 FROM evaluation_sessions WHERE project_id=? AND status<>'CANCELLED'",
                (row["id"],),
            ).fetchone()
        )
    if locked:
        require(
            all(
                b.get(k) == row[k]
                for k in ("name", "contact_organization", "contact_department")
            )
            and (
                "evaluation_date" not in b
                or (b.get("evaluation_date") or None)
                == dated(c, row)["evaluation_date"]
            ),
            "평가 준비 후 사업 식별 정보와 평가일은 변경할 수 없습니다. 담당 연락처만 수정하세요.",
            "PROJECT_LOCKED",
        )
    result = public(s, update(c, "projects", row, b, contacts(s, b, row["id"])), True)
    save_evaluation_date(c, row["id"], b)
    return dated(c, result)


def archive_project(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    row = allowed(s, a, b, True)
    text(b, "reason", 1000)
    return public(
        s,
        update(
            c,
            "projects",
            row,
            b,
            {"deleted_at": now(), "deleted_by": a.id, "status": "CANCELLED"},
        ),
    )


def project_detail(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    row = allowed(s, a, b)
    return {
        "project": dated(c, public(s, row, True)) | progress(s, row["id"]),
        "vendors": rows(
            c,
            "SELECT * FROM project_vendors WHERE project_id=? AND deleted_at IS NULL ORDER BY sort_order,id",
            (row["id"],),
        ),
    }


def save_vendor(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    project = allowed(s, a, b, True)
    values = {
        "project_id": project["id"],
        "display_code": text(b, "display_code", 20),
        "legal_name": text(b, "legal_name"),
        "sort_order": integer(b, "sort_order", 0, 10000),
        "active": 1,
    }
    duplicate = c.execute(
        "SELECT id FROM project_vendors WHERE project_id=? AND legal_name=? AND active=1 AND id<>?",
        (project["id"], values["legal_name"], b.get("vendor_id", "")),
    ).fetchone()
    require(not duplicate, "같은 업체가 등록되어 있습니다.")
    if b.get("vendor_id"):
        row = one(
            c,
            "SELECT * FROM project_vendors WHERE id=? AND project_id=? AND deleted_at IS NULL",
            (text(b, "vendor_id"), project["id"]),
        )
        return update(c, "project_vendors", row, b, values)
    identity = insert(c, "project_vendors", values)
    return one(c, "SELECT * FROM project_vendors WHERE id=?", (identity,))


def archive_vendor(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    project = allowed(s, a, b, True)
    row = one(
        c,
        "SELECT * FROM project_vendors WHERE id=? AND project_id=?",
        (text(b, "vendor_id"), project["id"]),
    )
    return update(
        c,
        "project_vendors",
        row,
        b,
        {"active": 0, "deleted_at": now(), "deleted_by": a.id},
    )
