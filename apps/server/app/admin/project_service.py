"""PRJ-01..07. The admin database owns projects and vendor identities."""

import json
import re
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

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

ARCHIVE_SCHEMA = """CREATE TABLE IF NOT EXISTS project_archive.deleted_projects (
    project_id TEXT PRIMARY KEY,
    department_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    status_before TEXT NOT NULL,
    evaluation_date TEXT,
    project_created_at TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    deleted_by TEXT NOT NULL,
    deletion_reason TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    contact_phone_cipher BLOB NOT NULL,
    contact_email_cipher BLOB
)"""


def _attach_deleted_database(c: sqlite3.Connection, s: Store) -> None:
    archive = s.runtime.path.with_name("projects_delete.sqlite3")
    # ATTACH in rollback-journal mode commits this DB and admin.sqlite3 together.
    require(
        c.execute("PRAGMA main.journal_mode").fetchone()[0].lower() == "delete",
        "사업 삭제 보관 DB의 트랜잭션 모드를 확인하세요.",
        "ARCHIVE_DB_UNAVAILABLE", 503,
    )
    c.execute("ATTACH DATABASE ? AS project_archive", (str(archive),))
    archive.chmod(0o600)
    require(
        c.execute("PRAGMA project_archive.journal_mode").fetchone()[0].lower() == "delete",
        "사업 삭제 보관 DB의 트랜잭션 모드를 확인하세요.",
        "ARCHIVE_DB_UNAVAILABLE", 503,
    )
    c.execute(ARCHIVE_SCHEMA)


