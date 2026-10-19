"""Local integrated web host. Explicit synthetic mode, no external API calls."""

import argparse
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from app.committee.committee_app.v2_web_demo import local_runtime
from app.shared.db import Store


async def setup(folder: Path, demo: bool, samples: Path | None) -> Store:
    runtime, _ = local_runtime(folder)
    store = Store(runtime, folder / "evaluation.sqlite3")
    await store.initialize()
    if demo:
        from app.shared.demo_data import seed

        await seed(store, samples)
    return store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Create isolated synthetic accounts and fixtures",
    )
    parser.add_argument(
        "--local-test-login",
        action="store_true",
        help="Prefill existing local test accounts without creating demo projects",
    )
    parser.add_argument("--port", type=int, default=5190)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--original-ui",
        action="store_true",
        default=True,
        help="Attach separate API bindings to immutable original design screens",
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/database")
    parser.add_argument("--samples", type=Path)
    parser.add_argument("--documents-db", type=Path, help="문서 파싱·원본 저장 SQLite 경로")
    args = parser.parse_args()
    store = asyncio.run(setup(args.data_dir.resolve(), args.demo, args.samples))
    import uvicorn
    from app.api.web_api import create_app

    uvicorn.run(
        create_app(store, demo=args.demo, local_test_login=args.local_test_login,
                   port=args.port, original_ui=args.original_ui,
                   documents_db=args.documents_db),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
