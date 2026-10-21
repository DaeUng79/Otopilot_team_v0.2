"""ADM-01..05. Account and permission changes revoke existing sessions."""

import secrets
import sqlite3

from app.admin.auth_service import password_hash
from app.committee.committee_app.v2_core import now
from app.shared.db import DTO, Actor, Store, insert, one, paginate, require, rows, text, update

PERMISSIONS = {
    "MANAGE_ADMINS",
    "MANAGE_PROJECTS",
    "MANAGE_DOCUMENTS",
    "MANAGE_COMMITTEE",
    "VIEW_RESULTS",
    "VIEW_DASHBOARD",
}
# 부서관리자 기본 권한 (2026-10-18): 데모 계정(web-demo 등)과 같은 묶음. ADM-02로 만든 계정에 권한이 하나도 없어
# 첫 화면(PRJ-01 → MANAGE_PROJECTS)부터 403이 나던 문제를 막는다. 총괄관리자는 ADM-05(권한 저장)로 조정할 수 있다.
DEFAULT_DEPARTMENT_PERMISSIONS = PERMISSIONS - {"MANAGE_ADMINS"}


def guard(s: Store, a: Actor) -> None:
    s.admin(a, "MANAGE_ADMINS")
    require(
        a.role == "SUPER_ADMIN",
        "총괄관리자만 계정을 관리할 수 있습니다.",
        "FORBIDDEN",
        403,
    )


def public(c: sqlite3.Connection, row: DTO) -> DTO:
    return {
        k: row[k]
        for k in (
            "id",
            "username",
            "display_name",
            "department_id",
            "role",
            "active",
            "version",
        )
    } | {
        "permissions": [
            r[0]
            for r in c.execute(
                "SELECT permission_code FROM admin_permissions WHERE admin_id=? ORDER BY permission_code",
                (row["id"],),
            )
        ]
    }