def _insert_deleted_snapshot(
    c: sqlite3.Connection, s: Store, row: DTO, *, status_before: str,
    deleted_at: str, deleted_by: str, reason: str,
) -> None:
    snapshot = dated(c, public(s, row))
    snapshot["business_summary"] = _business_summary(s, row["id"])
    c.execute(
        """INSERT OR IGNORE INTO project_archive.deleted_projects (
            project_id,department_id,project_name,status_before,evaluation_date,
            project_created_at,deleted_at,deleted_by,deletion_reason,snapshot_json,
            contact_phone_cipher,contact_email_cipher
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (row["id"], row["department_id"], row["name"], status_before,
         snapshot["evaluation_date"], row["created_at"], deleted_at, deleted_by,
         reason, json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
         row["contact_phone_cipher"], row["contact_email_cipher"]),
    )


def _project_tables(c: sqlite3.Connection, schema: str) -> list[str]:
    """Return project-scoped tables in child-before-parent foreign-key order."""
    tables = [row[0] for row in c.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    scoped = {table for table in tables if any(
        column[1] == "project_id" for column in c.execute(f'PRAGMA {schema}.table_info("{table}")')
    )}
    dependencies = {table: {row[2] for row in c.execute(
        f'PRAGMA {schema}.foreign_key_list("{table}")') if row[2] in scoped and row[2] != table}
                    for table in scoped}
    ordered = []
    while scoped:
        ready = sorted(table for table in scoped if not any(
            table in dependencies[other] for other in scoped if other != table
        ))
        require(bool(ready), "사업 관계 테이블의 삭제 순서를 확인하세요.", "PURGE_SCHEMA_INVALID", 503)
        ordered.extend(ready)
        scoped.difference_update(ready)
    return ordered


def _purge_documents(c: sqlite3.Connection, s: Store, project_id: str) -> None:
    path = s.documents_path or s.runtime.path.with_name("documents_parse.sqlite3")
    if not path.is_file():
        return
    c.execute("ATTACH DATABASE ? AS document_purge", (str(path),))
    require(c.execute("PRAGMA document_purge.journal_mode").fetchone()[0].lower() == "delete",
            "문서 DB의 트랜잭션 모드를 확인하세요.", "PURGE_DB_UNAVAILABLE", 503)
    tables = {row[0] for row in c.execute(
        "SELECT name FROM document_purge.sqlite_master WHERE type='table'"
    )}
    for table in ("requirement_jobs", "criteria_jobs"):
        if table in tables:
            require(not c.execute(
                f"SELECT 1 FROM document_purge.{table} WHERE project_id=? "
                "AND status IN ('queued','running') LIMIT 1", (project_id,)
            ).fetchone(), "문서 처리가 끝난 뒤 사업을 삭제하세요.", "PROJECT_LOCKED", 409)
    scoped = _project_tables(c, "document_purge")
    ids = set()
    for table in scoped:
        require(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", table),
                "문서 테이블 이름을 확인하세요.", "PURGE_SCHEMA_INVALID", 503)
        columns = {row[1] for row in c.execute(f'PRAGMA document_purge.table_info("{table}")')}
        if "document_id" in columns:
            ids.update(row[0] for row in c.execute(
                f'SELECT document_id FROM document_purge."{table}" WHERE project_id=? AND document_id IS NOT NULL',
                (project_id,),
            ))
    for table in scoped:
        c.execute(f'DELETE FROM document_purge."{table}" WHERE project_id=?', (project_id,))
    if "documents" not in tables:
        return
    linked = [table for table in scoped if "document_id" in {
        row[1] for row in c.execute(f'PRAGMA document_purge.table_info("{table}")')
    }]
    for document_id in ids:
        if any(c.execute(
            f'SELECT 1 FROM document_purge."{table}" WHERE document_id=? LIMIT 1',
            (document_id,),
        ).fetchone() for table in linked):
            continue
        for table in ("criteria_results", "requirement_results", "rfp_toc_snapshots",
                      "table_cells",
                      "snapshot_assets", "blocks", "pages", "parse_snapshots"):
            if table in tables:
                c.execute(f'DELETE FROM document_purge."{table}" WHERE document_id=?',
                          (document_id,))
        c.execute("DELETE FROM document_purge.documents WHERE document_id=?", (document_id,))
        if "source_files" in tables:
            if "managed_result_files" in tables:
                c.execute("DELETE FROM document_purge.source_files WHERE sha256=? "
                          "AND NOT EXISTS (SELECT 1 FROM document_purge.managed_result_files "
                          "WHERE source_sha256=?)", (document_id, document_id))
            else:
                c.execute("DELETE FROM document_purge.source_files WHERE sha256=?",
                          (document_id,))
    if "assets" in tables and "snapshot_assets" in tables:
        c.execute("DELETE FROM document_purge.assets WHERE NOT EXISTS "
                  "(SELECT 1 FROM document_purge.snapshot_assets WHERE snapshot_assets.sha256=assets.sha256)")
    require(not c.execute("PRAGMA document_purge.foreign_key_check").fetchall(),
            "문서 관계 데이터 삭제를 확인하세요.", "PURGE_FK_INVALID", 503)


def reclaim_document_space(s: Store) -> int:
    """Shrink the document DB after a successful project-delete transaction."""
    path = s.documents_path or s.runtime.path.with_name("documents_parse.sqlite3")
    if not path.is_file():
        return 0
    with closing(sqlite3.connect(path, timeout=30)) as db:
        if db.execute("PRAGMA freelist_count").fetchone()[0] == 0:
            return 0
        before = path.stat().st_size
        db.execute("VACUUM")
        return before - path.stat().st_size


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
    reason = text(b, "reason", 1000)
    # The archive and active databases commit together in rollback-journal mode.
    _attach_deleted_database(c, s)
    deleted_at = now()
    _insert_deleted_snapshot(
        c, s, row, status_before=row["status"], deleted_at=deleted_at,
        deleted_by=a.id, reason=reason,
    )
    deleted = update(
        c, "projects", row, b,
        {"deleted_at": deleted_at, "deleted_by": a.id, "status": "CANCELLED"},
    )
    c.execute("UPDATE project_vendors SET active=0,deleted_at=?,deleted_by=?,"
              "version=version+1 WHERE project_id=? AND deleted_at IS NULL",
              (deleted_at, a.id, row["id"]))
    # Publish a tombstone before removing the active project row.
    from app.shared.integration_contracts import publish_admin_snapshots
    publish_admin_snapshots(c)
    _purge_documents(c, s, row["id"])
    for table in _project_tables(c, "main"):
        require(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", table),
                "사업 테이블 이름을 확인하세요.", "PURGE_SCHEMA_INVALID", 503)
        c.execute(f'DELETE FROM main."{table}" WHERE project_id=?', (row["id"],))
    c.execute("DELETE FROM main.projects WHERE id=?", (row["id"],))
    require(not c.execute("PRAGMA main.foreign_key_check").fetchall(),
            "사업 관계 데이터 삭제를 확인하세요.", "PURGE_FK_INVALID", 503)
    return public(s, deleted)


def backfill_deleted_projects(s: Store) -> int:
    """Move legacy soft-deleted project metadata into the separate archive DB."""
    with s.connect("admin", True) as c:
        legacy = rows(
            c, "SELECT * FROM projects WHERE deleted_at IS NOT NULL ORDER BY deleted_at,id"
        )
        if not legacy:
            return 0
        _attach_deleted_database(c, s)
        before = c.execute(
            "SELECT COUNT(*) FROM project_archive.deleted_projects"
        ).fetchone()[0]
        for row in legacy:
            _insert_deleted_snapshot(
                c, s, row, status_before="UNKNOWN",
                deleted_at=row["deleted_at"], deleted_by=row["deleted_by"] or "",
                reason="기존 삭제 기록: 삭제 사유 미보관",
            )
        after = c.execute(
            "SELECT COUNT(*) FROM project_archive.deleted_projects"
        ).fetchone()[0]
        return after - before


def _business_summary(s: Store, project_id: str) -> DTO:
    """Freeze the latest RFP's three requirement summaries when available."""
    result: DTO = {key: [] for key in (
        "current_status", "background_and_need", "scope"
    )}
    path = s.documents_path or s.runtime.path.with_name("documents_parse.sqlite3")
    if not path.is_file():
        return result
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('project_rfp_uploads','rfp_snapshot_bindings','requirement_results','parse_snapshots')"
        )}
        if len(tables) < 4:
            return result
        upload = db.execute(
            """SELECT u.document_id,b.parse_revision FROM project_rfp_uploads u
               JOIN rfp_snapshot_bindings b ON b.project_id=u.project_id
                 AND b.upload_revision=u.revision
               WHERE u.project_id=? ORDER BY u.revision DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        if upload is None:
            return result
        saved = db.execute(
            """SELECT result_json FROM requirement_results
               WHERE document_id=? AND source_revision=?
               ORDER BY created_at DESC LIMIT 1""",
            (upload["document_id"], upload["parse_revision"]),
        ).fetchone()
        if saved is None:
            return result
        parsed = db.execute(
            "SELECT document_json FROM parse_snapshots WHERE document_id=? AND revision=?",
            (upload["document_id"], upload["parse_revision"]),
        ).fetchone()
        require(parsed is not None, "요구사항 결과의 파싱 원문이 없습니다.", "DOCUMENT_MISSING")
        page_map = {}
        for block in json.loads(parsed[0]).get("blocks", []):
            pages = block.get("physical_page_numbers") or [block.get("physical_page_number")]
            page_map[block.get("block_id")] = [page for page in pages
                                                if isinstance(page, int) and page > 0]
        extracted = json.loads(saved[0]).get("business_status") or {}
        for category in result:
            for point in extracted.get(category, []):
                pages = sorted({page for block_id in point.get("source_block_ids", [])
                                for page in page_map.get(block_id, [])})
                result[category].append({"text": point["text"], "pages": pages})
    return result


def _deleted_database(s: Store) -> Path:
    return s.runtime.path.with_name("projects_delete.sqlite3")


def _deleted_connection(s: Store) -> sqlite3.Connection | None:
    path = _deleted_database(s)
    if not path.is_file():
        return None
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deleted_projects'"
    ).fetchone():
        connection.close()
        return None
    return connection


def list_deleted_projects(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    s.admin(a, "MANAGE_PROJECTS")
    connection = _deleted_connection(s)
    if connection is None:
        return paginate([], b)
    try:
        query = str(b.get("search", "")).strip()
        require(len(query) <= 200, "검색어가 너무 깁니다.", "INPUT_INVALID", 422)
        items = rows(
            connection,
            """SELECT project_id AS id,project_name AS name,status_before AS status,
               evaluation_date,deleted_at,deletion_reason,department_id,
               json_extract(snapshot_json,'$.contact_name') AS contact_name
               FROM deleted_projects WHERE (?='SUPER_ADMIN' OR department_id=?)
               AND (project_name LIKE ? OR deletion_reason LIKE ?)
               ORDER BY deleted_at DESC,project_id""",
            (a.role, a.department_id, "%" + query + "%", "%" + query + "%"),
        )
        return paginate(items, b)
    finally:
        connection.close()


def deleted_project_detail(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    s.admin(a, "MANAGE_PROJECTS")
    pid = text(b, "deleted_project_id")
    connection = _deleted_connection(s)
    require(connection is not None, "삭제된 사업을 찾을 수 없습니다.", "NOT_FOUND", 404)
    try:
        row = one(
            connection,
            "SELECT * FROM deleted_projects WHERE project_id=? AND (?='SUPER_ADMIN' OR department_id=?)",
            (pid, a.role, a.department_id),
        )
        detail = json.loads(row["snapshot_json"])
        detail.update(
            id=pid, status=row["status_before"], deleted_at=row["deleted_at"],
            deleted_by=row["deleted_by"], deletion_reason=row["deletion_reason"],
            evaluation_date=row["evaluation_date"],
            contact_phone=s.runtime.decrypt(row["contact_phone_cipher"], pid + ":phone"),
            contact_email=s.runtime.decrypt(row["contact_email_cipher"], pid + ":email")
            if row["contact_email_cipher"] else "",
        )
        return detail
    finally:
        connection.close()


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
    # 이전 버전에서 삭제한 업체는 행과 자료가 남아 있었다. 같은 법인명이나
    # 표시 코드를 다시 쓰기 전에 그 잔여 자료를 지우고 새 ID를 발급한다.
    archived = rows(c,
        "SELECT id FROM project_vendors WHERE project_id=? AND active=0 "
        "AND deleted_at IS NOT NULL AND (legal_name=? OR display_code=?)",
        (project["id"], values["legal_name"], values["display_code"]),
    )
    for old in archived:
        _purge_vendor(c, s, project["id"], old["id"])
    identity = insert(c, "project_vendors", values)
    return one(c, "SELECT * FROM project_vendors WHERE id=?", (identity,))


def _purge_vendor(c: sqlite3.Connection, s: Store, project_id: str, vendor_id: str) -> None:
    """업체·제안서·분석·평가 참조를 관리 DB 거래와 함께 영구 삭제한다."""
    from app.documents.document_gateway import delete_upload

    attached = {row[1] for row in c.execute("PRAGMA database_list")}
    if "vendor_evaluation" not in attached:
        c.execute("ATTACH DATABASE ? AS vendor_evaluation", (str(s.evaluation_path),))
        require(c.execute("PRAGMA vendor_evaluation.journal_mode").fetchone()[0].lower() == "delete",
                "평가 DB의 트랜잭션 모드를 확인하세요.", "PURGE_DB_UNAVAILABLE", 503)
    require(not c.execute(
        "SELECT 1 FROM vendor_evaluation.evaluation_sessions WHERE project_id=? LIMIT 1",
        (project_id,),
    ).fetchone(), "평가가 시작된 사업의 업체는 삭제할 수 없습니다.", "PROJECT_LOCKED", 409)

    document_path = s.documents_path or s.runtime.path.with_name("documents_parse.sqlite3")
    if document_path.is_file():
        if "vendor_documents" not in attached:
            c.execute("ATTACH DATABASE ? AS vendor_documents", (str(document_path),))
            require(c.execute("PRAGMA vendor_documents.journal_mode").fetchone()[0].lower() == "delete",
                    "문서 DB의 트랜잭션 모드를 확인하세요.", "PURGE_DB_UNAVAILABLE", 503)
        uploads = rows(c,
            "SELECT id FROM vendor_documents.project_proposal_uploads "
            "WHERE project_id=? AND vendor_id=?", (project_id, vendor_id))
        for upload in uploads:
            delete_upload(document_path, project_id, proposal_upload_id=upload["id"],
                          connection=c, schema="vendor_documents")
    else:
        uploads = []

    upload_ids = [upload["id"] for upload in uploads]
    ref_ids = [row[0] for row in c.execute(
        "SELECT id FROM vendor_evaluation.ref_proposal_uploads "
        "WHERE project_id=? AND vendor_id=?", (project_id, vendor_id))]
    all_ids = set(upload_ids + ref_ids + [vendor_id])
    require(not c.execute(
        "SELECT 1 FROM vendor_evaluation.session_proposals WHERE vendor_id=? LIMIT 1",
        (vendor_id,),
    ).fetchone(), "평가에 사용된 업체는 삭제할 수 없습니다.", "PROJECT_LOCKED", 409)
    c.execute("DELETE FROM vendor_evaluation.ref_proposal_uploads WHERE project_id=? AND vendor_id=?",
              (project_id, vendor_id))
    c.execute("DELETE FROM vendor_evaluation.ref_project_vendors WHERE id=? AND project_id=?",
              (vendor_id, project_id))
    for identity in all_ids:
        for schema in ("vendor_evaluation", "main"):
            c.execute(f"DELETE FROM {schema}.audit_events WHERE project_id=? AND entity_id=?",
                      (project_id, identity))
            c.execute(f"DELETE FROM {schema}.sync_inbox WHERE aggregate_id=?",
                      (identity,))
            c.execute(f"DELETE FROM {schema}.sync_outbox WHERE aggregate_id=?",
                      (identity,))
    c.execute("DELETE FROM project_vendors WHERE id=? AND project_id=?", (vendor_id, project_id))
    require(not c.execute("PRAGMA vendor_evaluation.foreign_key_check").fetchall(),
            "평가 자료의 업체 연결을 확인하세요.", "PURGE_FK_INVALID", 503)
    if document_path.is_file():
        require(not c.execute("PRAGMA vendor_documents.foreign_key_check").fetchall(),
                "문서 자료의 업체 연결을 확인하세요.", "PURGE_FK_INVALID", 503)


def archive_vendor(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    project = allowed(s, a, b, True)
    row = one(
        c,
        "SELECT * FROM project_vendors WHERE id=? AND project_id=?",
        (text(b, "vendor_id"), project["id"]),
    )
    require(row["deleted_at"] is None, "이미 삭제된 업체입니다.", "NOT_FOUND", 404)
    require(row["version"] == integer(b, "version", 1),
            "업체 정보가 변경되었습니다. 다시 조회하세요.", "VERSION_CONFLICT", 409)
    _purge_vendor(c, s, project["id"], row["id"])
    return {"id": row["id"], "status": "DELETED"}
