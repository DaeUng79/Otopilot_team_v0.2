"""문서 도우미(CHAT-01·02) 어댑터. 오대웅 모듈 `apps/chatbot/chatbot.py` 를 경로 import 로 재사용한다(chatbot 무수정).

- 업체마다 회차에 고정된 제안서(document_id)의 활성 파싱 본문 전체를 문맥으로 보내고(임베딩 없음), 답변을 업체별로 돌려준다.
- 평가 회차의 고정 parse_revision 스냅샷을 읽는다. 이후 재파싱된 활성 버전은 답변 근거로 섞지 않는다.
- 질문·답변은 저장하지 않는다. 감사 기록에는 업체·글자 수·토큰 수만 남긴다.
- OPENAI_API_KEY 는 chatbot.get_client 가 환경변수 → 저장소 루트 .env 순으로 읽는다. 없으면 503 으로 "준비 중" 상태를 알린다.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any

from . import evidence
from .db import connect_documents
from .envelope import ApiError, upstream_unavailable
from .settings import PM01_DIR, REPO_ROOT

CHATBOT_PATH = REPO_ROOT / "apps" / "chatbot" / "chatbot.py"
STEP3_NAME = "apps.documents.requirements_extract"
STEP3_CANDIDATES = (
    PM01_DIR / "requirements_extract.py",
)
MAX_VENDORS = 3
MAX_HISTORY = 6
_PAGE_REF = re.compile(r"(?<!\d)(\d{1,4})(?:\s*[~\-–]\s*(\d{1,4}))?\s*(?:쪽|페이지|p\b)", re.IGNORECASE)
_PAGE_PREFIX = re.compile(r"\bp(?:age)?\.?\s*(\d{1,4})(?:\s*[~\-–]\s*(\d{1,4}))?", re.IGNORECASE)
_PAGE_LABEL = re.compile(r"\[\s*페이지\s*번호\s*(\d{1,4}(?:\s*[~\-–]\s*\d{1,4})?)\s*쪽\s*\]")

_lock = threading.Lock()
_module: ModuleType | None = None


def _load_file(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise upstream_unavailable("문서 도우미 모듈을 읽을 수 없어요.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_step3() -> None:
    """chatbot.py 가 `apps.documents.step3...` 를 패키지 import 하므로, 이 저장소 배치(코드는 PM-01 복사본·.documents)에 맞춰 채운다."""
    if STEP3_NAME in sys.modules:
        return
    try:
        importlib.import_module(STEP3_NAME)
        return
    except ImportError:
        pass
    path = next((p for p in STEP3_CANDIDATES if p.is_file()), None)
    if path is None:
        raise upstream_unavailable("문서 도우미가 쓰는 파서 모듈(step3)을 찾을 수 없어요.")
    for package, directory in (("apps", REPO_ROOT / "apps"), ("apps.documents", REPO_ROOT / "apps" / "documents")):
        if package not in sys.modules:
            stub = ModuleType(package)
            stub.__path__ = [str(directory)]  # 다른 apps.* 네임스페이스 import 도 계속 되도록 경로를 남긴다
            sys.modules[package] = stub
    _load_file(STEP3_NAME, path)


def load_chatbot() -> ModuleType:
    global _module
    with _lock:
        if _module is None:
            if not CHATBOT_PATH.is_file():
                raise upstream_unavailable("문서 도우미 모듈(apps/chatbot/chatbot.py)이 없어요.")
            _ensure_step3()
            _module = _load_file("chatbot_chatbot", CHATBOT_PATH)
        return _module


def make_client(chatbot: ModuleType):
    """OpenAI 클라이언트. 키가 없으면 503 으로 '준비 중' 을 알린다(키 값은 어디에도 남기지 않는다)."""
    try:
        for dependency in ('openai', 'tiktoken', 'dotenv'):
            if importlib.util.find_spec(dependency) is None:
                raise upstream_unavailable("문서 도우미 실행 환경이 준비되지 않았습니다. 담당자에게 문의해 주세요.")
        return chatbot.get_client()
    except chatbot.ChatbotError as exc:
        raise ApiError("UPSTREAM_UNAVAILABLE", "문서 도우미 연결 설정이 필요합니다. 담당자에게 문의해 주세요.", 503,
                       retryable=False) from exc
    except ImportError as exc:
        raise upstream_unavailable("문서 도우미 실행 환경이 준비되지 않았습니다.") from exc


def pages_from_text(text: str, *, limit: int = 8) -> list[int]:
    """답변 속 '12쪽', '12페이지', 'p.12' 및 쪽 범위를 모은다(문서 순)."""
    found: list[int] = []
    for pattern in (_PAGE_REF, _PAGE_PREFIX):
        for first, second in pattern.findall(text or ""):
            a = int(first)
            b = int(second) if second else a
            lo, hi = (a, b) if a <= b else (b, a)
            for page in range(lo, min(hi, lo + 3) + 1):
                if page >= 1 and page not in found:
                    found.append(page)
    return sorted(found)[:limit]


def tidy_answer(text: str) -> str:
    """'[페이지번호 12쪽]' 을 '[12쪽]' 으로 줄인다. 내용은 바꾸지 않는다."""
    return _PAGE_LABEL.sub(lambda m: f"[{m.group(1)}쪽]", text or "").strip()


def _history_messages(history: list[str]) -> list[dict[str, str]]:
    # 화면은 성공한 질문 글만 보낸다(답변은 저장하지 않는 정책). 이전 질문은 맥락으로만 넘긴다.
    return [{"role": "user", "content": f"(이전 질문) {q}"} for q in history[-MAX_HISTORY:] if q and q.strip()]


def _prepare_one(chatbot: ModuleType, docs_db: Path, proposal: dict[str, Any], question: str, history: list[str]):
    context = chatbot.load_context(
        docs_db, [proposal["document_id"]],
        revisions={proposal["document_id"]: proposal["parse_revision"]},
    )
    document = context["documents"][0]
    if document["revision"] != proposal["parse_revision"]:
        raise ApiError("STALE_SOURCE", "평가 시작 때 고정한 제안서와 현재 문서 버전이 달라요. 담당자에게 알려 주세요.", 409)
    messages, dropped, tokens = chatbot.build_messages(context["content"], _history_messages(history), question)
    return context, messages, dropped, tokens


def _finish_one(chatbot: ModuleType, context: dict, docs_db: Path, proposal: dict[str, Any],
                question: str, raw: str, dropped: int, tokens: int) -> dict[str, Any]:
    document = context["documents"][0]
    text, tables, _invalid = chatbot.answer_parts(raw, context["source_tables"])
    text = tidy_answer(text)
    known_pages = {p for block in document["blocks"] for p in block.get("pages", []) if isinstance(p, int) and p > 0}
    pages = [p for p in pages_from_text(text) if p in known_pages]
    page_source = "citation"
    table_refs = []
    for table in tables:
        block_pages = table["block"].get("physical_page_numbers") or []
        page = block_pages[0] if block_pages else None
        table_refs.append({"page": page, "block_id": table["block"].get("block_id")})
        if page in known_pages and page not in pages:
            pages.append(page)
    if not pages and text:
        with connect_documents(docs_db) as conn:
            candidates = evidence.find_candidates(conn, proposal["document_id"], proposal["parse_revision"], question, limit=3)
        pages = [item["page"] for item in candidates if item["page"] in known_pages]
        page_source = "candidate" if pages else "unavailable"
    pages = list(dict.fromkeys(pages))[:8] if page_source == "candidate" else sorted(set(pages))[:8]
    return {"text": text, "pages": pages, "page_source": page_source, "tables": table_refs,
            "history_dropped": dropped, "tokens": tokens}


def answer_one(chatbot: ModuleType, client, docs_db: Path, proposal: dict[str, Any], question: str, history: list[str]) -> dict[str, Any]:
    """업체 하나의 제안서로 답한다. 반환: {text, pages, tables, history_dropped} 또는 {text: None, error}."""
    try:
        context, messages, dropped, tokens = _prepare_one(chatbot, docs_db, proposal, question, history)
        raw = "".join(chatbot.stream_answer(client, messages))
    except chatbot.ChatbotError as exc:
        return {"text": None, "pages": [], "tables": [], "error": str(exc)}
    return _finish_one(chatbot, context, docs_db, proposal, question, raw, dropped, tokens)


def prepare_stream(docs_db: Path | None, proposals: list[dict[str, Any]], question: str, history: list[str]):
    """HTTP 응답을 시작하기 전에 설정·문서 버전·입력 한도를 검사한다."""
    if docs_db is None or not Path(docs_db).is_file():
        raise upstream_unavailable("문서 DB 에 연결할 수 없어 문서 도우미를 쓸 수 없어요.")
    if not proposals:
        raise ApiError("VALIDATION_FAILED", "물어볼 업체를 하나 이상 골라 주세요.", 422)
    if len(proposals) > MAX_VENDORS:
        raise ApiError("VALIDATION_FAILED", f"한 번에 {MAX_VENDORS}개 업체까지 물어볼 수 있어요.", 422)
    chatbot = load_chatbot()
    client = make_client(chatbot)
    prepared = []
    for proposal in proposals:
        try:
            context, messages, dropped, tokens = _prepare_one(chatbot, Path(docs_db), proposal, question, history)
            prepared.append((proposal, context, messages, dropped, tokens, None))
        except chatbot.ChatbotError as exc:
            prepared.append((proposal, None, None, 0, 0, str(exc)))
    return chatbot, client, Path(docs_db), question, prepared


def stream_answers(prepared):
    """업체별 텍스트 조각을 보내고 마지막에 출처가 포함된 확정 답변을 보낸다."""
    chatbot, client, docs_db, question, items = prepared
    for proposal, context, messages, dropped, tokens, error in items:
        vendor = proposal["session_proposal_id"]
        if error:
            yield {"type": "answer", "vendor": vendor, "answer": {"text": None, "pages": [], "tables": [], "error": error}}
            continue
        raw, shown = "", ""
        try:
            for chunk in chatbot.stream_answer(client, messages):
                raw += chunk
                visible, _, _ = chatbot.answer_parts(raw, context["source_tables"], streaming=True)
                if visible.startswith(shown):
                    delta = visible[len(shown):]
                    if delta:
                        yield {"type": "delta", "vendor": vendor, "text": delta}
                elif visible != shown:
                    yield {"type": "replace", "vendor": vendor, "text": visible}
                shown = visible
            answer = _finish_one(chatbot, context, docs_db, proposal, question, raw, dropped, tokens)
        except chatbot.ChatbotError as exc:
            answer = {"text": None, "pages": [], "tables": [], "error": str(exc)}
        yield {"type": "answer", "vendor": vendor, "answer": answer}
    yield {"type": "done"}


def answer_for_proposals(docs_db: Path | None, proposals: list[dict[str, Any]], question: str, history: list[str]) -> dict[str, Any]:
    """선택한 업체(최대 3)를 병렬로 묻고 업체별 답을 모은다. 반환: {answers: {session_proposal_id: …}, model}."""
    if docs_db is None or not Path(docs_db).is_file():
        raise upstream_unavailable("문서 DB 에 연결할 수 없어 문서 도우미를 쓸 수 없어요.")
    if not proposals:
        raise ApiError("VALIDATION_FAILED", "물어볼 업체를 하나 이상 골라 주세요.", 422, fields={"vendors": "업체를 골라 주세요."})
    if len(proposals) > MAX_VENDORS:
        raise ApiError("VALIDATION_FAILED", f"한 번에 {MAX_VENDORS}개 업체까지 물어볼 수 있어요.", 422, fields={"vendors": "업체 수를 줄여 주세요."})
    chatbot = load_chatbot()
    client = make_client(chatbot)
    docs_path = Path(docs_db)
    with ThreadPoolExecutor(max_workers=len(proposals)) as pool:
        futures = {p["session_proposal_id"]: pool.submit(answer_one, chatbot, client, docs_path, p, question, history) for p in proposals}
        answers = {pid: future.result() for pid, future in futures.items()}
    return {"answers": answers, "model": chatbot.MODEL}
