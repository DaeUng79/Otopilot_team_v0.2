"""평가표 사람 승인(CRT-03·04·05).

연결용 신규 파일 · 오대웅(DaeUng79) 문서 모듈 검토 대상.
설계(인계서 v2 §15 CRITERIA 모듈)의 `open_draft`·`save_draft`·`approve_criteria`를 구현한다.
AI 초안(`criteria_results`, step4)은 읽기만 하고 수정하지 않는다. 검토 시작은 초안을
복사해 `approved_criteria_versions(DRAFT)`를 만들고, 확정은 APPROVED로 바꾼 뒤
`criteria.approved` 계약 payload를 돌려준다(평가 DB 전달은 서버 어댑터가 한다).
표 열은 schema_v2.json을 따르되 `criteria_results`·`requirement_results`·`ref_admin_users`
외래키는 새 문서 DB에 그 표가 없을 수 있어 선언하지 않고, 항목에는 화면의 '근거 쪽'을 담는
`source_page`와 `source_page_end` 열을 더했다. 배점은 평가 DB와 같은 점수×10000 정수다.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .hwpx_storage import SCHEMA, connect

SCALE = 10000
CRITERIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS approved_criteria_versions (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    upload_revision INTEGER NOT NULL,
    draft_result_id TEXT,
    requirement_result_id TEXT,
    document_id TEXT NOT NULL,
    parse_revision TEXT NOT NULL,
    approval_no INTEGER NOT NULL CHECK(approval_no > 0),
    status TEXT NOT NULL CHECK(status IN ('DRAFT','APPROVED','RETIRED')),
    total_max_score INTEGER NOT NULL CHECK(total_max_score > 0),
    draft_snapshot_json TEXT NOT NULL,
    approved_snapshot_json TEXT,
    snapshot_sha256 TEXT,
    approved_by TEXT,
    approved_at TEXT,
    UNIQUE(project_id, approval_no),
    UNIQUE(project_id, id),
    FOREIGN KEY(project_id, upload_revision) REFERENCES rfp_snapshot_bindings(project_id, upload_revision),
    FOREIGN KEY(document_id, parse_revision) REFERENCES parse_snapshots(document_id, revision)
);
CREATE TABLE IF NOT EXISTS approved_criteria_items (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    approved_criteria_version_id TEXT NOT NULL REFERENCES approved_criteria_versions(id),
    parent_id TEXT REFERENCES approved_criteria_items(id),
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    is_scorable INTEGER NOT NULL CHECK(is_scorable IN (0,1)),
    max_score INTEGER NOT NULL CHECK(max_score >= 0),
    score_step INTEGER NOT NULL CHECK(score_step > 0),
    sort_order INTEGER NOT NULL,
    source_block_id TEXT,
    source_page INTEGER,
    source_page_end INTEGER,
    UNIQUE(approved_criteria_version_id, code),
    UNIQUE(project_id, approved_criteria_version_id, id)
);
"""
# AI 초안이 없을 때 쓰는 기본 서식(정성 80점). 제목·배점은 화면에서 고친다.
DEFAULT_TEMPLATE = [
    ("1", "사업 이해도", 5), ("2", "사업추진 체계", 10), ("3", "수행 방안 및 기술", 20),
    ("4", "운영·서비스 계획", 20), ("5", "보안·품질 관리", 10), ("6", "추진일정 및 예산계획", 5),
    ("7", "사업홍보 및 사후관리", 5), ("8", "추가 제안", 5),
]


class CriteriaApprovalError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 검증 오류."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _packed(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_packed(value).encode()).hexdigest()


