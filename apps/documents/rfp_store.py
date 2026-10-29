"""2단계: 1단계 문서 JSON과 원본 HWPX를 SQLite에 저장한다.

테이블·저장 로직은 storage_documents.py가 소유한다. 이 파일은 유지보수용 단계
진입점이며 요구사항 AI 추출은 수행하지 않는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .storage_documents import save_to_sqlite

DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "server/data/database/documents_parse.sqlite3"


def save_document(document: dict, database: Path, *, source: Path | None = None,
                  asset_dir: Path | None = None, project_id: str | None = None,
                  project_name: str | None = None) -> dict:
    return save_to_sqlite(document, database, source_path=source, asset_root=asset_dir,
                          project_id=project_id, project_name=project_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="2단계: 문서 JSON과 원본을 SQLite에 저장")
    parser.add_argument("json_path", type=Path, help="1단계에서 생성한 JSON")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--source", type=Path, help="원본 HWPX")
    parser.add_argument("--asset-dir", type=Path, help="1단계 이미지 폴더")
    parser.add_argument("--project-id", help="문서를 연결할 사업 ID")
    parser.add_argument("--project-name", help="사업 이름")
    args = parser.parse_args()
    try:
        document = json.loads(args.json_path.read_text(encoding="utf-8"))
        assets = args.asset_dir or args.json_path.with_suffix(".assets")
        saved = save_document(document, args.database, source=args.source,
                              asset_dir=assets, project_id=args.project_id,
                              project_name=args.project_name)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"SQLite 저장 실패: {error}\n")
    print(json.dumps(saved, ensure_ascii=False))


if __name__ == "__main__":
    main()
