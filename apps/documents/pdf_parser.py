"""연결용 신규 파서 · 오대웅(DaeUng79) 문서 모듈 검토 대상.

PDF 제안서를 hwpx_parser와 같은 문서 JSON 모양으로 바꾼다. 결과는 그대로
`hwpx_storage.save_to_sqlite`에 넣을 수 있고, 평가 화면의 DocumentReader와
step3 요구사항 추출(compact_blocks)이 그대로 읽는다.

- 물리 페이지 1장 = PDF 페이지 1장. 인쇄 쪽번호는 읽지 않으므로 page_number도 물리 번호다.
- 글자만 뽑는다(pypdf, 없으면 PyMuPDF). 표·그림은 추출하지 않고 warnings에 한 번 남긴다.
- 빈 줄, 또는 번호·글머리표로 시작하는 줄을 새 문단의 시작으로 본다.
  짧은 제목 줄(40자 이하)은 다음 줄과 합치지 않고 혼자 문단이 된다. 평가 화면 목차는
  `숫자. 제목` 꼴의 짧은 문단에서 뽑기 때문이다(rfp_adapter.DocumentReader.overview).

이 모듈은 import 시점에 서드파티를 불러오지 않는다. PDF 라이브러리는 parse_pdf 안에서만 쓴다.
pptx_parser는 여기의 문서 뼈대·블록 생성 함수를 같이 쓴다.

예: python apps/documents/pdf_parser.py 제안서.pdf
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

try:
    from .hwpx_parser import SCHEMA_VERSION, add_table_context
except ImportError:  # 단독 실행 (apps/documents가 sys.path에 있을 때)
    from hwpx_parser import SCHEMA_VERSION, add_table_context

PDF_PARSER_VERSION = "pdf-text-1.0"
MAX_PDF_PAGES = 2000
MIN_TEXT_CHARS = 200          # 이보다 글자가 적으면 스캔·이미지 PDF로 본다
HEADING_MAX_CHARS = 40        # 이 길이 이하의 번호·글머리표 줄은 혼자 문단이 된다

# 새 문단을 여는 줄: "1." "1)" "(1)" "1.2" "가." "가)" "(가)" "Ⅰ." "IV." "①" "㉠" 글머리표.
_HEADING_START = re.compile(
    r"^(?:"
    r"\(?\d{1,3}(?:[.．)]|(?:\.\d{1,3})+)(?=\s|$|[가-힣A-Za-z(\[「『\"'])"  # 1. 1) (1) 1.2 — "3.5%"는 제외
    r"|\(?[가-힣][.．)]\s*"                       # 가. 가) (가)
    r"|\(?[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]+[.．)]?\s*"   # Ⅰ. Ⅱ) Ⅲ
    r"|\(?[IVX]{1,5}[.．)]\s+"                    # I. IV)
    r"|[①-⑳⑴-⒇㉠-㉭ⓐ-ⓩ]\s*"                     # ① ⑴ ㉠ ⓐ
    r"|[□■○●◦◇◆▪▫▶▷►▸•・·‣⦁※☐☑✓✔\-–—]\s*"       # 글머리표
    r")"
)
_SPACE = re.compile(r"[ \t 　\v\f\r]+")


# ---------------------------------------------------------------------------
# 문서 뼈대·블록 생성 (pdf_parser·pptx_parser 공용)
# ---------------------------------------------------------------------------

def document_skeleton(path: Path, data: bytes, parser_version: str, pagination_source: str) -> dict[str, Any]:
    """hwpx_parser.parse_hwpx와 같은 최상위 키를 가진 빈 문서를 만든다."""
    digest = hashlib.sha256(data).hexdigest()
    return {
        "document_id": digest, "source_sha256": digest,
        "filename": path.name, "schema_version": SCHEMA_VERSION,
        "parser_version": parser_version,
        "blocks": [], "tables": [], "images": [], "assets": [],
        "warnings": [], "pages": [], "pagination_source": pagination_source,
    }


def page_entry(number: int, page_number_source: str) -> dict[str, Any]:
    """pages 항목. 인쇄 쪽번호를 읽지 않으므로 page_number는 물리 번호와 같다."""
    return {"physical_page_number": number, "page_number": number,
            "page_number_source": page_number_source}


def _block_base(document: dict[str, Any], kind: str, counts: dict[str, int],
                page: int, source_index: int, page_number_source: str) -> dict[str, Any]:
    """블록 공통 필드. block_id는 유형별로, order는 문서 전체에서 센다."""
    counts[kind] = counts.get(kind, 0) + 1
    prefix = {"paragraph": "p", "table": "tbl"}[kind]
    return {
        "block_id": f"{prefix}_{counts[kind]:04d}", "type": kind,
        "order": len(document["blocks"]), "section": f"page_{page}",
        "source_paragraph_index": source_index, "source_xml_path": None,
        "parent_block_id": None, "parent_cell_id": None,
        "page_number": page, "physical_page_number": page,
        "page_number_source": page_number_source,
        "physical_page_numbers": [page], "page_numbers": [page],
        "page_mapping_level": "page",
    }


def add_paragraph_block(document: dict[str, Any], counts: dict[str, int], *, text: str,
                        page: int, source_index: int, page_number_source: str) -> dict[str, Any] | None:
    """비어 있지 않은 문단 블록을 문서에 붙이고 돌려준다. 빈 글은 None."""
    text = text.strip()
    if not text:
        return None
    block = _block_base(document, "paragraph", counts, page, source_index, page_number_source)
    block.update(text=text, runs=[])
    document["blocks"].append(block)
    return block


def add_table_block(document: dict[str, Any], counts: dict[str, int], *, grid: list[list[str]],
                    page: int, source_index: int, page_number_source: str) -> dict[str, Any] | None:
    """직사각형 문자열 격자를 표 블록으로 붙인다. 셀 전부 비었거나 격자가 없으면 None.

    짧은 행은 빈 셀로 채워 직사각형을 유지한다(table_cells 투영과 화면 렌더가 격자를 전제한다).
    """
    if not grid:
        return None
    cols = max(len(row) for row in grid)
    if cols == 0:
        return None
    cells = []
    for r, row in enumerate(grid):
        padded = [str(value or "").strip() for value in row] + [""] * (cols - len(row))
        cells.append([{"cell_id": f"c_r{r}_c{c}", "row": r, "col": c, "row_span": 1, "col_span": 1, "text": value}
                      for c, value in enumerate(padded)])
    if not any(cell["text"] for row in cells for cell in row):
        return None
    text = "\n".join(" | ".join(cell["text"].replace("\n", " ") for cell in row) for row in cells)
    block = _block_base(document, "table", counts, page, source_index, page_number_source)
    table = {"cells": cells, "image_path": None, "rows": len(cells), "cols": cols,
             "context_before": [], "context_after": [],
             "page_number": page, "physical_page_number": page, "page_number_source": page_number_source}
    block.update(text=text, table=table, table_index=counts["table"], image_path=None)
    document["blocks"].append(block)
    document["tables"].append(table)
    return block


def finish_document(document: dict[str, Any]) -> dict[str, Any]:
    """표 앞뒤 문단 문맥을 채우고 order가 블록 순서와 같은지 확인한다."""
    for index, block in enumerate(document["blocks"]):
        block["order"] = index
    add_table_context(document)
    return document


# ---------------------------------------------------------------------------
# 문단 나누기 (순수 함수 · 단위 테스트 대상)
# ---------------------------------------------------------------------------

def normalize_space(text: str) -> str:
    """탭·전각 공백·연속 공백을 한 칸으로 줄이고 양끝을 자른다. 줄바꿈은 호출자가 다룬다."""
    return _SPACE.sub(" ", text).strip()


def looks_like_heading(line: str) -> bool:
    """번호·글머리표로 시작하는 줄인지 본다. 새 문단의 시작으로 취급한다."""
    return bool(_HEADING_START.match(line))


def split_paragraphs(lines: list[str]) -> list[str]:
    """줄 목록을 문단 목록으로 합친다.

    - 빈 줄은 문단을 끝낸다.
    - 번호·글머리표로 시작하는 줄은 새 문단을 연다. 그 줄이 짧으면(HEADING_MAX_CHARS 이하)
      혼자 문단이 되고, 길면 뒤따르는 일반 줄을 이어 붙인다.
    - 그 밖의 줄은 앞 문단에 공백 한 칸으로 이어 붙인다.
    - 결과 문단은 모두 비어 있지 않다.
    """
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for raw in lines:
        line = normalize_space(raw)
        if not line:
            flush()
            continue
        if looks_like_heading(line):
            flush()
            if len(line) <= HEADING_MAX_CHARS:
                paragraphs.append(line)
                continue
        current.append(line)
    flush()
    return paragraphs


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def parse_pdf(path: str | Path) -> dict[str, Any]:
    """PDF에서 페이지별 글자를 뽑아 문서 JSON을 만든다.

    RuntimeError: PDF 파서가 없을 때. ValueError: 암호 PDF, 스캔·이미지 PDF, 페이지 수 초과, 손상 파일.
    """
    import io

    path = Path(path)
    data = path.read_bytes()
    try:
        import pypdf
        from pypdf.errors import PyPdfError
    except ImportError:
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError(
                "PDF 제안서를 읽으려면 pypdf 또는 PyMuPDF 패키지가 필요합니다. "
                "apps/server/requirements.txt를 확인하세요."
            ) from error
        document = document_skeleton(path, data, "pdf-text-pymupdf-1.0", "pdf")
        try:
            with pymupdf.open(stream=data, filetype="pdf") as reader:
                if reader.needs_pass:
                    raise ValueError("암호가 걸린 PDF는 올릴 수 없어요.")
                return _extract_pdf_pages(document, len(reader),
                                          lambda index: reader.load_page(index).get_text("text", sort=True))
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(f"PDF 파일을 읽을 수 없어요 ({type(error).__name__}).") from error

    document = document_skeleton(path, data, PDF_PARSER_VERSION, "pdf")
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # 빈 암호로 열리는 "소유자 암호만" PDF는 허용한다. 그 밖은 사용자 암호가 필요하다.
            try:
                opened = reader.decrypt("")
            except Exception as error:  # DependencyError(AES) 포함
                raise ValueError("암호가 걸린 PDF는 올릴 수 없어요.") from error
            if not opened:
                raise ValueError("암호가 걸린 PDF는 올릴 수 없어요.")
        return _extract_pdf_pages(document, len(reader.pages),
                                  lambda index: reader.pages[index].extract_text())
    except ValueError:
        raise
    except PyPdfError as error:
        if "password" in str(error).lower() or "decrypt" in str(error).lower():
            raise ValueError("암호가 걸린 PDF는 올릴 수 없어요.") from error
        raise ValueError(f"PDF 파일을 읽을 수 없어요 ({type(error).__name__}).") from error


def _extract_pdf_pages(document: dict[str, Any], page_count: int, read_page) -> dict[str, Any]:
    warnings = document["warnings"]
    if page_count == 0:
        raise ValueError("페이지가 없는 PDF예요.")
    if page_count > MAX_PDF_PAGES:
        raise ValueError(f"PDF는 {MAX_PDF_PAGES}쪽까지만 올릴 수 있어요. (현재 {page_count}쪽)")

    counts: dict[str, int] = {}
    text_chars = 0
    source_index = 0
    for page_index in range(page_count):
        number = page_index + 1
        document["pages"].append(page_entry(number, "pdf_page"))
        try:
            raw = read_page(page_index) or ""
        except Exception as error:
            message = str(error).lower()
            if "password" in message or "decrypt" in message:
                raise ValueError("암호가 걸린 PDF는 올릴 수 없어요.") from error
            warnings.append({"code": "pdf_page_text_failed", "page": number,
                             "error_type": type(error).__name__})
            continue
        for paragraph in split_paragraphs(raw.splitlines()):
            if add_paragraph_block(document, counts, text=paragraph, page=number,
                                   source_index=source_index, page_number_source="pdf_page"):
                source_index += 1
                text_chars += len(re.sub(r"\s+", "", paragraph))

    if text_chars < MIN_TEXT_CHARS:
        raise ValueError("스캔·이미지 PDF는 지원하지 않아요. 글자가 포함된 PDF를 올려 주세요.")

    warnings.append({"code": "pdf_tables_not_extracted",
                     "detail": "PDF 표는 글자 흐름으로만 들어갑니다. 표 격자·그림은 추출하지 않습니다."})
    return finish_document(document)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용법: python pdf_parser.py <제안서.pdf>")
    result = parse_pdf(sys.argv[1])
    print("파싱 완료:", result["filename"])
    print("페이지:", len(result["pages"]), "블록:", len(result["blocks"]),
          "표:", len(result["tables"]), "경고:", len(result["warnings"]))
