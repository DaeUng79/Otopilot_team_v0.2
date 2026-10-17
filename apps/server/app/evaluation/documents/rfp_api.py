# EV-03 · VIEW-01~03 · DOC-05
"""제안요청서 읽기 API. 문서 API(step0)의 읽기 함수를 rfp_adapter 로 재사용하고, 세션·참석(정책 A)·고정 버전을 검사한다.

GET /api/v2/evaluator/projects/{project_id}/documents/rfp                   개요(문서·쪽·목차)
GET /api/v2/evaluator/projects/{project_id}/documents/rfp/pages/{n}         쪽 내용(문단·표·그림)
GET /api/v2/evaluator/projects/{project_id}/documents/rfp/pages/{n}/svg     원본 쪽 SVG (pyhwpxlib 없으면 503 → 화면이 파싱 대체)
GET /api/v2/evaluator/projects/{project_id}/documents/rfp/source            원본 파일 다운로드 (DOC-05, audit)
GET /api/v2/evaluator/projects/{project_id}/documents/assets/{sha256}       쪽 그림
"""

from __future__ import annotations

import re
from urllib.parse import quote

from app.evaluation.documents.app import App, Request, Response
from app.evaluation.documents.audit import record
from app.evaluation.documents.auth import require_attended, require_project
from app.evaluation.documents.db import connect, connect_documents
from app.evaluation.documents.envelope import not_found
from app.evaluation.documents.rfp_adapter import DocumentReader, RfpReader
from app.evaluation.documents.envelope import ApiError

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _binding(conn, project_id: str):
    row = conn.execute(
        "SELECT * FROM ref_rfp_bindings WHERE project_id = ? AND is_deleted = 0 ORDER BY upload_revision DESC LIMIT 1", (project_id,)
    ).fetchone()
    return dict(row) if row else None


def _reader(req: Request, *, touch: bool = False):
    """세션·사업·참석을 확인하고 (principal, binding) 을 돌려준다."""
    with connect(req.settings.db_path, write=touch) as conn:
        principal = req.principal(conn, touch=touch)
        require_project(principal, req.params["project_id"])
        require_attended(principal)
        binding = _binding(conn, principal.project_id)
    return principal, binding


def register(app: App) -> None:
    def overview(req: Request) -> Response:
        principal, binding = _reader(req, touch=True)
        with connect_documents(req.settings.documents_db_path) as docs:
            data = RfpReader(docs, principal.project_id, binding).overview()
        # 사업명은 평가 DB 사본(ref_projects)을 기준으로 한다. 문서 DB 의 projects.name 과 다를 수 있다(깨진 글자 등).
        data["project"] = {"id": principal.project_id, "name": principal.project["name"]}
        data["document"]["title"] = f"{principal.project['name']} 제안요청서"
        data["binding"] = None if binding is None else {"upload_revision": binding["upload_revision"], "parse_revision": binding["parse_revision"]}
        return Response(data=data)

    def page(req: Request) -> Response:
        principal, binding = _reader(req)
        with connect_documents(req.settings.documents_db_path) as docs:
            return Response(data=RfpReader(docs, principal.project_id, binding).page(int(req.params["n"])))

    def page_svg(req: Request) -> Response:
        principal, binding = _reader(req)
        with connect_documents(req.settings.documents_db_path) as docs:
            svg = RfpReader(docs, principal.project_id, binding).page_svg(int(req.params["n"]))
        return Response(raw=svg, content_type="image/svg+xml; charset=utf-8", cache_control="private, max-age=86400")

    def source(req: Request) -> Response:
        principal, binding = _reader(req)
        with connect_documents(req.settings.documents_db_path) as docs:
            name, data = RfpReader(docs, principal.project_id, binding).source()
        with connect(req.settings.db_path, write=True) as conn:
            record(conn, actor_type="EVALUATOR", actor_id=principal.assignment_id, project_id=principal.project_id, action="DOC-05",
                   entity_type="rfp_source", entity_id=binding["document_id"] if binding else "latest", detail={"filename": name, "bytes": len(data)})
        return Response(raw=data, content_type="application/octet-stream",
                        headers=[("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")])

    def asset(req: Request) -> Response:
        principal, binding = _reader(req)
        sha = req.params["sha256"]
        if not SHA256.fullmatch(sha):
            raise not_found("그림을 찾을 수 없어요.")
        with connect_documents(req.settings.documents_db_path) as docs:
            allowed = [binding] if binding else []
            session = principal.evaluation_session
            if principal.is_participant and session and session['status'] in {'OPEN', 'ALL_SUBMITTED', 'FINALIZED'}:
                with connect(req.settings.db_path) as conn:
                    allowed += [dict(r) for r in conn.execute(
                        "SELECT u.document_id,u.parse_revision FROM session_proposals sp "
                        "JOIN ref_proposal_uploads u ON u.id=sp.proposal_upload_id WHERE sp.session_id=?",
                        (session['id'],))]
            for document in allowed:
                try:
                    data, mime = DocumentReader(docs, principal.project_id, document['document_id'],
                                                document['parse_revision'], title='', label='').asset(sha)
                    break
                except ApiError as exc:
                    if exc.status != 404:
                        raise
            else:
                raise not_found("이 평가에서 열람할 수 없는 그림입니다.")
        return Response(raw=data, content_type=mime, cache_control="private, max-age=86400")

    base = r"/projects/(?P<project_id>[^/]+)/documents"
    app.route("GET", base + r"/rfp", overview)
    app.route("GET", base + r"/rfp/pages/(?P<n>\d+)", page)
    app.route("GET", base + r"/rfp/pages/(?P<n>\d+)/svg", page_svg)
    app.route("GET", base + r"/rfp/source", source)
    app.route("GET", base + r"/assets/(?P<sha256>[0-9a-f]+)", asset)
