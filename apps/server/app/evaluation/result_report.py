"""RES-05 HTML: 내부 결재·상급자 보고용 '제안서 평가결과 보고서' (2026-10-18).

확정 집계(result_runs·result_items·result_inputs)와 제출·서명 기록을 그대로 읽어 사람이 읽는 문서로 만든다.
점수 계산과 순위는 result_service가 저장한 값만 쓰고 여기서 다시 계산하지 않는다. 이 모듈이 하는 일은
표시 변환뿐이다: 점수 저장값(×10000) → 점수, 제외 코드 → 한글, UTC → 한국표준시, 식별자 → 업체명·위원명.
해시 같은 검증 정보는 본문에서 빼고 별첨에만 둔다. 저장 구조는 바꾸지 않는다.

인쇄: A4 세로. 문서 전체를 표(.doc) 하나에 담아 thead·tfoot을 쪽마다 반복시키는 방식으로 쪽 머리글·바닥글을
만든다(Chrome은 @page 여백 상자를 지원하지 않는다). 작은 표는 .keep으로 한 쪽에 묶는다.
"""

import base64
import html
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.shared.db import DTO, Store, one, rows

KST = timezone(timedelta(hours=9))
EXCLUSION = {"NONE": "산정 포함", "LOWEST": "최저점 제외", "HIGHEST": "최고점 제외"}
PURPOSE = {"EVALUATION": "평가 제출 서명", "CHAIR_RESULT": "위원장 결과 확인 서명"}
ROMAN = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ"]


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def kst(iso: str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """ISO(UTC) 문자열 → 한국표준시 표기. 값이 없으면 '—'."""
    if not iso:
        return "—"
    try:
        moment = datetime.fromisoformat(str(iso))
    except ValueError:
        return esc(iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).strftime(fmt)


def pts(raw: int | str | None) -> str:
    """저장 점수(×10000 정수) → 소수 둘째 자리 점수 문자열."""
    if raw is None:
        return "—"
    return f"{(Decimal(int(raw)) / Decimal(10000)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def allocation(raw: int) -> str:
    """배점은 10, 20처럼 정수로 보이면 소수점을 뺀다."""
    text = pts(raw)
    return text.rstrip("0").rstrip(".") if "." in text else text


def average(value: str) -> str:
    """result_items.average_decimal(이미 반올림된 문자열)을 자리수만 맞춰 표시한다."""
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):,.2f}"


def policy_lines(policy: DTO) -> list[str]:
    lines = []
    exclude = policy.get("exclude")
    if exclude == "one_lowest_one_highest_total":
        lines.append("업체별로 참여 위원의 평가 총점 가운데 최고점 1명과 최저점 1명을 제외합니다.")
    elif exclude:
        lines.append(f"제외 규칙: {exclude}")
    places = policy.get("decimal_places")
    rounding = policy.get("rounding")
    place_text = {1: "첫째", 2: "둘째", 3: "셋째"}.get(places, f"{places}번째")
    round_text = "반올림" if rounding == "ROUND_HALF_UP" else str(rounding or "")
    lines.append(
        f"제외 후 남은 위원의 총점 합계를 산정 대상 위원 수로 나눈 값을 최종 평가점수로 하며, "
        f"소수점 {place_text} 자리까지 {round_text}하여 표시합니다."
    )
    if policy.get("rank") == "competition_on_display_average":
        lines.append("최종 평가점수가 높은 업체부터 순위를 정하며, 점수가 같으면 공동 순위로 하고 다음 순위는 그 수만큼 건너뜁니다.")
    if policy.get("tie_break") == "participant_id_ascending":
        lines.append("최고점 또는 최저점이 같은 위원이 여럿이면 시스템에 등록된 참여자 순서에 따라 1명만 제외합니다.")
    return lines


def _admin_lookup(s: Store, project_id: str) -> DTO:
    """관리 DB에서 업체명·주관 부서·평가일을 읽는다. 평가 DB 사본에는 업체명이 없다."""
    info: DTO = {"vendor_names": {}, "department": None, "evaluation_date": None}
    try:
        with s.connect("admin") as adb:
            info["vendor_names"] = {
                r["id"]: r["legal_name"]
                for r in adb.execute(
                    "SELECT id, legal_name FROM project_vendors WHERE project_id=?", (project_id,)
                )
            }
            dept = adb.execute(
                "SELECT d.name, d.organization_name FROM projects p JOIN departments d ON d.id=p.department_id WHERE p.id=?",
                (project_id,),
            ).fetchone()
            if dept:
                info["department"] = " ".join(x for x in (dept["organization_name"], dept["name"]) if x)
            date = adb.execute(
                "SELECT evaluation_date FROM project_evaluation_dates WHERE project_id=?", (project_id,)
            ).fetchone()
            info["evaluation_date"] = date[0] if date else None
    except sqlite3.Error:
        pass
    return info


