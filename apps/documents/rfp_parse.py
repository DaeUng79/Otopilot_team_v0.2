"""1단계: HWPX 원본을 문서 JSON으로 파싱한다.

핵심 파서 구현은 parser_hwpx.py에 두고, 서비스와 수동 실행의 단계 진입점을
이 파일로 통일한다. 이 단계는 SQLite를 수정하지 않는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .parser_hwpx import parse_hwpx


def parse_document(source: Path, *, asset_dir: Path | None = None) -> dict:
    return parse_hwpx(source, output_dir=asset_dir, strict_pagination=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="1단계: HWPX를 JSON으로 파싱")
    parser.add_argument("source", type=Path, help="원본 HWPX")
    parser.add_argument("--output-json", type=Path, required=True, help="저장할 JSON 파일")
    parser.add_argument("--asset-dir", type=Path, help="추출된 이미지 저장 폴더")
    args = parser.parse_args()
    if args.source.suffix.lower() != ".hwpx" or not args.source.is_file():
        parser.error("존재하는 HWPX 파일을 지정해 주세요.")
    assets = args.asset_dir or args.output_json.with_suffix(".assets")
    try:
        document = parse_document(args.source, asset_dir=assets)
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(1, f"파싱 실패: {error}\n")
    print(json.dumps({"json": str(args.output_json), "assets": str(assets),
                      "document_id": document["document_id"],
                      "blocks": len(document["blocks"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