def initialize(db_path: Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.executescript(SCHEMA + CRITERIA_SCHEMA)
        columns = {row[1] for row in db.execute("PRAGMA table_info(approved_criteria_items)")}
        if "source_page_end" not in columns:
            db.execute("ALTER TABLE approved_criteria_items ADD COLUMN source_page_end INTEGER")


def _binding(db, project_id: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT project_id,upload_revision,document_id,parse_revision FROM rfp_snapshot_bindings "
        "WHERE project_id=? ORDER BY upload_revision DESC LIMIT 1", (project_id,)).fetchone()
    return dict(row) if row else None


def _criteria_table_page(db, document_id: str, parse_revision: str) -> int | None:
    """제안요청서에서 정성 평가표(평가+배점 머리글)가 있는 쪽을 찾는다. 없으면 None."""
    for row in db.execute(
        "SELECT block_json FROM blocks WHERE document_id=? AND revision=? AND type='table' "
        "ORDER BY order_index", (document_id, parse_revision)):
        block = json.loads(row[0])
        rows = block.get("table", {}).get("cells", [])
        head = " ".join(re.sub(r"\s+", "", c.get("text", "")) for r in rows[:4] for c in r)
        if "평가" in head and ("배점" in head or "점수" in head):
            pages = block.get("physical_page_numbers") or []
            if pages:
                return pages[0]
    return None


def _page_range(pages: list[int]) -> tuple[int, int | None] | None:
    pages = sorted({page for page in pages if isinstance(page, int) and page > 0})
    return (pages[0], pages[-1] if pages[-1] != pages[0] else None) if pages else None


def _compact(value: Any) -> str:
    return re.sub(r"\W+", "", str(value or "")).lower()


def _table_sources(db, binding: dict[str, Any]):
    for record in db.execute(
        "SELECT block_id,block_json,physical_page_numbers_json FROM blocks "
        "WHERE document_id=? AND revision=? AND type='table' ORDER BY order_index",
        (binding["document_id"], binding["parse_revision"]),
    ):
        block = json.loads(record["block_json"])
        rows = block.get("table", {}).get("cells", [])
        pages = _page_range(json.loads(record["physical_page_numbers_json"] or "[]"))
        if pages and rows:
            yield record["block_id"], rows, pages


def split_scored_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """원문 평가항목 한 셀의 점수별 지표를 독립 평가행으로 펼친다.

    원문 배점과 세부 점수 합이 다르면 점수를 추측하지 않고 원래 행을 유지한다.
    """
    expanded = []
    for row in rows:
        title = row.get("evaluation_item") or ""
        parts = [part.strip() for part in re.split(r"(?:^|\s)[∘○◦•∙●]\s*", title) if part.strip()]
        if len(parts) < 2:
            expanded.append(row)
            continue
        details = []
        for part in parts:
            match = re.search(r"[（(]\s*(\d+)\s*점\s*[)）]", part)
            if not match:
                break
            item_title = part[:match.start()].strip()
            if not item_title:
                break
            details.append((item_title, int(match.group(1)), part[match.end():].strip()))
        if len(details) != len(parts) or sum(score for _, score, _ in details) != row.get("score"):
            expanded.append(row)
            continue
        for index, (item_title, score, note) in enumerate(details, 1):
            item = dict(row)
            item["row_id"] = f"{row.get('row_id', '')}-{index:02d}"
            item["evaluation_item"] = item_title
            item["score"] = score
            if note:
                item["evaluation_criteria"] = "\n".join(filter(None, (note, row.get("evaluation_criteria"))))
            expanded.append(item)
    return expanded


def _rows_with_source_pages(db, binding: dict[str, Any], rows: list[dict[str, Any]],
                            template_source: str | None = None) -> list[dict[str, Any]]:
    """원문 평가표의 행 또는 요구사항 그룹과 연결된 쪽 범위를 찾는다."""
    paragraphs = []
    for block in db.execute(
        "SELECT block_id,text,physical_page_numbers_json FROM blocks "
        "WHERE document_id=? AND revision=? AND type='paragraph' ORDER BY order_index",
        (binding["document_id"], binding["parse_revision"]),
    ):
        pages = json.loads(block["physical_page_numbers_json"] or "[]")
        if pages and block["text"]:
            paragraphs.append((block["block_id"], block["text"], pages[0]))
    tables = list(_table_sources(db, binding))
    result = []
    for row in split_scored_rows(rows):
        item = dict(row)
        source = template_source or item.get("template_source")
        title = _compact(item.get("evaluation_item"))
        score = item.get("score")
        if title and isinstance(score, (int, float)):
            point = re.compile(rf"[（(]\s*{score:g}\s*점\s*[)）]")
            for block_id, text, page in paragraphs:
                if title in _compact(text) and point.search(text):
                    item["source_page"] = page
                    item["source_block_id"] = block_id
                    break
        if item.get("source_page") is None and source == "request_document" and title:
            # 표 셀에 항목명과 배점이 분리되어 있어도 같은 행이면 원문 평가표로 인정한다.
            for block_id, table_rows, pages in tables:
                header = _compact(" ".join(str(c.get("text", "")) for r in table_rows[:4] for c in r))
                if "평가" not in header or not ("배점" in header or "점수" in header):
                    continue
                for cells in table_rows:
                    texts = [str(cell.get("text", "")) for cell in cells]
                    if (any(title in _compact(value) for value in texts)
                            and any(re.fullmatch(rf"\s*{score:g}\s*점?\s*", value) for value in texts)):
                        item["source_page"], item["source_page_end"] = pages
                        item["source_block_id"] = block_id
                        break
                if item.get("source_page") is not None:
                    break
        if item.get("source_page") is None and source == "generated_from_summary":
            group = _compact(item.get("evaluation_division"))
            if group:
                for block_id, table_rows, pages in tables:
                    header = _compact(" ".join(str(c.get("text", "")) for r in table_rows[:4] for c in r))
                    if not ("요구사항" in header and ("구분" in header or "분류" in header or "유형" in header)):
                        continue
                    if any(any(group == _compact(c.get("text")) for c in cells) for cells in table_rows):
                        item["source_page"], item["source_page_end"] = pages
                        item["source_block_id"] = block_id
                        break
        result.append(item)
    return result


def scoring_rows_with_source_pages(db_path: Path, project_id: str,
                                   rows: list[dict[str, Any]],
                                   template_source: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as db:
        binding = _binding(db, project_id)
        return _rows_with_source_pages(db, binding, rows, template_source) if binding else split_scored_rows(rows)


def _items_from_ai(rows: list[dict[str, Any]], page: int | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    divisions: list[str] = []
    for row in split_scored_rows(rows):
        division = row.get("evaluation_division") or "평가부문"
        if division not in divisions:
            divisions.append(division)
            items.append({"code": str(len(divisions)), "parent_code": None, "title": division,
                          "description": None, "max_score": 0, "source_page": page})
        number = len([i for i in items if i["parent_code"] == str(divisions.index(division) + 1)]) + 1
        criteria = (row.get("evaluation_criteria") or "").strip()
        elements = row.get("evaluation_elements") or []
        description = criteria + ("".join("\n- " + e for e in elements) if elements else "")
        items.append({"code": f"{divisions.index(division) + 1}.{number}",
                      "parent_code": str(divisions.index(division) + 1),
                      "title": row.get("evaluation_item") or "평가항목",
                      "description": description or None,
                      "max_score": float(row.get("score") or 0),
                      "source_page": row.get("source_page"),
                      "source_page_end": row.get("source_page_end")})
    return items


def _items_from_template(page: int | None) -> list[dict[str, Any]]:
    return [{"code": code, "parent_code": None, "title": title, "description": None,
             "max_score": float(score), "source_page": page} for code, title, score in DEFAULT_TEMPLATE]


def validate_items(items: list[dict[str, Any]], total_points: float | None = None) -> list[dict[str, Any]]:
    """코드 유일·계층·배점 합·근거 쪽을 검사하고 저장용 정규화 목록을 돌려준다."""
    if not isinstance(items, list) or not items:
        raise CriteriaApprovalError("평가항목이 비어 있습니다.")
    codes = [str(i.get("code", "")).strip() for i in items]
    if any(not c for c in codes):
        raise CriteriaApprovalError("코드가 빈 항목이 있습니다.")
    if len(set(codes)) != len(codes):
        raise CriteriaApprovalError("코드가 겹치는 항목이 있습니다.")
    normalized = []
    for order, item in enumerate(items):
        code = str(item["code"]).strip()
        parent = str(item.get("parent_code") or "").strip() or None
        if parent and parent not in codes:
            raise CriteriaApprovalError(f"{code}번의 상위 항목 {parent}이(가) 없습니다.")
        if parent and not code.startswith(parent + "."):
            raise CriteriaApprovalError(f"코드 {code}는 상위 {parent} 아래에 맞지 않습니다.")
        title = str(item.get("title") or "").strip()
        if not title:
            raise CriteriaApprovalError(f"{code}번 평가 항목 이름이 비었습니다.")
        try:
            points = float(item.get("max_score") or 0)
        except (TypeError, ValueError):
            raise CriteriaApprovalError(f"{code}번 배점은 숫자여야 합니다.") from None
        if points < 0:
            raise CriteriaApprovalError(f"{code}번 배점이 음수입니다.")
        page = item.get("source_page")
        if page not in (None, ""):
            try:
                page = int(page)
            except (TypeError, ValueError):
                raise CriteriaApprovalError(f"{code}번 근거 쪽은 숫자여야 합니다.") from None
        else:
            page = None
        end = item.get("source_page_end")
        if end not in (None, ""):
            try:
                end = int(end)
            except (TypeError, ValueError):
                raise CriteriaApprovalError(f"{code}번 근거 쪽 범위는 숫자여야 합니다.") from None
        else:
            end = None
        if page is not None and page < 1 or end is not None and (page is None or end <= page):
            raise CriteriaApprovalError(f"{code}번 근거 쪽 범위를 확인해 주세요.")
        normalized.append({"code": code, "parent_code": parent, "title": title,
                           "description": (str(item.get("description")).strip() or None)
                           if item.get("description") not in (None, "") else None,
                           "max_score": round(points * SCALE), "source_page": page,
                           "source_page_end": end,
                           "sort_order": order})
    parents = {i["parent_code"] for i in normalized if i["parent_code"]}
    for i in normalized:
        i["is_scorable"] = 0 if i["code"] in parents else 1
    leaf_sum = sum(i["max_score"] for i in normalized if i["is_scorable"])
    if leaf_sum <= 0:
        raise CriteriaApprovalError("말단 배점 합이 0입니다.")
    if total_points is not None and leaf_sum != round(total_points * SCALE):
        raise CriteriaApprovalError(
            f"말단 배점 합 {leaf_sum / SCALE:g}점이 기술 배점 {total_points:g}점과 다릅니다.")
    return normalized


def _write_items(db, version_id: str, project_id: str, items: list[dict[str, Any]]) -> None:
    db.execute("DELETE FROM approved_criteria_items WHERE approved_criteria_version_id=?", (version_id,))
    ids: dict[str, str] = {}
    for item in sorted(items, key=lambda i: (i["parent_code"] is not None, i["sort_order"])):
        identity = str(uuid4())
        ids[item["code"]] = identity
        db.execute(
            "INSERT INTO approved_criteria_items "
            "(id,created_at,updated_at,version,project_id,approved_criteria_version_id,parent_id,"
            "code,title,description,is_scorable,max_score,score_step,sort_order,source_block_id,"
            "source_page,source_page_end) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (identity, _now(), _now(), 1, project_id, version_id,
             ids.get(item["parent_code"]) if item["parent_code"] else None,
             item["code"], item["title"], item["description"], item["is_scorable"],
             item["max_score"], SCALE, item["sort_order"], None, item["source_page"],
             item["source_page_end"]))


def _read_items(db, version_id: str) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM approved_criteria_items WHERE approved_criteria_version_id=? "
                      "ORDER BY sort_order", (version_id,)).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [dict(r) | {"parent_code": by_id[r["parent_id"]]["code"] if r["parent_id"] else None,
                       "points": r["max_score"] / SCALE} for r in rows]


def _read_version(db, version_id: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM approved_criteria_versions WHERE id=?", (version_id,)).fetchone()
    if row is None:
        raise LookupError("평가표 작업본을 찾을 수 없습니다.")
    return dict(row) | {"items": _read_items(db, version_id),
                        "total_points": row["total_max_score"] / SCALE}


def list_versions(db_path: Path, project_id: str) -> list[dict[str, Any]]:
    if not Path(db_path).is_file():
        return []
    with connect(db_path) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approved_criteria_versions'").fetchone():
            return []
        ids = [r[0] for r in db.execute(
            "SELECT id FROM approved_criteria_versions WHERE project_id=? ORDER BY approval_no", (project_id,))]
        return [_read_version(db, i) for i in ids]


def open_draft(db_path: Path, *, project_id: str, source: str, ai_result: dict[str, Any] | None,
               actor_id: str, restart: bool = False) -> dict[str, Any]:
    """CRT-03: 초안을 복사한다. restart 요청은 기존 작업본을 이력으로 남기고 새 복사본을 연다."""
    initialize(db_path)
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT id FROM approved_criteria_versions WHERE project_id=? AND status='DRAFT' "
            "ORDER BY approval_no DESC LIMIT 1", (project_id,)).fetchone()
        if existing and not restart:
            current = _read_version(db, existing[0])
            if source == "ai" and current["draft_result_id"] != (ai_result or {}).get("_id"):
                raise CriteriaApprovalError("현재 검토본은 AI 초안과 다릅니다. AI 초안 반영을 선택해 새 검토본을 열어 주세요.")
            return current
        binding = _binding(db, project_id)
        if binding is None:
            raise CriteriaApprovalError("제안요청서를 먼저 등록해 주세요.")
        page = _criteria_table_page(db, binding["document_id"], binding["parse_revision"])
        if source == "ai":
            if not ai_result or not ai_result.get("rows"):
                raise CriteriaApprovalError("AI 초안이 아직 없습니다. 초안 생성을 먼저 실행해 주세요.")
            items = _items_from_ai(_rows_with_source_pages(
                db, binding, ai_result["rows"], ai_result.get("template_source")), page)
            total = float(ai_result.get("total_score") or sum(r.get("score", 0) for r in ai_result["rows"]))
            draft_result_id = ai_result.get("_id")
        else:
            items = _items_from_template(page)
            total = float(sum(s for _, _, s in DEFAULT_TEMPLATE))
            draft_result_id = None
        normalized = validate_items(items, total)
        if existing:
            db.execute(
                "UPDATE approved_criteria_versions SET status='RETIRED',updated_at=? WHERE id=?",
                (_now(), existing[0]),
            )
        approval_no = db.execute(
            "SELECT COALESCE(MAX(approval_no),0)+1 FROM approved_criteria_versions WHERE project_id=?",
            (project_id,)).fetchone()[0]
        identity = str(uuid4())
        db.execute(
            "INSERT INTO approved_criteria_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)",
            (identity, _now(), _now(), 1, project_id, binding["upload_revision"], draft_result_id, None,
             binding["document_id"], binding["parse_revision"], approval_no, "DRAFT",
             round(total * SCALE), _packed({"source": source, "items": normalized, "opened_by": actor_id})))
        _write_items(db, identity, project_id, normalized)
        return _read_version(db, identity)


def save_draft(db_path: Path, *, project_id: str, draft_id: str, version: int,
               items: list[dict[str, Any]], total_points: float | None) -> dict[str, Any]:
    """CRT-04: DRAFT의 항목·배점·근거를 통째로 바꾼다(낙관적 잠금)."""
    initialize(db_path)
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM approved_criteria_versions WHERE id=? AND project_id=?",
                         (draft_id, project_id)).fetchone()
        if row is None:
            raise LookupError("평가표 작업본을 찾을 수 없습니다.")
        if row["status"] != "DRAFT":
            raise CriteriaApprovalError("확정된 평가표는 고칠 수 없습니다. 새 검토를 시작하세요.")
        if row["version"] != version:
            raise CriteriaApprovalError("다른 작업에서 변경했습니다. 다시 조회하세요.")
        total = total_points if total_points is not None else row["total_max_score"] / SCALE
        normalized = validate_items(items, total)
        _write_items(db, draft_id, project_id, normalized)
        db.execute("UPDATE approved_criteria_versions SET total_max_score=?,updated_at=?,version=version+1 WHERE id=?",
                   (round(total * SCALE), _now(), draft_id))
        return _read_version(db, draft_id)