def report_context(c: sqlite3.Connection, s: Store, session: DTO, payload: DTO, confirmation: DTO) -> DTO:
    sid = session["id"]
    project = one(c, "SELECT name FROM ref_projects WHERE id=?", (session["project_id"],))
    admin = _admin_lookup(s, session["project_id"])

    proposals = rows(c, "SELECT * FROM session_proposals WHERE session_id=? ORDER BY display_code", (sid,))
    vendors = []
    for p in proposals:
        name = admin["vendor_names"].get(p["vendor_id"])
        vendors.append({"id": p["id"], "code": p["display_code"], "short": f"{p['display_code']}사",
                        "name": name, "label": name or f"{p['display_code']}사"})
    by_vendor = {v["id"]: v for v in vendors}

    participants = rows(
        c,
        "SELECT p.id, a.name_snapshot AS name, a.organization_snapshot AS org FROM session_participants p "
        "JOIN ref_committee_assignments a ON a.id=p.assignment_id WHERE p.session_id=? ORDER BY a.name_snapshot, p.id",
        (sid,),
    )
    chair_id = session["chair_participant_id"]
    for p in participants:
        p["is_chair"] = p["id"] == chair_id
    by_participant = {p["id"]: p for p in participants}

    items = {i["session_proposal_id"]: i for i in payload["items"]}
    inputs = {(i["session_proposal_id"], i["participant_id"]): i for i in payload["inputs"]}

    criteria = rows(
        c,
        "SELECT id, code, title, max_score FROM ref_approved_criteria_items WHERE approved_criteria_version_id=? "
        "AND is_scorable=1 AND is_deleted=0 ORDER BY sort_order, id",
        (session["approved_criteria_version_id"],),
    )
    version = one(
        c,
        "SELECT approval_no, total_max_score, approved_at, snapshot_sha256 FROM ref_approved_criteria_versions WHERE id=?",
        (session["approved_criteria_version_id"],),
    )
    sheets = rows(
        c,
        "SELECT sh.id, sh.participant_id, sh.session_proposal_id, sh.total_score, o.opinion FROM score_sheets sh "
        "LEFT JOIN score_sheet_opinions o ON o.sheet_id=sh.id WHERE sh.session_id=?",
        (sid,),
    )
    entries: dict[str, dict[str, int | None]] = {}
    for e in rows(
        c,
        "SELECT e.sheet_id, e.criterion_id, e.score FROM score_entries e JOIN score_sheets sh ON sh.id=e.sheet_id WHERE sh.session_id=?",
        (sid,),
    ):
        entries.setdefault(e["sheet_id"], {})[e["criterion_id"]] = e["score"]
    sheet_of = {(sh["participant_id"], sh["session_proposal_id"]): sh for sh in sheets}

    submissions = {r["participant_id"]: r for r in rows(c, "SELECT * FROM evaluation_submissions WHERE session_id=?", (sid,))}
    signatures = {
        r["id"]: r
        for r in rows(
            c,
            "SELECT id, signer_participant_id, purpose, payload_sha256, image_blob, image_sha256, signed_at, consent_text_version "
            "FROM signatures WHERE session_id=?",
            (sid,),
        )
    }
    run = payload["run"]
    try:
        policy = json.loads(run.get("policy_snapshot_json") or session["aggregation_policy_json"])
    except (TypeError, ValueError):
        policy = {}

    # 업체별 산정 요약(표시용). 합계·제외·평균은 저장값을 그대로 쓴다.
    summary = []
    for v in vendors:
        item = items.get(v["id"])
        scored = []
        for p in participants:
            entry = inputs.get((v["id"], p["id"]))
            scored.append({"participant": p, "score": entry["total_score"] if entry else None,
                           "exclusion": entry["exclusion"] if entry else None})
        total_all = sum(x["score"] for x in scored if x["score"] is not None)
        highest = next((x for x in scored if x["exclusion"] == "HIGHEST"), None)
        lowest = next((x for x in scored if x["exclusion"] == "LOWEST"), None)
        included = [x for x in scored if x["exclusion"] == "NONE"]
        summary.append({"vendor": v, "item": item, "scored": scored, "total_all": total_all,
                        "highest": highest, "lowest": lowest, "included": included})
    ranked = sorted([x for x in summary if x["item"]], key=lambda x: (x["item"]["rank"], x["vendor"]["code"]))

    return {
        "project_name": project["name"], "department": admin["department"], "evaluation_date": admin["evaluation_date"],
        "session": session, "run": run, "confirmation": confirmation, "policy": policy,
        "vendors": vendors, "by_vendor": by_vendor, "participants": participants, "by_participant": by_participant,
        "chair": by_participant.get(chair_id), "items": items, "summary": summary, "ranked": ranked,
        "criteria": criteria, "criteria_version": version, "sheet_of": sheet_of, "entries": entries,
        "submissions": submissions, "signatures": signatures,
    }


