"""Mount the selectively migrated EV-03/04/05 APIs on the existing service."""
import asyncio
import logging
import sqlite3
import uuid
from urllib.parse import parse_qs

from fastapi import Request as HttpRequest
from fastapi.responses import JSONResponse, Response

from app.evaluation.documents import comparison_api, proposal_api, rfp_api
from app.evaluation.documents.app import App, Request
from app.evaluation.documents.auth import load_principal
from app.evaluation.documents.db import connect
from app.evaluation.documents.envelope import ApiError, failure, success
from app.evaluation.documents.settings import API_PREFIX, Settings
from app.api.project_documents import resolve_database
from app.shared.db import require


def install_document_routes(app, store, actor, *, documents_db=None):
    path = resolve_database(documents_db, store.runtime.path.parent)
    settings = Settings(store.evaluation_path, path)
    dispatcher = App(settings)
    for module in (rfp_api, proposal_api, comparison_api):
        module.register(dispatcher)

    def dispatch(request, body, request_id):
        with connect(settings.db_path) as conn:
            principal = load_principal(conn, settings, request.cookies.get("simsa_v2_session"), touch=False)
        if request.url.path == API_PREFIX + "/auth/me" and request.method == "GET":
            return JSONResponse(success(principal.summary(), request_id))
        req = Request(request.method, request.url.path, parse_qs(request.url.query),
                      dict(request.headers), body, request_id, {}, settings, principal)
        result = dispatcher.dispatch(req)
        headers = dict(result.headers)
        headers["Cache-Control"] = "no-store"
        if result.raw is not None:
            return Response(result.raw, status_code=result.status, media_type=result.content_type, headers=headers)
        return JSONResponse(success(result.data, request_id, **result.meta), status_code=result.status, headers=headers)

    @app.api_route(API_PREFIX + "/{path:path}", methods=["GET", "POST"])
    async def endpoint(request: HttpRequest, path: str):
        person = await actor(request)
        require(person.role == "EVALUATOR", "평가위원 권한이 필요합니다.", "FORBIDDEN", 403)
        request_id = str(uuid.uuid4())
        try:
            chunks = bytearray()
            async for chunk in request.stream():
                chunks.extend(chunk)
                if len(chunks) > settings.max_json_bytes:
                    raise ApiError("FILE_TOO_LARGE", "요청이 너무 큽니다.", 413)
            if chunks and request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                raise ApiError("INPUT_INVALID", "JSON 요청이 필요합니다.", 415)
            return await asyncio.to_thread(dispatch, request, bytes(chunks), request_id)
        except ApiError as exc:
            return JSONResponse(failure(exc, request_id), status_code=exc.status)
        except sqlite3.Error:
            logging.getLogger(__name__).exception("Evaluator document storage failure %s", request_id)
            exc = ApiError("UPSTREAM_UNAVAILABLE", "문서 저장소를 확인하지 못했습니다. 담당자에게 문의해 주세요.", 503)
            return JSONResponse(failure(exc, request_id), status_code=503)
