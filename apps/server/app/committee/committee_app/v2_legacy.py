"""Explicit, non-destructive legacy pool migration; never infer project ID mappings.

Old draws, contacts, assignments and login data remain in the original DB. They do
not meet v2 rules and cannot be silently re-labelled as v2 confirmed evidence.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.committee.candidate_pool import _contacts, _insert, _specialties

from .v2_contracts import CandidateCreate
from .v2_core import DTO, Context, ModuleError, Runtime, digest, validate


async def migrate_legacy_pool(
    ctx: Context,
    *,
    source: Path,
    department_id: str,
    specialty_map: dict[str, str],
    runtime: Runtime,
    expected_sha256: str | None = None,
) -> DTO:
    """No expected hash = inspect only. Passing the returned hash explicitly imports.

    Preserve candidate IDs. Any invalid row or collision rolls back the whole batch.
    Explicit alias mapping prevents accidental category merging.
    """
    if source.resolve() == runtime.path:
        raise ModuleError("LEGACY_TARGET", "원본과 새 DB는 다른 파일이어야 합니다.", 422)

    def read_source(conn: sqlite3.Connection) -> DTO:
        runtime.authorize(conn, ctx, department_id)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as old:
            old.row_factory = sqlite3.Row
            try:
                rows = [
                    dict(r)
                    for r in old.execute(
                        "SELECT id,payload,active,phone,version FROM candidates ORDER BY id"
                    )
                ]
            except sqlite3.DatabaseError as exc:
                raise ModuleError(
                    "LEGACY_FORMAT", "지원하는 기존 후보 DB 형식이 아닙니다.", 422
                ) from exc
        fingerprint = digest(rows)
        commands, errors = [], []
        seen: set[str] = set()
        for row in rows:
            try:
                item = json.loads(row["payload"])
                if not isinstance(item, dict):
                    raise ValueError("Legacy payload must be an object")
                fields = item.get("fields", [])
                if any(f not in specialty_map for f in fields):
                    raise ModuleError(
                        "SPECIALTY_UNKNOWN", "기존 전문분야와 새 코드의 대응이 필요합니다.", 422
                    )
                command = validate(
                    CandidateCreate,
                    {
                        "department_id": department_id,
                        "name": item.get("name", ""),
                        "organization_name": item.get("organization", ""),
                        "department_name": item.get("department") or None,
                        "position": item.get("position") or None,
                        "phone": row["phone"] or "",
                        "email": item.get("email") or None,
                        "specialty_ids": sorted({specialty_map[f] for f in fields}),
                    },
                )
                if not row["active"]:
                    raise ModuleError(
                        "LEGACY_INACTIVE",
                        "비활성·불완전 후보는 원본에서 검토 후 별도 이전하세요.",
                        422,
                    )
                phone, _ = _contacts(command.phone, command.email)
                _specialties(conn, command.specialty_ids)
                phone_key = runtime.lookup("phone", department_id, phone)
                if (
                    phone_key in seen
                    or conn.execute(
                        "SELECT 1 FROM evaluator_candidates WHERE id=? OR "
                        "(department_id=? AND phone_lookup_hmac=?)",
                        (row["id"], department_id, phone_key),
                    ).fetchone()
                ):
                    raise ModuleError("LEGACY_CONFLICT", "후보 ID 또는 휴대전화가 중복됩니다.")
                seen.add(phone_key)
                commands.append((row["id"], command))
            except (ModuleError, ValueError, TypeError) as exc:
                errors.append(
                    {
                        "id": row["id"],
                        "code": exc.code if isinstance(exc, ModuleError) else "LEGACY_INVALID",
                    }
                )
        report: DTO = {
            "source_sha256": fingerprint,
            "source_count": len(rows),
            "valid_count": len(commands),
            "errors": errors,
            "imported_count": 0,
            "mode": "PREVIEW",
        }
        if expected_sha256 is None:
            return report
        if expected_sha256 != fingerprint:
            raise ModuleError("STALE_SOURCE", "미리보기 이후 기존 후보 자료가 변경되었습니다.")
        if errors:
            raise ModuleError("LEGACY_INVALID", "미리보기 오류를 해결해야 이전할 수 있습니다.", 422)
        for cid, value in commands:
            _insert(conn, ctx, runtime, value, candidate_id=cid)
        runtime.audit(conn, ctx, "LEGACY-IMPORT", "evaluator_candidates", fingerprint)
        return report | {"mode": "IMPORTED", "imported_count": len(commands)}

    return await runtime.run(
        ctx,
        "LEGACY-IMPORT",
        {
            "department_id": department_id,
            "source": str(source.resolve()),
            "specialty_map": specialty_map,
            "source_sha256": expected_sha256,
        },
        read_source,
        write=expected_sha256 is not None,
    )