CSS = """
:root{--navy:#1f3864;--ink:#111827;--muted:#4b5563;--line:#b9c2cc;--soft:#e3e8ee;--head:#f1f4f8;--accent:#eaf0f8}
*{box-sizing:border-box}
html,body{margin:0;background:#fff;color:var(--ink)}
body{font-family:"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo","Noto Sans KR","Noto Sans CJK KR",sans-serif;font-size:10.5pt;line-height:1.55;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.sheet{max-width:210mm;margin:0 auto;padding:18mm 16mm 22mm;background:#fff}
.toolbar{position:sticky;top:0;z-index:5;display:flex;justify-content:space-between;align-items:center;gap:12px;background:#fff;border-bottom:1px solid var(--soft);padding:10px 16px;font-size:10pt;color:var(--muted)}
.toolbar button{border:1px solid var(--navy);background:var(--navy);color:#fff;border-radius:4px;padding:7px 14px;font:inherit;font-weight:700;cursor:pointer}
.doc{width:100%;border-collapse:collapse;margin:0}
.doc>thead,.doc>tfoot{display:none}
.doc>thead>tr>td,.doc>tfoot>tr>td,.doc>tbody>tr>td{border:0;padding:0;text-align:left;vertical-align:top;background:transparent}
.doc>thead>tr,.doc>tfoot>tr,.doc>tbody>tr{break-inside:auto;page-break-inside:auto}
.run-head,.run-foot{display:flex;justify-content:space-between;gap:8mm;font-size:8.5pt;color:#6b7280;white-space:nowrap}
.run-head{border-bottom:1px solid var(--soft);padding:0 0 1.2mm;margin:0 0 5mm}
.run-foot{border-top:1px solid var(--soft);padding:1.2mm 0 0;margin:5mm 0 0}
.doc-title{text-align:center;border-top:3px solid var(--navy);border-bottom:1px solid var(--navy);padding:9mm 4mm 7mm;margin:0 0 8mm}
.doc-kind{margin:0 0 2mm;font-size:11pt;letter-spacing:.35em;color:var(--navy);font-weight:700}
h1{margin:0;font-size:19pt;line-height:1.35;color:var(--navy);letter-spacing:-.02em;word-break:keep-all}
.doc-meta{margin:3mm 0 0;color:var(--muted);font-size:10pt}
h2{font-size:13.5pt;color:var(--navy);border-bottom:1.5px solid var(--navy);padding-bottom:1.5mm;margin:9mm 0 3.5mm;break-after:avoid;page-break-after:avoid}
h3{font-size:11pt;color:var(--navy);margin:5.5mm 0 2mm;break-after:avoid;page-break-after:avoid}
h2:first-child{margin-top:0}
p{margin:0 0 2.5mm;word-break:keep-all}
table{width:100%;border-collapse:collapse;margin:0 0 4mm;font-size:10pt;break-inside:auto}
table.keep{break-inside:avoid;page-break-inside:avoid}
thead{display:table-header-group}
tr{break-inside:avoid;page-break-inside:avoid}
th,td{border:1px solid var(--line);padding:1.7mm 2.4mm;vertical-align:middle;text-align:center;word-break:keep-all}
th{background:var(--head);font-weight:700;color:#1f2937}
.nw{white-space:nowrap}
td.l,th.l{text-align:left}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.sub,.sub{color:var(--muted);font-size:9pt}
table.kv th{width:34mm;text-align:left}
table.kv td{text-align:left}
tr.rank-1 td{background:var(--accent);font-weight:700}
td.score{font-weight:700;font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:8.5pt;line-height:1.5;padding:0 1.6mm;border-radius:2px;border:1px solid var(--line);color:var(--muted);background:#fff;white-space:nowrap}
.tag.hi{border-color:#b45309;color:#92400e;background:#fff7ed}
.tag.lo{border-color:#1d4ed8;color:#1e40af;background:#eff6ff}
.summary{border:1px solid var(--line);border-left:4px solid var(--navy);background:#fafbfd;padding:3mm 4mm;margin:2mm 0 4mm;break-inside:avoid;page-break-inside:avoid}
.summary b{color:var(--navy)}
ul.rule{margin:0 0 3mm;padding-left:5mm}ul.rule li{margin:0 0 1mm}
.note{color:var(--muted);font-size:9pt;margin:1mm 0 3mm}
.page{break-before:page;page-break-before:always}
.sig-table td{height:22mm}
.sig-table img{height:18mm;max-width:60mm;object-fit:contain;display:block;margin:0 auto}
.mono{font-family:Consolas,"D2Coding","Courier New",monospace;font-size:8.5pt;word-break:break-all;text-align:left}
.verify th{width:44mm}.verify td{text-align:left;font-size:9pt}
@page{size:A4 portrait;margin:14mm 15mm 14mm}
@media print{
 body{font-size:10pt}
 .toolbar{display:none}
 .sheet{max-width:none;margin:0;padding:0}
 .doc>thead{display:table-header-group}
 .doc>tfoot{display:table-footer-group}
 a{color:inherit;text-decoration:none}
}
@media screen{body{background:#e9ecf0}.sheet{box-shadow:0 1px 4px rgba(0,0,0,.12);margin:14px auto 40px}}
"""


