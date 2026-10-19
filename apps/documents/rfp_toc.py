"""Resolve a parsed RFP's printed table of contents to fixed physical pages.

Adapted from the EV-03 preview's document API. The caller supplies the
document ID and parse revision already authorized for this evaluator.
"""

import json
import re
import unicodedata
from collections import Counter

TOC_ROW = re.compile(r"^(?P<title>.+?)[\s\t.·…]*\t\s*(?P<page>\d+)\s*$")
ROMAN = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s*\S")
NUMBERED = re.compile(r"^(\d+)\.\s*\S")
LEADING_MARK = re.compile(r"^(?:\[[^\]]*\]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s*|\d+[.)]|[가-힣]\.)\s*")
SENTENCE_END = re.compile(r"(다|함|음)\.?$")


def _norm(value):
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", value or ""))


def _title_key(title):
    return _norm(LEADING_MARK.sub("", title.strip(), count=1))


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


def _printed_toc(paragraphs):
    start = next(
        (index for index, (_, value, _, top) in enumerate(paragraphs)
         if top and _norm(value) == "목차"), None
    )
    if start is None:
        return [], set()
    entries, toc_pages = [], set(paragraphs[start][2])
    for _, value, pages, _ in paragraphs[start + 1:]:
        if entries and pages and min(pages) > max(toc_pages) and not (
            TOC_ROW.match(value) or ROMAN.match(value)
        ):
            break
        match = TOC_ROW.match(value)
        if match:
            title = match["title"].strip()
            level = 1 if ROMAN.match(title) or not NUMBERED.match(title) else 2
            entries.append({"t": title, "printed": int(match["page"]), "lv": level})
            toc_pages.update(pages)
            continue
        if ROMAN.match(value):
            entries.append({"t": value, "printed": None, "lv": 1})
            toc_pages.update(pages)
        elif entries and pages and min(pages) > max(toc_pages):
            break
    # Section headings in a printed TOC often omit their page number. Their
    # first numbered child supplies the printed page used for navigation.
    for index, entry in enumerate(entries):
        if entry["printed"] is None:
            entry["printed"] = next(
                (later["printed"] for later in entries[index + 1:]
                 if later["printed"] is not None), None
            )
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
    offset = offsets.most_common(1)[0][0] if offsets else None
    output, previous = [], 0
    for entry in entries:
        key = _title_key(entry["t"])
        candidates = {
            physical for physical, printed in page_table.items()
            if printed == entry["printed"] and physical not in toc_pages
        }
        expected = entry["printed"] + offset if (
            entry["printed"] is not None and offset is not None
        ) else None
        if expected in page_table and expected not in toc_pages:
            candidates.add(expected)
        hits = sorted(page for page in candidates if key and key in texts.get(page, ""))
        item = {"t": entry["t"], "lv": entry["lv"],
                "printed": entry["printed"], "page": None, "seen": False}
        if len(hits) == 1:
            item.update(page=hits[0], seen=True)
        elif key and expected is not None:
            nearby = [
                page for page in range(max(previous, expected - 1, 1), expected + 5)
                if page in page_table and page not in toc_pages
                and key in texts.get(page, "")
            ]
            if len(nearby) == 1:
                item.update(page=nearby[0], seen=True, adjusted=True)
        previous = item["page"] or previous
        output.append(item)
    for index, item in enumerate(output):
        if item["seen"] or item["lv"] != 1 or not ROMAN.match(item["t"]):
            continue
        child = next(
            (later for later in output[index + 1:]
             if later["lv"] == 2 and later["seen"]
             and later["printed"] == item["printed"]),
            None,
        )
        if child:
            item.update(page=child["page"], seen=True, adjusted=True)
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
            clean = len(pages) == 1 and page_table.get(pages[0]) is not None
            output.append({"t": value, "lv": level, "page": pages[0],
                           "seen": clean, "printed": page_table.get(pages[0])})
    return output


def build_toc(conn, document_id, revision, pages):
    """Return preview-compatible TOC entries for this immutable parse revision."""
    page_table = {row["n"]: row["label"] for row in pages}
    paragraphs = _paragraphs(conn, document_id, revision)
    printed, toc_pages = _printed_toc(paragraphs)
    return (_locate_printed(printed, page_table, paragraphs, toc_pages)
            if printed else _heading_toc(paragraphs, page_table))


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
        (document_id, revision, json.dumps(toc, ensure_ascii=False)),
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
            return json.loads(row[0])
    return build_toc(conn, document_id, revision, pages)
