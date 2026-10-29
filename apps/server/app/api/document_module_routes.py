"""DOC-03·04·06, CRT-01~05, PRO-01~03, MAT-01~03 연결 라우트 (2026-10-18).

설계도(인계서 v2 §11)의 `/document-api/...` 경로를 기존 제안요청서 라우트와 같은
`/api/v2/...` 아래에 둔다. 업무 처리는 apps/documents의 rfp_workflow·criteria_review·
proposal_uploads·document_gateway·material_service가 맡고, 여기서는
권한·사업 상태 확인과 평가 DB 계약 전달(`criteria.approved`, `proposal.ready`,
`proposal.archived`)만 한다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile

from app.committee.committee_app.v2_core import digest
from app.documents import (criteria_review, document_gateway, material_service, proposal_analysis_jobs,
                           proposal_uploads, rfp_workflow)
from app.documents import requirements_extract as step3
from app.documents import criteria_generate as step4
from app.documents import proposal_analysis as step5
from app.documents import requirements_review as specs
from app.shared.db import require, rows
from app.shared.integration_contracts import apply_event
from app.evaluation.documents.envelope import ApiError
from app.evaluation.documents.rfp_adapter import DocumentReader
from app.documents.storage_documents import connect

MAX_FILE_SIZE = 50 * 1024 * 1024
PROPOSAL_TYPES = (".hwpx", ".pdf", ".pptx")
MATERIAL_TYPES = (".pdf", ".hwpx", ".hwp", ".xlsx", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".zip", ".html")
log = logging.getLogger(__name__)


def ai_ready() -> bool:
    """Report readiness only when the key and required AI packages are present."""
    if not all(importlib.util.find_spec(name) for name in ("openai", "tiktoken", "dotenv")):
        return False
    if (os.environ.get("OPENAI_API_KEY") or "").strip():
        return True
    from dotenv import dotenv_values

    return bool((dotenv_values(step3.ENV_PATH, interpolate=False).get("OPENAI_API_KEY") or "").strip())


def event_envelope(contract: str, aggregate_id: str, payload: dict, *, version: int = 1) -> dict:
    """문서 모듈 → 평가 DB 계약 봉투(인계서 v2 §08)."""
    return {"event_id": str(uuid4()), "contract_name": contract, "schema_version": 2,
            "aggregate_id": aggregate_id, "aggregate_version": version,
            "payload": payload, "payload_sha256": digest(payload)}


def run(fn, *args, **kwargs):
    """문서 어댑터의 예외를 화면용 응답(JSON 오류)으로 바꾼다."""
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        require(False, str(exc), "NOT_FOUND", 404)
    except RuntimeError as exc:
        require(False, str(exc), "UPSTREAM_UNAVAILABLE", 503)
    except (step3.RequirementsError, step4.CriteriaError, criteria_review.CriteriaApprovalError,
            ValueError) as exc:
        require(False, str(exc) or "입력 형식과 필수 항목을 확인하세요.", "INPUT_INVALID", 422)


async def json_body(request: Request) -> dict:
    if int(request.headers.get("content-length", "0") or 0) == 0:
        return {}
    body = await request.json()
    require(isinstance(body, dict), "입력 객체가 필요합니다.", "INPUT_INVALID", 422)
    return body


def install_document_module_routes(app, store, actor, sync, project, database: Path) -> None:
    try:
        rfp_workflow.initialize_jobs(database)
    except Exception:  # 문서 DB가 아직 없으면 첫 업로드 때 만들어진다.
        log.info("document DB not initialized yet: %s", database)

    async def vendor_of(project_id: str, vendor_id: str) -> dict:
        with store.connect("admin") as db:
            row = db.execute(
                "SELECT id,display_code,legal_name,version FROM project_vendors "
                "WHERE id=? AND project_id=? AND deleted_at IS NULL", (vendor_id, project_id)).fetchone()
        require(row is not None, "업체를 찾을 수 없습니다.", "NOT_FOUND", 404)
        return dict(row)

    async def read_upload(request: Request, *, accept: tuple[str, ...], label: str) -> tuple[str, bytes, dict]:
        form = await request.form()
        file = form.get("file")
        require(isinstance(file, UploadFile), f"{label} 파일을 선택하세요.", "INPUT_INVALID", 422)
        filename = Path((file.filename or "").replace("\\", "/")).name
        kinds = "·".join(a[1:].upper() for a in accept)
        require(bool(filename) and len(filename) <= 255 and filename.lower().endswith(accept),
                f"{kinds} 파일만 올릴 수 있습니다.", "INPUT_INVALID", 422)
        data = await file.read(MAX_FILE_SIZE + 1)
        await file.close()
        require(0 < len(data) <= MAX_FILE_SIZE, "50MB 이하의 파일을 올려 주세요.", "FILE_TOO_LARGE", 413)
        return filename, data, {k: v for k, v in form.items() if k != "file"}

    def attachment(data: bytes, filename: str) -> Response:
        return Response(data, media_type="application/octet-stream",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)})

    # ---- DOC-03·04 요구사항 추출 ----
    @app.get("/api/v2/projects/{project_id}/requirements")
    async def requirements_status(project_id: str, request: Request):
        await project(request, project_id)
        return {"data": await asyncio.to_thread(run, rfp_workflow.requirement_status, database, project_id)}

    @app.get("/api/v2/projects/{project_id}/requirements/preview")
    async def requirements_preview(project_id: str, request: Request):
        await project(request, project_id)

        def read_saved():
            state = rfp_workflow.requirement_status(database, project_id)
            require(state["status"] in {"done", "needs_review"}, "완료된 요구사항 추출 결과가 없습니다.", "NOT_FOUND", 404)
            upload = rfp_workflow.latest_rfp(database, project_id)
            require(upload is not None, "제안요청서를 찾을 수 없습니다.", "NOT_FOUND", 404)
            result = step3.load_saved_requirements(database, upload["document_id"])
            require(result is not None, "저장된 요구사항 결과가 없습니다.", "NOT_FOUND", 404)
            with connect(database) as db:
                spec = specs.latest(db, project_id, upload["revision"], result)
                approved = specs.latest(db, project_id, upload["revision"], result, approved=True)
                history = ([dict(r) for r in db.execute("SELECT id,status,version,created_at,approved_at FROM requirement_spec_versions WHERE project_id=? AND upload_revision=? ORDER BY created_at DESC", (project_id, upload["revision"]))] if specs._exists(db) else [])
            return {"specification": spec, "approved_specification": approved, "specification_history": history,
                    "ready": state.get("ready", False),
                    "filename": upload["filename"], "revision": upload["revision"],
                    "created_at": result.get("created_at"), "status": result.get("status"),
                    "business_status": result.get("business_status") or {},
                    "requirement_list": result.get("requirement_list") or {},
                    "details": result.get("details") or {},
                    "duplicate_code_resolutions": result.get("duplicate_code_resolutions") or [],
                    "warnings": result.get("warnings") or []}

        return {"data": await asyncio.to_thread(run, read_saved)}

    @app.put("/api/v2/projects/{project_id}/requirements/specifications/{spec_id}")
    async def specification_review(project_id: str, spec_id: str, request: Request):
        await project(request, project_id, edit=True)
        person = await actor(request)
        body = await json_body(request)
        require(type(body.get("version")) is int, "명세서 버전을 확인하세요.", "INPUT_INVALID", 422)
        require(type(body.get("approve", False)) is bool, "확정 여부를 확인하세요.", "INPUT_INVALID", 422)
        require(not body.get("approve") or body.get("confirmed") is True,
                "원문 근거와 추가 의무 여부를 검토한 후 확정해 주세요.", "INPUT_INVALID", 422)
        def save():
            upload = rfp_workflow.latest_rfp(database, project_id)
            require(upload is not None, "제안요청서가 없습니다.", "NOT_FOUND", 404)
            with connect(database) as db:
                busy = db.execute("SELECT 1 FROM requirement_jobs WHERE project_id=? AND revision=? AND status IN ('queued','running')",
                                  (project_id, upload["revision"])).fetchone()
            require(not busy, "요구사항 분석 중에는 명세서를 변경할 수 없습니다.", "CONFLICT", 409)
            result = step3.load_saved_requirements(database, upload["document_id"])
            require(result is not None, "요구사항을 먼저 분석해 주세요.", "NOT_FOUND", 404)
            return specs.review(database, project_id, upload, result, spec_id, body["version"],
                                items=body.get("items"), approve=body.get("approve", False), actor_id=person.id)
        return {"data": await asyncio.to_thread(run, save)}

    @app.get("/api/v2/projects/{project_id}/requirements/proposal-comparison")
    async def requirements_proposal_comparison(project_id: str, request: Request):
        await project(request, project_id)
        return {"data": await asyncio.to_thread(run, step5.comparison_overview, database, project_id)}

    @app.get("/api/v2/projects/{project_id}/requirements/proposal-analysis/jobs")
    async def proposal_analysis_status(project_id: str, request: Request):
        await project(request, project_id)
        return {"data": proposal_analysis_jobs.status(project_id)}

    @app.post("/api/v2/projects/{project_id}/requirements/proposal-analysis/jobs")
    async def proposal_analysis_start(project_id: str, request: Request):
        await project(request, project_id, edit=True)
        body = await json_body(request)
        proposal_upload_id = body.get("proposal_upload_id")
        require(isinstance(proposal_upload_id, str) and bool(proposal_upload_id),
                "분석할 제안서를 선택해 주세요.", "INPUT_INVALID", 422)
        require(ai_ready(), "OpenAI 설정을 확인해 주세요.", "UPSTREAM_UNAVAILABLE", 503)
        return {"data": await asyncio.to_thread(run, proposal_analysis_jobs.queue,
                                                database, project_id, proposal_upload_id)}

    @app.post("/api/v2/projects/{project_id}/requirements/jobs")
    async def requirements_job(project_id: str, request: Request):
        await project(request, project_id, edit=True)
        body = await json_body(request)
        return {"data": await asyncio.to_thread(run, rfp_workflow.queue_requirements, database, project_id,
                                                force=bool(body.get("force")), mode=body.get("mode", "auto"))}

    # ---- CRT-01·02 AI 초안, CRT-03~05 사람 승인 ----
    def criteria_state(project_id: str) -> dict:
        versions = criteria_review.list_versions(database, project_id)
        draft = rfp_workflow.criteria_status(database, project_id)
        if draft.get("result"):
            draft["result"]["scoring_rows"] = criteria_review.scoring_rows_with_source_pages(
                database, project_id, draft["result"]["rows"],
                draft["result"].get("template_source"))
        with store.connect() as db:
            acked = {r["id"] for r in rows(
                db, "SELECT id FROM ref_approved_criteria_versions WHERE project_id=? AND status='APPROVED' AND is_deleted=0",
                (project_id,))}
            frozen = {r["approved_criteria_version_id"] for r in rows(
                db, "SELECT approved_criteria_version_id FROM evaluation_sessions WHERE project_id=? AND status<>'CANCELLED'",
                (project_id,))}
        for v in versions:
            v["ack"] = v["id"] in acked
            v["frozen"] = v["id"] in frozen
        return {"rfp": rfp_workflow.latest_rfp(database, project_id),
                "requirements": rfp_workflow.requirement_status(database, project_id),
                "draft": draft,
                "versions": versions,
                "ai_ready": ai_ready()}

    @app.get("/api/v2/projects/{project_id}/criteria")
    async def criteria_get(project_id: str, request: Request):
        await project(request, project_id)
        return {"data": await asyncio.to_thread(run, criteria_state, project_id)}

    @app.post("/api/v2/projects/{project_id}/criteria/jobs")
    async def criteria_job(project_id: str, request: Request):
        await project(request, project_id, edit=True)
        body = await json_body(request)
        await asyncio.to_thread(run, rfp_workflow.queue_pipeline, database, project_id, force=bool(body.get("force")))
        return {"data": await asyncio.to_thread(run, criteria_state, project_id)}

    @app.post("/api/v2/projects/{project_id}/criteria-drafts")
    async def criteria_open_draft(project_id: str, request: Request):
        await project(request, project_id, edit=True)
        person = await actor(request)
        body = await json_body(request)
        source = body.get("source", "ai")
        require(source in {"ai", "template"}, "초안 출처를 확인하세요.", "INPUT_INVALID", 422)
        require(type(body.get("restart", False)) is bool, "새 검토 여부를 확인하세요.", "INPUT_INVALID", 422)
        ai_result = rfp_workflow.criteria_status(database, project_id).get("result") if source == "ai" else None
        draft = await asyncio.to_thread(run, criteria_review.open_draft, database, project_id=project_id,
                                        source=source, ai_result=ai_result, actor_id=person.id,
                                        restart=body.get("restart", False))
        return JSONResponse({"data": draft}, status_code=201)

    @app.put("/api/v2/projects/{project_id}/criteria-drafts/{draft_id}")
    async def criteria_save_draft(project_id: str, draft_id: str, request: Request):
        await project(request, project_id, edit=True)
        body = await json_body(request)
        require(type(body.get("version")) is int, "version을 확인하세요.", "INPUT_INVALID", 422)
        total = body.get("total_points")
        require(total is None or isinstance(total, (int, float)), "기술 배점을 확인하세요.", "INPUT_INVALID", 422)
        draft = await asyncio.to_thread(run, criteria_review.save_draft, database, project_id=project_id,
                                        draft_id=draft_id, version=body["version"], items=body.get("items"),
                                        total_points=total)
        return {"data": draft}

    @app.post("/api/v2/projects/{project_id}/criteria-drafts/{draft_id}/approve")
    async def criteria_approve(project_id: str, draft_id: str, request: Request):
        await project(request, project_id, edit=True)
        person = await actor(request)
        body = await json_body(request)
        require(type(body.get("version")) is int, "version을 확인하세요.", "INPUT_INVALID", 422)
        saved, payload = await asyncio.to_thread(
            run, criteria_review.approve_criteria, database, project_id=project_id, draft_id=draft_id,
            version=body["version"], actor_id=person.id, confirmed=body.get("confirmed"))
        await sync()
        # 평가 DB로 criteria.approved 계약 전달. 수신(APPLIED) 뒤에야 회차를 준비할 수 있다.
        ack = await asyncio.to_thread(apply_event, store, event_envelope("criteria.approved", draft_id, payload), "documents")
        return {"data": {"version": saved, "ack": ack}}

    @app.post("/api/v2/projects/{project_id}/criteria-drafts/{draft_id}/resend")
    async def criteria_resend(project_id: str, draft_id: str, request: Request):
        await project(request, project_id)
        payload = criteria_review.approved_payload(database, project_id, draft_id)
        require(payload is not None, "확정된 평가표가 아닙니다.", "NOT_FOUND", 404)
        await sync()
        ack = await asyncio.to_thread(apply_event, store, event_envelope("criteria.approved", draft_id, payload), "documents")
        return {"data": {"ack": ack}}

    # ---- PRO-01~03 업체별 제안서 ----
    @app.get("/api/v2/projects/{project_id}/proposals")
    async def proposals_list(project_id: str, request: Request):
        await project(request, project_id)
        return {"data": {"uploads": await asyncio.to_thread(proposal_uploads.list_proposals,
                                                            database, project_id)}}

    @app.post("/api/v2/projects/{project_id}/vendors/{vendor_id}/proposals")
    async def proposal_upload(project_id: str, vendor_id: str, request: Request):
        row = await project(request, project_id, edit=True)
        person = await actor(request)
        vendor = await vendor_of(project_id, vendor_id)
        filename, data, _ = await read_upload(request, accept=PROPOSAL_TYPES, label="제안서")
        await sync()
        with store.connect() as db:
            minimum_revision = db.execute(
                "SELECT COALESCE(MAX(upload_revision),0)+1 FROM ref_proposal_uploads "
                "WHERE project_id=? AND vendor_id=?", (project_id, vendor_id)
            ).fetchone()[0]
        try:
            upload = await asyncio.to_thread(
                proposal_uploads.register_proposal, database, project_id=project_id,
                project_name=row["name"], vendor_id=vendor_id, filename=filename, data=data,
                uploaded_by=person.id, minimum_revision=minimum_revision)
        except (ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
            require(False, str(exc) or "문서 구조를 확인하세요.", "INPUT_INVALID", 422)
        except RuntimeError as exc:
            require(False, str(exc), "UPSTREAM_UNAVAILABLE", 503)
        except Exception:
            log.exception("proposal parse or storage failed")
            require(False, "제안서를 파싱하거나 저장하지 못했습니다.", "DOCUMENT_SAVE_FAILED", 500)
        await sync()
        ack = await asyncio.to_thread(
            apply_event, store,
            event_envelope("proposal.ready", upload["id"], proposal_uploads.ready_event(upload)),
            "documents")
        return JSONResponse({"data": upload | {"display_code": vendor["display_code"], "ack": ack}}, status_code=201)

    @app.post("/api/v2/projects/{project_id}/proposals/{upload_id}/resend")
    async def proposal_resend(project_id: str, upload_id: str, request: Request):
        await project(request, project_id)
        upload = await asyncio.to_thread(run, proposal_uploads.get_proposal, database, project_id, upload_id)
        require(upload["status"] in {"READY", "ARCHIVED"}, "전달할 수 없는 제안서 상태입니다.", "NOT_READY", 409)
        await sync()
        ack = await asyncio.to_thread(
            apply_event, store,
            event_envelope("proposal.archived" if upload["status"] == "ARCHIVED" else "proposal.ready",
                           upload["id"], proposal_uploads.ready_event(upload),
                           version=upload["version"]),
            "documents")
        return {"data": {"ack": ack}}

    @app.get("/api/v2/projects/{project_id}/proposals/{upload_id}/download")
    async def proposal_download(project_id: str, upload_id: str, request: Request):
        await project(request, project_id)
        upload = await asyncio.to_thread(run, proposal_uploads.get_proposal, database, project_id, upload_id)
        source = await asyncio.to_thread(document_gateway.view_source, database, upload["document_id"])
        require(source is not None, "원본 파일을 찾을 수 없습니다.", "NOT_FOUND", 404)
        return attachment(source[1], upload["filename"])

    @app.get("/api/v2/projects/{project_id}/proposals/{upload_id}/source")
    async def proposal_source(project_id: str, upload_id: str, request: Request):
        await project(request, project_id)
        upload = await asyncio.to_thread(run, proposal_uploads.get_proposal, database, project_id, upload_id)
        parsed = await asyncio.to_thread(run, document_gateway.parsed_blocks, database,
                                         upload["document_id"], upload["parse_revision"])
        return {"data": parsed | {"filename": upload["filename"], "revision": upload["upload_revision"]}}

    def proposal_reader(db, project_id: str, upload_id: str) -> tuple[DocumentReader, dict]:
        upload = run(proposal_uploads.get_proposal, database, project_id, upload_id)
        reader = DocumentReader(db, project_id, upload["document_id"], upload["parse_revision"],
                                title=upload["filename"], label="제안서")
        return reader, upload

    def read_proposal(project_id: str, upload_id: str, action):
        try:
            with connect(database) as db:
                reader, upload = proposal_reader(db, project_id, upload_id)
                return action(reader, upload)
        except ApiError as exc:
            require(False, exc.message, exc.code, exc.status)

    @app.get("/api/v2/projects/{project_id}/proposals/{upload_id}/preview")
    async def proposal_preview(project_id: str, upload_id: str, request: Request):
        await project(request, project_id)
        def overview(reader, upload):
            data = reader.overview()
            # PDF text lines often resemble headings, but do not form a reliable TOC.
            if upload["format"] == "PDF":
                data["toc"] = []
            data["upload_revision"] = upload["upload_revision"]
            data["format"] = upload["format"]
            return data
        return {"data": await asyncio.to_thread(read_proposal, project_id, upload_id, overview)}

    @app.get("/api/v2/projects/{project_id}/proposals/{upload_id}/preview/pages/{number}")
    async def proposal_preview_page(project_id: str, upload_id: str, number: int, request: Request):
        await project(request, project_id)
        def page(reader, _upload):
            data = reader.page(number)
            for block in data["blocks"]:
                if block["type"] == "image":
                    sha = block["src"].rsplit("/", 1)[-1]
                    block["src"] = (f"/api/v2/projects/{quote(project_id, safe='')}/proposals/"
                                    f"{quote(upload_id, safe='')}/preview/assets/{sha}")
            return data
        return {"data": await asyncio.to_thread(read_proposal, project_id, upload_id, page)}

    @app.get("/api/v2/projects/{project_id}/proposals/{upload_id}/preview/pages/{number}/svg")
    async def proposal_preview_svg(project_id: str, upload_id: str, number: int, request: Request):
        await project(request, project_id)
        svg = await asyncio.to_thread(read_proposal, project_id, upload_id,
                                      lambda reader, _upload: reader.page_svg(number))
        return Response(svg, media_type="image/svg+xml")

    @app.get("/api/v2/projects/{project_id}/proposals/{upload_id}/preview/pages/{number}/png")
    async def proposal_preview_png(project_id: str, upload_id: str, number: int, request: Request):
        await project(request, project_id)
        png = await asyncio.to_thread(read_proposal, project_id, upload_id,
                                      lambda reader, _upload: reader.page_png(number))
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/v2/projects/{project_id}/proposals/{upload_id}/preview/assets/{sha256}")
    async def proposal_preview_asset(project_id: str, upload_id: str, sha256: str, request: Request):
        await project(request, project_id)
        require(bool(re.fullmatch(r"[0-9a-f]{64}", sha256)), "그림을 찾을 수 없습니다.", "NOT_FOUND", 404)
        data, mime = await asyncio.to_thread(read_proposal, project_id, upload_id,
                                             lambda reader, _upload: reader.asset(sha256))
        return Response(data, media_type=mime)

    @app.delete("/api/v2/projects/{project_id}/proposals/{upload_id}")
    async def proposal_archive(project_id: str, upload_id: str, request: Request):
        await project(request, project_id, edit=True)
        with store.connect() as db:
            require(not db.execute(
                "SELECT 1 FROM evaluation_sessions WHERE project_id=? LIMIT 1",
                (project_id,)).fetchone(),
                "평가 회차가 연결된 문서는 삭제할 수 없습니다.", "DOCUMENT_IN_USE", 409)
        result = await asyncio.to_thread(run, document_gateway.delete_upload, database, project_id,
                                         proposal_upload_id=upload_id)
        with store.connect(write=True) as db:
            db.execute("DELETE FROM ref_proposal_uploads WHERE id=? AND project_id=?",
                       (upload_id, project_id))
            db.execute("DELETE FROM sync_inbox WHERE aggregate_id=? AND source='documents'",
                       (upload_id,))
            db.execute("DELETE FROM audit_events WHERE project_id=? AND entity_id=?",
                       (project_id, upload_id))
        return {"data": result}

    @app.delete("/api/v2/projects/{project_id}/rfp/{revision}")
    async def rfp_archive(project_id: str, revision: int, request: Request):
        await project(request, project_id, edit=True)
        with store.connect() as db:
            require(not db.execute(
                "SELECT 1 FROM evaluation_sessions WHERE project_id=? LIMIT 1",
                (project_id,)).fetchone(),
                "평가 회차가 연결된 문서는 삭제할 수 없습니다.", "DOCUMENT_IN_USE", 409)
        result = await asyncio.to_thread(run, document_gateway.delete_upload, database, project_id,
                                         upload_revision=revision)
        with store.connect(write=True) as db:
            bindings = [row[0] for row in db.execute(
                "SELECT id FROM ref_rfp_bindings WHERE project_id=? AND upload_revision=?",
                (project_id, revision))]
            for binding_id in bindings:
                versions = [row[0] for row in db.execute(
                    "SELECT id FROM ref_approved_criteria_versions WHERE rfp_binding_id=?",
                    (binding_id,))]
                for version_id in versions:
                    while db.execute(
                        "DELETE FROM ref_approved_criteria_items WHERE approved_criteria_version_id=? "
                        "AND id NOT IN (SELECT parent_id FROM ref_approved_criteria_items "
                        "WHERE parent_id IS NOT NULL)", (version_id,)).rowcount:
                        pass
                    db.execute("DELETE FROM ref_approved_criteria_versions WHERE id=?", (version_id,))
                    db.execute("DELETE FROM sync_inbox WHERE aggregate_id=? AND source='documents'",
                               (version_id,))
                    db.execute("DELETE FROM audit_events WHERE project_id=? AND entity_id=?",
                               (project_id, version_id))
                db.execute("DELETE FROM ref_rfp_bindings WHERE id=?", (binding_id,))
                db.execute("DELETE FROM audit_events WHERE project_id=? AND entity_id=?",
                           (project_id, binding_id))
        return {"data": result}

    # ---- MAT-01~03 결과 자료 ----
    async def material_scope(request: Request) -> list[dict]:
        person = await actor(request)
        store.admin(person, "MANAGE_DOCUMENTS")
        with store.connect("admin") as db:
            return rows(db, "SELECT p.id,p.name,p.department_id,p.status,d.name AS department_name "
                            "FROM projects p JOIN departments d ON d.id=p.department_id "
                            "WHERE p.deleted_at IS NULL AND (?='SUPER_ADMIN' OR p.department_id=?) ORDER BY p.created_at",
                        (person.role, person.department_id))

    @app.get("/api/v2/materials")
    async def materials(request: Request):
        projects = await material_scope(request)
        items = await asyncio.to_thread(material_service.list_materials, database, [p["id"] for p in projects])
        ids = {p["id"] for p in projects}
        with store.connect() as db:
            finalized = [s for s in rows(db, "SELECT id AS session_id,project_id,round_no,closed_at FROM evaluation_sessions "
                                             "WHERE status='FINALIZED' ORDER BY closed_at") if s["project_id"] in ids]
        with store.connect("admin") as db:
            vendors = {r["id"]: r for r in rows(db, "SELECT id,project_id,display_code,legal_name FROM project_vendors")}
        for item in items:
            vendor = vendors.get(item.get("vendor_id") or "")
            if vendor:
                item["display_code"], item["legal_name"] = vendor["display_code"], vendor["legal_name"]
        return {"data": {"projects": projects, "items": items, "results": finalized}}

    @app.post("/api/v2/projects/{project_id}/result-files")
    async def result_file_register(project_id: str, request: Request):
        row = await project(request, project_id)
        person = await actor(request)
        filename, data, fields = await read_upload(request, accept=MATERIAL_TYPES, label="결과 자료")
        saved = await asyncio.to_thread(run, material_service.register_result_file, database, project_id=project_id,
                                        project_name=row["name"], filename=filename, data=data,
                                        title=str(fields.get("title", "")),
                                        description=str(fields.get("description", "")) or None,
                                        uploaded_by=person.id)
        return JSONResponse({"data": saved}, status_code=201)

    @app.post("/api/v2/projects/{project_id}/result-files/{file_id}/revisions")
    async def result_file_revise(project_id: str, file_id: str, request: Request):
        await project(request, project_id)
        person = await actor(request)
        form = await request.form()
        file = form.get("file")
        filename = data = None
        if isinstance(file, UploadFile) and file.filename:
            filename = Path(file.filename.replace("\\", "/")).name
            require(filename.lower().endswith(MATERIAL_TYPES), "지원하지 않는 파일 형식입니다.", "INPUT_INVALID", 422)
            data = await file.read(MAX_FILE_SIZE + 1)
            await file.close()
            require(0 < len(data) <= MAX_FILE_SIZE, "50MB 이하의 파일을 올려 주세요.", "FILE_TOO_LARGE", 413)
        try:
            version = int(str(form.get("version", "")))
        except ValueError:
            version = -1
        require(version > 0, "version을 확인하세요.", "INPUT_INVALID", 422)
        saved = await asyncio.to_thread(run, material_service.revise_result_file, database, project_id=project_id,
                                        file_id=file_id, version=version, uploaded_by=person.id,
                                        description=str(form.get("description", "")) or None,
                                        filename=filename, data=data, title=str(form.get("title", "")) or None)
        return {"data": saved}

    @app.get("/api/v2/projects/{project_id}/result-files/{file_id}/download")
    async def result_file_download(project_id: str, file_id: str, request: Request):
        await project(request, project_id)
        item = await asyncio.to_thread(run, material_service.get_result_file, database, project_id, file_id)
        source = await asyncio.to_thread(document_gateway.view_source, database, item["source_sha256"])
        require(source is not None, "원본 파일을 찾을 수 없습니다.", "NOT_FOUND", 404)
        return attachment(source[1], item["filename"])
