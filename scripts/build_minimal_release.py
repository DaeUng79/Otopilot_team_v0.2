"""Build a compact ZIP with the integrated service and its current test data."""

from __future__ import annotations

import sys
import sqlite3
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "simsa-service-minimal-2026-10-19.zip"
SOURCE_DIRS = (
    "apps/server/app",
    "apps/server/contracts",
    "apps/server/fixtures",
    "apps/server/migrations",
    "apps/documents",
    "apps/chatbot",
    "apps/web/src/runtime",
    "apps/web/src/screens",
    "apps/web/src/evaluator",
    "apps/web/src/bindings",
    "apps/web/public/fonts",
)
SOURCE_FILES = (
    "apps/server/run.py",
    "apps/server/requirements.txt",
    "apps/web/public/index.html",
    "start_service.py",
    "start_simsa_v2.py",
    "start_simsa_v2.cmd",
    "README.MD",
    "apps/server/data/database/keys.bin",
    "apps/server/data/database/access-code.txt",
    "apps/server/data/database/sample-manifest.json",
)
DATABASE_FILES = (
    "apps/server/data/database/admin.sqlite3",
    "apps/server/data/database/evaluation.sqlite3",
    "apps/server/data/database/documents_parse.sqlite3",
    "apps/server/data/database/projects_delete.sqlite3",
)
EXCLUDED_NAMES = {".DS_Store", "__pycache__", "node_modules", ".venv"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".md", ".map"}

PACKAGE_README = """# 심사 서비스 테스트 DB 포함 실행 안내

서비스 코드, 화면 파일, 현재 테스트용 SQLite DB 4개, keys.bin,
access-code.txt가 포함되어 있습니다. 테스트 코드, 과거 백업,
환경변수 파일, 별도 샘플 문서 폴더는 포함하지 않았습니다.
Railway 볼륨의 기존 /data는 코드 압축본을 배포해도 자동으로 바뀌지
않습니다. DB와 키를 배포할 때는 README.MD의 Railway 안내를 따르세요.

프로젝트 루트에서 Python 3.13으로 실행합니다.

macOS:

    python3 -m venv .venv
    .venv/bin/python -m pip install -r apps/server/requirements.txt
    .venv/bin/python start_service.py --port 5190

Windows PowerShell:

    py -3.13 -m venv .venv
    .venv\\Scripts\\python.exe -m pip install -r apps/server/requirements.txt
    .venv\\Scripts\\python.exe start_service.py --port 5190

브라우저에서 http://127.0.0.1:5190/ 을 엽니다. 포함된 테스트 DB를
그대로 사용하므로 --demo를 붙이지 마세요. 자세한 데이터 경로와
Railway 설정은 README.MD의 실행 안내를 참고하세요.
"""


def included(path: Path) -> bool:
    if path.as_posix() == "README.MD":
        return True
    if any(part in EXCLUDED_NAMES for part in path.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name.startswith(".env"):
        return False
    return True


def main() -> int:
    files = {ROOT / rel for rel in SOURCE_FILES}
    for directory in SOURCE_DIRS:
        files.update(path for path in (ROOT / directory).rglob("*") if path.is_file())
    files = {path for path in files if path.is_file() and included(path.relative_to(ROOT))}
    with tempfile.TemporaryDirectory(prefix="simsa-db-snapshot-") as temp_dir:
        snapshots = []
        for rel in DATABASE_FILES:
            source = ROOT / rel
            target = Path(temp_dir) / source.name
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original:
                if original.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"DB integrity check failed: {rel}")
                with sqlite3.connect(target) as copy:
                    original.backup(copy)
            snapshots.append((target, rel))
        with zipfile.ZipFile(DEST, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(files):
                archive.write(path, path.relative_to(ROOT).as_posix())
            for path, rel in snapshots:
                archive.write(path, rel)
            archive.writestr("PACKAGE_README.MD", PACKAGE_README)
    print(f"{DEST} ({DEST.stat().st_size / 1024 / 1024:.2f} MiB; {len(files) + len(DATABASE_FILES) + 1} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
