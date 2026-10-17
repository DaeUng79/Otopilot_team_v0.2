"""SQLite unit of work. Each connection owns one database; no cross-DB joins."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.committee.committee_app.v2_core import Context, ModuleError, Runtime, digest, now, packed

ROOT = Path(__file__).resolve().parents[2]
DTO = dict[str, Any]
MODEL = json.loads((ROOT / "contracts/schema_v2.json").read_text("utf8"))
TABLES = {
    t["name"]: {f[0] for f in t["fields"]}
    for t in MODEL["tables"]
    if t["db"] in {"admin", "evaluation"}
}


@dataclass(frozen=True)
class Actor:
    id: str
    role: str
    department_id: str | None = None
    project_id: str | None = None


def require(
    condition: Any, message: str, code: str = "NOT_READY", status: int = 409
) -> None:
    if not condition:
        raise ModuleError(code, message, status)


def text(body: DTO, key: str, maximum: int = 200, default: str | None = None) -> str:
    value = body.get(key, default)
    require(
        isinstance(value, str) and 0 < len(value.strip()) <= maximum,
        f"{key}: 올바른 값을 입력하세요.",
        "INPUT_INVALID",
        422,
    )
    return str(value).strip()


def integer(body: DTO, key: str, low: int = 0, high: int = 10**10) -> int:
    value = body.get(key)
    require(
        type(value) is int and low <= value <= high,
        f"{key}: 정수 범위를 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    assert isinstance(value, int)
    return value


def one(c: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> DTO:
    row = c.execute(sql, args).fetchone()
    require(row is not None, "대상을 찾을 수 없습니다.", "NOT_FOUND", 404)
    return dict(row)


def rows(c: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[DTO]:
    return [dict(r) for r in c.execute(sql, args)]


def insert(c: sqlite3.Connection, table: str, values: DTO) -> str:
    require(
        table in TABLES and set(values) <= TABLES[table],
        "내부 저장 계약 오류",
        "SCHEMA_INVALID",
        500,
    )
    data = {
        "id": str(uuid4()),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
    } | values
    data = {k: v for k, v in data.items() if k in TABLES[table]}
    c.execute(
        f"INSERT INTO {table} ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
        tuple(data.values()),
    )
    return str(data.get("id", data.get("event_id", "")))


def update(c: sqlite3.Connection, table: str, row: DTO, body: DTO, values: DTO) -> DTO:
    require(
        table in TABLES and set(values) <= TABLES[table],
        "내부 저장 계약 오류",
        "SCHEMA_INVALID",
        500,
    )
    require(
        integer(body, "version", 1) == row["version"],
        "다른 사용자가 변경했습니다. 다시 조회하세요.",
        "VERSION_CONFLICT",
    )
    data = values | {"version": row["version"] + 1, "updated_at": now()}
    changed = c.execute(
        f"UPDATE {table} SET "
        + ",".join(k + "=?" for k in data)
        + " WHERE id=? AND version=?",
        (*data.values(), row["id"], row["version"]),
    ).rowcount
    require(changed == 1, "다시 조회하세요.", "VERSION_CONFLICT")
    return row | data


def future(hours: int = 8) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def paginate(items: list[DTO], body: DTO) -> DTO:
    page = integer({"page": body.get("page", 1)}, "page", 1, 1000000)
    size = integer({"page_size": body.get("page_size", 50)}, "page_size", 1, 200)
    return {
        "items": items[(page - 1) * size : page * size],
        "total": len(items),
        "page": page,
        "page_size": size,
    }


class Store:
    def __init__(self, runtime: Runtime, evaluation_path: Path) -> None:
        self.runtime, self.evaluation_path = runtime, evaluation_path

    @contextmanager
    def connect(
        self, database: str = "evaluation", write: bool = False
    ) -> Iterator[sqlite3.Connection]:
        path = self.runtime.path if database == "admin" else self.evaluation_path
        conn = sqlite3.connect(path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def initialize(self) -> None:
        self.evaluation_path.parent.mkdir(parents=True, exist_ok=True)
        for database in ("admin", "evaluation"):
            for path in sorted((ROOT / "migrations" / database).glob(f"*_yujin_{database}_*.sql")):
                sql = path.read_text("utf8")
                with self.connect(database, True) as c:
                    c.execute(
                        "CREATE TABLE IF NOT EXISTS schema_migrations(migration_name TEXT NOT NULL PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)"
                    )
                    checksum = hashlib.sha256(sql.encode()).hexdigest()
                    old = c.execute(
                        "SELECT checksum FROM schema_migrations WHERE migration_name=?",
                        (path.name,),
                    ).fetchone()
                    require(
                        not old or old[0] == checksum,
                        "적용된 마이그레이션 파일이 변경되었습니다.",
                        "MIGRATION_CHANGED",
                    )
                    if not old:
                        c.executescript("BEGIN IMMEDIATE;\n" + sql)
                        c.execute(
                            "INSERT INTO schema_migrations VALUES (?,?,?)",
                            (path.name, checksum, now()),
                        )
                    require(
                        not c.execute("PRAGMA foreign_key_check").fetchall(),
                        "외래키 검증에 실패했습니다.",
                        "FK_INVALID",
                    )
        await self.runtime.initialize()

    def admin(
        self, actor: Actor, permission: str, project_id: str | None = None
    ) -> DTO:
        require(
            actor.role in {"SUPER_ADMIN", "DEPARTMENT_ADMIN"},
            "관리자 권한이 필요합니다.",
            "FORBIDDEN",
            403,
        )
        with self.connect("admin") as c:
            person = dict(self.runtime.authorize(c, Context(actor.id)))
            if person["department_id"]:
                self.runtime.authorize(c, Context(actor.id), person["department_id"])
            if person["role"] != "SUPER_ADMIN":
                require(
                    c.execute(
                        "SELECT 1 FROM admin_permissions WHERE admin_id=? AND permission_code=?",
                        (actor.id, permission),
                    ).fetchone(),
                    "이 기능의 권한이 없습니다.",
                    "FORBIDDEN",
                    403,
                )
            if project_id:
                self.runtime.project(c, Context(actor.id), project_id)
            return person

    def session(
        self,
        c: sqlite3.Connection,
        actor: Actor,
        body: DTO,
        admin: bool = False,
        permission: str = "MANAGE_PROJECTS",
    ) -> DTO:
        session = one(
            c,
            "SELECT * FROM evaluation_sessions WHERE id=?",
            (text(body, "session_id"),),
        )
        if admin:
            self.admin(actor, permission, session["project_id"])
        else:
            require(
                actor.role == "EVALUATOR" and actor.project_id == session["project_id"],
                "본인 사업만 접근할 수 있습니다.",
                "FORBIDDEN",
                403,
            )
        return session

    def participant(
        self, c: sqlite3.Connection, actor: Actor, session: DTO, chair: bool = False
    ) -> DTO:
        require(
            actor.role == "EVALUATOR", "평가위원 권한이 필요합니다.", "FORBIDDEN", 403
        )
        row = one(
            c,
            "SELECT * FROM session_participants WHERE session_id=? AND assignment_id=?",
            (session["id"], actor.id),
        )
        require(
            not chair or row["id"] == session["chair_participant_id"],
            "위원장만 실행할 수 있습니다.",
            "FORBIDDEN",
            403,
        )
        return row

    def transact(
        self,
        actor: Actor,
        action: str,
        body: DTO,
        request_key: str,
        handler: Any,
        *,
        database: str = "evaluation",
        write: bool = True,
    ) -> DTO:
        try:
            with self.connect(database, write) as c:
                if write:
                    require(
                        8 <= len(request_key) <= 150,
                        "재시도 식별키가 필요합니다.",
                        "REQUEST_KEY_REQUIRED",
                        422,
                    )
                    previous = c.execute(
                        "SELECT * FROM idempotency_records WHERE actor_scope=? AND operation=? AND request_key=?",
                        (actor.id, action, request_key),
                    ).fetchone()
                    if previous:
                        require(
                            previous["request_sha256"] == digest(body),
                            "같은 요청키의 내용이 다릅니다.",
                            "IDEMPOTENCY_CONFLICT",
                        )
                        cached = json.loads(previous["response_json"])
                        if database == "admin" and "cipher" in cached:
                            return json.loads(
                                self.runtime.decrypt(
                                    base64.b64decode(cached["cipher"]),
                                    f"integrated:{actor.id}:{action}:{request_key}",
                                )
                            )
                        return cached
                result = handler(c, self, actor, body)
                if write:
                    if database == "admin":
                        from app.shared.sync_service import publish_admin

                        publish_admin(c)
                    insert(
                        c,
                        "audit_events",
                        {
                            "actor_type": "EVALUATOR"
                            if actor.role == "EVALUATOR"
                            else "ADMIN",
                            "actor_id": actor.id,
                            "project_id": body.get("project_id"),
                            "action": action,
                            "entity_type": action.split("-")[0],
                            "entity_id": str(result.get("id", "")),
                            "detail_json": "{}",
                        },
                    )
                    insert(
                        c,
                        "idempotency_records",
                        {
                            "actor_scope": actor.id,
                            "operation": action,
                            "request_key": request_key,
                            "request_sha256": digest(body),
                            "response_json": packed(
                                {
                                    "cipher": base64.b64encode(
                                        self.runtime.encrypt(
                                            packed(result),
                                            f"integrated:{actor.id}:{action}:{request_key}",
                                        )
                                    ).decode()
                                }
                            )
                            if database == "admin"
                            else packed(result),
                            "expires_at": future(24),
                        },
                    )
                return result
        except sqlite3.IntegrityError as exc:
            raise ModuleError(
                "CONSTRAINT_CONFLICT", "중복 또는 관계 제약을 확인하세요."
            ) from exc
