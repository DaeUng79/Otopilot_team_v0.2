import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .errors import DomainError
from .excel import MAX_BYTES
from .limits import BodyLimitMiddleware
from .responses import CandidateRead, ContactRead, DrawRead, ImportPreview, ProjectRead
from .service import CommitteeService


@dataclass(frozen=True)
class Settings:
    db_path: Path
    local_admin: bool = False
    verification_mode: Literal["disabled", "demo"] = "disabled"
    port: int = 5187
    demo_data: bool = False
    public_origin: str = ""


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CandidateInput(Input):
    name: str = Field(default="", max_length=100)
    organization: str = Field(default="", max_length=200)
    position: str = Field(default="", max_length=100)
    birth_date: str = Field(default="", max_length=30)
    region: str = Field(default="", max_length=100)
    category: str = Field(default="", max_length=100)
    department: str = Field(default="", max_length=200)
    specialty: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=254)
    memo: str = Field(default="", max_length=2000)
    source_serial: str = Field(default="", max_length=100)
    enabled: bool = True


class CandidateUpdate(CandidateInput):
    expected_version: int = Field(ge=0)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=200)
    fields: list[str] = Field(min_length=1, max_length=30)
    target: Literal[7, 8, 9]


class Reviewed(Input):
    reviewed: Literal[True]


class CriteriaInput(Input):
    fields: list[str] = Field(min_length=1, max_length=30)
    target: Literal[7, 8, 9]
    expected_version: int = Field(ge=0)


class DemoLogin(Input):
    project_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    contact: str = Field(min_length=1, max_length=254)


class ContactInput(Input):
    status: Literal["미연락", "연락 불가", "참여 가능", "참여 불가", "제척"]
    note: str = Field(default="", max_length=2000)
    expected_version: int = Field(ge=0)


class FinalInput(Input):
    candidate_ids: list[str] = Field(min_length=7, max_length=9)
    reserve_ids: list[str] = Field(min_length=3, max_length=3)
    expected_version: int = Field(ge=0)


class OtpInput(Input):
    project_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=30)


class OtpProof(Input):
    request_id: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^\d{6}$")