def approve_criteria(db_path: Path, *, project_id: str, draft_id: str, version: int,
                     actor_id: str, confirmed: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """CRT-05: 검증 후 APPROVED로 바꾸고 (저장본, criteria.approved payload)를 돌려준다."""
    if confirmed is not True:
        raise CriteriaApprovalError("원문·배점·빠진 항목을 확인했다는 동의가 필요합니다.")
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        current = _read_version(db, draft_id)
        if current["project_id"] != project_id:
            raise LookupError("평가표 작업본을 찾을 수 없습니다.")
        if current["status"] != "DRAFT":
            raise CriteriaApprovalError("이미 확정된 평가표입니다.")
        if current["version"] != version:
            raise CriteriaApprovalError("다른 작업에서 변경했습니다. 다시 조회하세요.")
        items = current["items"]
        leaves = [i for i in items if i["is_scorable"]]
        if sum(i["max_score"] for i in leaves) != current["total_max_score"]:
            raise CriteriaApprovalError("말단 배점 합이 기술 배점과 다릅니다.")
        missing = [i["code"] for i in leaves if i["source_page"] is None]
        if missing:
            raise CriteriaApprovalError("원문 근거 쪽이 없는 항목이 있습니다: " + ", ".join(missing))
        approved_at = _now()
        payload_items = [{
            "id": i["id"], "project_id": project_id, "approved_criteria_version_id": draft_id,
            "parent_id": i["parent_id"], "code": i["code"], "title": i["title"],
            "description": i["description"], "is_scorable": i["is_scorable"],
            "max_score": i["max_score"], "score_step": i["score_step"], "sort_order": i["sort_order"],
        } for i in items]
        payload = {
            "id": draft_id, "project_id": project_id, "approval_no": current["approval_no"],
            "total_max_score": current["total_max_score"], "status": "APPROVED",
            "approved_at": approved_at,
            "rfp_pin": {"project_id": project_id, "upload_revision": current["upload_revision"],
                        "document_id": current["document_id"], "parse_revision": current["parse_revision"]},
            "items": payload_items, "snapshot_sha256": _digest(payload_items),
        }
        db.execute(
            "UPDATE approved_criteria_versions SET status='APPROVED',approved_snapshot_json=?,"
            "snapshot_sha256=?,approved_by=?,approved_at=?,updated_at=?,version=version+1 WHERE id=?",
            (_packed(payload), payload["snapshot_sha256"], actor_id, approved_at, approved_at, draft_id))
        # 같은 사업의 이전 승인표는 RETIRED(새 승인이 최신).
        db.execute("UPDATE approved_criteria_versions SET status='RETIRED',updated_at=? "
                   "WHERE project_id=? AND status='APPROVED' AND id<>?", (approved_at, project_id, draft_id))
        return _read_version(db, draft_id), payload


def approved_payload(db_path: Path, project_id: str, version_id: str) -> dict[str, Any] | None:
    """재전송용: 저장된 승인 payload."""
    with connect(db_path) as db:
        row = db.execute("SELECT approved_snapshot_json FROM approved_criteria_versions WHERE id=? AND project_id=? AND status IN ('APPROVED','RETIRED')",
                         (version_id, project_id)).fetchone()
    return json.loads(row[0]) if row and row[0] else None
