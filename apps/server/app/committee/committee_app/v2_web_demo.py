"""Isolated local fixtures; never import mock users as authenticated admins."""

import secrets
from pathlib import Path
from uuid import uuid4

from app.committee import candidate_pool

from .v2_core import Context, Runtime, now


async def seed_demo(runtime: Runtime) -> None:
    await runtime.initialize(development_parents=True)
    with runtime.connect(write=True) as conn:
        if conn.execute(
            "SELECT 1 FROM idempotency_records WHERE operation='WEB-DEMO-SEED'"
        ).fetchone():
            return
        if not conn.execute("SELECT 1 FROM departments WHERE id='web-demo-dept'").fetchone():
            runtime.insert(
                conn,
                "departments",
                {
                    "id": "web-demo-dept",
                    "organization_name": "가상기관",
                    "name": "시연 부서",
                    "code": "WEB-DEMO",
                    "active": 1,
                },
            )
            runtime.insert(
                conn,
                "admin_users",
                {
                    "id": "web-demo-admin",
                    "department_id": "web-demo-dept",
                    "username": "web-demo",
                    "password_hash": "not-a-shared-login-account",
                    "role": "DEPARTMENT_ADMIN",
                    "display_name": "시연 관리자",
                    "active": 1,
                    "password_changed_at": now(),
                },
            )
            for pid, name in [
                ("p1", "시연사업 1 · 분야별 3배수"),
                ("p2", "시연사업 2 · 직접 등록"),
            ]:
                runtime.insert(
                    conn,
                    "projects",
                    {
                        "id": pid,
                        "department_id": "web-demo-dept",
                        "name": name,
                        "contact_organization": "가상기관",
                        "contact_department": "시연 부서",
                        "contact_position": "가상직책",
                        "contact_name": "가상담당자",
                        "contact_phone_cipher": runtime.encrypt("01000000000", pid + ":phone"),
                        "status": "PREPARING",
                        "created_by": "web-demo-admin",
                    },
                )
            for sid, name in [("AI", "인공지능"), ("SEC", "정보보안"), ("SYS", "시스템 운영")]:
                runtime.insert(
                    conn,
                    "specialties",
                    {
                        "id": sid,
                        "code": sid,
                        "name": name,
                        "aliases_json": "[]",
                        "active": 1,
                    },
                )
    for i in range(1, 28):
        phone = f"010{i:08d}"
        with runtime.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM evaluator_candidates WHERE department_id=? AND phone_lookup_hmac=?",
                ("web-demo-dept", runtime.lookup("phone", "web-demo-dept", phone)),
            ).fetchone()
        if not exists:
            await candidate_pool.create_candidate(
                Context("web-demo-admin", str(uuid4())),
                {
                    "department_id": "web-demo-dept",
                    "name": f"가상위원{i:02d}",
                    "organization_name": "가상소속",
                    "phone": phone,
                    "specialty_ids": ["AI" if i <= 12 else "SEC" if i <= 21 else "SYS"],
                },
                runtime=runtime,
            )
    await runtime.run(
        Context("web-demo-admin", "seed-once"), "WEB-DEMO-SEED", {}, lambda c: {"seeded": True}
    )


def local_runtime(folder: Path) -> tuple[Runtime, str]:
    """Preserve keys across restarts. Never replace keys for an existing DB."""
    folder.mkdir(parents=True, exist_ok=True)
    key_file, db_path = folder / "keys.bin", folder / "admin.sqlite3"
    if not key_file.exists():
        if db_path.exists():
            raise ValueError("Existing demo DB has no key file. Restore its original keys.")
        with key_file.open("xb") as stream:
            stream.write(secrets.token_bytes(96))
        key_file.chmod(0o600)
    keys = key_file.read_bytes()
    if len(keys) != 96:
        raise ValueError("Invalid local key file")
    access_file = folder / "access-code.txt"
    if not access_file.exists():
        with access_file.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
        access_file.chmod(0o600)
    return Runtime(db_path, pii_key=keys[:32], lookup_key=keys[32:64], auth_key=keys[64:]), (
        access_file.read_text(encoding="utf-8").strip()
    )