def create_app(settings: Settings) -> FastAPI:
    service = CommitteeService(settings.db_path)
    app = FastAPI(title="Lex6won 평가위원 관리 API", version="0.1.0")
    app.state.service = service
    admin_cookie = f"committee_admin_{settings.port}"
    evaluator_cookie = f"committee_evaluator_{settings.port}"
    app.add_middleware(BodyLimitMiddleware)
    attempts: dict[str, deque[float]] = defaultdict(deque)
    allowed_hosts = {
        f"127.0.0.1:{settings.port}",
        f"localhost:{settings.port}",
        "127.0.0.1",
        "localhost",
        "testserver",
    }
    allowed_origins = {f"http://127.0.0.1:{settings.port}", f"http://localhost:{settings.port}"}
    if settings.public_origin:
        allowed_hosts.add(urlsplit(settings.public_origin).netloc)
        allowed_origins.add(settings.public_origin)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def input_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Deliberately omit submitted values (passwords, phone numbers, OTPs).
        details = [{"loc": error["loc"], "msg": error["msg"]} for error in exc.errors()]
        response = JSONResponse({"detail": details}, status_code=422)
        if request.url.path.endswith("/auth/demo-login"):
            await asyncio.to_thread(service.logout, request.cookies.get(evaluator_cookie, ""))
            response.delete_cookie(evaluator_cookie, path="/api/v1/committee")
        return response

    @app.middleware("http")
    async def local_boundary(request: Request, call_next: Any) -> Response:
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"detail": "허용된 로컬 호스트가 아닙니다."}, status_code=403)
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                return JSONResponse(
                    {"detail": "다른 사이트의 요청은 허용하지 않습니다."}, status_code=403
                )
            if request.headers.get("x-committee-client") != "local-ui":
                return JSONResponse(
                    {"detail": "위원 관리 클라이언트 요청이 필요합니다."}, status_code=403
                )
        content_length = request.headers.get("content-length")
        if content_length and (
            not content_length.isdigit() or int(content_length) > MAX_BYTES + 65536
        ):
            return JSONResponse({"detail": "요청 크기 제한을 초과했습니다."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        return response

    async def admin(request: Request) -> None:
        await asyncio.to_thread(service.require_admin, request.cookies.get(admin_cookie, ""))

    prefix = "/api/v1/committee"

    @app.get(prefix + "/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "local_admin": settings.local_admin,
            "verification_mode": settings.verification_mode,
            "database": "sqlite",
            "production_auth": False,
            "demo_data": settings.demo_data,
            "login_origin": settings.public_origin,
        }

    @app.post(prefix + "/local/session")
    async def login(request: Request, response: Response) -> dict[str, bool]:
        if not settings.local_admin:
            raise DomainError(
                503, "관리자 인증 연결 전입니다. 로컬 실행에만 --local-admin을 사용하세요."
            )
        if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise DomainError(403, "로컬 관리자 접속만 허용합니다.")
        token = await asyncio.to_thread(service.admin_session)
        response.set_cookie(
            admin_cookie, token, httponly=True, samesite="strict", max_age=3600, path=prefix
        )
        return {"local_development": True}

    @app.get(
        prefix + "/candidates", dependencies=[Depends(admin)], response_model=list[CandidateRead]
    )
    async def list_candidates() -> list[dict[str, Any]]:
        return await asyncio.to_thread(service.list_candidates)

    @app.post(
        prefix + "/candidates",
        status_code=201,
        dependencies=[Depends(admin)],
        response_model=CandidateRead,
    )
    async def add_candidate(body: CandidateInput) -> dict[str, Any]:
        return await asyncio.to_thread(service.add_candidate, body.model_dump())

    @app.put(
        prefix + "/candidates/{cid}", dependencies=[Depends(admin)], response_model=CandidateRead
    )
    async def update_candidate(cid: str, body: CandidateUpdate) -> dict[str, Any]:
        patch = body.model_dump(exclude_unset=True, exclude={"expected_version"})
        return await asyncio.to_thread(service.update_candidate, cid, patch, body.expected_version)

    @app.post(
        prefix + "/imports/preview", dependencies=[Depends(admin)], response_model=ImportPreview
    )
    async def import_preview(
        file: Annotated[UploadFile, File()], password: Annotated[str, Form(max_length=256)] = ""
    ) -> dict[str, Any]:
        try:
            raw = await file.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise DomainError(413, "파일은 8MB 이하로 등록하세요.")
            return await asyncio.to_thread(
                service.import_preview, raw, password, file.filename or ""
            )
        finally:
            await file.close()

    @app.post(prefix + "/imports/{preview_id}/commit", dependencies=[Depends(admin)])
    async def import_commit(preview_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(service.commit_import, preview_id)

    @app.get(prefix + "/projects", dependencies=[Depends(admin)], response_model=list[ProjectRead])
    async def projects() -> list[dict[str, Any]]:
        return await asyncio.to_thread(service.list_projects)

    @app.post(
        prefix + "/projects",
        status_code=201,
        dependencies=[Depends(admin)],
        response_model=ProjectRead,
    )
    async def create_project(body: ProjectInput) -> dict[str, Any]:
        return await asyncio.to_thread(service.create_project, body.name, body.fields, body.target)

    @app.get(prefix + "/projects/{pid}/pool", dependencies=[Depends(admin)])
    async def pool(pid: str) -> dict[str, Any]:
        return await asyncio.to_thread(service.preview_pool, pid)

    @app.post(
        prefix + "/proposals",
        status_code=201,
        dependencies=[Depends(admin)],
        response_model=ProjectRead,
    )
    async def register_proposal(
        file: Annotated[UploadFile, File()], name: Annotated[str, Form(max_length=200)] = ""
    ) -> dict[str, Any]:
        try:
            raw = await file.read(MAX_BYTES + 1)
            return await asyncio.to_thread(
                service.register_proposal, raw, file.filename or "", name
            )
        finally:
            await file.close()

    @app.get(prefix + "/projects/{pid}/proposal", dependencies=[Depends(admin)])
    async def proposal(pid: str) -> Response:
        raw, filename = await asyncio.to_thread(service.proposal, pid)
        return Response(
            raw,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe="")
            },
        )

    @app.put(
        prefix + "/projects/{pid}/criteria",
        dependencies=[Depends(admin)],
        response_model=ProjectRead,
    )
    async def configure_project(pid: str, body: CriteriaInput) -> dict[str, Any]:
        return await asyncio.to_thread(
            service.configure_project, pid, body.fields, body.target, body.expected_version
        )

    @app.get(
        prefix + "/projects/{pid}/draw",
        dependencies=[Depends(admin)],
        response_model=DrawRead | None,
    )
    async def draw_read(pid: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(service.get_draw, pid)

    @app.post(
        prefix + "/projects/{pid}/draw",
        status_code=201,
        dependencies=[Depends(admin)],
        response_model=DrawRead,
    )
    async def draw_create(pid: str, body: Reviewed) -> dict[str, Any]:
        return await asyncio.to_thread(service.draw, pid, body.reviewed)

    @app.put(
        prefix + "/projects/{pid}/contacts/{cid}",
        dependencies=[Depends(admin)],
        response_model=ContactRead,
    )
    async def contact(pid: str, cid: str, body: ContactInput) -> dict[str, Any]:
        return await asyncio.to_thread(
            service.update_contact, pid, cid, body.status, body.note, body.expected_version
        )

    @app.post(
        prefix + "/projects/{pid}/finalize", dependencies=[Depends(admin)], response_model=DrawRead
    )
    async def finalize(pid: str, body: FinalInput) -> dict[str, Any]:
        return await asyncio.to_thread(
            service.finalize, pid, body.candidate_ids, body.expected_version, body.reserve_ids
        )

    @app.post(prefix + "/projects/{pid}/assign", dependencies=[Depends(admin)])
    async def assign(pid: str) -> dict[str, Any]:
        return await asyncio.to_thread(service.assign, pid)

    @app.get(prefix + "/audit", dependencies=[Depends(admin)])
    async def audit() -> list[dict[str, Any]]:
        return await asyncio.to_thread(service.audit)

    @app.post(prefix + "/auth/request")
    async def request_otp(request: Request, body: OtpInput) -> dict[str, Any]:
        key = request.client.host if request.client else "unknown"
        hits = attempts[key]
        while hits and hits[0] < monotonic() - 60:
            hits.popleft()
        if len(hits) >= 10:
            raise DomainError(429, "요청이 많습니다. 잠시 후 다시 시도하세요.")
        hits.append(monotonic())
        return await asyncio.to_thread(
            service.issue_otp, body.project_id, body.name, body.phone, settings.verification_mode
        )

    @app.get(prefix + "/auth/project")
    async def login_project(project_id: str) -> dict[str, str]:
        return await asyncio.to_thread(service.login_project, project_id)

    @app.post(prefix + "/auth/demo-login")
    async def demo_login(request: Request, body: DemoLogin) -> Response:
        # A shared device must never retain the previous evaluator after a failed attempt.
        await asyncio.to_thread(service.logout, request.cookies.get(evaluator_cookie, ""))
        try:
            key = request.client.host if request.client else "unknown"
            hits = attempts[key]
            while hits and hits[0] < monotonic() - 60:
                hits.popleft()
            if len(hits) >= 10:
                raise DomainError(429, "요청이 많습니다. 1분 후 다시 시도하세요.")
            hits.append(monotonic())
            result = await asyncio.to_thread(
                service.demo_login,
                body.project_id,
                body.name,
                body.contact,
                settings.verification_mode,
            )
            token = result.pop("token")
            response = JSONResponse(result)
            response.set_cookie(
                evaluator_cookie, token, httponly=True, samesite="strict", max_age=900, path=prefix
            )
            return response
        except DomainError as exc:
            response = JSONResponse({"detail": exc.message}, status_code=exc.status)
            response.delete_cookie(evaluator_cookie, path=prefix)
            return response

    @app.post(prefix + "/auth/logout")
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        await asyncio.to_thread(service.logout, request.cookies.get(evaluator_cookie, ""))
        response.delete_cookie(evaluator_cookie, path=prefix)
        return {"logged_out": True}

    @app.post(prefix + "/auth/verify")
    async def verify_otp(body: OtpProof, response: Response) -> dict[str, Any]:
        if settings.verification_mode != "demo":
            raise DomainError(503, "실제 본인인증 제공자가 연결되지 않았습니다.")
        result = await asyncio.to_thread(service.verify_otp, body.request_id, body.code)
        token = result.pop("token")
        response.set_cookie(
            evaluator_cookie, token, httponly=True, samesite="strict", max_age=900, path=prefix
        )
        return result

    @app.get(prefix + "/auth/me")
    async def assignment_me(request: Request, project_id: str) -> dict[str, Any]:
        if settings.verification_mode != "demo":
            raise DomainError(503, "실제 본인인증 제공자가 연결되지 않았습니다.")
        return await asyncio.to_thread(
            service.verification, request.cookies.get(evaluator_cookie, ""), project_id
        )

    web = Path(__file__).resolve().parents[1] / "web"

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(web / "index.html")

    app.mount("/assets", StaticFiles(directory=web), name="assets")
    return app
