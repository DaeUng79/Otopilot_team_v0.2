"""Read the existing evaluator session and enforce project/attendance access.

Session issuance, revocation and roster revalidation remain in admin.auth_service.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .db import later, now, parse_time
from .envelope import ApiError, auth_required, forbidden
from .settings import Settings


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

@dataclass
class Principal:
    session_id: str
    session_token_hash: str
    assignment: dict[str, Any]
    project: dict[str, Any]
    attendance: dict[str, Any] | None = None
    evaluation_session: dict[str, Any] | None = None
    participant: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def assignment_id(self) -> str:
        return self.assignment["id"]

    @property
    def project_id(self) -> str:
        return self.project["id"]

    @property
    def attended(self) -> bool:
        return bool(self.attendance and self.attendance["status"] == "CONFIRMED")

    @property
    def is_participant(self) -> bool:
        return self.participant is not None

    @property
    def is_chair(self) -> bool:
        return bool(
            self.evaluation_session and self.participant
            and self.evaluation_session.get("chair_participant_id") == self.participant["id"]
        )

    @property
    def role_label(self) -> str:
        if self.is_chair:
            return "위원장"
        if self.assignment["member_kind"] == "RESERVE":
            return "예비위원"
        return "위원"

    def summary(self) -> dict[str, Any]:
        """화면에 주는 요약. 전화·HMAC·토큰은 포함하지 않는다."""
        session = self.evaluation_session
        return {
            "principal": {
                "assignment_id": self.assignment_id,
                "member_kind": self.assignment["member_kind"],
                "reserve_order": self.assignment["reserve_order"],
                "display_name": self.assignment["name_snapshot"],
                "organization": self.assignment["organization_snapshot"],
                "role_label": self.role_label,
            },
            "project": {"id": self.project_id, "name": self.project["name"], "status": self.project["status"],
                        **self.extras.get("project_extra", {})},
            "attendance": None if self.attendance is None else {
                "status": self.attendance["status"],
                "consent_version": self.attendance["consent_version"],
                "confirmed_at": self.attendance["confirmed_at"],
            },
            "participant": self.is_participant,
            "chair": self.is_chair,
            "session": None if session is None else {
                "id": session["id"],
                "round_no": session["round_no"],
                "status": session["status"],
                "submitted": self.extras.get("submitted", 0),
                "participant_count": self.extras.get("participant_count", 0),
                "dev": self.extras.get("dev", False),
            },
        }

def current_evaluation_session(conn: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM evaluation_sessions WHERE project_id = ? AND status <> 'CANCELLED' "
        "ORDER BY round_no DESC LIMIT 1", (project_id,),
    ).fetchone()
    return dict(row) if row else None

def load_principal(conn: sqlite3.Connection, settings: Settings, token: str | None, *, touch: bool = True) -> Principal:
    """쿠키 토큰 → 세션 → 배정 → 사업. 매 요청 명단 상태를 다시 확인하고 유휴 만료를 연장한다."""
    if not token:
        raise auth_required()
    hashed = token_hash(token)
    session = conn.execute("SELECT * FROM auth_sessions WHERE token_hash = ?", (hashed,)).fetchone()
    if session is None or session["revoked_at"] is not None:
        raise auth_required()
    current = now()
    if session["expires_at"] < current:
        raise auth_required()
    created = parse_time(session["created_at"])
    if (parse_time(current) - created).total_seconds() > settings.session_absolute_seconds:
        raise auth_required()
    assignment = conn.execute(
        "SELECT * FROM ref_committee_assignments WHERE id = ? AND is_deleted = 0", (session["principal_id"],)
    ).fetchone()
    if assignment is None or assignment["status"] != "INVITED" or assignment["project_id"] != session["project_id"]:
        raise auth_required()
    project = conn.execute("SELECT * FROM ref_projects WHERE id = ? AND is_deleted = 0", (session["project_id"],)).fetchone()
    if project is None:
        raise auth_required()
    if touch:
        conn.execute("UPDATE auth_sessions SET expires_at = ?, updated_at = ? WHERE token_hash = ?",
                     (later(settings.session_idle_seconds), current, hashed))
    principal = Principal(session_id=session["id"], session_token_hash=hashed,
                          assignment=dict(assignment), project=dict(project))
    principal.extras["project_extra"] = project_extra(settings, project["id"])
    attendance = conn.execute("SELECT * FROM attendance_records WHERE assignment_id = ?", (assignment["id"],)).fetchone()
    principal.attendance = dict(attendance) if attendance else None
    evaluation_session = current_evaluation_session(conn, project["id"])
    principal.evaluation_session = evaluation_session
    if evaluation_session:
        participant = conn.execute(
            "SELECT * FROM session_participants WHERE session_id = ? AND assignment_id = ?",
            (evaluation_session["id"], assignment["id"]),
        ).fetchone()
        principal.participant = dict(participant) if participant else None
        counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM session_participants WHERE session_id = ?) AS participants, "
            "(SELECT COUNT(*) FROM evaluation_submissions WHERE session_id = ?) AS submitted",
            (evaluation_session["id"], evaluation_session["id"]),
        ).fetchone()
        principal.extras["participant_count"] = counts["participants"]
        principal.extras["submitted"] = counts["submitted"]
        try:
            policy = json.loads(evaluation_session["aggregation_policy_json"])
            principal.extras["dev"] = policy.get("origin") == "DEV_SEED"
        except (ValueError, TypeError):
            principal.extras["dev"] = False
    return principal

def project_extra(settings: Settings, project_id: str) -> dict[str, Any]:
    """평가일·담당자 연락처는 문서 DB(project_profiles) 에서 읽는다. 문서 DB 가 없으면 빈 값."""
    from .db import connect_documents
    try:
        with connect_documents(settings.documents_db_path) as docs:
            if docs.execute("SELECT 1 FROM sqlite_master WHERE name = 'project_profiles'").fetchone() is None:
                return {}
            row = docs.execute("SELECT owner, tel, date FROM project_profiles WHERE project_id = ?", (project_id,)).fetchone()
            if row is None:
                return {}
            return {"evaluation_date": row["date"] or "", "owner": row["owner"] or "", "owner_tel": row["tel"] or ""}
    except Exception:  # noqa: BLE001 - 문서 DB 장애가 로그인을 막지 않는다
        return {}

def require_project(principal: Principal, project_id: str) -> None:
    if principal.project_id != project_id:
        raise ApiError("NOT_FOUND", "찾을 수 없어요.", 404)

def require_attended(principal: Principal) -> None:
    if not principal.attended:
        raise forbidden("먼저 참석 확인이 필요해요.", code="ATTENDANCE_REQUIRED")

def require_participant(principal: Principal) -> None:
    if principal.evaluation_session is None:
        raise ApiError("NOT_READY", "평가회차가 아직 준비되지 않았어요.", 409)
    if not principal.is_participant:
        raise forbidden("실제 평가 참여자로 확정된 위원만 할 수 있어요. 담당자에게 문의해 주세요.", code="NOT_PARTICIPANT")

def require_session(principal: Principal, session_id: str, *statuses: str) -> dict[str, Any]:
    session = principal.evaluation_session
    if session is None or session["id"] != session_id:
        raise ApiError("NOT_FOUND", "평가회차를 찾을 수 없어요.", 404)
    if statuses and session["status"] not in statuses:
        raise ApiError("NOT_READY", f"지금은 할 수 없어요 (회차 상태: {session['status']}).", 409)
    return session

def require_chair(principal: Principal) -> None:
    require_participant(principal)
    if not principal.is_chair:
        raise forbidden("위원장만 할 수 있어요.", code="CHAIR_ONLY")
