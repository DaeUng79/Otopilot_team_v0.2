"""Authenticated RFP upload and read routes for the integrated service."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile

from app.committee.committee_app.v2_core import digest, now
from app.documents.hwpx_parser import parse_hwpx
from app.documents.hwpx_storage import SCHEMA, connect, save_to_sqlite
from app.evaluation.documents.envelope import ApiError
from app.evaluation.documents.rfp_adapter import RfpReader
from app.shared.db import require
from app.shared.sync_service import ref

MAX_FILE_SIZE = 50 * 1024 * 1024
UPLOAD_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_rfp_uploads (
 project_id TEXT NOT NULL, revision INTEGER NOT NULL,
 document_id TEXT NOT NULL REFERENCES documents(document_id),
 filename TEXT NOT NULL, byte_size INTEGER NOT NULL, uploaded_at TEXT NOT NULL,
 page_count INTEGER NOT NULL, block_count INTEGER NOT NULL,
 warning_count INTEGER NOT NULL, PRIMARY KEY(project_id,revision));
CREATE TABLE IF NOT EXISTS rfp_snapshot_bindings (
 project_id TEXT NOT NULL, upload_revision INTEGER NOT NULL,
 document_id TEXT NOT NULL, parse_revision TEXT NOT NULL,
 bound_at TEXT NOT NULL, binding_source TEXT NOT NULL,
 PRIMARY KEY(project_id,upload_revision),
 FOREIGN KEY(project_id,upload_revision)
 REFERENCES project_rfp_uploads(project_id,revision),
 FOREIGN KEY(document_id,parse_revision)
 REFERENCES parse_snapshots(document_id,revision));
"""


def resolve_database(configured: Path | None) -> Path:
    from app.evaluation.documents.settings import REPO_ROOT
    path = configured or os.environ.get("EVAL_DOCUMENTS_DB_PATH")
    result = Path(path) if path else REPO_ROOT / "apps/documents/documents_parse.sqlite3"
    return result if result.is_absolute() else REPO_ROOT / result


def _initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript(SCHEMA + UPLOAD_SCHEMA)


def _uploads(path: Path, project_id: str) -> list[dict]:
    if not path.is_file():
        return []
    with connect(path) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_rfp_uploads'"
        ).fetchone():
            return []
        bound = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rfp_snapshot_bindings'"
        ).fetchone()
        binding = ("LEFT JOIN rfp_snapshot_bindings b ON "
                   "b.project_id=u.project_id AND b.upload_revision=u.revision "
                   if bound else "")
        revision = "b.parse_revision" if bound else "NULL AS parse_revision"
        return [dict(row) for row in db.execute(
            "SELECT u.revision,u.document_id,u.filename,u.byte_size,u.uploaded_at,"
            "u.page_count,u.block_count,u.warning_count," + revision + " "
            "FROM project_rfp_uploads u " + binding +
            "WHERE u.project_id=? ORDER BY u.revision DESC", (project_id,))]


def _latest_uploads(path: Path) -> list[dict]:
    """Return the latest registered RFP for each project."""
    if not path.is_file():
        return []
    with connect(path) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_rfp_uploads'"
        ).fetchone():
            return []
        return [dict(row) for row in db.execute(
            "SELECT u.project_id,u.revision,u.filename,u.byte_size,u.uploaded_at "
            "FROM project_rfp_uploads u WHERE u.revision=("
            "SELECT MAX(revision) FROM project_rfp_uploads "
            "WHERE project_id=u.project_id) ORDER BY u.project_id"
        )]


def _save(path: Path, project_id: str, project_name: str,
          filename: str, data: bytes) -> dict:
    _initialize(path)
    with tempfile.TemporaryDirectory(prefix="simsa-rfp-") as directory:
        source = Path(directory) / filename
        source.write_bytes(data)
        parsed = parse_hwpx(source, output_dir=Path(directory) / "assets",
                            strict_pagination=False)
        saved = save_to_sqlite(parsed, path, source_path=source,
                               project_id=project_id, project_name=project_name)
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        revision = db.execute(
            "SELECT COALESCE(MAX(revision),0)+1 FROM project_rfp_uploads WHERE project_id=?",
            (project_id,)).fetchone()[0]
        db.execute(
            "INSERT INTO project_rfp_uploads VALUES (?,?,?,?,?,?,?,?,?)",
            (project_id, revision, saved["document_id"], filename, len(data), now(),
             saved["pages"], saved["blocks"], len(parsed.get("warnings", []))),
        )
        db.execute(
            "INSERT INTO rfp_snapshot_bindings VALUES (?,?,?,?,?,?)",
            (project_id, revision, saved["document_id"], saved["revision"],
             now(), "UPLOAD_RETURN"),
        )
    return _uploads(path, project_id)[0]


