import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db import Database
from .errors import DomainError
from .excel import MAX_BYTES, email_of, fields_of, phone_of, prepare_candidate, read_candidates

CONTACT_STATUSES = {"미연락", "연락 불가", "참여 가능", "참여 불가", "제척"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def packed(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def candidate_read(row: sqlite3.Row) -> dict[str, Any]:
    return {"email": ""} | json.loads(row["payload"]) | {"id": row["id"], "version": row["version"]}


class CommitteeService:
    def __init__(self, path: Path) -> None:
        self.db = Database(path)
        self._otp_key = secrets.token_bytes(32)

    def _audit(
        self,
        conn: sqlite3.Connection,
        action: str,
        subject: str,
        details: dict[str, Any],
        actor: str = "local-admin",
    ) -> None:
        conn.execute(
            "INSERT INTO audit_events(action,subject,actor,details,created_at) VALUES (?,?,?,?,?)",
            (action, subject, actor, packed(details), now()),
        )

    def _project(self, conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise DomainError(404, "평가과제를 찾을 수 없습니다.")
        return dict(row) | {"fields": json.loads(row["fields"])}

    def _draw(self, conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        self._project(conn, project_id)
        row = conn.execute("SELECT * FROM draws WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise DomainError(409, "먼저 3배수 예비명단을 추첨하세요.")
        return row

    def _read_draw(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["shortlist"] = json.loads(row["shortlist"])
        result["pool_count"] = len(json.loads(row["pool_snapshot"]))
        result["final_ids"] = json.loads(row["final_ids"])
        result["reserve_ids"] = json.loads(row["reserve_ids"])
        result.pop("pool_snapshot")
        result["contacts"] = [
            dict(c)
            for c in conn.execute(
                "SELECT * FROM contacts WHERE project_id=?", (row["project_id"],)
            ).fetchall()
        ]
        ids = {item["id"] for item in result["shortlist"]}
        result["current_candidates"] = [
            candidate_read(candidate)
            for candidate in conn.execute("SELECT * FROM candidates")
            if candidate["id"] in ids
        ]
        return result

    def list_candidates(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [
                candidate_read(row)
                for row in conn.execute(
                    "SELECT * FROM candidates ORDER BY created_at,id"
                ).fetchall()
            ]

    def _insert_candidate(
        self, conn: sqlite3.Connection, payload: dict[str, Any], source_key: str | None = None
    ) -> dict[str, Any]:
        cid = str(uuid4())
        try:
            conn.execute(
                "INSERT INTO candidates(id,payload,phone,active,source_key,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (cid, packed(payload), payload["phone"], int(payload["active"]), source_key, now()),
            )
        except sqlite3.IntegrityError as exc:
            raise DomainError(
                409, "이미 등록된 휴대전화·이메일 또는 원본 행입니다. 중복을 확인하세요."
            ) from exc
        return payload | {"id": cid, "version": 0}

    def add_candidate(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = prepare_candidate(body)
        with self.db.connect(write=True) as conn:
            item = self._insert_candidate(conn, payload)
            self._audit(conn, "candidate.create", item["id"], {"active": item["active"]})
            return item

    def update_candidate(
        self, cid: str, patch: dict[str, Any], expected_version: int
    ) -> dict[str, Any]:
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
            if row is None:
                raise DomainError(404, "후보를 찾을 수 없습니다.")
            if row["version"] != expected_version:
                raise DomainError(409, "다른 곳에서 후보를 변경했습니다. 다시 불러오세요.")
            finalized = conn.execute(
                "SELECT final_ids,reserve_ids FROM draws WHERE finalized_at IS NOT NULL"
            )
            if any(
                cid in json.loads(draw["final_ids"]) + json.loads(draw["reserve_ids"])
                for draw in finalized.fetchall()
            ):
                raise DomainError(409, "최종 확정된 위원 정보는 변경 절차가 필요합니다.")
            old = candidate_read(row)
            new = prepare_candidate(old | patch)
            try:
                conn.execute(
                    "UPDATE candidates SET payload=?,phone=?,active=?,version=version+1 WHERE id=?",
                    (packed(new), new["phone"], int(new["active"]), cid),
                )
            except sqlite3.IntegrityError as exc:
                raise DomainError(
                    409, "다른 후보가 같은 휴대전화 또는 이메일을 사용하고 있습니다."
                ) from exc
            self._audit(conn, "candidate.update", cid, {"version": expected_version + 1})
            critical = ["name", "phone", "email", "organization", "specialty", "enabled"]
            if any(old.get(key) != new.get(key) for key in critical):
                affected = conn.execute(
                    "SELECT c.project_id FROM contacts c JOIN draws d ON d.project_id=c.project_id "
                    "WHERE c.candidate_id=? AND d.finalized_at IS NULL",
                    (cid,),
                ).fetchall()
                for contact in affected:
                    conn.execute(
                        "UPDATE contacts SET status='미연락',version=version+1,updated_at=? "
                        "WHERE project_id=? AND candidate_id=?",
                        (now(), contact["project_id"], cid),
                    )
                    conn.execute(
                        "UPDATE draws SET version=version+1 WHERE project_id=?",
                        (contact["project_id"],),
                    )
                    self._audit(conn, "contact.recheck", cid, {"project": contact["project_id"]})
            return new | {"id": cid, "version": expected_version + 1}

    def import_preview(self, raw: bytes, password: str, filename: str) -> dict[str, Any]:
        rows = read_candidates(raw, password, filename)
        digest = hashlib.sha256(raw).hexdigest()
        with self.db.connect(write=True) as conn:
            conn.execute(
                "DELETE FROM imports WHERE committed_at IS NULL AND expires_at<?", (time.time(),)
            )
            if conn.execute(
                "SELECT 1 FROM imports WHERE file_hash=? AND committed_at IS NOT NULL", (digest,)
            ).fetchone():
                raise DomainError(409, "이미 등록 확정한 파일입니다. 후보 수정 화면을 사용하세요.")
            existing = {
                row[0] for row in conn.execute("SELECT phone FROM candidates WHERE phone!=''")
            }
            conflicts = [item["source_row"] for item in rows if item["phone"] in existing]
            preview_id = str(uuid4())
            conn.execute(
                "INSERT INTO imports VALUES (?,?,?,?,?,NULL)",
                (preview_id, digest, Path(filename).name, packed(rows), time.time() + 1800),
            )
            return {
                "id": preview_id,
                "filename": Path(filename).name,
                "rows": rows,
                "total": len(rows),
                "active": sum(item["active"] for item in rows),
                "drafts": sum(not item["active"] for item in rows),
                "conflict_rows": conflicts,
                "expires_in": 1800,
            }

    def commit_import(self, preview_id: str) -> dict[str, Any]:
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM imports WHERE id=?", (preview_id,)).fetchone()
            if row is None or row["expires_at"] < time.time():
                raise DomainError(409, "미리보기가 만료되었습니다. 다시 업로드하세요.")
            if row["committed_at"]:
                raise DomainError(409, "이미 등록 확정한 요청입니다.")
            if conn.execute(
                "SELECT 1 FROM imports WHERE file_hash=? AND committed_at IS NOT NULL",
                (row["file_hash"],),
            ).fetchone():
                raise DomainError(409, "다른 요청에서 같은 파일을 먼저 등록했습니다.")
            items = json.loads(row["payload"])
            for item in items:
                source_key = f"{row['file_hash']}:{item['source_sheet']}:{item['source_row']}"
                self._insert_candidate(conn, item, source_key)
            conn.execute(
                "UPDATE imports SET committed_at=?,payload='[]' WHERE id=?", (now(), preview_id)
            )
            self._audit(conn, "import.commit", preview_id, {"rows": len(items)})
            return {"registered": len(items), "drafts": sum(not item["active"] for item in items)}

    def create_project(self, name: str, fields: list[str], target: int) -> dict[str, Any]:
        normalized = fields_of(",".join(fields))
        if target not in {7, 8, 9} or not name.strip() or not normalized:
            raise DomainError(422, "과제명·분야와 최종 정원 7·8·9명 중 하나를 선택하세요.")
        if len(name) > 200 or len(normalized) > 30:
            raise DomainError(422, "과제명은 200자, 선택 분야는 30개 이하로 입력하세요.")
        with self.db.connect(write=True) as conn:
            pid = str(uuid4())
            conn.execute(
                "INSERT INTO projects(id,name,fields,target,created_at) VALUES (?,?,?,?,?)",
                (pid, name.strip(), packed(normalized), target, now()),
            )
            self._audit(conn, "project.create", pid, {"target": target, "fields": normalized})
            return self._project(conn, pid)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [
                dict(row) | {"fields": json.loads(row["fields"])}
                for row in conn.execute(
                    "SELECT * FROM projects ORDER BY created_at DESC,id"
                ).fetchall()
            ]

    def register_proposal(self, raw: bytes, filename: str, name: str = "") -> dict[str, Any]:
        # Store the proposal as an attachment; parsing and evaluation belong to the team module.
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if (
            not filename.lower().endswith(".pdf")
            or not raw.startswith(b"%PDF-")
            or b"%%EOF" not in raw[-1024:]
            or len(raw) > MAX_BYTES
        ):
            raise DomainError(422, "8MB 이하의 PDF 제안서를 등록하세요.")
        title = name.strip() or Path(filename).stem
        if not title or len(title) > 200 or len(filename) > 255:
            raise DomainError(422, "프로젝트명은 200자, 파일명은 255자 이하로 입력하세요.")
        digest = hashlib.sha256(raw).hexdigest()
        with self.db.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM proposals WHERE sha256=?", (digest,)).fetchone():
                raise DomainError(409, "이미 등록된 제안서입니다. 기존 프로젝트를 선택하세요.")
            pid = str(uuid4())
            conn.execute(
                "INSERT INTO projects(id,name,fields,target,created_at,configured) "
                "VALUES (?,?,'[]',7,?,0)",
                (pid, title, now()),
            )
            conn.execute(
                "INSERT INTO proposals VALUES (?,?,?,?,?)", (pid, filename, digest, raw, now())
            )
            self._audit(conn, "proposal.register", pid, {"sha256": digest})
            return self._project(conn, pid)

    def proposal(self, pid: str) -> tuple[bytes, str]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT content,filename FROM proposals WHERE project_id=?", (pid,)
            ).fetchone()
            if not row:
                raise DomainError(404, "등록된 제안서가 없습니다.")
            return bytes(row["content"]), row["filename"]

    def configure_project(
        self, pid: str, fields: list[str], target: int, version: int
    ) -> dict[str, Any]:
        normalized = fields_of(",".join(fields))
        if target not in {7, 8, 9} or not normalized or len(normalized) > 30:
            raise DomainError(422, "분야와 최종 정원 7·8·9명 중 하나를 선택하세요.")
        with self.db.connect(write=True) as conn:
            project = self._project(conn, pid)
            if (
                project["version"] != version
                or conn.execute("SELECT 1 FROM draws WHERE project_id=?", (pid,)).fetchone()
            ):
                raise DomainError(409, "이미 추첨했거나 조건이 변경되었습니다. 다시 불러오세요.")
            conn.execute(
                "UPDATE projects SET fields=?,target=?,configured=1,version=version+1 WHERE id=?",
                (packed(normalized), target, pid),
            )
            self._audit(conn, "project.configure", pid, {"target": target, "fields": normalized})
            return self._project(conn, pid)

    def get_project(self, pid: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            return self._project(conn, pid)

    def _pool(self, conn: sqlite3.Connection, project: dict[str, Any]) -> list[dict[str, Any]]:
        selected = set(project["fields"])
        return [
            item
            for row in conn.execute("SELECT * FROM candidates WHERE active=1 ORDER BY id")
            if selected.intersection((item := candidate_read(row))["fields"])
        ]

    def preview_pool(self, pid: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            project = self._project(conn, pid)
            count = len(self._pool(conn, project))
            required = project["target"] * 3
            return {"eligible": count, "required": required, "shortage": max(0, required - count)}

    def draw(self, pid: str, reviewed: bool) -> dict[str, Any]:
        if not reviewed:
            raise DomainError(422, "추첨 조건을 확인한 뒤 추첨하세요.")
        with self.db.connect(write=True) as conn:
            project = self._project(conn, pid)
            if not project["configured"]:
                raise DomainError(422, "위원 수와 분야를 먼저 선택하세요.")
            if conn.execute("SELECT 1 FROM draws WHERE project_id=?", (pid,)).fetchone():
                raise DomainError(
                    409, "이미 추첨한 과제입니다. 재추첨은 별도 변경 절차가 필요합니다."
                )
            pool = self._pool(conn, project)
            required = project["target"] * 3
            if len(pool) < required:
                raise DomainError(422, f"3배수 후보가 {required - len(pool)}명 부족합니다.")
            snapshot = [
                {
                    key: item[key]
                    for key in [
                        "id",
                        "name",
                        "organization",
                        "position",
                        "fields",
                        "phone",
                        "version",
                    ]
                }
                for item in pool
            ]
            digest = hashlib.sha256(packed(snapshot).encode()).hexdigest()
            shortlist = secrets.SystemRandom().sample(snapshot, required)
            did = str(uuid4())
            conn.execute(
                "INSERT INTO draws(id,project_id,pool_snapshot,shortlist,snapshot_sha256,method,"
                "actor,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    did,
                    pid,
                    packed(snapshot),
                    packed(shortlist),
                    digest,
                    "system-random-sample-v1",
                    "local-admin",
                    now(),
                ),
            )
            for item in shortlist:
                conn.execute(
                    "INSERT INTO contacts VALUES (?,?,?,'',0,?)", (pid, item["id"], "미연락", now())
                )
            self._audit(conn, "draw.create", did, {"count": required, "hash": digest})
            return self._read_draw(conn, self._draw(conn, pid))

    def get_draw(self, pid: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            self._project(conn, pid)
            row = conn.execute("SELECT * FROM draws WHERE project_id=?", (pid,)).fetchone()
            return self._read_draw(conn, row) if row else None

    def update_contact(
        self, pid: str, cid: str, status: str, note: str, expected_version: int
    ) -> dict[str, Any]:
        if status not in CONTACT_STATUSES or len(note) > 2000:
            raise DomainError(422, "통화 상태 또는 메모 길이를 확인하세요.")
        if status == "제척" and not note.strip():
            raise DomainError(422, "제척 사유를 메모에 입력하세요.")
        with self.db.connect(write=True) as conn:
            draw = self._draw(conn, pid)
            if draw["finalized_at"]:
                raise DomainError(409, "최종 확정된 명단의 통화 결과는 변경할 수 없습니다.")
            row = conn.execute(
                "SELECT * FROM contacts WHERE project_id=? AND candidate_id=?", (pid, cid)
            ).fetchone()
            if row is None:
                raise DomainError(422, "예비명단에 포함된 후보만 연락 결과를 저장할 수 있습니다.")
            if row["version"] != expected_version:
                raise DomainError(409, "통화 기록이 변경되었습니다. 다시 불러오세요.")
            conn.execute(
                "UPDATE contacts SET status=?,note=?,version=version+1,updated_at=? "
                "WHERE project_id=? AND candidate_id=?",
                (status, note.strip(), now(), pid, cid),
            )
            conn.execute("UPDATE draws SET version=version+1 WHERE project_id=?", (pid,))
            self._audit(conn, "contact.update", cid, {"project": pid, "status": status})
            return dict(
                conn.execute(
                    "SELECT * FROM contacts WHERE project_id=? AND candidate_id=?", (pid, cid)
                ).fetchone()
            )

    def finalize(
        self, pid: str, ids: list[str], expected_version: int, reserve_ids: list[str] | None = None
    ) -> dict[str, Any]:
        reserve_ids = reserve_ids or []
        with self.db.connect(write=True) as conn:
            draw = self._draw(conn, pid)
            project = self._project(conn, pid)
            if draw["finalized_at"] or draw["version"] != expected_version:
                raise DomainError(409, "명단이 확정되었거나 변경되었습니다. 다시 불러오세요.")
            allowed = {item["id"] for item in json.loads(draw["shortlist"])}
            if (
                len(ids) != project["target"]
                or len(set(ids)) != len(ids)
                or not set(ids) <= allowed
            ):
                raise DomainError(422, "예비명단에서 중복 없이 최종 정원만큼 선택하세요.")
            if (
                len(reserve_ids) != 3
                or len(set(ids + reserve_ids)) != len(ids) + 3
                or not set(reserve_ids) <= allowed
            ):
                raise DomainError(422, "최종위원과 겹치지 않는 예비위원 3명을 선택하세요.")
            for cid in ids + reserve_ids:
                contact = conn.execute(
                    "SELECT status FROM contacts WHERE project_id=? AND candidate_id=?", (pid, cid)
                ).fetchone()
                candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
                if not contact or contact["status"] != "참여 가능" or not candidate["active"]:
                    raise DomainError(422, "참여 가능한 활성 후보만 최종 확정할 수 있습니다.")
                if not set(project["fields"]).intersection(candidate_read(candidate)["fields"]):
                    raise DomainError(
                        422, "현재 후보 전문분야가 이번 선정 분야에 해당하지 않습니다."
                    )
                if cid in ids and not candidate_read(candidate)["auth_ready"]:
                    raise DomainError(422, "최종위원의 휴대전화 또는 이메일을 먼저 등록하세요.")
            conn.execute(
                "UPDATE draws SET final_ids=?,reserve_ids=?,finalized_at=?,assigned_at=?,"
                "version=version+1 WHERE project_id=?",
                (packed(ids), packed(reserve_ids), now(), now(), pid),
            )
            for cid in ids:
                conn.execute("INSERT INTO assignments VALUES (?,?,?)", (pid, cid, now()))
            self._audit(
                conn, "selection.finalize", pid, {"candidate_ids": ids, "reserve_ids": reserve_ids}
            )
            return self._read_draw(conn, self._draw(conn, pid))

    def assign(self, pid: str) -> dict[str, Any]:
        with self.db.connect(write=True) as conn:
            draw = self._draw(conn, pid)
            if not draw["finalized_at"]:
                raise DomainError(409, "최종위원을 먼저 확정하세요.")
            if not draw["assigned_at"]:
                for cid in json.loads(draw["final_ids"]):
                    conn.execute("INSERT INTO assignments VALUES (?,?,?)", (pid, cid, now()))
                conn.execute(
                    "UPDATE draws SET assigned_at=?,version=version+1 WHERE project_id=?",
                    (now(), pid),
                )
                self._audit(
                    conn, "assignment.create", pid, {"count": len(json.loads(draw["final_ids"]))}
                )
            return {
                "assignments": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM assignments WHERE project_id=?", (pid,)
                    ).fetchall()
                ]
            }

    def audit(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM audit_events ORDER BY id DESC LIMIT 100"
                ).fetchall()
            ]

    def admin_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.db.connect(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))
            conn.execute(
                "INSERT INTO sessions VALUES (?,'admin',NULL,NULL,'local',?)",
                (token_hash(token), time.time() + 3600),
            )
        return token

    def require_admin(self, token: str) -> None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT kind,expires_at FROM sessions WHERE token_hash=?", (token_hash(token),)
            ).fetchone()
            if not row or row["kind"] != "admin" or row["expires_at"] <= time.time():
                raise DomainError(401, "로컬 관리자 세션이 필요합니다.")

    def issue_otp(self, pid: str, name: str, phone: str, mode: str) -> dict[str, Any]:
        if mode != "demo":
            raise DomainError(503, "실제 본인인증 제공자가 연결되지 않았습니다.")
        phone = phone_of(phone)
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT c.* FROM candidates c JOIN assignments a ON a.candidate_id=c.id "
                "WHERE a.project_id=? AND c.phone=? AND c.active=1",
                (pid, phone),
            ).fetchone()
            if not row or not phone or candidate_read(row)["name"] != name.strip():
                raise DomainError(403, "입력 정보와 최종 과제 배정을 확인하세요.")
            recent = conn.execute(
                "SELECT created_at FROM otp_requests WHERE project_id=? AND candidate_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (pid, row["id"]),
            ).fetchone()
            if recent and recent[0] > time.time() - 60:
                raise DomainError(429, "인증 코드는 60초 후 다시 요청할 수 있습니다.")
            code = str(secrets.randbelow(900000) + 100000)
            request_id = str(uuid4())
            digest = hmac.new(self._otp_key, f"{request_id}:{code}".encode(), "sha256").hexdigest()
            conn.execute(
                "INSERT INTO otp_requests VALUES (?,?,?,?,?,0,0,?)",
                (request_id, pid, row["id"], digest, time.time() + 300, time.time()),
            )
            return {"request_id": request_id, "expires_in": 300, "mode": "demo", "demo_code": code}

    def logout(self, token: str) -> None:
        with self.db.connect(write=True) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash=? AND kind='evaluator'", (token_hash(token),)
            )

    def demo_login(self, pid: str, name: str, contact: str, mode: str) -> dict[str, Any]:
        if mode != "demo":
            raise DomainError(503, "테스트 로그인이 꺼져 있습니다.")
        is_email = "@" in contact
        value = email_of(contact) if is_email else phone_of(contact)
        with self.db.connect(write=True) as conn:
            rows = conn.execute(
                "SELECT c.* FROM candidates c JOIN assignments a ON a.candidate_id=c.id "
                "WHERE a.project_id=? AND c.active=1",
                (pid,),
            ).fetchall()
            matched = [
                candidate_read(row)
                for row in rows
                if candidate_read(row)["name"] == name.strip()
                and candidate_read(row).get("email" if is_email else "phone", "") == value
            ]
            if not value or len(matched) != 1:
                raise DomainError(403, "이름·연락처와 최종위원 등록 여부를 담당자에게 확인하세요.")
            cid = matched[0]["id"]
            token = secrets.token_urlsafe(32)
            conn.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))
            conn.execute(
                "INSERT INTO sessions VALUES (?,'evaluator',?,?,'demo',?)",
                (token_hash(token), pid, cid, time.time() + 900),
            )
            self._audit(conn, "login.demo", pid, {"candidate_id": cid}, actor="demo-evaluator")
            return {
                "token": token,
                "candidate_id": cid,
                "project_id": pid,
                "name": matched[0]["name"],
                "verification_mode": "demo",
                "production_verified": False,
            }

    def login_project(self, pid: str) -> dict[str, str]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT p.name FROM projects p JOIN draws d ON d.project_id=p.id "
                "WHERE p.id=? AND d.assigned_at IS NOT NULL",
                (pid,),
            ).fetchone()
            if not row:
                raise DomainError(
                    404, "로그인이 준비된 프로젝트가 아닙니다. 담당자에게 확인하세요."
                )
            return {"id": pid, "name": row["name"]}

    def verify_otp(self, request_id: str, code: str) -> dict[str, Any]:
        error: DomainError | None = None
        verified: dict[str, Any] = {}
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM otp_requests WHERE id=?", (request_id,)).fetchone()
            if not row or row["used"] or row["expires_at"] <= time.time() or row["attempts"] >= 5:
                raise DomainError(403, "인증 요청이 만료되었거나 사용 제한을 초과했습니다.")
            digest = hmac.new(self._otp_key, f"{request_id}:{code}".encode(), "sha256").hexdigest()
            if not hmac.compare_digest(digest, row["code_hash"]):
                conn.execute(
                    "UPDATE otp_requests SET attempts=attempts+1 WHERE id=?", (request_id,)
                )
                error = DomainError(403, "인증 코드가 맞지 않습니다.")
            else:
                token = secrets.token_urlsafe(32)
                conn.execute("UPDATE otp_requests SET used=1 WHERE id=?", (request_id,))
                conn.execute(
                    "INSERT INTO sessions VALUES (?,'evaluator',?,?,'demo',?)",
                    (token_hash(token), row["project_id"], row["candidate_id"], time.time() + 900),
                )
                self._audit(
                    conn,
                    "verification.demo",
                    row["project_id"],
                    {"candidate_id": row["candidate_id"]},
                    actor="demo-evaluator",
                )
                verified = {
                    "token": token,
                    "project_id": row["project_id"],
                    "candidate_id": row["candidate_id"],
                    "verification_mode": "demo",
                }
        if error:
            raise error
        return verified

    def verification(self, token: str, pid: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT s.*,c.payload FROM sessions s JOIN assignments a "
                "ON a.project_id=s.project_id AND a.candidate_id=s.candidate_id "
                "JOIN candidates c ON c.id=s.candidate_id "
                "WHERE s.token_hash=? AND s.kind='evaluator' AND s.project_id=? AND c.active=1",
                (token_hash(token), pid),
            ).fetchone()
            if not row or row["expires_at"] <= time.time():
                raise DomainError(403, "이 과제의 인증된 최종 배정위원만 조회할 수 있습니다.")
            return {
                "project_id": pid,
                "candidate_id": row["candidate_id"],
                "name": json.loads(row["payload"])["name"],
                "verification_mode": row["mode"],
                "production_verified": False,
                "project_name": self._project(conn, pid)["name"],
                "next": "평가 준비 완료",
            }
