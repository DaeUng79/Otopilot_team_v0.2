"""AUTH-01..03: persistent, hashed sessions; evaluator login never records attendance."""

import hashlib
import hmac
import secrets
import sqlite3

from app.committee.committee_app.v2_core import now
from app.shared.db import DTO, Actor, Store, future, insert, one, require, text, update


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    return (
        "scrypt$"
        + salt
        + "$"
        + hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        ).hex()
    )


def valid_password(password: str, encoded: str) -> bool:
    try:
        kind, salt, _ = encoded.split("$")
        return kind == "scrypt" and hmac.compare_digest(
            password_hash(password, salt), encoded
        )
    except (ValueError, TypeError):
        return False


def make_session(
    c: sqlite3.Connection, principal_id: str, project_id: str | None, method: str
) -> str:
    token = secrets.token_urlsafe(32)
    insert(
        c,
        "auth_sessions",
        {
            "principal_id": principal_id,
            "project_id": project_id,
            "auth_method": method,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": future(),
            "revoked_at": None,
        },
    )
    return token


def must_change(store: Store, actor: Actor) -> bool:
    if actor.role == "EVALUATOR":
        return False
    with store.connect("admin") as c:
        return bool(
            c.execute(
                "SELECT 1 FROM admin_password_requirements WHERE admin_id=? AND must_change=1",
                (actor.id,),
            ).fetchone()
        )


