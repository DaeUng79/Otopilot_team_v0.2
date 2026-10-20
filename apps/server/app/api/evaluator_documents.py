"""Mount the selectively migrated EV-03/04/05 APIs on the existing service."""
import asyncio
import json
import logging
import sqlite3
import uuid
from urllib.parse import parse_qs

from fastapi import Request as HttpRequest
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.evaluation.documents import chat_adapter, comparison_api, proposal_api, rfp_api
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

    async def read_body(request):
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > settings.max_json_bytes:
                raise ApiError("FILE_TOO_LARGE", "요청이 너무 큽니다.", 413)
        if chunks and request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise ApiError("INPUT_INVALID", "JSON 요청이 필요합니다.", 415)
        return bytes(chunks)

    def next_event(iterator):
        return next(iterator, None)

    @app.post(API_PREFIX + "/projects/{project_id}/sessions/{session_id}/chat/stream")
    async def stream_chat(request: HttpRequest, project_id: str, session_id: str):
        person = await actor(request)
        require(person.role == "EVALUATOR", "평가위원 권한이 필요합니다.", "FORBIDDEN", 403)
        request_id = str(uuid.uuid4())
        try:
            body = await read_body(request)
            def prepare():
                with connect(settings.db_path) as conn:
                    principal = load_principal(conn, settings, request.cookies.get("simsa_v2_session"), touch=False)
                req = Request("POST", request.url.path, parse_qs(request.url.query), dict(request.headers), body,
                              request_id, {"project_id": project_id, "session_id": session_id}, settings, principal)
                principal, session, targets, question, history = comparison_api.prepare_chat(req)
                prepared = chat_adapter.prepare_stream(settings.documents_db_path, targets, question, history)
                comparison_api.record_chat(req, principal, session, targets, question, prepared[0].MODEL)
                return prepared
            prepared = await asyncio.to_thread(prepare)
        except ApiError as exc:
            return JSONResponse(failure(exc, request_id), status_code=exc.status)
        except sqlite3.Error:
            logging.getLogger(__name__).exception("Evaluator chat storage failure %s", request_id)
            exc = ApiError("UPSTREAM_UNAVAILABLE", "문서 저장소를 확인하지 못했습니다. 담당자에게 문의해 주세요.", 503)
            return JSONResponse(failure(exc, request_id), status_code=503)

        async def events():
            iterator = chat_adapter.stream_answers(prepared)
            try:
                while True:
                    event = await asyncio.to_thread(next_event, iterator)
                    if event is None:
                        break
                    yield (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            except Exception:
                logging.getLogger(__name__).exception("Evaluator chat stream failure %s", request_id)
                yield (json.dumps({"type": "error", "message": "답변을 이어받지 못했어요. 다시 질문해 주세요."},
                                  ensure_ascii=False) + "\n").encode("utf-8")

        return StreamingResponse(events(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.api_route(API_PREFIX + "/{path:path}", methods=["GET", "POST"])
    async def endpoint(request: HttpRequest, path: str):
        person = await actor(request)
        require(person.role == "EVALUATOR", "평가위원 권한이 필요합니다.", "FORBIDDEN", 403)
        request_id = str(uuid.uuid4())
        try:
            body = await read_body(request)
            return await asyncio.to_thread(dispatch, request, body, request_id)
        except ApiError as exc:
            return JSONResponse(failure(exc, request_id), status_code=exc.status)
        except sqlite3.Error:
            logging.getLogger(__name__).exception("Evaluator document storage failure %s", request_id)
            exc = ApiError("UPSTREAM_UNAVAILABLE", "문서 저장소를 확인하지 못했습니다. 담당자에게 문의해 주세요.", 503)
            return JSONResponse(failure(exc, request_id), status_code=503)
