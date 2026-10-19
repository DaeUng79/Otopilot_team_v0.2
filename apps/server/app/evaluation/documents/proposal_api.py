# EV-04 · VIEW-01~03
"""제안서 업체별 읽기 API. 회차에 고정된 업체·제안서(session_proposals → ref_proposal_uploads 의 document_id·parse_revision)만 읽는다.

GET /api/v2/evaluator/projects/{p}/sessions/{s}/proposals                          업체 목록(표시 코드·쪽 수·원본 유무)
GET /api/v2/evaluator/projects/{p}/sessions/{s}/proposals/{id}                     개요(문서·쪽·목차)
GET /api/v2/evaluator/projects/{p}/sessions/{s}/proposals/{id}/pages/{n}           쪽 내용
GET /api/v2/evaluator/projects/{p}/sessions/{s}/proposals/{id}/pages/{n}/svg       원본 쪽 SVG
GET /api/v2/evaluator/projects/{p}/sessions/{s}/proposals/{id}/source              원본 다운로드 (VIEW-03, audit)
정책 B: 실제 참여자, 회차 OPEN 이상. 업체 실명은 어디에도 없다(표시 코드만).
**연계 대기**: 제안서 업로드(PRO-01)가 문서 DB 에 생기기 전까지 개발 시드는 RFP 문서를 제안서 자리에 둔다(dev_stand_in).
"""

from __future__ import annotations

from urllib.parse import quote

from app.evaluation.documents.app import App, Request, Response
from app.evaluation.documents.audit import record
from app.evaluation.documents.auth import require_attended, require_participant, require_project, require_session
from app.evaluation.documents.db import connect, connect_documents
from app.evaluation.documents.envelope import not_found
from app.evaluation.documents.rfp_adapter import DocumentReader
from app.evaluation.documents.scoring import display_name


def _context(req: Request, conn, *, touch: bool = False):
    principal = req.principal(conn, touch=touch)
    require_project(principal, req.params["project_id"])
    require_attended(principal)
    require_participant(principal)
    session = require_session(principal, req.params["session_id"], "OPEN", "ALL_SUBMITTED", "FINALIZED")
    return principal, session


def _proposal(conn, session_id: str, proposal_id: str) -> dict:
    row = conn.execute(
        "SELECT sp.id, sp.display_code, u.document_id, u.parse_revision, u.format, u.status FROM session_proposals sp "
        "JOIN ref_proposal_uploads u ON u.id = sp.proposal_upload_id WHERE sp.id = ? AND sp.session_id = ?", (proposal_id, session_id)).fetchone()
    if row is None:
        raise not_found("이 회차의 업체가 아니에요.")
    return dict(row)


def _reader(req: Request, docs, principal, proposal: dict) -> DocumentReader:
    name = display_name(proposal["display_code"])
    return DocumentReader(docs, principal.project_id, proposal["document_id"], proposal["parse_revision"],
                          title=f"{name} 제안서", label=f"{name} 제안서")


def register(app: App) -> None:
    def listing(req: Request) -> Response:
        with connect(req.settings.db_path, write=True) as conn:
            principal, session = _context(req, conn, touch=True)
            rows = conn.execute(
                "SELECT sp.id, sp.display_code, u.document_id, u.parse_revision, u.format FROM session_proposals sp "
                "JOIN ref_proposal_uploads u ON u.id = sp.proposal_upload_id WHERE sp.session_id = ? ORDER BY sp.display_code", (session["id"],)).fetchall()
        items = []
        try:
            with connect_documents(req.settings.documents_db_path) as docs:
                for r in rows:
                    count = docs.execute("SELECT COUNT(*) FROM pages WHERE document_id = ? AND revision = ?", (r["document_id"], r["parse_revision"])).fetchone()[0]
                    items.append({"session_proposal_id": r["id"], "display_code": r["display_code"], "display_name": display_name(r["display_code"]),
                                  "format": r["format"], "page_count": count, "available": count > 0})
        except Exception:  # noqa: BLE001 - 문서 DB 가 없으면 목록만
            items = [{"session_proposal_id": r["id"], "display_code": r["display_code"], "display_name": display_name(r["display_code"]),
                      "format": r["format"], "page_count": 0, "available": False} for r in rows]
        return Response(data={"proposals": items, "note": "평가 시작 때 고정된 제안서예요 · A사 표시는 화면용이에요 · 파일 안의 회사명은 지워지지 않을 수 있어요"})

    def overview(req: Request) -> Response:
        with connect(req.settings.db_path, write=True) as conn:
            principal, session = _context(req, conn, touch=True)
            proposal = _proposal(conn, session["id"], req.params["proposal_id"])
        with connect_documents(req.settings.documents_db_path) as docs:
            data = _reader(req, docs, principal, proposal).overview()
        data["proposal"] = {"session_proposal_id": proposal["id"], "display_code": proposal["display_code"], "display_name": display_name(proposal["display_code"])}
        return Response(data=data)

    def page(req: Request) -> Response:
        with connect(req.settings.db_path) as conn:
            principal, session = _context(req, conn)
            proposal = _proposal(conn, session["id"], req.params["proposal_id"])
        with connect_documents(req.settings.documents_db_path) as docs:
            return Response(data=_reader(req, docs, principal, proposal).page(int(req.params["n"])))

    def page_svg(req: Request) -> Response:
        with connect(req.settings.db_path) as conn:
            principal, session = _context(req, conn)
            proposal = _proposal(conn, session["id"], req.params["proposal_id"])
        with connect_documents(req.settings.documents_db_path) as docs:
            svg = _reader(req, docs, principal, proposal).page_svg(int(req.params["n"]))
        return Response(raw=svg, content_type="image/svg+xml; charset=utf-8", cache_control="private, max-age=86400")

    def page_png(req: Request) -> Response:
        with connect(req.settings.db_path) as conn:
            principal, session = _context(req, conn)
            proposal = _proposal(conn, session["id"], req.params["proposal_id"])
        with connect_documents(req.settings.documents_db_path) as docs:
            png = _reader(req, docs, principal, proposal).page_png(int(req.params["n"]))
        return Response(raw=png, content_type="image/png", cache_control="private, max-age=86400")

    def source(req: Request) -> Response:
        with connect(req.settings.db_path) as conn:
            principal, session = _context(req, conn)
            proposal = _proposal(conn, session["id"], req.params["proposal_id"])
        with connect_documents(req.settings.documents_db_path) as docs:
            name, data = _reader(req, docs, principal, proposal).source()
        with connect(req.settings.db_path, write=True) as conn:
            record(conn, actor_type="EVALUATOR", actor_id=principal.assignment_id, project_id=principal.project_id, action="VIEW-03",
                   entity_type="proposal_source", entity_id=proposal["id"], detail={"display_code": proposal["display_code"], "bytes": len(data)})
        return Response(raw=data, content_type="application/octet-stream",
                        headers=[("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")])

    base = r"/projects/(?P<project_id>[^/]+)/sessions/(?P<session_id>[^/]+)/proposals"
    app.route("GET", base, listing)
    app.route("GET", base + r"/(?P<proposal_id>[^/]+)", overview)
    app.route("GET", base + r"/(?P<proposal_id>[^/]+)/pages/(?P<n>\d+)", page)
    app.route("GET", base + r"/(?P<proposal_id>[^/]+)/pages/(?P<n>\d+)/svg", page_svg)
    app.route("GET", base + r"/(?P<proposal_id>[^/]+)/pages/(?P<n>\d+)/png", page_png)
    app.route("GET", base + r"/(?P<proposal_id>[^/]+)/source", source)
