"""자동 근거 찾기 (평가위원 쪽 대체 경로).

담당자가 확정한 근거(문서 DB proposal_evidence CONFIRMED)나 PRO-04 의 제안(SUGGESTED)이 아직 없을 때,
제안서 본문(문서 DB blocks, 회차에 고정된 parse_revision)에서 평가항목의 제목·설명과 겹치는 문단을 찾아 후보로 돌려준다.
사전·LLM 없이 토큰 일치(문서 안 희소성 가중치)와 글자 2-gram 겹침만 쓰므로 결정적이고 재현 가능하다.
결과는 어디까지나 '후보'라서 화면에는 '자동 추천 · 담당자 확정 전' 으로 표시하고, 담당자 확정 근거가 생기면 그쪽이 우선한다.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from typing import Any, Iterable

# 평가 설명에 흔한 '평가 관점' 낱말과 조사. 제안서 본문과 겹쳐도 근거가 되지 않으므로 뺀다.
STOPWORDS = frozenset({
    "및", "등", "위한", "위해", "계획의", "구체성", "실현", "가능성", "적절성", "체계성", "실효성", "타당성", "충실성", "우수성",
    "명확성", "완성도", "여부", "정도", "수준", "대한", "관한", "있는", "있음", "없음", "경우", "통한", "통해", "하는", "되는", "제시",
    "제안", "내용", "방안", "사항", "의", "을", "를", "이", "가", "은", "는", "에", "로", "과", "와",
})
_PARTICLE = re.compile(r"(의|을|를|이|가|은|는|에|로|과|와|및)$")
_SPLIT = re.compile(r"[\s\W_]+")
EXCERPT_CHARS = 160
HEADING_CHARS = 40
MIN_SCORE = 2.0
MIN_TITLE_FRACTION = 0.4   # 제목 낱말 가중치의 이만큼은 맞아야 후보다
MIN_BIGRAM_RATIO = 0.5     # 또는 제목 글자 2-gram 의 절반 이상이 들어 있어야 한다


def normalize(text: str | None) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", text or ""))


def tokens(text: str | None) -> list[str]:
    """2글자 이상 낱말. 3글자 이상이면 끝 조사를 뗀다. 평가 관점 낱말은 뺀다."""
    out: list[str] = []
    for raw in _SPLIT.split(unicodedata.normalize("NFKC", text or "")):
        word = _PARTICLE.sub("", raw) if len(raw) > 2 else raw
        if len(word) >= 2 and word not in STOPWORDS and word not in out:
            out.append(word)
    return out


def bigrams(text: str | None) -> set[str]:
    flat = normalize(text)
    return {flat[i:i + 2] for i in range(len(flat) - 1)}


class Query:
    """평가항목 하나에 대한 질의.

    제목 낱말은 문서 안 희소성(idf)으로 가중치를 매겨, 맞은 가중치 비율 × 6점. 설명 낱말은 0.7점씩,
    제목 글자 2-gram 겹침 비율은 최대 1.5점. 짧은 문단(절 제목)에 제목 가중치의 절반 이상이 맞으면 +2.5점.
    corpus 는 문서의 문단(정규화된 문자열)이며, 없으면 모든 낱말 가중치를 1로 본다.
    """

    def __init__(self, title: str, description: str | None = None, corpus: Iterable[str] | None = None) -> None:
        self.title_tokens = [normalize(t) for t in tokens(title)]
        self.desc_tokens = [normalize(t) for t in tokens(description) if normalize(t) not in self.title_tokens]
        self.title_bigrams = bigrams(title)
        flats = list(corpus) if corpus is not None else []
        total = len(flats)
        self.weights = {t: (math.log((total + 1) / (sum(1 for f in flats if t in f) + 1)) if total else 1.0) or 0.01 for t in self.title_tokens}
        self.total_weight = sum(self.weights.values())

    @property
    def usable(self) -> bool:
        return bool(self.title_tokens) or len(self.title_bigrams) >= 2

    def score(self, text: str, flat: str | None = None) -> float:
        flat = normalize(text) if flat is None else flat
        if not flat:
            return 0.0
        matched = sum(self.weights[t] for t in self.title_tokens if t in flat)
        fraction = matched / self.total_weight if self.total_weight else 0.0
        ratio = len(self.title_bigrams & bigrams(text)) / len(self.title_bigrams) if self.title_bigrams else 0.0
        if fraction < MIN_TITLE_FRACTION and ratio < MIN_BIGRAM_RATIO:
            return 0.0
        score = 6.0 * fraction + 0.7 * sum(1 for t in self.desc_tokens if t in flat) + 1.5 * ratio
        if len(text.strip()) <= HEADING_CHARS and fraction >= 0.5:
            score += 2.5  # 짧은 문단에 제목이 대부분 들어 있다 → 절 제목으로 본다
        return score


def _paragraphs(conn: sqlite3.Connection, document_id: str, parse_revision: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT block_id, text, physical_page_numbers_json FROM blocks WHERE document_id = ? AND revision = ? AND type = 'paragraph' "
        "AND length(trim(text)) >= 6 ORDER BY order_index", (document_id, parse_revision)).fetchall()


def _excerpt(rows: list[sqlite3.Row], index: int) -> str:
    """절 제목이면 같은 쪽의 다음 문단을 이어 붙여 맥락을 준다."""
    text = rows[index]["text"].strip()
    if len(text) <= HEADING_CHARS:
        page = json.loads(rows[index]["physical_page_numbers_json"] or "[]")[:1]
        for follow in rows[index + 1:index + 3]:
            if json.loads(follow["physical_page_numbers_json"] or "[]")[:1] != page:
                break
            text = f"{text} — {follow['text'].strip()}"
            if len(text) >= EXCERPT_CHARS:
                break
    return text[:EXCERPT_CHARS]


def find_candidates(conn: sqlite3.Connection, document_id: str, parse_revision: str, title: str, description: str | None = None,
                    *, limit: int = 3) -> list[dict[str, Any]]:
    """문서(고정 버전)에서 평가항목과 가장 겹치는 문단을 쪽당 하나씩, 점수순으로 최대 limit 개 돌려준다.
    [{page, block_id, excerpt, score}] · 하나도 없으면 []."""
    rows = _paragraphs(conn, document_id, parse_revision)
    if not rows:
        return []
    flats = [normalize(r["text"]) for r in rows]
    query = Query(title, description, flats)
    if not query.usable:
        return []
    scored: list[tuple[float, int, int]] = []
    for index, row in enumerate(rows):
        pages = json.loads(row["physical_page_numbers_json"] or "[]")
        if not pages:
            continue
        value = query.score(row["text"], flats[index])
        if value >= MIN_SCORE:
            scored.append((value, int(pages[0]), index))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    output: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for value, page, index in scored:
        if page in seen_pages:
            continue
        seen_pages.add(page)
        output.append({"page": page, "block_id": rows[index]["block_id"], "excerpt": _excerpt(rows, index), "score": round(value, 2)})
        if len(output) >= limit:
            break
    return output
