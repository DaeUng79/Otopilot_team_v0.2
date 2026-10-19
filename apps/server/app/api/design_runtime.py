"""Attach behavior to immutable design HTML; never replace CSS or screen markup."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT.parent / "web"
SCRIPT = re.compile(r"(<script\b[^>]*>)([\s\S]*?)(</script>)", re.IGNORECASE)


def connected_html(relative: str) -> HTMLResponse | None:
    """Attach screen behavior to the English-path runtime copy under src."""
    base = WEB / "src/runtime"
    target = (base / relative).resolve()
    if not target.is_relative_to(base.resolve()):
        raise HTTPException(404)
    if target.suffix != ".html" or not target.is_file():
        return None
    parts = relative.split("/")
    screen = (
        "ENTRY"
        if "entry" in parts
        else next((p[:5] for p in parts if re.match(r"(?:SA|PM|EV)-\d\d(?:-|$)", p)), "")
    )
    key = screen + ("-overview" if target.name == "overview.html" else "")
    folders = list((WEB / "src/screens").glob("*/" + screen + "-*"))
    binding = (
        (
            folders[0]
            / ("overview-binding.js" if key.endswith("-overview") else "binding.js")
        )
        if len(folders) == 1
        else WEB / "missing-binding"
    )
    if screen in {"PM-08"}:
        binding = WEB / "src/bindings/external-boundary.js"
    content = target.read_bytes().replace(b"\r\n", b"\n")
    html = content.decode("utf8")
    if relative in {"dept-admin/PM-02/design/rfp-preview.html",
                    "dept-admin/PM-02/design/requirements-preview.html"}:
        return html_response(html)
    if screen in {"EV-03", "EV-04", "EV-05"}:
        # Keep the approved layout; use the integrated document behavior instead
        # of prototype data and scripts.
        html = SCRIPT.sub("", html)
        html = html.replace('href="../../_eval.css"', 'href="/src/evaluator/common/eval.css"')
        html = html.replace('href="../../EV-05/design/compare.html"', 'id="to-compare" href="../../EV-05/design/compare.html"')
        html = html.replace('href="../../EV-04/design/proposals.html"', 'id="to-proposals" href="../../EV-04/design/proposals.html"')
        css = '<link rel="stylesheet" href="/src/evaluator/common/reader.css">'
        if screen != "EV-03":
            name = "proposals" if screen == "EV-04" else "compare"
            css += f'<link rel="stylesheet" href="/src/evaluator/{screen}/{name}.css">'
        html = html.replace('</head>', css + '</head>')
        html = html.replace('</body>', f'<script type="module" src="/src/evaluator/{screen}/main.js"></script></body>')
        return html_response(html)
    if not screen or not binding.is_file():
        return html_response(html)
    scripts = [m for m in SCRIPT.finditer(html) if "src=" not in m[1] and m[2].strip()]
    if not scripts:
        raise HTTPException(409, "원본 기능 스크립트를 확인하세요.")
    main = scripts[-1]
    source = main[2].strip()
    # These are prototype data constants, not markup or styling. The binding
    # replaces their values with the current session's authoritative data.
    if screen == "PM-03":
        # 기술 배점 합계는 평가표 초안(AI 또는 서식)의 값으로 바뀐다.
        source = _patch(source, "const LIMIT=80;", "let LIMIT=80;")
    if screen == "PM-04":
        # 정원 5~9명(직접 선정은 체크한 인원), 예비위원 1~3명 (2026-10-18 사용자 결정).
        source = _patch(source, "S.cap<=7||lk", "S.cap<=5||lk")
        source = _patch(source, "(7~9명)", "(5~9명)")
        source = _patch(source, "${[1,2,3,4].map(n=>", "${[1,2,3].map(n=>")
        source = _patch(
            source,
            "{ok:!dupo,t:'예비 순서',s:res.length?(dupo?'순서를 1부터 겹치지 않게 정해 주세요':`예비 ${res.length}명 · 순서 확인`):'예비 없음'}",
            "{ok:!dupo&&res.length>=1&&res.length<=3,t:'예비위원 1~3명 (권장 2명)',s:res.length<1||res.length>3?`예비 ${res.length}명 · 1~3명을 정해 주세요`:(dupo?'순서를 1부터 겹치지 않게 정해 주세요':`예비 ${res.length}명 · 순서 확인`)}",
        )
    if screen == "PM-05":
        source = source.replace("const CAP=7,MIN=5;", "let CAP=7,MIN=5;")
    if screen == "PM-06":
        source = source.replace("const N=7;", "let N=7;")
        source = source.replace("x.toFixed(1)", "x.toFixed(2)")
    if screen == "PM-07":
        source = source.replace("r.field===ff", "r.field.split(', ').includes(ff)")
    # Expose the original renderer's lexical data only inside its own function.
    source = re.sub(r"^\(function\s*\([^)]*\)\s*\{", "", source)
    if source != main[2].strip():
        source = re.sub(r"\}\)\(\);?\s*$", "", source)
    code = binding.read_text("utf8")
    wrapped = (
        '<script src="/src/bindings/common.js"></script>\n<script>\n'
        "(async function(){try{await Live.begin("
        + json.dumps(key)
        + ");\n"
        + source
        + "\n"
        + code
        + "\nLive.finish();}catch(error){Live.fail(error);}})();\n</script>"
    )
    rendered = html[: main.start()] + wrapped + html[main.end() :]
    return html_response(rendered)


def _patch(source: str, old: str, new: str) -> str:
    """Replace a prototype constant; fail loudly if the design file drifted."""
    if old not in source:
        raise HTTPException(409, f"원본 화면 스크립트에서 바꿀 구문을 찾지 못했습니다: {old[:40]}")
    return source.replace(old, new)


def html_response(rendered: str) -> HTMLResponse:
    """Permit only the exact inline scripts in the verified, served document."""
    hashes = {
        "'sha256-"
        + base64.b64encode(hashlib.sha256(m[2].encode("utf8")).digest()).decode("ascii")
        + "'"
        for m in SCRIPT.finditer(rendered)
        if not re.search(r"\bsrc\s*=", m[1], re.IGNORECASE) and m[2].strip()
    }
    return HTMLResponse(
        rendered,
        headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self' "
            + " ".join(sorted(hashes))
            + "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
            "base-uri 'none'; form-action 'self'"
        },
    )
