"""Same-origin web/API host. Never expose database paths, keys or sync envelopes."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import deque
from dataclasses import asdict
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import quote, urlsplit

from app.admin import auth_service
from app.committee import committee_roster
from app.committee.committee_app.limits import BodyLimitMiddleware
from app.committee.committee_app.v2_core import Context, ExportFile, ModuleError
from app.committee.committee_app.v2_gateway import dispatch_action
from app.shared.db import DTO, ROOT, Actor, Store, one, require, rows
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.api.gateway import ACTIONS, READS
from app.evaluation.result_service import export_report
from starlette.datastructures import UploadFile
from app.shared.sync_service import deliver_outbox

WEB = ROOT.parent / "web"
DESIGN_WEB = WEB / "public"
COOKIE = "simsa_v2_session"


def create_app(
    store: Store, *, demo: bool = False, port: int = 5190, original_ui: bool = False,
    documents_db: Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="심사임당 v2 통합", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(BodyLimitMiddleware)
    failures: deque[float] = deque()
    sync_lock = asyncio.Lock()

    async def sync() -> None:
        async with sync_lock:
            await asyncio.to_thread(deliver_outbox, store)

    @app.exception_handler(ModuleError)
    async def domain_error(request: Request, exc: ModuleError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
        )

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "INPUT_INVALID",
                    "message": "입력 형식과 필수 항목을 확인하세요.",
                }
            },
            status_code=422,
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "CONSTRAINT_CONFLICT",
                    "message": "중복 또는 관계 제약을 확인하세요.",
                }
            },
            status_code=409,
        )

    @app.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        host = request.headers.get("host", "")
        hostname = urlsplit("//" + host).hostname
        if hostname not in {"localhost", "127.0.0.1", "testserver"}:
            return JSONResponse(
                {"error": {"message": "허용되지 않은 주소입니다."}}, status_code=403
            )
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            same = not origin or urlsplit(origin).netloc == host
            client = request.headers.get("x-simsa-client") == "v2-web" or (
                request.url.path.startswith("/committee-v2/api/")
                and request.headers.get("x-committee-client") == "v2-web"
            )
            if not same or not client:
                return JSONResponse(
                    {"error": {"message": "허용되지 않은 웹 요청입니다."}},
                    status_code=403,
                )
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'",
        )
        return response

    async def actor(request: Request) -> Actor:
        person = await asyncio.to_thread(
            auth_service.authorize, store, request.cookies.get(COOKIE, "")
        )
        if request.url.path not in {
            "/api/v2/bootstrap",
            "/committee-v2/api/bootstrap",
            "/api/v2/actions/AUTH-03",
            "/api/v2/actions/AUTH-04",
        }:
            require(
                not auth_service.must_change(store, person),
                "초기 비밀번호를 변경한 뒤 이용하세요.",
                "PASSWORD_CHANGE_REQUIRED",
                423,
            )
        return person

    from app.api.evaluator_documents import install_document_routes
    install_document_routes(app, store, actor, documents_db=documents_db)

    def output(value: DTO | ExportFile, request_id: str = "") -> Response:
        if isinstance(value, ExportFile):
            return Response(
                value.content,
                media_type=value.media_type,
                headers={
                    "Content-Disposition": "attachment; filename*=UTF-8''"
                    + quote(value.filename)
                },
            )
        return JSONResponse(
            {
                "data": value,
                "meta": {
                    "request_id": request_id,
                    **{k: value[k] for k in ("version", "sync_status") if k in value},
                },
            }
        )

    @app.get("/api/v2/config")
    async def config() -> DTO:
        return {
            "data": {
                "demo": demo,
                "action_manifest": json.loads(
                    (ROOT / "contracts/actions_v2.json").read_text("utf8")
                ),
                "demo_accounts": {
                    "super": "super-demo",
                    "department": "web-demo",
                    "password": "DemoOnly!2026",
                    "project_id": "demo-evaluation",
                    "evaluators": [
                        {"name": f"가상위원{i:02d}", "last4": f"{i:04d}"}
                        for i in range(1, 8)
                    ],
                }
                if demo
                else None,
            }
        }

    @app.post("/api/v2/actions/{action_id}")
    @app.post("/committee-v2/api/actions/{action_id}")
    async def action(action_id: str, request: Request) -> Response:
        body = await request.json()
        require(isinstance(body, dict), "입력 객체가 필요합니다.", "INPUT_INVALID", 422)
        if action_id in {"AUTH-01", "AUTH-02"}:
            moment = monotonic()
            while failures and failures[0] < moment - 60:
                failures.popleft()
            require(
                len(failures) < 10,
                "로그인 실패가 반복되었습니다. 1분 후 다시 시도하세요.",
                "LOGIN_LIMIT",
                429,
            )
            await sync()
            try:
                if action_id == "AUTH-02" and not body.get("project_id"):
                    choices = await asyncio.to_thread(
                        auth_service.evaluator_projects, store, body
                    )
                    if len(choices) > 1:
                        return output({"selection_required": True, "projects": choices})
                    body = body | {"project_id": choices[0]["id"]}
                token, person = await asyncio.to_thread(
                    auth_service.login_admin
                    if action_id == "AUTH-01"
                    else auth_service.login_evaluator,
                    store,
                    body,
                )
            except ModuleError:
                failures.append(moment)
                raise
            response = output(
                asdict(person)
                | {"must_change_password": auth_service.must_change(store, person)}
            )
            response.set_cookie(
                COOKIE, token, httponly=True, samesite="strict", max_age=28800, path="/"
            )
            return response
        person = await actor(request)
        if action_id == "AUTH-03":
            await asyncio.to_thread(
                auth_service.logout, store, request.cookies.get(COOKIE, "")
            )
            response = output({"logged_out": True})
            response.delete_cookie(COOKIE, path="/")
            return response
        key = request.headers.get("idempotency-key", "")
        if action_id == "AUTH-04":
            result = await asyncio.to_thread(
                store.transact,
                person,
                action_id,
                body,
                key,
                auth_service.change_password,
                database="admin",
                write=True,
            )
            response = output(result)
            response.delete_cookie(COOKIE, path="/")
            return response
        require(
            not auth_service.must_change(store, person),
            "초기 비밀번호를 변경한 뒤 이용하세요.",
            "PASSWORD_CHANGE_REQUIRED",
            423,
        )
        if action_id.startswith(("COM-", "DRAW-", "ROS-")):
            store.admin(person, "MANAGE_COMMITTEE", body.get("project_id"))
            result = await dispatch_action(
                Context(person.id, key), action_id, body, runtime=store.runtime
            )
            if action_id == "COM-01" and isinstance(result, dict):
                with (
                    store.connect("admin") as admin_db,
                    store.connect() as evaluation_db,
                ):
                    for candidate in result["data"]["items"]:
                        assignments = admin_db.execute(
                            "SELECT a.id FROM committee_assignments a JOIN project_nominees n ON n.id=a.nominee_id WHERE n.candidate_id=?",
                            (candidate["id"],),
                        ).fetchall()
                        projects: set[str] = set()
                        for assignment in assignments:
                            projects.update(
                                r[0]
                                for r in evaluation_db.execute(
                                    "SELECT project_id FROM session_participants WHERE assignment_id=?",
                                    (assignment[0],),
                                )
                            )
                        candidate["participation_count"] = len(projects)
            await sync()
            return (
                output(result)
                if isinstance(result, ExportFile)
                else JSONResponse(result)
            )
        await sync()
        if action_id == "RES-05":
            with store.connect() as c:
                return output(export_report(c, store, person, body))
        require(
            action_id in ACTIONS,
            "이 기능은 문서 담당 모듈의 연결 대상입니다.",
            "EXTERNAL_MODULE_REQUIRED",
            501,
        )
        if action_id in {"SCO-04", "RES-03"}:
            require(
                body.get("purpose")
                == ("EVALUATION" if action_id == "SCO-04" else "CHAIR_RESULT"),
                "버튼과 서명 목적이 다릅니다.",
                "INPUT_INVALID",
                422,
            )
        database = (
            "admin" if action_id.startswith(("ADM-", "PRJ-", "DASH-")) else "evaluation"
        )
        # Check authorization before replaying idempotency responses as well.
        if database == "admin":
            store.admin(
                person,
                "MANAGE_ADMINS"
                if action_id.startswith("ADM")
                else "VIEW_DASHBOARD"
                if action_id.startswith("DASH")
                else "MANAGE_PROJECTS",
                body.get("project_id"),
            )
        elif action_id in {"ATT-00", "ATT-02", "ATT-03", "ATT-04", "ATT-05"}:
            store.admin(person, "MANAGE_PROJECTS", body.get("project_id"))
        if body.get("session_id"):
            with store.connect() as c:
                store.session(
                    c,
                    person,
                    body,
                    person.role != "EVALUATOR",
                    permission="VIEW_RESULTS"
                    if action_id.startswith("RES-")
                    else "MANAGE_PROJECTS",
                )
        result = await asyncio.to_thread(
            store.transact,
            person,
            action_id,
            body,
            key,
            ACTIONS[action_id],
            database=database,
            write=action_id not in READS,
        )
        await sync()
        return output(result, key)

    @app.get("/api/v2/bootstrap")
    @app.get("/committee-v2/api/bootstrap")
    async def bootstrap(request: Request) -> DTO:
        person = await actor(request)
        await sync()
        if person.role == "EVALUATOR":
            with store.connect("admin") as admin_db:
                project_row = one(
                    admin_db, "SELECT * FROM projects WHERE id=?", (person.project_id,)
                )
                from app.admin.project_service import dated, public

                project_info = dated(admin_db, public(store, project_row, True))
            with store.connect() as c:
                assignment = one(
                    c,
                    "SELECT name_snapshot,member_kind FROM ref_committee_assignments WHERE id=?",
                    (person.id,),
                )
                return {
                    "data": {
                        "actor": asdict(person) | {"name": assignment["name_snapshot"]},
                        "synthetic_data": demo,
                        "projects": [
                            {
                                k: project_info[k]
                                for k in (
                                    "id",
                                    "name",
                                    "evaluation_date",
                                    "contact_name",
                                    "contact_phone",
                                )
                            }
                        ],
                        "sessions": rows(
                            c,
                            "SELECT id,status,chair_participant_id FROM evaluation_sessions WHERE project_id=? ORDER BY round_no DESC",
                            (person.project_id,),
                        ),
                        "attendance": rows(
                            c,
                            "SELECT id,status,version FROM attendance_records WHERE assignment_id=?",
                            (person.id,),
                        ),
                        "participants": rows(
                            c,
                            "SELECT id,session_id FROM session_participants WHERE assignment_id=?",
                            (person.id,),
                        ),
                        "member_kind": assignment["member_kind"],
                    }
                }
        with store.connect("admin") as c:
            user = one(
                c,
                "SELECT display_name,username FROM admin_users WHERE id=?",
                (person.id,),
            )
            return {
                "data": {
                    "actor": asdict(person)
                    | {"name": user["display_name"], "username": user["username"]},
                    "must_change_password": auth_service.must_change(store, person),
                    "shared_auth_connected": True,
                    "synthetic_data": demo,
                    "projects": rows(
                        c,
                        "SELECT p.id,p.name,p.department_id,p.status,t.evaluation_date FROM projects p LEFT JOIN project_evaluation_dates t ON t.project_id=p.id WHERE p.deleted_at IS NULL AND (?='SUPER_ADMIN' OR p.department_id=?) ORDER BY p.created_at,p.id",
                        (person.role, person.department_id),
                    ),
                    "departments": rows(
                        c,
                        "SELECT id,name,organization_name FROM departments WHERE active=1 AND deleted_at IS NULL AND (?='SUPER_ADMIN' OR id=?)",
                        (person.role, person.department_id),
                    ),
                    "specialties": rows(
                        c,
                        "SELECT id,name,code FROM specialties WHERE active=1 ORDER BY code",
                    ),
                }
            }

    @app.get("/committee-v2/api/projects/{project_id}")
    async def committee_state(project_id: str, request: Request) -> DTO:
        person = await actor(request)
        store.admin(person, "MANAGE_COMMITTEE", project_id)
        await sync()
        result = await committee_roster.list_nominees(
            Context(person.id), {"project_id": project_id}, runtime=store.runtime
        )
        with store.connect("admin") as c:
            result.update(
                draw_members=rows(
                    c,
                    "SELECT dm.id,dm.specialty_id FROM draw_members dm JOIN committee_draws d ON d.id=dm.draw_id WHERE d.project_id=?",
                    (project_id,),
                ),
                quotas=rows(
                    c,
                    "SELECT specialty_id,final_count FROM field_quotas WHERE project_id=?",
                    (project_id,),
                ),
                assignments=rows(
                    c,
                    "SELECT id,nominee_id,member_kind,reserve_order,name_snapshot,organization_snapshot,status FROM committee_assignments WHERE project_id=?",
                    (project_id,),
                ),
            )
            draw = c.execute(
                "SELECT id,created_at FROM committee_draws WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            handoff = c.execute(
                "SELECT o.event_id,o.status,o.last_error_code FROM sync_outbox o JOIN committee_rosters r ON r.id=o.aggregate_id WHERE r.project_id=? AND o.contract_name='roster.confirmed' ORDER BY o.created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            result.update(
                draw=dict(draw) if draw else None,
                handoff=dict(handoff) if handoff else None,
            )
        return {"data": result}

    @app.post("/committee-v2/api/imports/preview")
    async def preview(request: Request) -> Response:
        person = await actor(request)
        store.admin(person, "MANAGE_COMMITTEE")
        form = await request.form()
        file = form.get("file")
        require(
            isinstance(file, UploadFile),
            "엑셀 파일을 선택하세요.",
            "INPUT_INVALID",
            422,
        )
        assert isinstance(file, UploadFile)
        raw = await file.read(8 * 1024 * 1024 + 1)
        await file.close()
        require(
            len(raw) <= 8 * 1024 * 1024,
            "엑셀은 8MB 이하여야 합니다.",
            "FILE_TOO_LARGE",
            413,
        )
        command = {
            "department_id": str(form.get("department_id", "")),
            "scope": str(form.get("scope", "DEPARTMENT_POOL")),
            "filename": file.filename or "upload.xlsx",
        }
        if form.get("project_id"):
            command["project_id"] = str(form["project_id"])
        result = await dispatch_action(
            Context(person.id, request.headers.get("idempotency-key", "")),
            "COM-03",
            command,
            runtime=store.runtime,
            raw=raw,
            password=str(form.get("password", "")),
        )
        return JSONResponse(result)

    @app.delete("/committee-v2/api/session")
    async def legacy_logout(request: Request) -> Response:
        await actor(request)
        await asyncio.to_thread(
            auth_service.logout, store, request.cookies.get(COOKIE, "")
        )
        response = output({"connected": False})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/api/v2/result-sessions/{project_id}")
    async def result_sessions(project_id: str, request: Request) -> DTO:
        person = await actor(request)
        store.admin(person, "VIEW_RESULTS", project_id)
        with store.connect() as c:
            return {
                "data": {
                    "sessions": rows(
                        c,
                        "SELECT id,project_id,status FROM evaluation_sessions WHERE project_id=? ORDER BY round_no DESC",
                        (project_id,),
                    )
                }
            }

    @app.get("/api/v2/documents/{project_id}")
    async def documents(project_id: str, request: Request) -> DTO:
        person = await actor(request)
        if person.role == "EVALUATOR":
            require(
                person.project_id == project_id,
                "사업 접근 권한이 없습니다.",
                "FORBIDDEN",
                403,
            )
        else:
            store.admin(person, "MANAGE_DOCUMENTS", project_id)
        with store.connect() as c:
            return {
                "data": {
                    "criteria": rows(
                        c,
                        "SELECT id,approval_no,total_max_score,approved_snapshot_json FROM ref_approved_criteria_versions WHERE project_id=?",
                        (project_id,),
                    ),
                    "items": rows(
                        c,
                        "SELECT id,code,title,description,max_score,score_step FROM ref_approved_criteria_items WHERE project_id=? ORDER BY sort_order",
                        (project_id,),
                    ),
                    "proposals": rows(
                        c,
                        "SELECT p.id,v.display_code,p.format,p.status FROM ref_proposal_uploads p JOIN ref_project_vendors v ON v.id=p.vendor_id WHERE p.project_id=?",
                        (project_id,),
                    ),
                    "samples": [
                        {k: v for k, v in f.items() if k != "path"}
                        for f in sample_files()
                    ]
                    if demo and project_id == "demo-evaluation"
                    else [],
                    "external_notice": "문서 업로드·파싱·평가표 승인·근거 매핑·챗봇은 오대웅 담당 모듈입니다. 여기의 가상 승인표는 평가 연동 테스트용입니다.",
                }
            }

    def sample_files() -> list[DTO]:
        path = store.evaluation_path.parent / "sample-manifest.json"
        return json.loads(path.read_text("utf8")) if path.exists() else []

    @app.get("/api/v2/samples/{sample_id}")
    async def sample_download(sample_id: str, request: Request) -> Response:
        person = await actor(request)
        require(demo, "시연 모드에서만 제공됩니다.", "NOT_FOUND", 404)
        if person.role == "EVALUATOR":
            require(
                person.project_id == "demo-evaluation",
                "사업 접근 권한이 없습니다.",
                "FORBIDDEN",
                403,
            )
        else:
            store.admin(person, "MANAGE_DOCUMENTS", "demo-evaluation")
        item = next((f for f in sample_files() if f["id"] == sample_id), None)
        require(item is not None, "샘플 파일이 없습니다.", "NOT_FOUND", 404)
        assert item is not None
        path = Path(item["path"])
        require(path.is_file(), "샘플 원본 경로를 확인하세요.", "NOT_FOUND", 404)
        return FileResponse(
            path,
            filename=sample_id + path.suffix,
            media_type="application/pdf"
            if path.suffix.lower() == ".pdf"
            else "application/octet-stream",
        )

    @app.get("/committee-v2/")
    async def committee_index() -> FileResponse:
        return FileResponse(ROOT / "app/committee/web_v2/index.html")

    @app.get("/")
    @app.get("/index.html")
    async def index() -> Response:
        if original_ui:
            from fastapi.responses import RedirectResponse

            return RedirectResponse("/app/entry/design/entry.html")
        return FileResponse(DESIGN_WEB / "index.html")

    app.mount("/src", StaticFiles(directory=WEB / "src"), name="screens")
    app.mount("/fonts", StaticFiles(directory=WEB / "public/fonts"), name="fonts")
    @app.get("/app/{relative:path}")
    async def runtime_screen(relative: str) -> Response:
        from app.api.design_runtime import connected_html

        target = (WEB / "src/runtime" / relative).resolve()
        require(
            target.is_relative_to((WEB / "src/runtime").resolve()) and target.is_file(),
            "파일이 없습니다.", "NOT_FOUND", 404,
        )
        connected = connected_html(relative)
        return connected if connected is not None else FileResponse(target)
    app.mount(
        "/committee-v2/static",
        StaticFiles(directory=ROOT / "app/committee/web_v2"),
        name="committee-assets",
    )
    return app
