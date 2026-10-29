"""Local integrated web host."""

import argparse
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from app.committee.committee_app.v2_local_runtime import local_runtime
from app.shared.db import Store
from app.admin.auth_service import password_hash
from app.admin.project_service import _attach_deleted_database
from app.committee.committee_app.v2_core import now


async def setup(folder: Path) -> Store:
    runtime, _ = local_runtime(folder)
    store = Store(runtime, folder / "evaluation.sqlite3")
    await store.initialize()
    with store.connect("admin", True) as c:
        if not c.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
            timestamp = now()
            c.execute(
                "INSERT INTO admin_users "
                "(id,created_at,updated_at,version,department_id,username,password_hash,role,display_name,active,password_changed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("superadmin", timestamp, timestamp, 1, None, "superadmin",
                 password_hash("superadmin"), "SUPER_ADMIN", "총괄관리자", 1, timestamp),
            )
            c.execute(
                "INSERT INTO admin_password_requirements(admin_id,must_change) VALUES (?,1)",
                ("superadmin",),
            )
    with store.connect("admin") as c:
        _attach_deleted_database(c, store)
    return store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5190)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--original-ui",
        action="store_true",
        default=True,
        help="Attach separate API bindings to immutable original design screens",
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/database")
    parser.add_argument("--documents-db", type=Path, help="문서 파싱·원본 저장 SQLite 경로")
    args = parser.parse_args()
    store = asyncio.run(setup(args.data_dir.resolve()))
    import uvicorn
    from app.api.web_api import create_app

    uvicorn.run(
        create_app(store, port=args.port, original_ui=args.original_ui,
                   documents_db=args.documents_db),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
