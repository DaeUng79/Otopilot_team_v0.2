"""RES-01..05: immutable, reproducible aggregation and chair confirmation."""

import base64
import html
import json
import sqlite3
from decimal import ROUND_HALF_UP, Decimal

from app.committee.committee_app.v2_core import ExportFile, digest, now, packed
from app.shared.db import DTO, Actor, Store, insert, one, require, rows, text


def result_payload(c: sqlite3.Connection, session: DTO, run_id: str) -> DTO:
    run = one(
        c,
        "SELECT * FROM result_runs WHERE id=? AND session_id=?",
        (run_id, session["id"]),
    )
    items = rows(
        c,
        "SELECT r.*,p.display_code FROM result_items r JOIN session_proposals p ON p.id=r.session_proposal_id WHERE result_run_id=? ORDER BY rank,p.display_code",
        (run_id,),
    )
    inputs = rows(
        c,
        "SELECT * FROM result_inputs WHERE result_run_id=? ORDER BY session_proposal_id,participant_id",
        (run_id,),
    )
    payload = {"run": run, "items": items, "inputs": inputs}
    return payload | {"payload_sha256": digest(payload)}


def get_results(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    admin = a.role in {"SUPER_ADMIN", "DEPARTMENT_ADMIN"}
    session = s.session(c, a, b, admin, permission="VIEW_RESULTS")
    if admin:
        s.admin(a, "VIEW_RESULTS", session["project_id"])
    participant = None if admin else s.participant(c, a, session)
    count = c.execute(
        "SELECT COUNT(*) FROM evaluation_submissions WHERE session_id=?",
        (session["id"],),
    ).fetchone()[0]
    total = c.execute(
        "SELECT COUNT(*) FROM session_participants WHERE session_id=?", (session["id"],)
    ).fetchone()[0]
    result = {
        "session": session,
        "submitted_count": count,
        "participant_count": total,
        "is_chair": bool(
            participant and participant["id"] == session["chair_participant_id"]
        ),
    }
    can_view = (admin and session["status"] == "FINALIZED") or (
        participant is not None and participant["id"] == session["chair_participant_id"]
    )
    latest = c.execute(
        "SELECT id FROM result_runs WHERE session_id=? ORDER BY revision_no DESC LIMIT 1",
        (session["id"],),
    ).fetchone()
    if latest and can_view:
        result.update(result_payload(c, session, latest["id"]))
    return result


def aggregate_results(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    session = s.session(c, a, b)
    s.participant(c, a, session, True)
    require(
        session["status"] == "ALL_SUBMITTED",
        "참여 위원 전원이 제출해야 집계할 수 있습니다.",
        "SUBMISSIONS_INCOMPLETE",
    )
    existing = c.execute(
        "SELECT id FROM result_runs WHERE session_id=?", (session["id"],)
    ).fetchone()
    if existing:
        return result_payload(c, session, existing["id"])
    participants = rows(
        c,
        "SELECT id FROM session_participants WHERE session_id=? ORDER BY id",
        (session["id"],),
    )
    submissions = rows(
        c,
        "SELECT * FROM evaluation_submissions WHERE session_id=? ORDER BY participant_id",
        (session["id"],),
    )
    count = len(participants)
    require(
        count == len(submissions)
        and count >= 3
        and count >= session["minimum_attendees"],
        "제출 수와 운영 최소 인원을 확인하세요.",
        "QUORUM_INVALID",
    )
    from app.evaluation.evaluation_service import POLICY

    require(
        json.loads(session["aggregation_policy_json"]) == POLICY,
        "승인된 집계 정책을 확인하세요.",
        "POLICY_INVALID",
    )
    run = insert(
        c,
        "result_runs",
        {
            "project_id": session["project_id"],
            "session_id": session["id"],
            "revision_no": 1,
            "input_sha256": digest({"submissions": submissions, "policy": POLICY}),
            "policy_snapshot_json": packed(POLICY),
            "participant_count": count,
            "calculated_at": now(),
        },
    )
    values = []
    proposals = rows(
        c,
        "SELECT * FROM session_proposals WHERE session_id=? ORDER BY display_code",
        (session["id"],),
    )
    for proposal in proposals:
        sheets = rows(
            c,
            "SELECT sh.*,su.id AS submission_id FROM score_sheets sh JOIN evaluation_submissions su ON su.session_id=sh.session_id AND su.participant_id=sh.participant_id WHERE sh.session_proposal_id=? AND sh.status='SUBMITTED' ORDER BY sh.total_score,sh.participant_id",
            (proposal["id"],),
        )
        require(
            len(sheets) == count
            and all(sh["total_score"] is not None for sh in sheets),
            "완료 평가표 수를 확인하세요.",
        )
        for i, sheet in enumerate(sheets):
            insert(
                c,
                "result_inputs",
                {
                    "project_id": session["project_id"],
                    "result_run_id": run,
                    "session_proposal_id": proposal["id"],
                    "participant_id": sheet["participant_id"],
                    "submission_id": sheet["submission_id"],
                    "total_score": sheet["total_score"],
                    "exclusion": "LOWEST"
                    if i == 0
                    else "HIGHEST"
                    if i == count - 1
                    else "NONE",
                },
            )
        included = sum(sh["total_score"] for sh in sheets[1:-1])
        average = (Decimal(included) / Decimal(count - 2) / 10000).quantize(
            Decimal(".01"), rounding=ROUND_HALF_UP
        )
        values.append(
            {
                "project_id": session["project_id"],
                "result_run_id": run,
                "session_proposal_id": proposal["id"],
                "included_sum": included,
                "included_count": count - 2,
                "average_decimal": str(average),
            }
        )
    ordered = sorted(values, key=lambda x: Decimal(x["average_decimal"]), reverse=True)
    rank = 0
    previous = None
    for i, item in enumerate(ordered, 1):
        if item["average_decimal"] != previous:
            rank = i
        previous = item["average_decimal"]
        insert(c, "result_items", item | {"rank": rank})
    return result_payload(c, session, run)


def confirm_results(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    from app.evaluation.signature_service import verify_signature
    from app.shared.sync_service import publish

    session = s.session(c, a, b)
    participant = s.participant(c, a, session, True)
    require(session["status"] == "ALL_SUBMITTED", "최종 제출이 가능한 상태가 아닙니다.")
    result = result_payload(c, session, text(b, "result_run_id"))
    verify_signature(
        c, b, session, participant, "CHAIR_RESULT", result["payload_sha256"]
    )
    identity = insert(
        c,
        "chair_confirmations",
        {
            "project_id": session["project_id"],
            "session_id": session["id"],
            "result_run_id": b["result_run_id"],
            "chair_participant_id": participant["id"],
            "signature_id": b["signature_id"],
            "payload_sha256": result["payload_sha256"],
            "submitted_at": now(),
        },
    )
    c.execute(
        "UPDATE evaluation_sessions SET status='FINALIZED',closed_at=?,updated_at=?,version=version+1 WHERE id=?",
        (now(), now(), session["id"]),
    )
    payload = {
        "project_id": session["project_id"],
        "session_id": session["id"],
        "confirmation_id": identity,
        "result_run_id": b["result_run_id"],
        "payload_sha256": result["payload_sha256"],
        "submitted_at": one(
            c, "SELECT submitted_at FROM chair_confirmations WHERE id=?", (identity,)
        )["submitted_at"],
    }
    for destination in ("admin", "documents"):
        publish(
            c,
            "result.finalized",
            session["id"],
            session["version"] + 1,
            payload,
            destination,
        )
    return {"id": identity, "status": "FINALIZED", "sync_status": "PENDING"}


def export_workbook(c: sqlite3.Connection, session: DTO, payload: DTO, confirmation: DTO) -> ExportFile:
    """RES-05 format=xlsx: 공식 '제안서평가 집계표(정성)' 서식(result_workbook.py). 점수는 확정 집계와 같은 값."""
    from app.evaluation.result_workbook import build_aggregation_workbook

    project = one(c, "SELECT name FROM ref_projects WHERE id=?", (session["project_id"],))
    proposals = {p["id"]: p for p in rows(
        c, "SELECT * FROM session_proposals WHERE session_id=? ORDER BY display_code", (session["id"],))}
    vendors = [{"display_code": p["display_code"], "label": p["display_code"] + "사"}
               for p in proposals.values()]
    criteria = [{"code": i["code"], "title": i["title"], "max_score": i["max_score"] / 10000}
                for i in rows(
                    c, "SELECT code,title,max_score FROM ref_approved_criteria_items WHERE approved_criteria_version_id=? AND is_scorable=1 AND is_deleted=0 ORDER BY sort_order,id",
                    (session["approved_criteria_version_id"],))]
    participants = rows(
        c, "SELECT p.id,a.name_snapshot FROM session_participants p JOIN ref_committee_assignments a ON a.id=p.assignment_id WHERE p.session_id=? ORDER BY a.name_snapshot,p.id",
        (session["id"],))
    inputs = {(i["participant_id"], i["session_proposal_id"]): i for i in payload["inputs"]}
    evaluators = []
    for p in participants:
        scores, excluded = {}, {}
        for sp in proposals.values():
            sheet = c.execute("SELECT id,total_score FROM score_sheets WHERE session_id=? AND participant_id=? AND session_proposal_id=?",
                              (session["id"], p["id"], sp["id"])).fetchone()
            items = {r["code"]: (r["score"] or 0) / 10000 for r in c.execute(
                "SELECT i.code,e.score FROM score_entries e JOIN ref_approved_criteria_items i ON i.id=e.criterion_id WHERE e.sheet_id=?",
                (sheet["id"],))} if sheet else {}
            entry = inputs.get((p["id"], sp["id"]))
            scores[sp["display_code"]] = {"items": items, "total": (entry["total_score"] if entry else sheet["total_score"] or 0) / 10000}
            excluded[sp["display_code"]] = None if not entry or entry["exclusion"] == "NONE" else entry["exclusion"]
        evaluators.append({"name": p["name_snapshot"], "is_chair": p["id"] == session["chair_participant_id"],
                           "scores": scores, "excluded": excluded})
    summary = {}
    for item in payload["items"]:
        sp = proposals[item["session_proposal_id"]]
        totals = [e["scores"][sp["display_code"]]["total"] for e in evaluators]
        summary[sp["display_code"]] = {
            "subtotal": sum(totals), "max": max(totals) if totals else 0, "min": min(totals) if totals else 0,
            "included_sum": item["included_sum"] / 10000, "included_count": item["included_count"],
            "average": item["average_decimal"], "rank": item["rank"]}
    chair = next((e["name"] for e in evaluators if e["is_chair"]), "")
    report = {"project_name": project["name"], "finalized_at": confirmation["submitted_at"][:10],
              "vendors": vendors, "criteria": criteria, "evaluators": evaluators, "vendor_summary": summary,
              "signers": {"chair": chair, "reviewer": "", "author": ""},
              "policy_note": "최고·최저 각 1명 제외 평균, 소수 둘째 자리 반올림"}
    return ExportFile("evaluation-aggregation.xlsx", build_aggregation_workbook(report))


def export_report(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> ExportFile:
    admin = a.role in {"SUPER_ADMIN", "DEPARTMENT_ADMIN"}
    session = s.session(c, a, b, admin, permission="VIEW_RESULTS")
    if admin:
        s.admin(a, "VIEW_RESULTS", session["project_id"])
    else:
        s.participant(c, a, session, True)
    require(
        session["status"] == "FINALIZED",
        "위원장 최종 제출 후 보고서를 내려받을 수 있습니다.",
        "NOT_FINALIZED",
    )
    confirmation = one(
        c, "SELECT * FROM chair_confirmations WHERE session_id=?", (session["id"],)
    )
    payload = result_payload(c, session, confirmation["result_run_id"])
    require(
        payload["payload_sha256"] == confirmation["payload_sha256"],
        "확정 결과 해시가 다릅니다.",
        "PAYLOAD_CORRUPT",
    )
    if b.get("format") == "xlsx":
        return export_workbook(c, session, payload, confirmation)
    esc = lambda v: html.escape(str(v))
    table = "".join(
        "<tr>"
        + "".join(
            "<td>" + esc(item[k]) + "</td>"
            for k in (
                "display_code",
                "included_sum",
                "included_count",
                "average_decimal",
                "rank",
            )
        )
        + "</tr>"
        for item in payload["items"]
    )
    proof = "".join(
        "<tr>"
        + "".join(
            "<td>" + esc(item[k]) + "</td>"
            for k in (
                "session_proposal_id",
                "participant_id",
                "total_score",
                "exclusion",
            )
        )
        + "</tr>"
        for item in payload["inputs"]
    )
    signatures = rows(
        c,
        "SELECT sig.*,a.name_snapshot FROM signatures sig JOIN session_participants p ON p.id=sig.signer_participant_id JOIN ref_committee_assignments a ON a.id=p.assignment_id WHERE sig.id IN (SELECT signature_id FROM evaluation_submissions WHERE session_id=? UNION SELECT signature_id FROM chair_confirmations WHERE session_id=?) ORDER BY sig.purpose,sig.signed_at",
        (session["id"], session["id"]),
    )
    images = "".join(
        f'<figure><figcaption>{esc(sig["name_snapshot"])} / {esc(sig["purpose"])} / {esc(sig["signed_at"])}</figcaption><img alt="확인 서명" width="240" src="data:image/png;base64,{base64.b64encode(sig["image_blob"]).decode()}"><p>{esc(sig["payload_sha256"])}</p></figure>'
        for sig in signatures
    )
    project = one(
        c, "SELECT name FROM ref_projects WHERE id=?", (session["project_id"],)
    )
    document = f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>확정 평가결과</title><style>body{{font:16px sans-serif;margin:40px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:8px}}p,pre{{overflow-wrap:anywhere;white-space:pre-wrap}}figure{{break-inside:avoid}}</style><h1>{esc(project["name"])} 평가결과</h1><p>회차 {session["round_no"]} · 실제 참여 {payload["run"]["participant_count"]}명 · 최고·최저 각 1명 제외</p><p>최종 제출: {esc(confirmation["submitted_at"])}</p><table><tr><th>업체</th><th>합계(점수×10000)</th><th>분모</th><th>평균</th><th>순위</th></tr>{table}</table><h2>계산 근거</h2><pre>{esc(session["aggregation_policy_json"])}</pre><table><tr><th>제안서 ID</th><th>참여자 ID</th><th>총점×10000</th><th>제외 상태</th></tr>{proof}</table><h2>서명 증빙</h2>{images}<p>결과 해시 {esc(confirmation["payload_sha256"])}</p><p>브라우저 인쇄에서 PDF로 저장할 수 있습니다. 서명 이미지는 공인 전자서명이 아닙니다.</p></html>'
    return ExportFile(
        "evaluation-result.html", document.encode("utf8"), "text/html; charset=utf-8"
    )
