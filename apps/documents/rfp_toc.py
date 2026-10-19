"""Resolve a parsed RFP's printed table of contents to fixed physical pages.

Adapted from the EV-03 preview's document API. The caller supplies the
document ID and parse revision already authorized for this evaluator.

2026-10-18: printed TOCs come in several layouts — a "목 차" title cell with
one paragraph per row, a title/page pair split into separate cells, a
decorated header such as "•••• 목 차 ••••" or "【 목 차 】", a second TOC page
with its own header, chapter headers (Ⅰ. …) without a page number, and
appendix groups labelled 〔붙임〕 / 〔별지〕. Entries whose title cannot be
found on the expected page are still linked by the printed number plus the
measured page offset, so every entry can be opened; `assumed` marks that case.
"""

import json
import re
import unicodedata
from collections import Counter

# "제목 <탭 | 점선 리더 | 두 칸 이상 공백> 쪽번호"
TOC_ROW = re.compile(
    r"^(?P<title>.+?)(?:[\s\t]*[.·…‥⋯ㆍ]{2,}[\s\t]*|\t[\s\t]*|\s{2,})(?P<page>\d{1,3})\s*$"
)
PAGE_ONLY = re.compile(r"^\d{1,3}$")
ROMAN = re.compile(r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]{1,4})[.．]\s*\S")
NUMBERED = re.compile(r"^(\d+)[.．]\s*\S")
SUBNUMBERED = re.compile(r"^\d+\s*[-.．]\s*\d+")
GROUP = re.compile(r"^[〔\[(【]?\s*(?P<name>붙임|별지|별첨|부록|첨부|서식)\s*[〕\])】]?\s*$")
GROUP_PREFIX = re.compile(r"^[〔\[(【]?\s*(?:붙임|별지|별첨|부록|첨부|서식)(?![가-힣])")
LEADING_MARK = re.compile(r"^(?:\[[^\]]*\]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.．]\s*|\d+[.．)]|[가-힣][.．])\s*")
SENTENCE_END = re.compile(r"(다|함|음)\.?$")
FRAGMENT_MAX = 60


def _norm(value):
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", value or ""))


def _title_key(title):
    return _norm(LEADING_MARK.sub("", title.strip(), count=1))


def _is_toc_header(value):
    # "목   차", "•••• 목 차 ••••", "【 목 차 】" 모두 인정한다.
    return re.sub(r"[^가-힣]", "", value) == "목차"


def _paragraphs(conn, document_id, revision):
    records = conn.execute(
        "SELECT order_index,text,physical_page_numbers_json,parent_cell_id "
        "FROM blocks WHERE document_id=? AND revision=? AND type='paragraph' "
        "ORDER BY order_index", (document_id, revision)
    )
    return [
        (row["order_index"], (row["text"] or "").strip(),
         json.loads(row["physical_page_numbers_json"]), row["parent_cell_id"] is None)
        for row in records if (row["text"] or "").strip()
    ]


def _level(title, state):
    """1: 로마숫자 장·붙임 묶음, 2: 그 아래 번호 항목. 상위가 없으면 번호 항목이 1."""
    if ROMAN.match(title) or GROUP_PREFIX.match(title):
        state["parent"] = True
        return 1
    if SUBNUMBERED.match(title):
        return 2
    if NUMBERED.match(title):
        return 2 if state["parent"] else 1
    return 2