def _overview(ctx: DTO) -> str:
    s, run = ctx["session"], ctx["run"]
    vendors = ctx["vendors"]
    chair = ctx["chair"]
    date = ctx["evaluation_date"] or kst(s["locked_at"], "%Y-%m-%d")
    period = f"{esc(date)} {kst(s['locked_at'], '%H:%M')} ~ {kst(s['closed_at'], '%H:%M')} <span class='sub'>(평가 시작 ~ 결과 확정, 한국표준시)</span>"
    vendor_text = f"{len(vendors)}개 업체 · " + ", ".join(
        f"{esc(v['code'])}: {esc(v['name'])}" if v["name"] else f"{esc(v['code'])}: <span class='sub'>업체명 미등록</span>" for v in vendors
    )
    member_text = f"{run['participant_count']}명" + (f" (위원장 {esc(chair['name'])} 포함)" if chair else "")
    member_text += f" <span class='sub'>· 회차 정원 {s['target_count']}명, 최소 참석 {s['minimum_attendees']}명</span>"
    cv = ctx["criteria_version"]
    method = (f"제안서 평가(승인 평가표 제{cv['approval_no']}차, 총 {allocation(cv['total_max_score'])}점, "
              f"평가항목 {len(ctx['criteria'])}개) · 위원별 항목 점수 합계를 업체별 총점으로 함")
    rule = policy_lines(ctx["policy"])
    rule_text = " ".join(rule[:2]) if rule else "—"
    return f"""
<h2>{ROMAN[0]}. 평가 개요</h2>
<table class="kv keep">
<tr><th>사업명</th><td>{esc(ctx['project_name'])}</td></tr>
<tr><th>주관 부서</th><td>{esc(ctx['department']) if ctx['department'] else '—'}</td></tr>
<tr><th>평가 일시</th><td>{period}</td></tr>
<tr><th>평가 회차</th><td>제{s['round_no']}차</td></tr>
<tr><th>평가 대상 업체</th><td>{vendor_text}</td></tr>
<tr><th>참여 평가위원</th><td>{member_text}</td></tr>
<tr><th>평가 방법</th><td>{esc(method)}</td></tr>
<tr><th>점수 산정 기준</th><td>{esc(rule_text)}</td></tr>
</table>"""