def _parsed(path: Path, row: dict) -> dict:
    require(row.get("parse_revision"), "파싱 버전이 연결되지 않았습니다.", "NOT_FOUND", 404)
    with connect(path) as db:
        record = db.execute(
            "SELECT document_json FROM parse_snapshots WHERE document_id=? AND revision=?",
            (row["document_id"], row["parse_revision"]),
        ).fetchone()
    require(record, "파싱 원문을 찾을 수 없습니다.", "NOT_FOUND", 404)
    document = json.loads(record[0])
    visible = []
    for block in document.get("blocks", []):
        if block.get("parent_block_id") or block.get("type") not in {"paragraph", "table"}:
            continue
        item = {"type": block["type"], "pages": block.get("physical_page_numbers", [])}
        if block["type"] == "paragraph":
            item["text"] = block.get("text", "")
        else:
            item["rows"] = [[{"text": cell.get("text", ""),
                              "row_span": cell.get("row_span", 1),
                              "col_span": cell.get("col_span", 1)}
                             for cell in cells]
                            for cells in block.get("table", {}).get("cells", [])]
        visible.append(item)
    return {"filename": row["filename"], "revision": row["revision"],
            "warnings": document.get("warnings", []), "blocks": visible}


def install_project_document_routes(app, store, actor, sync, *, documents_db=None):
    database = resolve_database(documents_db)

    @app.get("/api/v2/admin/rfp-summary")
    async def admin_rfp_summary(request: Request):
        person = await actor(request)
        store.admin(person, "MANAGE_PROJECTS")
        require(person.role == "SUPER_ADMIN", "총괄관리자 권한이 필요합니다.", "FORBIDDEN", 403)
        return {"data": {"uploads": await asyncio.to_thread(_latest_uploads, database)}}

    async def project(request: Request, project_id: str, edit: bool = False) -> dict:
        person = await actor(request)
        store.admin(person, "MANAGE_DOCUMENTS", project_id)
        with store.connect("admin") as db:
            row = db.execute(
                "SELECT id,name,status,deleted_at FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        require(row is not None and row["deleted_at"] is None,
                "사업을 찾을 수 없습니다.", "NOT_FOUND", 404)
        if edit:
            require(row["status"] in {"DRAFT", "PREPARING", "READY"},
                    "평가 시작 후 문서를 변경할 수 없습니다.", "PROJECT_LOCKED", 409)
            with store.connect() as db:
                require(not db.execute(
                    "SELECT 1 FROM evaluation_sessions WHERE project_id=? AND status<>'CANCELLED'",
                    (project_id,)).fetchone(),
                    "평가 회차가 준비되어 문서를 변경할 수 없습니다.",
                    "PROJECT_LOCKED", 409)
        return dict(row)

    @app.get("/api/v2/projects/{project_id}/rfp")
    async def list_rfp(project_id: str, request: Request):
        await project(request, project_id)
        return {"data": {"uploads": await asyncio.to_thread(_uploads, database, project_id)}}

    def preview_reader(db, project_id: str, revision: int | None) -> tuple[RfpReader, dict]:
        upload = next((item for item in _uploads(database, project_id)
                       if revision is None or item["revision"] == revision), None)
        require(upload is not None and upload.get("parse_revision"),
                "등록된 제안요청서가 없습니다.", "NOT_FOUND", 404)
        return RfpReader(db, project_id, upload), upload

    def read_preview(project_id: str, action, revision: int | None = None):
        try:
            with connect(database) as db:
                reader, upload = preview_reader(db, project_id, revision)
                return action(reader, upload)
        except ApiError as exc:
            require(False, exc.message, exc.code, exc.status)

    @app.get("/api/v2/projects/{project_id}/rfp/preview")
    async def rfp_preview(project_id: str, request: Request):
        row = await project(request, project_id)
        def overview(reader, upload):
            data = reader.overview()
            data["project"] = {"id": project_id, "name": row["name"]}
            data["document"]["title"] = f"{row['name']} 제안요청서"
            data["upload_revision"] = upload["revision"]
            return data
        return {"data": await asyncio.to_thread(read_preview, project_id, overview)}

    @app.get("/api/v2/projects/{project_id}/rfp/preview/pages/{number}")
    async def rfp_preview_page(project_id: str, number: int, request: Request,
                               revision: int | None = None):
        await project(request, project_id)
        def page(reader, upload):
            data = reader.page(number)
            for block in data["blocks"]:
                if block["type"] == "image":
                    sha = block["src"].rsplit("/", 1)[-1]
                    block["src"] = (f"/api/v2/projects/{quote(project_id, safe='')}/rfp/preview/assets/{sha}"
                                    f"?revision={upload['revision']}")
            return data
        return {"data": await asyncio.to_thread(read_preview, project_id, page, revision)}

    @app.get("/api/v2/projects/{project_id}/rfp/preview/assets/{sha256}")
    async def rfp_preview_asset(project_id: str, sha256: str, request: Request,
                                revision: int | None = None):
        await project(request, project_id)
        require(re.fullmatch(r"[0-9a-f]{64}", sha256), "그림을 찾을 수 없습니다.", "NOT_FOUND", 404)
        data, mime = await asyncio.to_thread(
            read_preview, project_id, lambda reader, _upload: reader.asset(sha256), revision)
        return Response(data, media_type=mime)

    @app.post("/api/v2/projects/{project_id}/rfp")
    async def upload_rfp(project_id: str, request: Request):
        row = await project(request, project_id, edit=True)
        await sync()
        form = await request.form()
        file = form.get("file")
        require(isinstance(file, UploadFile), "HWPX 파일을 선택하세요.", "INPUT_INVALID", 422)
        filename = Path((file.filename or "").replace("\\", "/")).name
        require(bool(filename) and filename.lower().endswith(".hwpx")
                and len(filename) <= 255, "HWPX 파일만 올릴 수 있습니다.", "INPUT_INVALID", 422)
        data = await file.read(MAX_FILE_SIZE + 1)
        await file.close()
        require(0 < len(data) <= MAX_FILE_SIZE,
                "50MB 이하의 HWPX 파일을 올려 주세요.", "FILE_TOO_LARGE", 413)
        require(zipfile.is_zipfile(io.BytesIO(data)),
                "올바른 HWPX 파일이 아닙니다.", "INPUT_INVALID", 422)
        try:
            upload = await asyncio.to_thread(
                _save, database, project_id, row["name"], filename, data)
        except (ValueError, zipfile.BadZipFile, ET.ParseError):
            require(False, "HWPX 문서 구조를 확인하세요.", "INPUT_INVALID", 422)
        except Exception:
            logging.getLogger(__name__).exception("RFP parse or storage failed")
            require(False, "문서를 파싱하거나 저장하지 못했습니다.", "DOCUMENT_SAVE_FAILED", 500)
        # The evaluator reader uses a fixed binding in the evaluation DB.
        binding = {"project_id": project_id, "upload_revision": upload["revision"],
                   "document_id": upload["document_id"],
                   "parse_revision": upload["parse_revision"]}
        with store.connect(write=True) as db:
            ref(db, "ref_rfp_bindings", binding | {"id": digest(binding)},
                upload["revision"])
        return JSONResponse({"data": upload}, status_code=201)

    @app.get("/api/v2/projects/{project_id}/rfp/{revision}/source")
    async def rfp_source(project_id: str, revision: int, request: Request):
        await project(request, project_id)
        upload = next((u for u in await asyncio.to_thread(_uploads, database, project_id)
                       if u["revision"] == revision), None)
        require(upload is not None, "등록된 문서가 없습니다.", "NOT_FOUND", 404)
        return {"data": await asyncio.to_thread(_parsed, database, upload)}

    @app.get("/api/v2/projects/{project_id}/rfp/{revision}/download")
    async def rfp_download(project_id: str, revision: int, request: Request):
        await project(request, project_id)
        upload = next((u for u in await asyncio.to_thread(_uploads, database, project_id)
                       if u["revision"] == revision), None)
        require(upload is not None, "등록된 문서가 없습니다.", "NOT_FOUND", 404)
        with connect(database) as db:
            source = db.execute("SELECT data FROM source_files WHERE sha256=?",
                                (upload["document_id"],)).fetchone()
        require(source is not None, "원본 파일을 찾을 수 없습니다.", "NOT_FOUND", 404)
        return Response(bytes(source[0]), media_type="application/octet-stream",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''"
                                 + quote(upload["filename"])})