def search_admins(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    result = rows(
        c,
        "SELECT * FROM admin_users WHERE (display_name LIKE ? OR username LIKE ?) ORDER BY created_at",
        ("%" + str(b.get("search", "")) + "%",) * 2,
    )
    if b.get("department_id"):
        result = [r for r in result if r["department_id"] == b["department_id"]]
    if b.get("active") is not None:
        result = [r for r in result if bool(r["active"]) == b["active"]]
    return {
        **paginate([public(c, r) for r in result], b),
        "departments": rows(
            c,
            "SELECT id,name,organization_name FROM departments WHERE active=1 AND deleted_at IS NULL",
        ),
    }


def create_admin(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    password = text(b, "password", 256)
    require(
        len(password) >= 10,
        "초기 비밀번호는 10자 이상이어야 합니다.",
        "INPUT_INVALID",
        422,
    )
    dept = text(b, "department_id")
    require(
        c.execute(
            "SELECT 1 FROM departments WHERE id=? AND active=1 AND deleted_at IS NULL",
            (dept,),
        ).fetchone(),
        "활성 부서를 선택하세요.",
    )
    identity = insert(
        c,
        "admin_users",
        {
            "username": text(b, "username").casefold(),
            "display_name": text(b, "display_name"),
            "department_id": dept,
            "role": "DEPARTMENT_ADMIN",
            "password_hash": password_hash(password),
            "active": 1,
            "password_changed_at": now(),
        },
    )
    c.execute(
        "INSERT INTO admin_password_requirements(admin_id,must_change) VALUES(?,1)",
        (identity,),
    )
    for permission in sorted(DEFAULT_DEPARTMENT_PERMISSIONS):
        insert(
            c,
            "admin_permissions",
            {"admin_id": identity, "permission_code": permission, "granted_by": a.id},
        )
    return public(c, one(c, "SELECT * FROM admin_users WHERE id=?", (identity,)))


def revoke(c: sqlite3.Connection, identity: str) -> None:
    c.execute(
        "UPDATE auth_sessions SET revoked_at=?,updated_at=?,version=version+1 WHERE principal_id=? AND revoked_at IS NULL",
        (now(), now(), identity),
    )


def update_admin(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    row = one(c, "SELECT * FROM admin_users WHERE id=?", (text(b, "admin_id"),))
    if row["role"] == "SUPER_ADMIN":
        result = update(
            c, "admin_users", row, b, {"display_name": text(b, "display_name")}
        )
        return public(c, result)
    dept = text(b, "department_id")
    require(
        c.execute(
            "SELECT 1 FROM departments WHERE id=? AND active=1 AND deleted_at IS NULL",
            (dept,),
        ).fetchone(),
        "활성 부서를 선택하세요.",
    )
    data = {"display_name": text(b, "display_name"), "department_id": dept}
    if b.get("password"):
        password = text(b, "password", 256)
        require(
            len(password) >= 10,
            "비밀번호는 10자 이상이어야 합니다.",
            "INPUT_INVALID",
            422,
        )
        data.update(password_hash=password_hash(password), password_changed_at=now())
    result = update(c, "admin_users", row, b, data)
    revoke(c, row["id"])
    return public(c, result)


def deactivate_admin(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    row = one(c, "SELECT * FROM admin_users WHERE id=?", (text(b, "admin_id"),))
    require(row["id"] != a.id, "본인 계정은 비활성화할 수 없습니다.")
    require(
        row["role"] != "SUPER_ADMIN"
        or c.execute(
            "SELECT COUNT(*) FROM admin_users WHERE role='SUPER_ADMIN' AND active=1"
        ).fetchone()[0]
        > 1,
        "마지막 총괄관리자는 비활성화할 수 없습니다.",
    )
    result = update(
        c, "admin_users", row, b, {"active": 0, "deleted_at": now(), "deleted_by": a.id}
    )
    revoke(c, row["id"])
    return public(c, result)


def set_permissions(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    row = one(c, "SELECT * FROM admin_users WHERE id=?", (text(b, "admin_id"),))
    permissions = b.get("permission_codes")
    require(
        isinstance(permissions, list)
        and all(isinstance(p, str) and p in PERMISSIONS for p in permissions),
        "권한 코드를 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    assert isinstance(permissions, list)
    require(
        row["role"] == "DEPARTMENT_ADMIN" and row["active"],
        "활성 부서관리자만 권한을 변경할 수 있습니다.",
    )
    result = update(c, "admin_users", row, b, {})
    c.execute("DELETE FROM admin_permissions WHERE admin_id=?", (row["id"],))
    for p in sorted(set(permissions)):
        insert(
            c,
            "admin_permissions",
            {"admin_id": row["id"], "permission_code": p, "granted_by": a.id},
        )
    revoke(c, row["id"])
    return public(c, result)


def restore_admin(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    row = one(c, "SELECT * FROM admin_users WHERE id=?", (text(b, "admin_id"),))
    require(row["role"] == "DEPARTMENT_ADMIN", "부서관리자를 선택하세요.")
    require(
        c.execute(
            "SELECT 1 FROM departments WHERE id=? AND active=1 AND deleted_at IS NULL",
            (row["department_id"],),
        ).fetchone(),
        "활성 부서 계정만 복원할 수 있습니다.",
    )
    result = update(
        c, "admin_users", row, b, {"active": 1, "deleted_at": None, "deleted_by": None}
    )
    revoke(c, row["id"])
    return public(c, result)


def reset_password(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    guard(s, a)
    row = one(
        c, "SELECT * FROM admin_users WHERE id=? AND active=1", (text(b, "admin_id"),)
    )
    password = secrets.token_urlsafe(12) + "7!"
    result = update(
        c,
        "admin_users",
        row,
        b,
        {"password_hash": password_hash(password), "password_changed_at": now()},
    )
    c.execute(
        "INSERT INTO admin_password_requirements(admin_id,must_change) VALUES(?,1) ON CONFLICT(admin_id) DO UPDATE SET must_change=1",
        (row["id"],),
    )
    revoke(c, row["id"])
    return public(c, result) | {"temporary_password": password}