def _summary(ctx: DTO) -> str:
    ranked = ctx["ranked"]
    rows_html = ""
    for x in ranked:
        v, item = x["vendor"], x["item"]
        rows_html += (f"<tr class='rank-{item['rank']}'><td class='nw'>{item['rank']}위</td><td>{esc(v['code'])}</td>"
                      f"<td class='l'>{esc(v['name']) if v['name'] else '<span class=sub>업체명 미등록</span>'}</td>"
                      f"<td class='num score'>{average(item['average_decimal'])}</td>"
                      f"<td class='nw'>{item['included_count']}명</td><td class='num'>{pts(item['included_sum'])}</td></tr>")
    compare = ""
    for x in ranked:
        v, item = x["vendor"], x["item"]
        hi = f"{pts(x['highest']['score'])}<br><span class='sub nw'>{esc(x['highest']['participant']['name'])}</span>" if x["highest"] else "—"
        lo = f"{pts(x['lowest']['score'])}<br><span class='sub nw'>{esc(x['lowest']['participant']['name'])}</span>" if x["lowest"] else "—"
        compare += (f"<tr><td class='nw'>{esc(v['short'])}</td><td class='num'>{pts(x['total_all'])}</td><td class='num'>{hi}</td>"
                    f"<td class='num'>{lo}</td><td class='num'>{pts(item['included_sum'])}</td><td class='nw'>{item['included_count']}명</td>"
                    f"<td class='num score'>{average(item['average_decimal'])}</td></tr>")
    # 요약 문구: 순위대로 나열. 공동 순위는 '공동 n위'.
    phrases = []
    counts: dict[int, int] = {}
    for x in ranked:
        counts[x["item"]["rank"]] = counts.get(x["item"]["rank"], 0) + 1
    for x in ranked:
        v, item = x["vendor"], x["item"]
        rank_word = f"공동 {item['rank']}위" if counts[item["rank"]] > 1 else f"{item['rank']}위"
        phrases.append(f"<b>{esc(v['label'])}</b>({esc(v['short'])}) {average(item['average_decimal'])}점으로 {rank_word}")
    n = ctx["run"]["participant_count"]
    text = (f"참여 평가위원 {n}명의 평가 총점에서 업체별 최고점·최저점 각 1명을 제외한 {n - 2}명의 평균으로 산정한 결과, "
            + ", ".join(phrases) + "로 평가되었습니다.") if phrases else "확정된 집계 결과가 없습니다."
    missing = any(not v["name"] for v in ctx["vendors"])
    note = "<p class='note'>※ 업체명이 등록되지 않은 업체는 평가 시 표시명(A·B…)으로 표기했습니다.</p>" if missing else ""
    return f"""
<h2>{ROMAN[1]}. 평가결과 종합</h2>
<table class="keep">
<thead><tr><th class="nw" style="width:14mm">순위</th><th class="nw" style="width:13mm">구분</th><th class="l">업체명</th><th class="nw" style="width:28mm">최종 평가점수</th><th class="nw" style="width:30mm">산정 대상 위원</th><th class="nw" style="width:26mm">산정 합계</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
{note}
<div class="summary"><p style="margin:0">{text}</p></div>
<h3>업체별 점수 비교</h3>
<table class="keep">
<thead><tr><th class="nw" style="width:16mm">업체</th><th>전체 위원<br>총점 합계</th><th class="nw">최고점(제외)</th><th class="nw">최저점(제외)</th><th class="nw">산정 합계</th><th class="nw">산정 대상</th><th class="nw">최종 평가점수</th></tr></thead>
<tbody>{compare}</tbody>
</table>
<p class="note">최종 평가점수 = 산정 합계 ÷ 산정 대상 위원 수 (소수점 둘째 자리까지, 반올림). 점수 단위: 점.</p>"""


def _detail(ctx: DTO) -> str:
    summary, participants = ctx["summary"], ctx["participants"]
    head = "".join(f"<th colspan='2'>{esc(x['vendor']['short'])}</th>" for x in summary)
    sub = "".join("<th class='nw'>총점</th><th class='nw'>산정 구분</th>" for _ in summary)
    body = ""
    for i, p in enumerate(participants, 1):
        cells = ""
        for x in summary:
            entry = next(e for e in x["scored"] if e["participant"]["id"] == p["id"])
            tag = {"HIGHEST": "hi", "LOWEST": "lo"}.get(entry["exclusion"] or "", "")
            label = EXCLUSION.get(entry["exclusion"] or "", "—")
            cells += f"<td class='num'>{pts(entry['score'])}</td><td class='nw'><span class='tag {tag}'>{esc(label)}</span></td>"
        role = " <span class='sub'>(위원장)</span>" if p["is_chair"] else ""
        body += f"<tr><td>{i}</td><td class='l nw'>{esc(p['name'])}{role}</td><td class='l sub'>{esc(p['org'] or '')}</td>{cells}</tr>"

    def line(label: str, cell):
        return f"<tr><th colspan='3' class='l'>{label}</th>" + "".join(f"<td colspan='2' class='num'>{cell(x)}</td>" for x in summary) + "</tr>"

    foot = line("전체 위원 총점 합계", lambda x: pts(x["total_all"]))
    foot += line("최고점 제외", lambda x: f"− {pts(x['highest']['score'])}" if x["highest"] else "—")
    foot += line("최저점 제외", lambda x: f"− {pts(x['lowest']['score'])}" if x["lowest"] else "—")
    foot += line("산정 합계", lambda x: pts(x["item"]["included_sum"]) if x["item"] else "—")
    foot += line("산정 대상 위원 수", lambda x: f"{x['item']['included_count']}명" if x["item"] else "—")
    foot += line("최종 평가점수(평균)", lambda x: f"<b>{average(x['item']['average_decimal'])}</b>" if x["item"] else "—")
    foot += line("순위", lambda x: f"<b>{x['item']['rank']}위</b>" if x["item"] else "—")

    process = ""
    for x in summary:
        if not x["item"]:
            continue
        inc = " + ".join(pts(e["score"]) for e in x["included"])
        names = ", ".join(esc(e["participant"]["name"]) for e in x["included"])
        process += (f"<tr><td class='nw'>{esc(x['vendor']['short'])}</td><td class='l'>({inc}) ÷ {x['item']['included_count']} = "
                    f"<b>{average(x['item']['average_decimal'])}</b>점<br><span class='sub'>산정 대상 위원: {names}</span></td></tr>")
    criteria = "".join(
        f"<tr><td>{esc(cr['code'])}</td><td class='l'>{esc(cr['title'])}</td><td class='num'>{allocation(cr['max_score'])}</td></tr>"
        for cr in ctx["criteria"]
    )
    cv = ctx["criteria_version"]
    rules = "".join(f"<li>{esc(t)}</li>" for t in policy_lines(ctx["policy"]))
    return f"""
<h2>{ROMAN[2]}. 평가점수 산정 내역</h2>
<h3>1. 업체별 위원 평가점수</h3>
<table class="keep">
<thead><tr><th rowspan="2" class="nw" style="width:10mm">연번</th><th rowspan="2" class="l">평가위원</th><th rowspan="2" class="l">소속</th>{head}</tr><tr>{sub}</tr></thead>
<tbody>{body}{foot}</tbody>
</table>
<p class="note">산정 구분: 산정 포함 = 평균 산정에 포함된 점수, 최고점 제외·최저점 제외 = 업체별로 1명씩 제외한 점수.</p>
<h3>2. 최종 점수 산정 과정</h3>
<table class="keep">
<thead><tr><th class="nw" style="width:18mm">업체</th><th class="l">산식</th></tr></thead>
<tbody>{process}</tbody>
</table>
<h3>3. 적용 평가 기준</h3>
<p>승인 평가표 제{cv['approval_no']}차 (승인 {kst(cv['approved_at'])}) · 총 {allocation(cv['total_max_score'])}점</p>
<table class="keep">
<thead><tr><th class="nw" style="width:12mm">연번</th><th class="l">평가항목</th><th class="nw" style="width:20mm">배점</th></tr></thead>
<tbody>{criteria}<tr><th colspan="2" class="l">합계</th><td class="num"><b>{allocation(cv['total_max_score'])}</b></td></tr></tbody>
</table>
<h3>4. 점수 산정 규칙</h3>
<ul class="rule">{rules}</ul>"""


