"""COM-02..04: bounded XLSX preview, encrypted staging and atomic commit."""

import asyncio
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.committee.candidate_pool import _contacts, _insert
from app.committee.committee_app.errors import DomainError
from app.committee.committee_app.excel import read_candidates
from app.committee.committee_app.v2_contracts import CandidateCreate, CommitImport, Preview
from app.committee.committee_app.v2_core import (
    DTO,
    Context,
    ExportFile,
    ModuleError,
    Runtime,
    now,
    packed,
    validate,
    version,
)
from app.committee.committee_app.v2_excel import export_xlsx

HEADERS = ["성명", "소속", "부서", "직위", "전문분야", "휴대전화", "이메일"]
MAPPING = dict(
    zip(
        HEADERS,
        [
            "name",
            "organization_name",
            "department_name",
            "position",
            "specialty_ids",
            "phone",
            "email",
        ],
        strict=True,
    )
)


async def download_template(ctx: Context, command: DTO, *, runtime: Runtime) -> ExportFile:
    if command:
        raise ModuleError("INPUT_INVALID", "서식 다운로드에는 입력값이 필요하지 않습니다.", 422)
    await runtime.run(ctx, "COM-02", {}, lambda c: {}, write=False)
    return export_xlsx("committee-template.xlsx", HEADERS, [])


async def preview_import(
    ctx: Context, command: DTO, *, raw: bytes, password: str = "", runtime: Runtime
) -> DTO:
    body = validate(Preview, command)

    # Authenticate before decompressing or parsing untrusted spreadsheet bytes.
    def check(conn: sqlite3.Connection) -> DTO:
        runtime.authorize(conn, ctx, body.department_id)
        if body.project_id:
            project = runtime.project(conn, ctx, body.project_id, edit=True)
            runtime.unlocked(conn, body.project_id)
            if project["department_id"] != body.department_id:
                raise ModuleError("FORBIDDEN", "사업과 등록 부서가 다릅니다.", 403)
            rule = conn.execute(
                "SELECT selection_mode FROM committee_rules WHERE project_id=?", (body.project_id,)
            ).fetchone()
            if rule is None or rule[0] != "DIRECT":
                raise ModuleError("DIRECT_REQUIRED", "사업별 직접 등록 방식을 먼저 설정하세요.")
        return {}

    await runtime.run(ctx, "COM-03-AUTH", body.model_dump(), check, write=False)
    try:
        parsed = await asyncio.to_thread(
            read_candidates, raw, password, body.filename, strict=False
        )
    except DomainError as exc:
        raise ModuleError("FILE_INVALID", exc.message, 422) from exc
    sha = hashlib.sha256(raw).hexdigest()

    def preview(conn: sqlite3.Connection) -> DTO:
        check(conn)
        aliases: dict[str, str] = {}
        for row in conn.execute("SELECT * FROM specialties WHERE active=1"):
            for alias in [row["id"], row["code"], row["name"], *json.loads(row["aliases_json"])]:
                label = str(alias).strip().casefold()
                if label in aliases and aliases[label] != row["id"]:
                    raise ModuleError("CATALOG_AMBIGUOUS", "전문분야 별칭이 중복되어 있습니다.")
                aliases[label] = row["id"]
        seen: set[str] = set()
        rows, locations, errors = [], [], []
        for source in parsed:
            location = {"sheet": source["source_sheet"], "row": source["source_row"]}
            try:
                fields = [
                    f.strip()
                    for f in re.split(r"[,，;；\n]+", source.get("specialty", ""))
                    if f.strip()
                ]
                if any(f.casefold() not in aliases for f in fields):
                    raise ModuleError(
                        "SPECIALTY_UNKNOWN", "등록된 전문분야 이름 또는 코드를 사용하세요.", 422
                    )
                value = validate(
                    CandidateCreate,
                    {
                        "department_id": body.department_id,
                        "scope": body.scope,
                        "project_id": body.project_id,
                        "name": source.get("name", ""),
                        "organization_name": source.get("organization", ""),
                        "department_name": source.get("department") or None,
                        "position": source.get("position") or None,
                        "phone": source.get("phone", ""),
                        "email": source.get("email") or None,
                        "specialty_ids": sorted({aliases[f.casefold()] for f in fields}),
                    },
                )
                phone, email = _contacts(value.phone, value.email)
                key = runtime.lookup("phone", body.department_id, phone)
                if (
                    key in seen
                    or conn.execute(
                        "SELECT 1 FROM evaluator_candidates WHERE department_id=? AND "
                        "phone_lookup_hmac=?",
                        (body.department_id, key),
                    ).fetchone()
                ):
                    raise ModuleError(
                        "DUPLICATE_PHONE", "파일 또는 부서 명부에 동일한 휴대전화가 있습니다.", 422
                    )
                seen.add(key)
                rows.append(value.model_dump() | {"phone": phone, "email": email})
                locations.append(location)
            except ModuleError as exc:
                # 거른 줄도 미리보기 표에 그 줄 그대로 보이도록 입력값을 함께 준다 (2026-10-18).
                # 휴대전화는 뒷자리 4개만, 이메일은 있고 없음만. 등록 여부에는 영향이 없다(can_commit = 오류 없음).
                digits = re.sub(r"\D", "", str(source.get("phone", "") or ""))
                errors.append(
                    location
                    | {
                        "code": exc.code,
                        "message": exc.message,
                        "name": str(source.get("name", "") or ""),
                        "organization": str(source.get("organization", "") or ""),
                        "department": str(source.get("department") or ""),
                        "position": str(source.get("position") or ""),
                        "specialty": str(source.get("specialty", "") or ""),
                        "phone": ("***-****-" + digits[-4:]) if len(digits) >= 4 else "",
                        "email": "***" if source.get("email") else None,
                    }
                )
        pid = str(uuid4())
        expiry = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        runtime.insert(
            conn,
            "candidate_imports",
            {
                "id": pid,
                "department_id": body.department_id,
                "project_id": body.project_id,
                "scope": body.scope,
                "source_sha256": sha,
                "column_mapping_json": packed(MAPPING),
                "preview_cipher": runtime.encrypt(
                    packed({"rows": rows, "errors": errors}), pid + ":preview"
                ),
                "status": "PREVIEW",
                "expires_at": expiry,
                "created_by": ctx.actor_id,
            },
        )
        runtime.audit(conn, ctx, "COM-03", "candidate_imports", pid, body.project_id)
        return {
            "id": pid,
            "version": 1,
            "total": len(parsed),
            "valid_count": len(rows),
            "errors": errors,
            "can_commit": not errors,
            "expires_at": expiry,
            # 정상 줄에도 엑셀 위치(sheet·row)를 붙여 화면이 거른 줄과 함께 행 순서대로 보여 줄 수 있게 한다.
            "items": [
                r
                | location
                | {"phone": "***-****-" + r["phone"][-4:], "email": "***" if r["email"] else None}
                for r, location in zip(rows, locations, strict=True)
            ],
        }

    return await runtime.run(ctx, "COM-03", body.model_dump() | {"source_sha256": sha}, preview)