def _printed_toc(paragraphs):
    start = next(
        (index for index, (_, value, _, _) in enumerate(paragraphs) if _is_toc_header(value)),
        None,
    )
    if start is None:
        return [], set()
    entries, toc_pages = [], set(paragraphs[start][2])
    state = {"parent": False, "last": 0}  # last: 목차 쪽 번호는 단조 증가 (묶음 머리에서 초기화)
    pending = []  # 셀로 쪼개진 제목 조각 ("Ⅰ." / "사업개요" / "3")

    def add_parent(title):
        entries.append({"t": title, "printed": None, "lv": 1, "parent": True})
        state["parent"] = True
        state["last"] = 0

    def add_entry(title, printed, pages):
        # 쪽 번호가 뒤로 가면 목차가 끝나고 본문(장 제목 상자 등)이 시작된 것이다.
        if printed <= 0 or printed < state["last"]:
            return False
        entries.append({"t": title, "printed": printed, "lv": _level(title, state)})
        toc_pages.update(pages)
        state["last"] = printed
        return True

    def flush_pending():
        # 쪽 번호 없이 끝난 조각 중 장 제목(Ⅰ. …)만 상위 항목으로 남긴다.
        for fragment in pending:
            if ROMAN.match(fragment):
                add_parent(fragment)
        pending.clear()

    stop = False
    for _, value, pages, _ in paragraphs[start + 1:]:
        if entries and pages and min(pages) > max(toc_pages) + 1:
            break
        for line in value.splitlines():
            line = line.strip()
            if not line or _is_toc_header(line):
                continue
            group = GROUP.match(line)
            if group:
                flush_pending()
                add_parent(group["name"])
                toc_pages.update(pages)
                continue
            match = TOC_ROW.match(line)
            if match:
                flush_pending()
                if add_entry(match["title"].strip(), int(match["page"]), pages):
                    continue
                if int(match["page"]) > 0 and entries:
                    stop = True
                    break
                continue
            if PAGE_ONLY.match(line):
                title, pending[:] = " ".join(pending), []
                if title and not add_entry(title, int(line), pages) and int(line) > 0 and entries:
                    stop = True
                    break
                continue
            if len(line) <= FRAGMENT_MAX and not SENTENCE_END.search(line) and len(pending) < 3:
                pending.append(line)
                continue
            if entries:
                stop = True
                break
            pending.clear()
        if stop:
            break
    # 목차가 끝난 뒤 남은 조각(본문 첫 장 제목 등)은 버린다.
    pending.clear()
    # 쪽 번호가 있는 항목이 2개 이하면 인쇄 목차로 보지 않는다.
    if sum(1 for entry in entries if entry["printed"]) < 3:
        return [], set()
    return entries, toc_pages


def _locate_printed(entries, page_table, paragraphs, toc_pages):
    texts = {}
    for _, value, pages, _ in paragraphs:
        for page in pages:
            texts[page] = texts.get(page, "") + _norm(value)
    after = [
        (physical, printed) for physical, printed in page_table.items()
        if printed is not None and physical not in toc_pages
        and physical > max(toc_pages, default=0)
    ]
    offsets = Counter(physical - printed for physical, printed in after)
    global_offset = offsets.most_common(1)[0][0] if offsets else None
    # 쪽 번호 없는 쪽이 끼어 오프셋이 중간에 바뀌는 문서가 있어, 직전에 찾은 항목의 오프셋을 우선 쓴다.
    output, previous, local_offset = [], 0, None
    for entry in entries:
        item = {"t": entry["t"], "lv": entry["lv"],
                "printed": entry["printed"], "page": None, "seen": False}
        if entry.get("parent"):
            item["parent"] = True
            output.append(item)
            continue
        key = _title_key(entry["t"])
        offset = local_offset if local_offset is not None else global_offset
        expected = entry["printed"] + offset if offset is not None else None
        candidates = {
            physical for physical, printed in page_table.items()
            if printed == entry["printed"] and physical not in toc_pages
        }
        if expected in page_table:
            candidates.add(expected)
        hits = sorted(page for page in candidates if key and key in texts.get(page, ""))
        if len(hits) == 1:
            item.update(page=hits[0], seen=True)
        elif key and expected is not None:
            nearby = [
                page for page in range(max(previous, expected - 1, 1), expected + 5)
                if page in page_table and page not in toc_pages
                and key in texts.get(page, "")
            ]
            if len(nearby) == 1:
                item.update(page=nearby[0], seen=True)
        if item["page"] is None and expected in page_table and expected not in toc_pages:
            # 제목으로 확인하지 못해도 인쇄 쪽 번호 + 오프셋으로 연다.
            item.update(page=expected, seen=True, assumed=True)
        if item["page"] is not None:
            if expected is not None and item["page"] != expected:
                item["adjusted"] = True
            local_offset = item["page"] - entry["printed"]
        previous = item["page"] or previous
        output.append(item)
    # 쪽 번호 없는 장 제목·붙임 묶음은 첫 하위 항목의 쪽으로 연다.
    for index, item in enumerate(output):
        if item.get("parent"):
            child = next((o for o in output[index + 1:] if o["page"]), None)
            if child:
                item.update(page=child["page"], seen=True)
    return output