def change_password(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    from app.admin.admin_service import revoke

    require(a.role != "EVALUATOR", "관리자 계정으로 로그인하세요.", "FORBIDDEN", 403)
    row = one(c, "SELECT * FROM admin_users WHERE id=? AND active=1", (a.id,))
    require(
        valid_password(text(b, "current_password", 256), row["password_hash"]),
        "현재 비밀번호를 확인하세요.",
        "PASSWORD_INVALID",
        422,
    )
    password = text(b, "new_password", 256)
    require(
        len(password) >= 10 and password != b["current_password"],
        "기존과 다른 10자 이상의 비밀번호를 사용하세요.",
        "INPUT_INVALID",
        422,
    )
    update(
        c,
        "admin_users",
        row,
        {"version": row["version"]},
        {"password_hash": password_hash(password), "password_changed_at": now()},
    )
    c.execute(
        "UPDATE admin_password_requirements SET must_change=0 WHERE admin_id=?", (a.id,)
    )
    revoke(c, a.id)
    return {"changed": True, "login_required": True}


def login_admin(store: Store, body: DTO) -> tuple[str, Actor]:
    username = text(body, "username").casefold()
    password = text(body, "password", 256)
    with store.connect("admin", True) as c:
        row = c.execute(
            "SELECT * FROM admin_users WHERE username=? AND active=1 AND deleted_at IS NULL",
            (username,),
        ).fetchone()
        valid = valid_password(
            password,
            row["password_hash"]
            if row
            else password_hash("invalid-password", "00" * 16),
        )
        require(
            row is not None and valid, "로그인 정보를 확인하세요.", "LOGIN_FAILED", 401
        )
        actor = Actor(row["id"], row["role"], row["department_id"])
        if actor.department_id:
            require(
                c.execute(
                    "SELECT 1 FROM departments WHERE id=? AND active=1 AND deleted_at IS NULL",
                    (actor.department_id,),
                ).fetchone(),
                "로그인 정보를 확인하세요.",
                "LOGIN_FAILED",
                401,
            )
        return make_session(c, actor.id, None, "ADMIN_PASSWORD"), actor


def evaluator_projects(store: Store, body: DTO) -> list[DTO]:
    """Resolve only invitations matching supplied credentials; never list the pool."""
    name, last4 = text(body, "name"), text(body, "last4", 4)
    require(
        len(last4) == 4 and last4.isascii() and last4.isdecimal(),
        "휴대전화 뒤 4자리를 입력하세요.",
        "INPUT_INVALID",
        422,
    )
    with store.connect("admin") as admin, store.connect() as evaluation:
        projects = admin.execute(
            "SELECT p.id,p.name,t.evaluation_date FROM projects p "
            "JOIN departments d ON d.id=p.department_id "
            "LEFT JOIN project_evaluation_dates t ON t.project_id=p.id "
            "WHERE p.deleted_at IS NULL AND d.active=1 AND d.deleted_at IS NULL "
            "AND p.status<>'CANCELLED' ORDER BY t.evaluation_date DESC,p.id"
        ).fetchall()
        result = []
        for project in projects:
            matches = evaluation.execute(
                "SELECT a.id,a.auth_key_version FROM ref_committee_assignments a "
                "JOIN ref_committee_rosters r ON r.id=a.roster_id "
                "WHERE a.project_id=? AND a.login_lookup_hmac=? AND a.status='INVITED' "
                "AND a.is_deleted=0 AND r.status='CONFIRMED' AND r.is_deleted=0",
                (
                    project["id"],
                    store.runtime.login_lookup_hmac(project["id"], name, last4),
                ),
            ).fetchall()
            # Ambiguous identities within one project must never choose the first row.
            if (
                len(matches) != 1
                or matches[0]["auth_key_version"] != store.runtime.auth_key_version
            ):
                continue
            if admin.execute(
                "SELECT 1 FROM committee_assignments a JOIN committee_rosters r ON r.id=a.roster_id "
                "WHERE a.id=? AND a.project_id=? AND a.status='INVITED' AND r.status='CONFIRMED'",
                (matches[0]["id"], project["id"]),
            ).fetchone():
                result.append(dict(project))
        require(
            result,
            "로그인 정보를 확인하세요. 초청 명단 또는 중복 식별자는 담당자에게 확인하세요.",
            "LOGIN_FAILED",
            401,
        )
        return result


def login_evaluator(store: Store, body: DTO) -> tuple[str, Actor]:
    project = text(body, "project_id")
    name, last4 = text(body, "name"), text(body, "last4", 4)
    require(
        len(last4) == 4 and last4.isdecimal(),
        "휴대전화 뒤 4자리를 입력하세요.",
        "INPUT_INVALID",
        422,
    )
    with store.connect("admin") as a:
        require(
            a.execute(
                "SELECT 1 FROM projects p JOIN departments d ON d.id=p.department_id WHERE p.id=? AND p.deleted_at IS NULL AND d.active=1 AND p.status<>'CANCELLED'",
                (project,),
            ).fetchone(),
            "로그인 정보를 확인하세요.",
            "LOGIN_FAILED",
            401,
        )
    with store.connect(write=True) as c:
        matches = c.execute(
            "SELECT a.* FROM ref_committee_assignments a JOIN ref_committee_rosters r ON r.id=a.roster_id WHERE a.project_id=? AND a.login_lookup_hmac=? AND a.status='INVITED' AND a.is_deleted=0 AND r.status='CONFIRMED' AND r.is_deleted=0",
            (project, store.runtime.login_lookup_hmac(project, name, last4)),
        ).fetchall()
        require(
            len(matches) == 1,
            "로그인 정보를 확인하세요. 중복 식별자는 관리자 확인이 필요합니다.",
            "LOGIN_FAILED",
            401,
        )
        row = matches[0]
        active_assignment(store, row["id"], project)
        require(
            row["auth_key_version"] == store.runtime.auth_key_version,
            "인증 키 버전을 확인하세요.",
            "LOGIN_FAILED",
            401,
        )
        return make_session(c, row["id"], project, "EVALUATOR_NAME_LAST4"), Actor(
            row["id"], "EVALUATOR", project_id=project
        )


def authorize(store: Store, token: str) -> Actor:
    hashed = hashlib.sha256(token.encode()).hexdigest()
    for db in ("admin", "evaluation"):
        with store.connect(db) as c:
            session = c.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?",
                (hashed, now()),
            ).fetchone()
            if session is None:
                continue
            if db == "admin":
                row = c.execute(
                    "SELECT * FROM admin_users WHERE id=? AND active=1 AND deleted_at IS NULL AND password_changed_at<=?",
                    (session["principal_id"], session["created_at"]),
                ).fetchone()
                require(row, "세션이 만료되었습니다.", "AUTH_REQUIRED", 401)
                if row["department_id"]:
                    require(
                        c.execute(
                            "SELECT 1 FROM departments WHERE id=? AND active=1 AND deleted_at IS NULL",
                            (row["department_id"],),
                        ).fetchone(),
                        "비활성 부서입니다.",
                        "AUTH_REQUIRED",
                        401,
                    )
                return Actor(row["id"], row["role"], row["department_id"])
            row = c.execute(
                "SELECT a.* FROM ref_committee_assignments a JOIN ref_committee_rosters r ON r.id=a.roster_id WHERE a.id=? AND a.status='INVITED' AND a.is_deleted=0 AND r.status='CONFIRMED' AND r.is_deleted=0",
                (session["principal_id"],),
            ).fetchone()
            require(row, "초청 명단이 유효하지 않습니다.", "AUTH_REQUIRED", 401)
            active_assignment(store, row["id"], row["project_id"])
            with store.connect("admin") as admin:
                require(
                    admin.execute(
                        "SELECT 1 FROM projects p JOIN departments d ON d.id=p.department_id WHERE p.id=? AND p.deleted_at IS NULL AND d.active=1 AND p.status<>'CANCELLED'",
                        (row["project_id"],),
                    ).fetchone(),
                    "사업이 유효하지 않습니다.",
                    "AUTH_REQUIRED",
                    401,
                )
            return Actor(row["id"], "EVALUATOR", project_id=row["project_id"])
    require(False, "로그인이 필요합니다.", "AUTH_REQUIRED", 401)
    raise AssertionError("unreachable")


def active_assignment(store: Store, assignment_id: str, project_id: str) -> None:
    with store.connect("admin") as c:
        require(
            c.execute(
                "SELECT 1 FROM committee_assignments a JOIN committee_rosters r ON r.id=a.roster_id WHERE a.id=? AND a.project_id=? AND a.status='INVITED' AND r.status='CONFIRMED'",
                (assignment_id, project_id),
            ).fetchone(),
            "유효한 초청 명단을 확인하세요.",
            "AUTH_REQUIRED",
            401,
        )


def logout(store: Store, token: str) -> None:
    for db in ("admin", "evaluation"):
        with store.connect(db, True) as c:
            c.execute(
                "UPDATE auth_sessions SET revoked_at=?,updated_at=?,version=version+1 WHERE token_hash=? AND revoked_at IS NULL",
                (now(), now(), hashlib.sha256(token.encode()).hexdigest()),
            )