async def commit_import(ctx: Context, command: DTO, *, runtime: Runtime) -> DTO:
    body = validate(CommitImport, command)

    def commit(conn: sqlite3.Connection) -> DTO:
        row = conn.execute(
            "SELECT * FROM candidate_imports WHERE id=?", (body.preview_id,)
        ).fetchone()
        if row is None:
            raise ModuleError("NOT_FOUND", "등록 미리보기를 찾을 수 없습니다.", 404)
        runtime.authorize(conn, ctx, row["department_id"])
        if row["created_by"] != ctx.actor_id:
            raise ModuleError("FORBIDDEN", "미리보기를 생성한 관리자만 확정할 수 있습니다.", 403)
        version(row, body.version)
        if row["status"] != "PREVIEW" or row["expires_at"] < now():
            raise ModuleError("PREVIEW_EXPIRED", "이미 처리되었거나 만료된 미리보기입니다.")
        data = json.loads(runtime.decrypt(row["preview_cipher"], body.preview_id + ":preview"))
        if data["errors"]:
            raise ModuleError(
                "IMPORT_ERRORS", "엑셀의 오류를 모두 수정한 뒤 다시 미리보기 하세요.", 422
            )
        ids = [
            _insert(conn, ctx, runtime, validate(CandidateCreate, item))["id"]
            for item in data["rows"]
        ]
        conn.execute(
            "UPDATE candidate_imports SET "
            "status='COMMITTED',committed_at=?,updated_at=?,version=version+1 "
            "WHERE id=?",
            (now(), now(), body.preview_id),
        )
        runtime.audit(conn, ctx, "COM-04", "candidate_imports", body.preview_id, row["project_id"])
        return {
            "id": body.preview_id,
            "version": body.version + 1,
            "status": "COMMITTED",
            "candidate_ids": ids,
            "count": len(ids),
        }

    return await runtime.run(ctx, "COM-04", body.model_dump(), commit)
