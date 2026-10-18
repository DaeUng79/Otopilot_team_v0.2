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
         if top and re.sub(r"\s", "", value) == "목차"), None
    )
    if start is None:
        return [], set()
    entries, toc_pages = [], set(paragraphs[start][2])
    for _, value, pages, _ in paragraphs[start + 1:]:
        match = TOC_ROW.match(value)
        if not match:
            if entries:
                break
            continue
        title = match["title"].strip()
        level = 1 if NUMBERED.match(title) or ROMAN.match(title) else 2
        entries.append({"t": title, "printed": int(match["page"]), "lv": level})
        toc_pages.update(pages)
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
        expected = entry["printed"] + offset if offset is not None else None
        if expected in page_table:
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
