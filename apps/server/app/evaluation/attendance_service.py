"""ATT-01..04: attendance, participants and chair are distinct facts."""

import sqlite3

from app.committee.committee_app.v2_core import now
from app.shared.db import DTO, Actor, Store, insert, one, require, rows, text, update


def assignment_fields(s: Store, pid: str) -> dict[str, list[DTO]]:
    """Resolve committee-owned specialty labels through stable assignment IDs."""
    with s.connect("admin") as c:
        values = rows(
            c,
            "SELECT a.id,sp.id AS specialty_id,sp.name FROM committee_assignments a JOIN project_nominees n ON n.id=a.nominee_id LEFT JOIN draw_members dm ON dm.id=n.draw_member_id JOIN candidate_specialties cs ON cs.candidate_id=n.candidate_id JOIN specialties sp ON sp.id=cs.specialty_id WHERE a.project_id=? AND (dm.specialty_id IS NULL OR dm.specialty_id=sp.id)",
            (pid,),
        )
    result: dict[str, list[DTO]] = {}
    for value in values:
        result.setdefault(value["id"], []).append(
            {"id": value["specialty_id"], "name": value["name"]}
        )
    return result


def confirm_attendance(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    require(
        a.role == "EVALUATOR",
        "평가위원 본인만 참석을 확인할 수 있습니다.",
        "FORBIDDEN",
        403,
    )
    require(
        b.get("consent") is True,
        "안내문에 동의해야 참석을 확인할 수 있습니다.",
        "CONSENT_REQUIRED",
        422,
    )
    require(
        b.get("consent_version") == "attendance-v2",
        "최신 동의문을 확인하세요.",
        "CONSENT_REQUIRED",
        422,
    )
    status = b.get("status", "CONFIRMED")
    require(
        status in {"CONFIRMED", "DECLINED"},
        "참석 상태를 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    require(
        not c.execute(
            "SELECT 1 FROM session_participants WHERE assignment_id=?", (a.id,)
        ).fetchone(),
        "참여 명단 확정 후 참석을 변경할 수 없습니다.",
        "PARTICIPANTS_LOCKED",
    )
    require(
        not c.execute(
            "SELECT 1 FROM evaluation_sessions WHERE project_id=? AND status IN ('OPEN','ALL_SUBMITTED','FINALIZED')",
            (a.project_id,),
        ).fetchone(),
        "평가가 시작되어 참석을 변경할 수 없습니다.",
        "SESSION_LOCKED",
    )
    previous = c.execute(
        "SELECT * FROM attendance_records WHERE assignment_id=?", (a.id,)
    ).fetchone()
    values = {
        "project_id": a.project_id,
        "assignment_id": a.id,
        "status": status,
        "consent_version": "attendance-v2",
        "consented_at": now(),
        "confirmed_at": now() if status == "CONFIRMED" else None,
    }
    if previous:
        return update(c, "attendance_records", dict(previous), b, values)
    identity = insert(c, "attendance_records", values)
    return one(c, "SELECT * FROM attendance_records WHERE id=?", (identity,))


def list_attendance(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    pid = text(b, "project_id")
    s.admin(a, "MANAGE_PROJECTS", pid)
    assignments = rows(
        c,
        "SELECT a.id,a.name_snapshot,a.organization_snapshot,a.member_kind,a.roster_id,t.id AS attendance_id,t.status AS attendance_status,t.version AS attendance_version FROM ref_committee_assignments a LEFT JOIN attendance_records t ON t.assignment_id=a.id WHERE a.project_id=? AND a.status='INVITED' AND a.is_deleted=0 ORDER BY a.member_kind,a.reserve_order,a.name_snapshot",
        (pid,),
    )
    fields = assignment_fields(s, pid)
    for assignment in assignments:
        assignment["specialties"] = fields.get(assignment["id"], [])
    sessions = rows(
        c,
        "SELECT * FROM evaluation_sessions WHERE project_id=? ORDER BY round_no DESC",
        (pid,),
    )
    participants = rows(
        c,
        "SELECT p.*,a.name_snapshot FROM session_participants p JOIN ref_committee_assignments a ON a.id=p.assignment_id WHERE p.project_id=?",
        (pid,),
    )
    return {
        "assignments": assignments,
        "sessions": sessions,
        "participants": participants,
        "rosters": rows(
            c,
            "SELECT id,revision_no FROM ref_committee_rosters WHERE project_id=? AND status='CONFIRMED'",
            (pid,),
        ),
        "criteria": rows(
            c,
            "SELECT id,approval_no,total_max_score FROM ref_approved_criteria_versions WHERE project_id=? AND status='APPROVED' AND is_deleted=0",
            (pid,),
        ),
    }


def lock_participants(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    session = s.session(c, a, b, True)
    require(
        session["status"] == "PREPARING", "준비 중인 회차만 명단을 확정할 수 있습니다."
    )
    require(
        not c.execute(
            "SELECT 1 FROM session_participants WHERE session_id=?", (session["id"],)
        ).fetchone(),
        "이미 참여 명단이 확정되었습니다.",
        "PARTICIPANTS_LOCKED",
    )
    ids = b.get("attendance_ids")
    require(
        isinstance(ids, list)
        and all(isinstance(i, str) for i in ids)
        and len(ids) == len(set(ids)),
        "참석 확인자를 선택하세요.",
        "INPUT_INVALID",
        422,
    )
    assert isinstance(ids, list)
    require(
        session["minimum_attendees"] is not None
        and session["minimum_attendees"] <= len(ids) <= session["target_count"],
        "승인된 최소 인원과 정원을 확인하세요.",
        "QUORUM_INVALID",
    )
    fields = assignment_fields(s, session["project_id"])
    primary_ids = rows(
        c,
        "SELECT id FROM ref_committee_assignments WHERE roster_id=? AND member_kind='PRIMARY'",
        (session["roster_id"],),
    )
    required_fields = {f["id"] for p in primary_ids for f in fields.get(p["id"], [])}
    selected_fields: set[str] = set()
    for identity in ids:
        attendance = one(
            c,
            "SELECT t.*,a.roster_id FROM attendance_records t JOIN ref_committee_assignments a ON a.id=t.assignment_id WHERE t.id=? AND t.project_id=? AND t.status='CONFIRMED' AND a.status='INVITED'",
            (identity, session["project_id"]),
        )
        require(
            attendance["roster_id"] == session["roster_id"],
            "현재 명단의 참석자만 선택할 수 있습니다.",
        )
        selected_fields.update(
            f["id"] for f in fields.get(attendance["assignment_id"], [])
        )
        insert(
            c,
            "session_participants",
            {
                "project_id": session["project_id"],
                "session_id": session["id"],
                "assignment_id": attendance["assignment_id"],
                "attendance_id": identity,
                "locked_by": a.id,
            },
        )
    require(
        required_fields <= selected_fields,
        "본위원 명단의 각 분야에서 최소 1명 이상 참석해야 합니다.",
        "SPECIALTY_QUORUM_INVALID",
    )
    return update(c, "evaluation_sessions", session, b, {})


def designate_chair(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    session = s.session(c, a, b, True)
    require(session["status"] == "PREPARING", "평가 시작 전 위원장을 선택하세요.")
    participant = one(
        c,
        "SELECT * FROM session_participants WHERE id=? AND session_id=?",
        (text(b, "participant_id"), session["id"]),
    )
    return update(
        c,
        "evaluation_sessions",
        session,
        b,
        {"chair_participant_id": participant["id"]},
    )