def _heading_toc(paragraphs, page_table):
    output, last_number = [], 0
    for _, value, pages, top in paragraphs:
        if not top or len(value) > 40 or not pages:
            continue
        level = 0
        if ROMAN.match(value):
            level, last_number = 1, 0
        else:
            match = NUMBERED.match(value)
            if (match and not SENTENCE_END.search(value)
                    and int(match[1]) == last_number + 1 and output):
                level, last_number = 2, int(match[1])
        if level:
            # 본문 제목의 물리 쪽은 확정값이므로 인쇄 쪽 번호가 없어도 연다.
            output.append({"t": value, "lv": level, "page": pages[0],
                           "seen": True, "printed": page_table.get(pages[0])})
    return output


def build_toc(conn, document_id, revision, pages):
    """Return preview-compatible TOC entries for this immutable parse revision."""
    page_table = {row["n"]: row["label"] for row in pages}
    paragraphs = _paragraphs(conn, document_id, revision)
    printed, toc_pages = _printed_toc(paragraphs)
    if printed:
        located = _locate_printed(printed, page_table, paragraphs, toc_pages)
        if any(item["page"] for item in located):
            return located
    return _heading_toc(paragraphs, page_table)


TOC_SCHEMA = """
CREATE TABLE IF NOT EXISTS rfp_toc_snapshots (
 document_id TEXT NOT NULL,
 parse_revision TEXT NOT NULL,
 toc_json TEXT NOT NULL,
 extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (document_id, parse_revision),
 FOREIGN KEY (document_id, parse_revision)
 REFERENCES parse_snapshots(document_id, revision)
);
"""
TOC_ALGORITHM_VERSION = 2


def save_toc(conn, document_id, revision):
    """Persist navigation for an immutable parse snapshot before AI extraction."""
    conn.executescript(TOC_SCHEMA)
    pages = [
        {"n": row["physical_page_number"], "label": row["page_number"]}
        for row in conn.execute(
            "SELECT physical_page_number,page_number FROM pages "
            "WHERE document_id=? AND revision=? ORDER BY physical_page_number",
            (document_id, revision),
        )
    ]
    toc = build_toc(conn, document_id, revision, pages)
    conn.execute(
        "INSERT OR REPLACE INTO rfp_toc_snapshots(document_id,parse_revision,toc_json) "
        "VALUES (?,?,?)",
        (document_id, revision, json.dumps(
            {"algorithm_version": TOC_ALGORITHM_VERSION, "items": toc}, ensure_ascii=False)),
    )
    return toc


def load_toc(conn, document_id, revision, pages):
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rfp_toc_snapshots'"
    ).fetchone()
    if table:
        row = conn.execute(
            "SELECT toc_json FROM rfp_toc_snapshots "
            "WHERE document_id=? AND parse_revision=?",
            (document_id, revision),
        ).fetchone()
        if row:
            snapshot = json.loads(row[0])
            if isinstance(snapshot, dict) and snapshot.get("algorithm_version") == TOC_ALGORITHM_VERSION:
                return snapshot["items"]
            # Existing parse snapshots keep their source data. Recompute older
            # navigation with the improved table-of-contents parser on read.
    return build_toc(conn, document_id, revision, pages)