def _confirmation(ctx: DTO) -> str:
    body = ""
    for i, p in enumerate(ctx["participants"], 1):
        sub = ctx["submissions"].get(p["id"])
        sig = ctx["signatures"].get(sub["signature_id"]) if sub else None
        submitted = "제출 완료" if sub else "미제출"
        when = kst(sub["submitted_at"]) if sub else "—"
        signed = f"서명 완료 <span class='sub'>({kst(sig['signed_at'], '%H:%M')})</span>" if sig else "—"
        role = "위원장" if p["is_chair"] else "위원"
        body += (f"<tr><td>{i}</td><td class='l nw'>{esc(p['name'])}</td><td class='l sub'>{esc(p['org'] or '')}</td><td class='nw'>{role}</td>"
                 f"<td class='nw'>{submitted}</td><td class='nw'>{when}</td><td class='nw'>{signed}</td></tr>")
    conf = ctx["confirmation"]
    chair = ctx["chair"]
    chair_sig = ctx["signatures"].get(conf["signature_id"])
    return f"""
<h2>{ROMAN[3]}. 평가결과 확인</h2>
<h3>1. 평가위원별 제출·서명</h3>
<table class="keep">
<thead><tr><th class="nw" style="width:10mm">연번</th><th class="l">성명</th><th class="l">소속</th><th class="nw" style="width:16mm">구분</th><th class="nw" style="width:20mm">평가 제출</th><th class="nw" style="width:32mm">제출 일시</th><th class="nw" style="width:30mm">서명</th></tr></thead>
<tbody>{body}</tbody>
</table>
<h3>2. 위원장 최종 확인</h3>
<table class="kv keep">
<tr><th>위원장</th><td>{esc(chair['name']) if chair else '—'}{(' · ' + esc(chair['org'])) if chair and chair['org'] else ''}</td></tr>
<tr><th>결과 집계 일시</th><td>{kst(ctx['run']['calculated_at'])}</td></tr>
<tr><th>위원장 확인 서명</th><td>{'서명 완료 · ' + kst(chair_sig['signed_at']) if chair_sig else '—'}</td></tr>
<tr><th>평가결과 확정 일시</th><td><b>{kst(conf['submitted_at'])}</b></td></tr>
<tr><th>확정 상태</th><td>{'최종 확정(변경 불가)' if ctx['session']['status'] == 'FINALIZED' else esc(ctx['session']['status'])}</td></tr>
</table>
<p class="note">모든 일시는 한국표준시(KST) 기준입니다. 서명 이미지와 검증 정보는 별첨에 있습니다.</p>"""


