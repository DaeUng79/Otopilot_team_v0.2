"""Existing SA-02 department controls. Preserve referenced rows and revoke access."""

import re
import sqlite3

from app.admin.admin_service import guard, revoke
from app.committee.committee_app.v2_core import now
from app.shared.db import DTO, Actor, Store, insert, one, require, rows, text, update


def list_departments(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    return {
        "items": rows(
            c,
            "SELECT d.*,(SELECT COUNT(*) FROM projects p WHERE p.department_id=d.id AND p.deleted_at IS NULL) AS project_count FROM departments d WHERE d.deleted_at IS NULL ORDER BY d.code",
        )
    }


def save_department(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    data = {"organization_name": text(b, "organization_name"), "name": text(b, "name")}
    if b.get("department_id"):
        old = one(
            c,
            "SELECT * FROM departments WHERE id=? AND deleted_at IS NULL",
            (b["department_id"],),
        )
        return update(c, "departments", old, b, data)
    code = text(b, "code", 12)
    require(
        re.fullmatch(r"[A-Z0-9-]{3,12}", code) is not None,
        "부서 코드는 영문 대문자·숫자·붙임표 3~12자로 입력하세요.",
        "INPUT_INVALID",
        422,
    )
    identity = insert(c, "departments", data | {"code": code, "active": 1})
    return one(c, "SELECT * FROM departments WHERE id=?", (identity,))


def set_department_state(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    row = one(
        c,
        "SELECT * FROM departments WHERE id=? AND deleted_at IS NULL",
        (text(b, "department_id"),),
    )
    action = b.get("state")
    require(
        action in {"ACTIVE", "INACTIVE", "DELETED"},
        "부서 상태를 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    if action == "DELETED":
        require(
            not c.execute(
                "SELECT 1 FROM projects WHERE department_id=?", (row["id"],)
            ).fetchone(),
            "사업 기록이 있는 부서는 삭제 대신 비활성화하세요.",
        )
    data: DTO = {"active": int(action == "ACTIVE")}
    if action == "DELETED":
        data |= {"deleted_at": now(), "deleted_by": a.id}
    result = update(c, "departments", row, b, data)
    for account in rows(
        c, "SELECT id FROM admin_users WHERE department_id=?", (row["id"],)
    ):
        revoke(c, account["id"])
        if action == "DELETED":
            c.execute(
                "UPDATE admin_users SET active=0,deleted_at=?,deleted_by=?,version=version+1,updated_at=? WHERE id=?",
                (now(), a.id, now(), account["id"]),
            )
    return result
