"""ATT-00/05 and SCO-01..03/05. Integer scores, optimistic edits, atomic submissions."""

import sqlite3

from app.committee.committee_app.v2_core import digest, now, packed
from app.shared.db import DTO, Actor, Store, insert, integer, one, require, rows, text, update

POLICY = {
    "policy_version": "v2-1",
    "exclude": "one_lowest_one_highest_total",
    "tie_break": "participant_id_ascending",
    "rounding": "ROUND_HALF_UP",
    "decimal_places": 2,
    "rank": "competition_on_display_average",
}


def prepare_session(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    pid = text(b, "project_id")
    s.admin(a, "MANAGE_PROJECTS", pid)
    require(
        b.get("approve_policy") is True,
        "집계 규칙과 운영 최소 인원을 확인해야 합니다.",
        "POLICY_REQUIRED",
        422,
    )
    target = integer(b, "target_count", 5, 9)
    minimum = integer(b, "minimum_attendees", 3, target)
    roster = one(
        c,
        "SELECT * FROM ref_committee_rosters WHERE id=? AND project_id=? AND status='CONFIRMED' AND is_deleted=0",
        (text(b, "roster_id"), pid),
    )
    criterion = one(
        c,
        "SELECT * FROM ref_approved_criteria_versions WHERE id=? AND project_id=? AND status='APPROVED' AND is_deleted=0",
        (text(b, "approved_criteria_version_id"), pid),
    )
    require(
        c.execute(
            "SELECT COUNT(*) FROM ref_committee_assignments WHERE roster_id=? AND member_kind='PRIMARY' AND status='INVITED'",
            (roster["id"],),
        ).fetchone()[0]
        == target,
        "정원을 확정 명단과 맞춰주세요.",
    )
    require(
        not c.execute(
            "SELECT 1 FROM evaluation_sessions WHERE project_id=? AND status<>'CANCELLED'",
            (pid,),
        ).fetchone(),
        "이미 평가 회차가 준비되어 있습니다.",
    )
    round_no = c.execute(
        "SELECT COALESCE(MAX(round_no),0)+1 FROM evaluation_sessions WHERE project_id=?",
        (pid,),
    ).fetchone()[0]
    identity = insert(
        c,
        "evaluation_sessions",
        {
            "project_id": pid,
            "round_no": round_no,
            "roster_id": roster["id"],
            "approved_criteria_version_id": criterion["id"],
            "status": "PREPARING",
            "target_count": target,
            "minimum_attendees": minimum,
            "aggregation_policy_json": packed(POLICY),
            "policy_approved_by": a.id,
        },
    )
    return one(c, "SELECT * FROM evaluation_sessions WHERE id=?", (identity,))


def open_session(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    from app.shared.sync_service import publish

    session = s.session(c, a, b, True)
    require(
        session["status"] == "PREPARING"
        and session["chair_participant_id"]
        and session["policy_approved_by"],
        "참여자 확정과 위원장 지정이 필요합니다.",
    )
    participants = rows(
        c, "SELECT * FROM session_participants WHERE session_id=?", (session["id"],)
    )
    require(
        session["minimum_attendees"]
        and session["minimum_attendees"]
        <= len(participants)
        <= session["target_count"],
        "운영 최소 인원을 충족하지 못했습니다.",
        "QUORUM_INVALID",
    )
    require(
        c.execute(
            "SELECT 1 FROM ref_committee_rosters WHERE id=? AND status='CONFIRMED' AND is_deleted=0",
            (session["roster_id"],),
        ).fetchone(),
        "확정 명단이 유효하지 않습니다.",
    )
    criterion = one(
        c,
        "SELECT * FROM ref_approved_criteria_versions WHERE id=? AND status='APPROVED' AND is_deleted=0",
        (session["approved_criteria_version_id"],),
    )
    items = rows(
        c,
        "SELECT * FROM ref_approved_criteria_items WHERE approved_criteria_version_id=? AND is_scorable=1 AND is_deleted=0 ORDER BY sort_order,id",
        (criterion["id"],),
    )
    require(
        items and sum(i["max_score"] for i in items) == criterion["total_max_score"],
        "평가항목과 배점을 확인하세요.",
    )
    require(
        not any(
            c.execute(
                "SELECT 1 FROM ref_approved_criteria_items WHERE parent_id=? AND is_deleted=0",
                (i["id"],),
            ).fetchone()
            for i in items
        ),
        "상위 항목에는 점수를 입력할 수 없습니다.",
    )
    vendors = rows(
        c,
        "SELECT * FROM ref_project_vendors WHERE project_id=? AND active=1 AND is_deleted=0 ORDER BY sort_order,id",
        (session["project_id"],),
    )
    require(vendors, "평가할 업체가 없습니다.")
    for vendor in vendors:
        proposal = one(
            c,
            "SELECT * FROM ref_proposal_uploads WHERE vendor_id=? AND project_id=? AND status='READY' AND is_deleted=0 ORDER BY upload_revision DESC LIMIT 1",
            (vendor["id"], session["project_id"]),
        )
        sp = insert(
            c,
            "session_proposals",
            {
                "project_id": session["project_id"],
                "session_id": session["id"],
                "vendor_id": vendor["id"],
                "proposal_upload_id": proposal["id"],
                "display_code": vendor["display_code"],
            },
        )
        for participant in participants:
            sheet = insert(
                c,
                "score_sheets",
                {
                    "project_id": session["project_id"],
                    "session_id": session["id"],
                    "participant_id": participant["id"],
                    "session_proposal_id": sp,
                    "approved_criteria_version_id": criterion["id"],
                    "status": "DRAFT",
                },
            )
            for item in items:
                insert(
                    c,
                    "score_entries",
                    {
                        "project_id": session["project_id"],
                        "sheet_id": sheet,
                        "approved_criteria_version_id": criterion["id"],
                        "criterion_id": item["id"],
                        "score": None,
                        "max_score_snapshot": item["max_score"],
                        "comment": None,
                    },
                )
    result = update(
        c, "evaluation_sessions", session, b, {"status": "OPEN", "locked_at": now()}
    )
    publish(
        c,
        "EVALUATION_OPENED",
        session["id"],
        result["version"],
        {"project_id": session["project_id"], "session_id": session["id"]},
        "admin",
    )
    return result


def get_sheets(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    session = s.session(c, a, b)
    participant = s.participant(c, a, session)
    sheets = rows(
        c,
        "SELECT sh.*,sp.display_code FROM score_sheets sh JOIN session_proposals sp ON sp.id=sh.session_proposal_id WHERE sh.session_id=? AND sh.participant_id=? ORDER BY sp.display_code",
        (session["id"], participant["id"]),
    )
    for sheet in sheets:
        opinion = c.execute(
            "SELECT opinion FROM score_sheet_opinions WHERE sheet_id=?", (sheet["id"],)
        ).fetchone()
        sheet["opinion"] = opinion[0] if opinion else ""
        sheet["entries"] = rows(
            c,
            "SELECT e.*,i.code,i.title,i.description,i.score_step FROM score_entries e JOIN ref_approved_criteria_items i ON i.id=e.criterion_id WHERE e.sheet_id=? ORDER BY i.sort_order,i.id",
            (sheet["id"],),
        )
    return {"session": session, "participant": participant, "sheets": sheets}


def save_scores(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    session = s.session(c, a, b)
    participant = s.participant(c, a, session)
    require(
        session["status"] == "OPEN",
        "평가 입력이 가능한 상태가 아닙니다.",
        "SESSION_LOCKED",
    )
    sheet = one(
        c,
        "SELECT * FROM score_sheets WHERE id=? AND session_id=? AND participant_id=?",
        (text(b, "sheet_id"), session["id"], participant["id"]),
    )
    require(
        sheet["status"] == "DRAFT", "제출한 평가는 변경할 수 없습니다.", "SUBMITTED"
    )
    entries = b.get("entries")
    require(
        isinstance(entries, list) and all(isinstance(e, dict) for e in entries),
        "평가항목 배열을 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    assert isinstance(entries, list)
    existing = rows(
        c,
        "SELECT e.*,i.score_step FROM score_entries e JOIN ref_approved_criteria_items i ON i.id=e.criterion_id WHERE e.sheet_id=?",
        (sheet["id"],),
    )
    supplied = {text(e, "criterion_id"): e for e in entries}
    require(
        len(supplied) == len(entries)
        and set(supplied) == {e["criterion_id"] for e in existing},
        "모든 평가항목을 한 번씩 저장하세요.",
        "INPUT_INVALID",
        422,
    )
    total = 0
    complete = True
    for old in existing:
        new = supplied[old["criterion_id"]]
        score = new.get("score")
        require(
            score is None
            or (
                type(score) is int
                and 0 <= score <= old["max_score_snapshot"]
                and score % old["score_step"] == 0
            ),
            "점수 범위와 간격을 확인하세요.",
            "SCORE_INVALID",
            422,
        )
        comment = new.get("comment")
        require(
            comment is None or isinstance(comment, str) and len(comment) <= 4000,
            "의견은 4,000자 이내로 작성하세요.",
            "INPUT_INVALID",
            422,
        )
        c.execute(
            "UPDATE score_entries SET score=?,comment=?,version=version+1,updated_at=? WHERE id=?",
            (score, comment, now(), old["id"]),
        )
        complete = complete and score is not None
        total += score or 0
    if "opinion" in b:
        opinion = b["opinion"]
        require(
            isinstance(opinion, str) and len(opinion) <= 4000,
            "의견은 4,000자 이내로 작성하세요.",
            "INPUT_INVALID",
            422,
        )
        c.execute(
            "INSERT INTO score_sheet_opinions(sheet_id,opinion) VALUES(?,?) ON CONFLICT(sheet_id) DO UPDATE SET opinion=excluded.opinion",
            (sheet["id"], opinion),
        )
    return update(
        c, "score_sheets", sheet, b, {"total_score": total if complete else None}
    )


def review_scores(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    data = get_sheets(c, s, a, b)
    missing = []
    snapshots = []
    require(data["sheets"], "평가가 아직 시작되지 않았습니다.")
    for sheet in data["sheets"]:
        for entry in sheet["entries"]:
            if entry["score"] is None:
                missing.append(
                    {"display_code": sheet["display_code"], "criterion": entry["title"]}
                )
        snapshots.append(
            {
                k: sheet[k]
                for k in (
                    "id",
                    "version",
                    "session_proposal_id",
                    "approved_criteria_version_id",
                    "total_score",
                )
            }
            | {
                "opinion": sheet["opinion"],
                "entries": [
                    {
                        k: e[k]
                        for k in (
                            "criterion_id",
                            "score",
                            "comment",
                            "max_score_snapshot",
                        )
                    }
                    for e in sheet["entries"]
                ],
            }
        )
    payload = {
        "session_id": data["session"]["id"],
        "participant_id": data["participant"]["id"],
        "sheets": snapshots,
    }
    return {
        "payload_sha256": digest(payload),
        "missing": missing,
        "totals": [
            {"display_code": sh["display_code"], "total_score": sh["total_score"]}
            for sh in data["sheets"]
        ],
        "participant_id": data["participant"]["id"],
    }


def submit_evaluation(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    from app.evaluation.signature_service import verify_signature

    session = s.session(c, a, b)
    participant = s.participant(c, a, session)
    require(session["status"] == "OPEN", "제출할 수 없는 상태입니다.")
    review = review_scores(c, s, a, b)
    require(not review["missing"], "미입력 항목을 확인하세요.", "SCORES_INCOMPLETE")
    verify_signature(c, b, session, participant, "EVALUATION", review["payload_sha256"])
    identity = insert(
        c,
        "evaluation_submissions",
        {
            "project_id": session["project_id"],
            "session_id": session["id"],
            "participant_id": participant["id"],
            "signature_id": b["signature_id"],
            "payload_sha256": review["payload_sha256"],
            "submitted_at": now(),
        },
    )
    c.execute(
        "UPDATE score_sheets SET status='SUBMITTED',version=version+1,updated_at=? WHERE session_id=? AND participant_id=?",
        (now(), session["id"], participant["id"]),
    )
    count = c.execute(
        "SELECT COUNT(*) FROM evaluation_submissions WHERE session_id=?",
        (session["id"],),
    ).fetchone()[0]
    total = c.execute(
        "SELECT COUNT(*) FROM session_participants WHERE session_id=?", (session["id"],)
    ).fetchone()[0]
    if count == total:
        c.execute(
            "UPDATE evaluation_sessions SET status='ALL_SUBMITTED',version=version+1,updated_at=? WHERE id=?",
            (now(), session["id"]),
        )
    return {
        "id": identity,
        "submitted_at": now(),
        "submitted_count": count,
        "participant_count": total,
    }