def _appendix(ctx: DTO) -> str:
    participants, criteria = ctx["participants"], ctx["criteria"]
    # 별첨 1. 위원별 세부 평가점수 (업체별 표)
    detail = ""
    for x in ctx["summary"]:
        v = x["vendor"]
        head = "".join(f"<th class='nw'>{esc(p['name'])}</th>" for p in participants)
        body = ""
        for cr in criteria:
            cells = ""
            for p in participants:
                sheet = ctx["sheet_of"].get((p["id"], v["id"]))
                score = ctx["entries"].get(sheet["id"], {}).get(cr["id"]) if sheet else None
                cells += f"<td class='num'>{pts(score)}</td>"
            body += f"<tr><td>{esc(cr['code'])}</td><td class='l'>{esc(cr['title'])}</td><td class='num'>{allocation(cr['max_score'])}</td>{cells}</tr>"
        totals = ""
        for p in participants:
            entry = next(e for e in x["scored"] if e["participant"]["id"] == p["id"])
            totals += f"<td class='num'><b>{pts(entry['score'])}</b></td>"
        detail += f"""
<h3>{esc(v['short'])}{(' · ' + esc(v['name'])) if v['name'] else ''}</h3>
<table class="keep">
<thead><tr><th class="nw" style="width:10mm">연번</th><th class="l">평가항목</th><th class="nw" style="width:14mm">배점</th>{head}</tr></thead>
<tbody>{body}<tr><th colspan="2" class="l">총점</th><td class="num"><b>{allocation(ctx['criteria_version']['total_max_score'])}</b></td>{totals}</tr></tbody>
</table>"""

    # 별첨 2. 점수 산정 세부 내역 (제외 판정 순서)
    calc = ""
    for x in ctx["summary"]:
        ordered = sorted([e for e in x["scored"] if e["score"] is not None], key=lambda e: (e["score"], e["participant"]["id"]))
        rows_html = ""
        for i, e in enumerate(ordered, 1):
            sub = ctx["submissions"].get(e["participant"]["id"])
            tag = {"HIGHEST": "hi", "LOWEST": "lo"}.get(e["exclusion"] or "", "")
            rows_html += (f"<tr><td>{i}</td><td class='l nw'>{esc(e['participant']['name'])}</td><td class='num'>{pts(e['score'])}</td>"
                          f"<td class='nw'><span class='tag {tag}'>{esc(EXCLUSION.get(e['exclusion'] or '', '—'))}</span></td>"
                          f"<td class='nw'>{kst(sub['submitted_at']) if sub else '—'}</td></tr>")
        calc += f"""
<h3>{esc(x['vendor']['short'])} · 총점 오름차순</h3>
<table class="keep">
<thead><tr><th class="nw" style="width:10mm">순서</th><th class="l">평가위원</th><th class="nw" style="width:22mm">총점</th><th class="nw" style="width:26mm">산정 구분</th><th class="nw" style="width:34mm">평가 제출 일시</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>"""

    # 별첨 3. 종합 의견 (있을 때만)
    opinions = ""
    for x in ctx["summary"]:
        v = x["vendor"]
        rows_html = ""
        for p in participants:
            sheet = ctx["sheet_of"].get((p["id"], v["id"]))
            text = (sheet or {}).get("opinion") or ""
            if text.strip():
                rows_html += f"<tr><td class='l nw' style='width:30mm'>{esc(p['name'])}</td><td class='l'>{esc(text)}</td></tr>"
        if rows_html:
            opinions += f"<h3>{esc(v['short'])}{(' · ' + esc(v['name'])) if v['name'] else ''}</h3><table class='keep'><tbody>{rows_html}</tbody></table>"

    # 별첨 4. 서명 증빙
    sigs = sorted(ctx["signatures"].values(), key=lambda r: (r["purpose"] != "CHAIR_RESULT", r["signed_at"]))
    sig_rows = ""
    for r in sigs:
        p = ctx["by_participant"].get(r["signer_participant_id"], {"name": "—", "org": ""})
        img = base64.b64encode(r["image_blob"]).decode() if r["image_blob"] else ""
        image = f'<img alt="{esc(p["name"])} 서명" src="data:image/png;base64,{img}">' if img else "—"
        sig_rows += (f"<tr><td class='nw'>{esc(PURPOSE.get(r['purpose'], r['purpose']))}</td><td class='l nw'>{esc(p['name'])}</td>"
                     f"<td class='nw'>{kst(r['signed_at'], '%Y-%m-%d %H:%M:%S')}</td><td>{image}</td></tr>")

    # 별첨 5. 검증 정보
    conf, run, cv = ctx["confirmation"], ctx["run"], ctx["criteria_version"]
    consent = ", ".join(sorted({r["consent_text_version"] for r in sigs if r["consent_text_version"]})) or "—"
    verify = f"""
<tr><th class="l">확정 결과 해시</th><td class="mono">{esc(conf['payload_sha256'])}</td></tr>
<tr><th class="l">집계 입력 해시</th><td class="mono">{esc(run.get('input_sha256'))}</td></tr>
<tr><th class="l">집계 산출</th><td>제{run.get('revision_no', 1)}차 집계 · {kst(run.get('calculated_at'), '%Y-%m-%d %H:%M:%S')} · 집계 정책 {esc(ctx['policy'].get('policy_version', '—'))}</td></tr>
<tr><th class="l">평가표 승인 스냅샷 해시</th><td class="mono">{esc(cv['snapshot_sha256'])}</td></tr>
<tr><th class="l nw">서명 동의 문구</th><td>{esc(consent)}</td></tr>"""
    for r in sigs:
        p = ctx["by_participant"].get(r["signer_participant_id"], {"name": "—"})
        verify += (f"<tr><th class='l'>{esc(p['name'])} · {esc(PURPOSE.get(r['purpose'], r['purpose']))}</th>"
                   f"<td class='mono'>문서 해시 {esc(r['payload_sha256'])}<br>이미지 해시 {esc(r['image_sha256'])}</td></tr>")
    n_sig = "4" if opinions else "3"
    n_ver = "5" if opinions else "4"
    return f"""
<h2 class="page">별첨 1. 위원별 세부 평가점수</h2>
<p class="note">항목별 점수는 위원이 제출한 평가표 원본 값이며, 총점은 집계에 사용된 값과 같습니다.</p>
{detail}
<h2>별첨 2. 점수 산정 세부 내역</h2>
<p class="note">업체별로 총점을 오름차순으로 정렬한 뒤 첫 번째를 최저점, 마지막을 최고점으로 제외했습니다. 총점이 같으면 참여자 등록 순서를 따릅니다.</p>
{calc}
{('<h2>별첨 3. 평가위원 종합 의견</h2>' + opinions) if opinions else ''}
<h2 class="page">별첨 {n_sig}. 서명 증빙</h2>
<p class="note">평가 제출과 결과 확인 시 위원이 화면에 직접 그린 서명 이미지입니다. 전자서명법상 공인전자서명이 아니며, 제출 기록과 함께 확인용으로 보관합니다.</p>
<table class="sig-table">
<thead><tr><th class="nw" style="width:40mm">구분</th><th class="l">성명</th><th class="nw" style="width:36mm">서명 일시</th><th>서명 이미지</th></tr></thead>
<tbody>{sig_rows}</tbody>
</table>
<h2>별첨 {n_ver}. 검증 정보</h2>
<p class="note">보고서 본문의 점수·순위가 시스템에 저장된 확정 집계와 같은지 확인할 때 쓰는 값입니다. 본문 열람에는 필요하지 않습니다.</p>
<table class="kv verify">{verify}</table>"""


