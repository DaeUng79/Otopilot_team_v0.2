# EV-05 · VIEW-04 · CHAT-01·02
"""항목별 비교·문서 도우미 API. 기존 평가 세션과 문서 SQLite를 사용하는 통합 경로다.

GET  /api/v2/evaluator/projects/{p}/sessions/{s}/criteria                       확정표 항목·회차 업체 (왼쪽 목록)
GET  /api/v2/evaluator/projects/{p}/sessions/{s}/comparisons?criterion_id=&vendors=A,B
     업체별 근거를 우선순위로 채운다: ① 문서 DB proposal_evidence CONFIRMED(담당자 확정) ② SUGGESTED(PRO-04 제안, 확정 전)
     ③ 둘 다 없으면 제안서 본문(고정 parse_revision)에서 자동으로 찾은 후보(common/server/evidence.py, source=auto).
     응답 mode: confirmed | mixed | suggested | auto | none. available 은 proposal_evidence 테이블 존재 여부(연계 상태)다.
     문서 DB 에 연결할 수 없거나 찾은 게 없으면 columns:[] 와 note 로 빈 상태를 명시한다 (성공 모의응답으로 감추지 않는다).
POST /api/v2/evaluator/projects/{p}/sessions/{s}/chat {vendors[], question, history[]}
     문서 도우미. common/server/chat_adapter.py 가 오대웅 모듈 chatbot.py 를 경로 import 해 업체별(최대 3) 제안서 전체를 문맥으로 묻는다.
     응답 {answers:{session_proposal_id:{text,pages,tables,error?}}, model}. 문서 DB·OPENAI_API_KEY 가 없으면 503(화면은 "준비 중").
     대화는 저장하지 않는다. 감사 기록(CHAT-01)에는 업체·글자 수만 남긴다.
POST /api/v2/evaluator/projects/{p}/sessions/{s}/chat/stream
     같은 권한·문서를 검사한 뒤 NDJSON으로 delta, answer, done 이벤트를 순서대로 보낸다.
POST /api/v2/evaluator/projects/{p}/sessions/{s}/comparisons/summary {criterion_id}
     고정된 제안서 근거 블록을 apps/documents/proposal_evidence_summary.py에서 업체별로 정리한다.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache

from app.evaluation.documents.app import App, Request, Response
from app.evaluation.documents.audit import record
from app.evaluation.documents.auth import require_attended, require_participant, require_project, require_session
from app.evaluation.documents.db import connect, connect_documents
from app.evaluation.documents.envelope import ApiError, validation_failed
from app.evaluation.documents import chat_adapter, evidence, scoring, summary_store
from app.evaluation.documents.settings import PM01_DIR


@lru_cache(maxsize=1)
def _summary_module():
    path = PM01_DIR / "proposal_evidence_summary.py"
    spec = importlib.util.spec_from_file_location("proposal_evidence_summary", path)
    if spec is None or spec.loader is None:
        raise ApiError("UPSTREAM_UNAVAILABLE", "AI 정리 모듈을 읽을 수 없습니다.", 503)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _context(req: Request, conn):
    principal = req.principal(conn)
    require_project(principal, req.params["project_id"])
    require_attended(principal)
    require_participant(principal)
    session = require_session(principal, req.params["session_id"], "OPEN", "ALL_SUBMITTED", "FINALIZED")
    return principal, session


def prepare_chat(req: Request):
    """일반 답변과 스트리밍 답변에 같은 입력·권한·고정 문서 검사를 적용한다."""
    body = req.json()
    question = str(body.get("question") or "").strip()
    if not question or len(question) > 2000:
        raise validation_failed("질문을 2000자 이하로 써 주세요.", {"question": "내용을 확인해 주세요."})
    wanted = body.get("vendors") or []
    if not isinstance(wanted, list) or any(not isinstance(v, str) for v in wanted):
        raise validation_failed("업체 목록 형식이 올바르지 않아요.", {"vendors": "업체를 다시 골라 주세요."})
    history_raw = body.get("history") or []
    if not isinstance(history_raw, list) or any(not isinstance(h, str) or len(h) > 2000 for h in history_raw):
        raise validation_failed("이전 질문 형식이 올바르지 않아요.", {"history": "대화를 초기화한 뒤 다시 물어봐 주세요."})
    history = [h.strip() for h in history_raw[-chat_adapter.MAX_HISTORY:] if h.strip()]
    with connect(req.settings.db_path, write=True) as conn:
        principal, session = _context(req, conn)
        proposals = scoring.proposals_of(conn, session["id"])
        if wanted:
            known = {p["session_proposal_id"] for p in proposals}
            unknown = [v for v in wanted if v not in known]
            if unknown:
                raise validation_failed("이 회차의 업체가 아니에요.", {"vendors": "업체를 다시 골라 주세요."})
            proposals = [p for p in proposals if p["session_proposal_id"] in wanted]
        uploads = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, document_id, parse_revision FROM ref_proposal_uploads WHERE id IN (%s)" % ",".join("?" * len(proposals)),
            [p["proposal_upload_id"] for p in proposals]).fetchall()} if proposals else {}
    targets = []
    for p in proposals:
        upload = uploads.get(p["proposal_upload_id"]) or {}
        if upload.get("document_id") and upload.get("parse_revision"):
            targets.append({**p, "document_id": upload["document_id"], "parse_revision": upload["parse_revision"]})
    return principal, session, targets, question, history


def record_chat(req: Request, principal, session, targets, question, model, answered=None):
    with connect(req.settings.db_path, write=True) as conn:
        detail = {"vendors": [t["display_code"] for t in targets], "question_chars": len(question), "model": model}
        if answered is not None:
            detail["answered"] = answered
        record(conn, actor_type="EVALUATOR", actor_id=principal.assignment_id, project_id=principal.project_id, action="CHAT-01",
               entity_type="evaluation_session", entity_id=session["id"], detail=detail)


def register(app: App) -> None:
    def _head(p: dict) -> dict:
        return {"session_proposal_id": p["session_proposal_id"], "display_code": p["display_code"], "display_name": p["display_name"]}

    def _from_evidence_table(docs, criterion_id: str, p: dict, status: str, upload: dict) -> dict | None:
        """proposal_evidence(문서 담당 산출물)에서 해당 상태의 근거를 읽는다. CONFIRMED=담당자 확정, SUGGESTED=PRO-04 제안."""
        rows = docs.execute(
            "SELECT e.document_id, e.parse_revision, e.block_id, b.text, b.physical_page_numbers_json FROM proposal_evidence e "
            "LEFT JOIN blocks b ON b.document_id = e.document_id AND b.revision = e.parse_revision AND b.block_id = e.block_id "
            "WHERE e.criterion_id = ? AND e.proposal_upload_id = ? AND e.status = ? "
            "AND e.document_id = ? AND e.parse_revision = ? ORDER BY e.updated_at DESC LIMIT 3",
            (criterion_id, p["proposal_upload_id"], status, upload.get('document_id'), upload.get('parse_revision'))).fetchall()
        rows = [r for r in rows if (r["text"] or "").strip()]
        if not rows:
            return None
        import json
        matches = []
        for r in rows:
            pages = json.loads(r["physical_page_numbers_json"] or "[]")
            matches.append({"page": pages[0] if pages else None, "excerpt": r["text"].strip()[:160], "block_id": r["block_id"]})
        return {**_head(p), "source": "confirmed" if status == "CONFIRMED" else "suggested",
                "excerpt": [m["excerpt"] for m in matches], "page": matches[0]["page"], "matches": matches,
                "document_id": rows[0]["document_id"], "parse_revision": rows[0]["parse_revision"]}

    def _comparison_data(req: Request, criterion_id: str) -> dict:
        if not criterion_id:
            raise validation_failed("criterion_id 가 필요해요.", {"criterion_id": "평가항목을 골라 주세요."})
        wanted = [v.strip() for v in (req.arg("vendors") or "").split(",") if v.strip()]
        with connect(req.settings.db_path, write=True) as conn:
            principal, session = _context(req, conn)
            item = conn.execute("SELECT id, code, title, description, max_score FROM ref_approved_criteria_items WHERE id = ? AND approved_criteria_version_id = ?",
                                (criterion_id, session["approved_criteria_version_id"])).fetchone()
            if item is None:
                raise ApiError("NOT_FOUND", "이 회차의 평가항목이 아니에요.", 404)
            proposals = [p for p in scoring.proposals_of(conn, session["id"]) if not wanted or p["display_code"] in wanted]
            uploads = {r["id"]: dict(r) for r in conn.execute(
                "SELECT id, document_id, parse_revision FROM ref_proposal_uploads WHERE id IN (%s)" % ",".join("?" * len(proposals)),
                [p["proposal_upload_id"] for p in proposals]).fetchall()} if proposals else {}
        columns: list[dict] = []
        available = False
        docs_ok = True
        try:
            with connect_documents(req.settings.documents_db_path) as docs:
                has_table = docs.execute("SELECT 1 FROM sqlite_master WHERE name = 'proposal_evidence'").fetchone() is not None
                available = has_table
                for p in proposals:
                    col = None
                    upload = uploads.get(p["proposal_upload_id"]) or {}
                    if has_table:
                        col = _from_evidence_table(docs, criterion_id, p, "CONFIRMED", upload) or _from_evidence_table(docs, criterion_id, p, "SUGGESTED", upload)
                    if col is None:
                        # 담당자 확정 전에는 평가위원이 기다리지 않도록 제안서 본문에서 먼저 후보를 찾아 보여 준다
                        upload = uploads.get(p["proposal_upload_id"]) or {}
                        if upload.get("document_id") and upload.get("parse_revision"):
                            found = evidence.find_candidates(docs, upload["document_id"], upload["parse_revision"], item["title"], item["description"])
                            if found:
                                col = {**_head(p), "source": "auto", "excerpt": [m["excerpt"] for m in found], "page": found[0]["page"],
                                       "matches": [{"page": m["page"], "excerpt": m["excerpt"], "block_id": m["block_id"]} for m in found],
                                       "document_id": upload["document_id"], "parse_revision": upload["parse_revision"]}
                    if col:
                        columns.append(col)
        except ApiError:
            docs_ok = False
        sources = {c["source"] for c in columns}
        if not docs_ok:
            mode, note = "none", "문서 DB 에 연결할 수 없어 근거를 찾지 못했어요. 목차에서 직접 볼 수 있어요."
        elif not columns:
            mode, note = "none", "제안서에서 이 항목과 관련된 내용을 찾지 못했어요. 목차에서 직접 볼 수 있어요."
        elif sources == {"confirmed"}:
            mode, note = "confirmed", None
        elif "confirmed" in sources:
            mode, note = "mixed", "일부 업체는 담당자 확정 전이라 자동으로 찾은 후보예요. 쪽을 열어 직접 확인해 주세요."
        elif sources == {"suggested"}:
            mode, note = "suggested", "담당자가 아직 확정하지 않은 제안 근거예요. 쪽을 열어 직접 확인해 주세요."
        else:
            mode, note = "auto", "담당자가 확정한 근거가 아직 없어서, 제안서 본문에서 자동으로 찾은 후보예요. 쪽을 열어 직접 확인해 주세요."
        return {"criterion": dict(item), "available": available, "mode": mode, "columns": columns,
                "proposals": [_head(p) for p in proposals], "note": note}

    def comparisons(req: Request) -> Response:
        return Response(data=_comparison_data(req, req.arg("criterion_id")))

    def comparison_summary(req: Request) -> Response:
        criterion_id = str(req.json().get("criterion_id") or "")
        data = _comparison_data(req, criterion_id)
        proposals = []
        sources = []
        if data["columns"]:
            with connect_documents(req.settings.documents_db_path) as docs:
                for col in data["columns"]:
                    evidence_blocks = []
                    for match in col.get("matches", [])[:3]:
                        row = docs.execute(
                            "SELECT text FROM blocks WHERE document_id=? AND revision=? AND block_id=?",
                            (col["document_id"], col["parse_revision"], match["block_id"])).fetchone()
                        text = (row["text"] if row else "") or ""
                        if text.strip():
                            evidence_blocks.append({"page": match.get("page"), "text": text.strip()})
                    if evidence_blocks:
                        proposals.append({"id": col["session_proposal_id"], "evidence": evidence_blocks})
                        sources.append({"session_proposal_id": col["session_proposal_id"],
                                        "document_id": col["document_id"],
                                        "parse_revision": col["parse_revision"],
                                        "source": col["source"],
                                        "block_ids": [m["block_id"] for m in col.get("matches", [])[:3]]})
        criterion = str(data["criterion"].get("description") or "").split("\n-")[0]
        summarizer = _summary_module()
        try:
            summaries = summary_store.get_or_generate(
                req.settings.db_path, project_id=req.params["project_id"],
                session_id=req.params["session_id"], criterion_id=criterion_id,
                fingerprint={"title": data["criterion"]["title"], "criterion": criterion,
                             "sources": sources, "proposals": proposals},
                processor_version=summarizer.PROCESSOR_VERSION,
                generate=lambda: summarizer.summarize_item(data["criterion"]["title"], criterion, proposals),
            ) if proposals else {}
        except summarizer.SummaryUnavailable as exc:
            raise ApiError("UPSTREAM_UNAVAILABLE", str(exc), 503, retryable=True) from exc
        return Response(data={"summaries": summaries})

    def chat(req: Request) -> Response:
        principal, session, targets, question, history = prepare_chat(req)
        result = chat_adapter.answer_for_proposals(req.settings.documents_db_path, targets, question, history)
        record_chat(req, principal, session, targets, question, result["model"],
                    [pid for pid, a in result["answers"].items() if a.get("text")])
        return Response(data=result)

    def criteria(req: Request) -> Response:
        """EV-05 왼쪽 목록용: 확정표 항목(말단·상위)과 회차 업체."""
        with connect(req.settings.db_path, write=True) as conn:
            principal, session = _context(req, conn)
            version = conn.execute("SELECT id, approval_no, total_max_score FROM ref_approved_criteria_versions WHERE id = ?",
                                   (session["approved_criteria_version_id"],)).fetchone()
            return Response(data={"criteria": {"version_id": version["id"], "approval_no": version["approval_no"], "total_max_score": version["total_max_score"],
                                               "items": scoring.criteria_items(conn, version["id"])},
                                  "proposals": [{"session_proposal_id": p["session_proposal_id"], "display_code": p["display_code"], "display_name": p["display_name"]}
                                                for p in scoring.proposals_of(conn, session["id"])]},
                            meta={"dev": principal.extras.get("dev", False)})

    base = r"/projects/(?P<project_id>[^/]+)/sessions/(?P<session_id>[^/]+)"
    app.route("GET", base + r"/criteria", criteria)
    app.route("GET", base + r"/comparisons", comparisons)
    app.route("POST", base + r"/comparisons/summary", comparison_summary)
    app.route("POST", base + r"/chat", chat)
