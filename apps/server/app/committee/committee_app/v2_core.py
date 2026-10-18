"""Shared transaction, authorization and privacy boundary for the v2 modules."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import sys
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ValidationError

DTO = dict[str, Any]
M = TypeVar("M", bound=BaseModel)
ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "contracts/committee_schema_v2.json").is_file():
    ROOT = Path(sys.prefix)  # Wheel data-files; editable checkouts use the branch files above.
_SCHEMA = json.loads((ROOT / "contracts/committee_schema_v2.json").read_text(encoding="utf8"))
_IDENTIFIERS = {t["name"]: {f[0] for f in t["fields"]} for t in _SCHEMA["tables"]}


class ModuleError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Context:
    """Created by a trusted server authenticator, never from request JSON."""

    actor_id: str
    request_key: str = ""


@dataclass(frozen=True)
class ExportFile:
    filename: str
    content: bytes
    media_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def now() -> str:
    return datetime.now(UTC).isoformat()


def packed(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(packed(value).encode()).hexdigest()


def validate(model: type[M], command: DTO) -> M:
    try:
        return model.model_validate(command)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, e["loc"])) for e in exc.errors())
        raise ModuleError("INPUT_INVALID", f"입력 항목을 확인하세요: {fields}", 422) from exc


def version(row: sqlite3.Row, expected: int) -> None:
    if row["version"] != expected:
        raise ModuleError("VERSION_CONFLICT", "다른 작업에서 변경했습니다. 다시 조회하세요.")


class Runtime:
    def __init__(
        self,
        path: Path,
        *,
        pii_key: bytes,
        lookup_key: bytes,
        auth_key: bytes,
        auth_key_version: int = 1,
    ) -> None:
        if any(len(k) != 32 for k in (pii_key, lookup_key, auth_key)):
            raise ValueError("Three separate 32-byte keys are required")
        if len({pii_key, lookup_key, auth_key}) != 3 or auth_key_version < 1:
            raise ValueError("Keys must be distinct; auth_key_version must be positive")
        self.path = path.resolve()
        self._aes = AESGCM(pii_key)
        self._lookup_key, self._auth_key = lookup_key, auth_key
        self.auth_key_version = auth_key_version

    def encrypt(self, value: str, scope: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aes.encrypt(nonce, value.encode(), scope.encode())

    def decrypt(self, value: bytes, scope: str) -> str:
        try:
            return self._aes.decrypt(value[:12], value[12:], scope.encode()).decode()
        except (InvalidTag, ValueError, UnicodeError) as exc:
            raise ModuleError(
                "KEY_OR_DATA_INVALID", "암호화 키 또는 저장 자료를 확인하세요.", 503
            ) from exc

    def lookup(self, *values: str) -> str:
        return hmac.new(self._lookup_key, packed(values).encode(), hashlib.sha256).hexdigest()

    def login_lookup_hmac(self, project_id: str, name: str, last4: str) -> str:
        normalized = "".join(unicodedata.normalize("NFC", name).split()).casefold()
        return hmac.new(
            self._auth_key, packed([project_id, normalized, last4]).encode(), hashlib.sha256
        ).hexdigest()

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=20)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=20000")
            try:
                if write:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    async def initialize(self, *, development_parents: bool = False) -> None:
        await asyncio.to_thread(self._initialize, development_parents)

    def _initialize(self, development_parents: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            names = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "candidates" in names or (
                "projects" in names
                and "department_id"
                not in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
            ):
                raise ModuleError(
                    "LEGACY_SCHEMA", "기존 DB는 보존하고 새 admin.sqlite3로 이전하세요."
                )
            if development_parents:
                conn.executescript(
                    (ROOT / "fixtures/shared_parents.sql").read_text(encoding="utf8")
                )
            required = {"departments", "admin_users", "projects"}
            names = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not required.issubset(names):
                raise ModuleError(
                    "PARENT_SCHEMA_REQUIRED", "공통 부서·관리자·사업 스키마가 필요합니다."
                )
            for table in names.intersection(_IDENTIFIERS):
                # Identifiers are restricted to the checked-in schema, not request data.
                columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                if not _IDENTIFIERS[table].issubset(columns):
                    raise ModuleError(
                        "SCHEMA_INCOMPATIBLE", f"{table} 테이블이 v2 필드 계약과 다릅니다."
                    )
            migration = ROOT / "migrations/admin/20261016_lex_001.sql"
            content = migration.read_text(encoding="utf8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            if "schema_migrations" in names:
                row = conn.execute(
                    "SELECT checksum FROM schema_migrations WHERE migration_name=?",
                    (migration.name,),
                ).fetchone()
                if row:
                    if row[0] != checksum:
                        raise ModuleError(
                            "MIGRATION_CHANGED", "이미 적용한 migration이 변경되었습니다."
                        )
                    if conn.execute("PRAGMA foreign_key_check").fetchall():
                        raise ModuleError("FK_INVALID", "외래키 검증에 실패했습니다.")
                    return
            # executescript commits any pending transaction; BEGIN belongs inside the script.
            conn.executescript("BEGIN IMMEDIATE;\n" + content)
            conn.execute(
                "INSERT INTO schema_migrations VALUES (?,?,?)", (migration.name, checksum, now())
            )
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise ModuleError("FK_INVALID", "외래키 검증에 실패했습니다.")

    def authorize(
        self,
        conn: sqlite3.Connection,
        ctx: Context,
        department_id: str | None = None,
    ) -> sqlite3.Row:
        actor = conn.execute("SELECT * FROM admin_users WHERE id=?", (ctx.actor_id,)).fetchone()
        if actor is None or not actor["active"] or actor["deleted_at"] is not None:
            raise ModuleError("AUTH_REQUIRED", "유효한 관리자 세션이 필요합니다.", 401)
        if actor["role"] not in {"SUPER_ADMIN", "DEPARTMENT_ADMIN"}:
            raise ModuleError("FORBIDDEN", "관리 권한이 없습니다.", 403)
        if actor["role"] == "DEPARTMENT_ADMIN" and (
            not actor["department_id"] or department_id not in (None, actor["department_id"])
        ):
            raise ModuleError("FORBIDDEN", "소속 부서의 자료만 관리할 수 있습니다.", 403)
        if department_id is not None:
            dept = conn.execute(
                "SELECT active,deleted_at FROM departments WHERE id=?", (department_id,)
            ).fetchone()
            if dept is None or not dept[0] or dept[1] is not None:
                raise ModuleError("NOT_READY", "활성 부서가 아닙니다.")
        return actor

    def project(
        self, conn: sqlite3.Connection, ctx: Context, project_id: str, *, edit: bool = False
    ) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ModuleError("NOT_FOUND", "사업을 찾을 수 없습니다.", 404)
        self.authorize(conn, ctx, row["department_id"])
        if row["deleted_at"] is not None or (
            edit and row["status"] not in {"DRAFT", "PREPARING", "READY"}
        ):
            raise ModuleError("PROJECT_LOCKED", "위원 명단을 변경할 수 없는 사업 상태입니다.")
        return row

    @staticmethod
    def unlocked(conn: sqlite3.Connection, project_id: str) -> None:
        if conn.execute(
            "SELECT 1 FROM committee_rosters WHERE project_id=? AND status='CONFIRMED'",
            (project_id,),
        ).fetchone():
            raise ModuleError("ROSTER_LOCKED", "초청명단이 확정되어 변경할 수 없습니다.")

    @staticmethod
    def insert(conn: sqlite3.Connection, table: str, values: DTO) -> str:
        # Table/column identifiers are internal constants; never pass user identifiers.
        values = {
            "id": str(uuid4()),
            "created_at": now(),
            "updated_at": now(),
            "version": 1,
        } | values
        if table not in _IDENTIFIERS or not set(values).issubset(_IDENTIFIERS[table]):
            raise ValueError("Table and columns must belong to the checked-in v2 schema")
        cols = ",".join(values)
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()),
        )
        return str(values["id"])

    def audit(
        self,
        conn: sqlite3.Connection,
        ctx: Context,
        action: str,
        entity: str,
        entity_id: str,
        project_id: str | None = None,
    ) -> None:
        self.insert(
            conn,
            "audit_events",
            {
                "actor_type": "ADMIN",
                "actor_id": ctx.actor_id,
                "project_id": project_id,
                "action": action,
                "entity_type": entity,
                "entity_id": entity_id,
                "detail_json": "{}",
            },
        )

    async def run(
        self,
        ctx: Context,
        action: str,
        command: DTO,
        operation: Callable[[sqlite3.Connection], DTO],
        *,
        write: bool = True,
    ) -> DTO:
        return await asyncio.to_thread(self._run, ctx, action, command, operation, write)

    def _run(
        self,
        ctx: Context,
        action: str,
        command: DTO,
        operation: Callable[[sqlite3.Connection], DTO],
        write: bool,
    ) -> DTO:
        try:
            with self.connect(write=write) as conn:
                actor = self.authorize(conn, ctx)
                if actor["department_id"]:
                    self.authorize(conn, ctx, actor["department_id"])
                # Revalidate resource ownership even when returning an idempotent replay.
                if command.get("department_id"):
                    self.authorize(conn, ctx, command["department_id"])
                if command.get("project_id"):
                    self.project(conn, ctx, command["project_id"])
                for field, query in (
                    ("candidate_id", "SELECT department_id FROM evaluator_candidates WHERE id=?"),
                    ("preview_id", "SELECT department_id FROM candidate_imports WHERE id=?"),
                ):
                    if command.get(field):
                        resource = conn.execute(query, (command[field],)).fetchone()
                        if resource:
                            self.authorize(conn, ctx, resource[0])
                if not write:
                    return operation(conn)
                if not ctx.request_key or len(ctx.request_key) > 128:
                    raise ModuleError(
                        "IDEMPOTENCY_REQUIRED", "쓰기 요청에는 요청키가 필요합니다.", 422
                    )
                # Bind replay to current authorization scope as well as the actor.
                scope = packed(
                    [ctx.actor_id, actor["role"], actor["department_id"], actor["version"]]
                )
                request_hash = self.lookup("request", action, packed(command))
                aad = packed([scope, action, ctx.request_key])
                previous = conn.execute(
                    "SELECT * FROM idempotency_records WHERE actor_scope=? AND "
                    "operation=? AND request_key=?",
                    (scope, action, ctx.request_key),
                ).fetchone()
                if previous:
                    if previous["request_sha256"] != request_hash:
                        raise ModuleError(
                            "IDEMPOTENCY_CONFLICT", "같은 요청키에 다른 입력이 전달되었습니다."
                        )
                    if previous["expires_at"] < now():
                        raise ModuleError(
                            "REQUEST_EXPIRED", "만료된 요청키입니다. 새 키를 사용하세요."
                        )
                    result: DTO = json.loads(
                        self.decrypt(
                            base64.b64decode(json.loads(previous["response_json"])["cipher"]), aad
                        )
                    )
                    return result
                result = operation(conn)
                self.insert(
                    conn,
                    "idempotency_records",
                    {
                        "actor_scope": scope,
                        "operation": action,
                        "request_key": ctx.request_key,
                        "request_sha256": request_hash,
                        "response_json": packed(
                            {"cipher": base64.b64encode(self.encrypt(packed(result), aad)).decode()}
                        ),
                        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    },
                )
                return result
        except sqlite3.IntegrityError as exc:
            raise ModuleError(
                "CONSTRAINT_CONFLICT", "중복·외래키·확정 자료 제약을 확인하세요."
            ) from exc
        except sqlite3.OperationalError as exc:
            raise ModuleError(
                "DB_UNAVAILABLE", "DB 연결 상태를 확인하고 같은 요청키로 재시도하세요.", 503
            ) from exc