def build_report(c: sqlite3.Connection, s: Store, session: DTO, payload: DTO, confirmation: DTO) -> bytes:
    ctx = report_context(c, s, session, payload, confirmation)
    printed = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    title = f"{ctx['project_name']} 제안서 평가결과 보고서"
    document = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="toolbar">
<span>브라우저 인쇄에서 'PDF로 저장'을 고르면 이 화면과 같은 A4 문서로 저장됩니다. 인쇄물에는 이 안내와 버튼이 나오지 않습니다.</span>
<button type="button" onclick="window.print()">인쇄 · PDF 저장</button>
</div>
<table class="doc">
<thead><tr><td><div class="run-head"><span>제안서 평가결과 보고서</span><span>{esc(ctx['project_name'])}</span></div></td></tr></thead>
<tfoot><tr><td><div class="run-foot"><span>{esc(ctx['department'] or '')}</span><span>출력 {printed} · 확정 결과 {kst(confirmation['submitted_at'])}</span></div></td></tr></tfoot>
<tbody><tr><td>
<main class="sheet">
<header class="doc-title">
<p class="doc-kind">제안서 평가결과 보고서</p>
<h1>{esc(ctx['project_name'])}</h1>
<p class="doc-meta">{esc(ctx['department']) + ' · ' if ctx['department'] else ''}제{session['round_no']}차 평가 · 결과 확정 {kst(confirmation['submitted_at'])}</p>
</header>
{_overview(ctx)}
{_summary(ctx)}
{_detail(ctx)}
{_confirmation(ctx)}
{_appendix(ctx)}
</main>
</td></tr></tbody>
</table>
</body>
</html>"""
    return document.encode("utf-8")
