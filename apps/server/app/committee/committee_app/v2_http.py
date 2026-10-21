"""Thin HTTP adapter for v2. Local sessions never trust the React mock login.

No candidate, draw or roster business logic is duplicated here. A shared server
can later replace the session dependency with its authenticated administrator.
"""

import secrets
import sqlite3
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.committee import committee_roster

from .excel import MAX_BYTES
from .limits import BodyLimitMiddleware
from .v2_core import DTO, Context, ExportFile, ModuleError, Runtime
from .v2_gateway import dispatch_action, error_response

PREFIX = "/committee-v2/api"
COOKIE = "committee_v2_session"
WEB = Path(__file__).resolve().parents[1] / "web_v2"


@dataclass(frozen=True)
class WebSettings:
    actor_id: str
    access_code: str
    origins: tuple[str, ...] = ("http://127.0.0.1:5188", "http://localhost:5188")
    synthetic_data: bool = False
    session_seconds: int = 8 * 60 * 60


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_code: str = Field(min_length=1, max_length=256)


def create_app(runtime: Runtime, settings: WebSettings) -> FastAPI:
    if len(settings.access_code) < 32:
        raise ValueError("A separately generated access code of at least 32 characters is required")
    if any(urlsplit(o).hostname not in {"127.0.0.1", "localhost"} for o in settings.origins):
        raise ValueError("Local adapter only: use loopback origins")
    app = FastAPI(title="Lex6won 위원 v2 웹 연결", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimitMiddleware)
    sessions: dict[str, float] = {}
    attempts: deque[float] = deque()
    hosts = {urlsplit(o).netloc for o in settings.origins} | {"testserver"}

    @app.exception_handler(ModuleError)
    async def domain_error(request: Request, exc: ModuleError) -> JSONResponse:
        return JSONResponse(
            error_response(Context("", request.headers.get("idempotency-key", "")), exc),
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def input_error(request: Request, _: RequestValidationError) -> JSONResponse:
        return await domain_error(
            request, ModuleError("INPUT_INVALID", "입력 형식을 확인하세요.", 422)
        )

    @app.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        if request.headers.get("host") not in hosts:
            return await domain_error(
                request, ModuleError("HOST_FORBIDDEN", "허용된 주소가 아닙니다.", 403)
            )
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            if (origin and origin not in settings.origins) or request.headers.get(
                "x-committee-client"
            ) != "v2-web":
                return await domain_error(
                    request, ModuleError("ORIGIN_FORBIDDEN", "허용된 웹 요청이 아닙니다.", 403)
                )
        size = request.headers.get("content-length")
        if size and (not size.isdigit() or int(size) > MAX_BYTES + 65536):
            return await domain_error(
                request, ModuleError("FILE_TOO_LARGE", "파일은 8MB 이하여야 합니다.", 413)
            )
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'self'; "
                "base-uri 'none'; form-action 'self'",
            }
        )
        return response

    async def admin(request: Request) -> Context:
        token = request.cookies.get(COOKIE, "")
        if sessions.get(token, 0) <= monotonic():
            sessions.pop(token, None)
            raise ModuleError("AUTH_REQUIRED", "위원 관리 연결 코드를 입력하세요.", 401)
        ctx = Context(settings.actor_id, request.headers.get("idempotency-key", ""))
        await runtime.run(ctx, "WEB-AUTH", {}, lambda c: {}, write=False)
        return ctx

    def result(value: DTO | ExportFile) -> Response:
        if isinstance(value, ExportFile):
            return Response(
                value.content,
                media_type=value.media_type,
                headers={
                    "Content-Disposition": "attachment; filename*=UTF-8''" + quote(value.filename),
                },
            )
        return JSONResponse(value)

    @app.post(PREFIX + "/session")
    async def login(body: Login, request: Request, response: Response) -> DTO:
        if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise ModuleError("LOCAL_ONLY", "로컬 접속만 허용합니다.", 403)
        moment = monotonic()
        while attempts and attempts[0] < moment - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise ModuleError("LOGIN_LIMIT", "잠시 후 다시 연결하세요.", 429)
        attempts.append(moment)
        if not secrets.compare_digest(body.access_code.encode(), settings.access_code.encode()):
            raise ModuleError("AUTH_REQUIRED", "연결 코드가 일치하지 않습니다.", 401)
        await runtime.run(Context(settings.actor_id), "WEB-AUTH", {}, lambda c: {}, write=False)
        for expired in [key for key, expiry in sessions.items() if expiry <= moment]:
            sessions.pop(expired, None)
        sessions.pop(request.cookies.get(COOKIE, ""), None)
        token = secrets.token_urlsafe(32)
        sessions[token] = moment + settings.session_seconds
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="strict",
            path="/committee-v2",
            max_age=settings.session_seconds,
        )
        return {"data": {"connected": True}}

    @app.delete(PREFIX + "/session")
    async def logout(request: Request, response: Response) -> DTO:
        sessions.pop(request.cookies.get(COOKIE, ""), None)
        response.delete_cookie(COOKIE, path="/committee-v2")
        return {"data": {"connected": False}}

    @app.get(PREFIX + "/bootstrap")
    async def bootstrap(ctx: Annotated[Context, Depends(admin)]) -> DTO:
        def read(conn: sqlite3.Connection) -> DTO:
            actor = runtime.authorize(conn, ctx)
            projects = [
                dict(r)
                for r in conn.execute(
                    "SELECT p.id,p.name,p.department_id,p.status FROM projects p "
                    "JOIN departments d ON d.id=p.department_id "
                    "WHERE p.deleted_at IS NULL AND d.active=1 AND d.deleted_at IS NULL "
                    "AND (?='SUPER_ADMIN' OR p.department_id=?) ORDER BY p.created_at,p.id",
                    (actor["role"], actor["department_id"]),
                )
            ]
            departments = [
                dict(r)
                for r in conn.execute(
                    "SELECT id,name FROM departments WHERE active=1 AND deleted_at IS NULL "
                    "AND (?='SUPER_ADMIN' OR id=?) ORDER BY name",
                    (actor["role"], actor["department_id"]),
                )
            ]
            specialties = [
                dict(r)
                for r in conn.execute(
                    "SELECT id,name,code FROM specialties WHERE active=1 ORDER BY code"
                )
            ]
            return {
                "actor": {"id": actor["id"], "name": actor["display_name"]},
                "projects": projects,
                "departments": departments,
                "specialties": specialties,
                "synthetic_data": settings.synthetic_data,
                "shared_auth_connected": False,
            }

        return {"data": await runtime.run(ctx, "WEB-BOOTSTRAP", {}, read, write=False)}

    @app.get(PREFIX + "/projects/{project_id}")
    async def project_state(project_id: str, ctx: Annotated[Context, Depends(admin)]) -> DTO:
        state = await committee_roster.list_nominees(
            ctx, {"project_id": project_id}, runtime=runtime
        )

        def extra(conn: sqlite3.Connection) -> DTO:
            runtime.project(conn, ctx, project_id)
            draw = conn.execute(
                "SELECT id,created_at FROM committee_draws WHERE project_id=? AND status='CONFIRMED' "
                "ORDER BY revision_no DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            handoff = conn.execute(
                "SELECT o.event_id,o.status,o.last_error_code FROM sync_outbox o "
                "JOIN committee_rosters r ON r.id=o.aggregate_id WHERE r.project_id=? "
                "AND o.contract_name='roster.confirmed' ORDER BY o.created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            return {
                "quotas": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT specialty_id,final_count FROM field_quotas WHERE project_id=?",
                        (project_id,),
                    )
                ],
                "draw": dict(draw) if draw else None,
                "assignments": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT id,nominee_id,member_kind,reserve_order,name_snapshot,"
                        "organization_snapshot,status FROM committee_assignments "
                        "WHERE project_id=? "
                        "ORDER BY member_kind,reserve_order,name_snapshot",
                        (project_id,),
                    )
                ],
                "handoff": dict(handoff) if handoff else None,
            }

        state.update(
            await runtime.run(ctx, "WEB-PROJECT", {"project_id": project_id}, extra, write=False)
        )
        return {"data": state}

    @app.post(PREFIX + "/actions/{action_id}")
    async def action(
        action_id: str, command: DTO, ctx: Annotated[Context, Depends(admin)]
    ) -> Response:
        return result(await dispatch_action(ctx, action_id, command, runtime=runtime))

    @app.post(PREFIX + "/imports/preview")
    async def preview(
        ctx: Annotated[Context, Depends(admin)],
        file: Annotated[UploadFile, File()],
        department_id: Annotated[str, Form()],
        scope: Annotated[str, Form()] = "DEPARTMENT_POOL",
        project_id: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
    ) -> Response:
        raw = await file.read(MAX_BYTES + 1)
        await file.close()
        if len(raw) > MAX_BYTES:
            raise ModuleError("FILE_TOO_LARGE", "엑셀은 8MB 이하여야 합니다.", 413)
        command: DTO = {
            "department_id": department_id,
            "scope": scope,
            "filename": file.filename or "upload.xlsx",
        }
        if project_id:
            command["project_id"] = project_id
        return result(
            await dispatch_action(
                ctx, "COM-03", command, raw=raw, password=password, runtime=runtime
            )
        )

    @app.get("/committee-v2/")
    async def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/committee-v2/static", StaticFiles(directory=WEB), name="committee-v2-static")
    return app
