r"""PM-04 평가위원 선정 화면 실제 클릭 시험 (2026-10-18). Chrome 헤드리스를 DevTools 프로토콜로 조종한다.

준비: 복사본 DB로 5199 서버를 띄운다(apps/server/tests/e2e_full_flow.py 머리말과 같은 방법).
실행: websockets 패키지가 있는 Python으로
  python -I apps/server/tests/ui_pm04_committee.py <스크린샷 저장 폴더> sample-mydata-2026
확인 항목: 사업 후보 추가 창 너비 960px·검색·다중 선택 저장, 통화 완료 체크박스·칩, 명단 확정 본위원/예비 체크박스·
예비 순서 자동, 예비 1명일 때 버튼 잠김과 이유 표시, 7+2 확정 → 서버 명단 본위원 7·예비 2·평가 DB 수신 SENT.
마지막 줄 "RESULT: PASS"면 통과. 스크린샷 01~07이 저장 폴더에 남는다.
"""
import asyncio, base64, io, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
from http.cookiejar import CookieJar
from pathlib import Path
import websockets

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:5199"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
PID = sys.argv[2] if len(sys.argv) > 2 else "sample-mydata-2026"
PRIMARIES = int(sys.argv[3]) if len(sys.argv) > 3 else 7  # 체크할 본위원 수(5~9). 규칙 정원과 달라도 확정 때 자동으로 맞춘다.
CHROME = os.environ.get("CHROME_BIN") or next((path for path in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome"), shutil.which("chromium"),
) if path and Path(path).is_file()), None)
PORT = 9333
console: list[str] = []


def api(opener, action, body):
    req = urllib.request.Request(BASE + f"/api/v2/actions/{action}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Simsa-Client": "v2-web", "Idempotency-Key": f"ui-{time.time_ns()}"})
    try:
        with opener.open(req, timeout=60) as r:
            return json.loads(r.read())["data"]
    except urllib.error.HTTPError as e:
        raise AssertionError(f"{action} -> {e.code}: {e.read()[:200]!r}")


def login():
    jar = CookieJar(); opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    api(opener, "AUTH-01", {"username": "web-demo", "password": "DemoOnly!2026"})
    return opener, next(c.value for c in jar if c.name == "simsa_v2_session")


class CDP:
    def __init__(self, ws): self.ws, self.n, self.pending = ws, 0, {}
    async def send(self, method, **params):
        self.n += 1; mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg: raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if msg.get("method") == "Runtime.exceptionThrown":
                console.append("EXC " + json.dumps(msg["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:300])
            if msg.get("method") == "Runtime.consoleAPICalled" and msg["params"]["type"] in ("error", "warning"):
                console.append(msg["params"]["type"] + " " + " ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"])[:300])
    async def js(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", str(r["exceptionDetails"])))
        return r.get("result", {}).get("value")
    async def wait(self, expr, timeout=20, label=""):
        for _ in range(int(timeout * 4)):
            if await self.js(expr): return True
            await asyncio.sleep(0.25)
        raise TimeoutError(f"wait: {label or expr}")
    async def shot(self, name):
        r = await self.send("Page.captureScreenshot", format="png")
        (OUT / f"{name}.png").write_bytes(base64.b64decode(r["data"])); print(f"  screenshot {name}.png")
    async def click(self, selector):
        ok = await self.js(f"(()=>{{const el=document.querySelector({json.dumps(selector)});if(!el)return false;el.scrollIntoView();el.click();return true;}})()")
        assert ok, f"no element {selector}"
        await asyncio.sleep(0.4)


async def settle(cdp):
    """Live.capture가 처리 중이면 끝날 때까지 기다린다."""
    await cdp.wait("!document.querySelector('[aria-busy=true]')", 30, "busy")
    await asyncio.sleep(0.3)


async def main():
    if not CHROME:
        raise RuntimeError("Chrome을 찾지 못했습니다. CHROME_BIN 환경변수로 실행 파일을 지정하세요.")
    opener, cookie = login()
    profile = OUT / "chrome-profile"
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                             "--window-size=1700,1100", "--no-first-run", "--disable-gpu", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list").read()); break
            except Exception:
                time.sleep(0.5)
        page = next(p for p in pages if p["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            cdp = CDP(ws)
            await cdp.send("Runtime.enable"); await cdp.send("Page.enable"); await cdp.send("Network.enable")
            await cdp.send("Network.setCookie", name="simsa_v2_session", value=cookie, url=BASE + "/")
            # 사업 상태 준비: DIRECT 규칙이 없으면 저장
            state = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + f"/committee-v2/api/projects/{PID}", headers={"Cookie": f"simsa_v2_session={cookie}"})).read())["data"]
            if not state["rule"]:
                api(opener, "DRAW-01", {"project_id": PID, "selection_mode": "DIRECT", "target_count": 7, "reserve_count": 2, "quotas": [], "version": 0})
            print(f"초기: 후보 {len(state['items'])}명, 규칙 {state['rule'] and state['rule']['selection_mode']}, 명단 {'있음' if state['roster'] else '없음'}")
            assert not state["roster"], "이미 확정된 사업입니다. 다른 사업을 지정하세요."
            await cdp.send("Page.navigate", url=f"{BASE}/app/dept-admin/PM-04/design/committee.html?id={PID}")
            await cdp.wait("document.documentElement.dataset.liveReady==='true'||document.documentElement.dataset.liveError", 30, "page ready")
            err = await cdp.js("document.documentElement.dataset.liveError||''")
            assert not err, f"화면 오류: {err}"
            await cdp.shot("01-loaded")
            # ③ 연락·초청 단계로
            await cdp.click("#sub button[data-i='2']"); await settle(cdp)
            # 사업 후보 추가 창: 넓이·다중 선택
            need = max(0, 9 - len(state["items"]))
            if need:
                await cdp.click("#addc"); await settle(cdp)
                width = await cdp.js("document.getElementById('p').getBoundingClientRect().width")
                print(f"  후보 추가 창 너비 {width}px")
                assert width >= 900, "창이 넓어지지 않음"
                await cdp.js("(()=>{const q=document.getElementById('pick-q');q.value='가상위원';q.dispatchEvent(new Event('input',{bubbles:true}));})()")
                await asyncio.sleep(0.3)
                n = 0
                for _ in range(need):  # 사람처럼 한 명씩(체크할 때마다 목록이 다시 그려진다)
                    if not await cdp.js("(()=>{const b=document.querySelector('#p [data-pick]:not(:disabled):not(:checked)');if(!b)return false;b.click();return true;})()"):
                        break
                    n += 1; await asyncio.sleep(0.15)
                await settle(cdp)
                label = await cdp.js("document.getElementById('addm').textContent")
                print(f"  체크 {n}명 → 버튼 '{label}'")
                assert label == f"선택 {need}명 추가", label
                await cdp.shot("02-add-drawer")
                await cdp.click("#addm"); await settle(cdp)
                await cdp.wait("!document.getElementById('p').classList.contains('on')", 20, "drawer closed")
                await settle(cdp)
                count = await cdp.js("document.querySelectorAll('#stage tbody tr').length")
                print(f"  저장 후 후보 {count}명 (예상 {len(state['items']) + need})")
                assert count == len(state["items"]) + need
            await cdp.shot("03-contact-before")
            # 통화 완료 체크: 미완료인 사람을 9명까지 체크
            for _ in range(12):
                done = await cdp.js("document.querySelectorAll('#stage [data-done]:checked').length")
                if done >= 9: break
                ok = await cdp.js("(()=>{const b=document.querySelector('#stage [data-done]:not(:checked)');if(!b)return false;b.click();return true;})()")
                if not ok: break
                await settle(cdp); await asyncio.sleep(0.4)
            done = await cdp.js("document.querySelectorAll('#stage [data-done]:checked').length")
            chips = await cdp.js("[...document.querySelectorAll('#cst .chip')].map(b=>b.textContent).join(' | ')")
            selects = await cdp.js("document.querySelectorAll('#stage select[data-st]').length")
            print(f"  통화 완료 {done}명 · 칩: {chips} · 남은 드롭다운 {selects}개")
            assert selects == 0 and done >= 9
            await cdp.shot("04-contact-done")
            # ④ 명단 확정
            await cdp.click("#foot #nx"); await settle(cdp)
            picks = await cdp.js("document.querySelectorAll('#stage [data-pick-kind]').length")
            print(f"  명단 확정 체크박스 {picks}개 (드롭다운 {await cdp.js('document.querySelectorAll(\"#stage select[data-pk]\").length')}개)")
            assert picks >= 18
            pick_free = "(kind)=>{const tr=[...document.querySelectorAll('#stage tbody tr')].find(tr=>tr.querySelector('[data-pick-kind]')&&![...tr.querySelectorAll('[data-pick-kind]')].some(b=>b.checked)&&!tr.querySelector(`[data-pick-kind=${kind}]`).disabled);if(!tr)return false;tr.querySelector(`[data-pick-kind=${kind}]`).click();return true;}"
            for _ in range(PRIMARIES):
                assert await cdp.js(f"({pick_free})('본')"), "본위원 체크할 행이 없음"
                await asyncio.sleep(0.25)
            disabled_primary = await cdp.js("document.querySelectorAll('#stage [data-pick-kind=본]:disabled').length")
            why = await cdp.js("document.querySelector('#foot .why').textContent")
            btn = await cdp.js("document.getElementById('cf').disabled")
            cap = await cdp.js("document.querySelector('#stage .chk li .muted').textContent")
            print(f"  본위원 {PRIMARIES} + 예비 0: 버튼 비활성={btn}, 잠긴 본위원 칸 {disabled_primary}개(9명까지 허용), 정원 안내: {cap}, 안내: {why[:80]}")
            assert btn and "예비위원 1~3명" in why and disabled_primary == 0 and cap.startswith(f"{PRIMARIES}명"), (btn, disabled_primary, cap, why)
            await cdp.shot("05-roster-blocked")
            assert await cdp.js(f"({pick_free})('예비')"); await asyncio.sleep(0.4)
            orders = await cdp.js("[...document.querySelectorAll('#stage td span.tnum.strong')].map(s=>s.textContent).filter(t=>t.startsWith('예비')).join(',')")
            btn = await cdp.js("document.getElementById('cf').disabled"); why = await cdp.js("document.querySelector('#foot .why').textContent")
            print(f"  본위원 {PRIMARIES} + 예비 1: 버튼 비활성={btn}, 예비 순서 {orders}, 안내: {why[:70]}")
            assert not btn and orders == "예비 1"
            await cdp.shot("06-roster-ready")
            await cdp.click("#cf"); await asyncio.sleep(0.5)
            title = await cdp.js("document.getElementById('dlg-t').textContent")
            print(f"  확인창: {title}"); assert f"본위원 {PRIMARIES}명, 예비 1명" in title
            await cdp.click("#dlg-ok"); await settle(cdp)
            await cdp.wait("!!document.getElementById('dlr')", 30, "roster confirmed")
            rost = await cdp.js("document.getElementById('rf')?'sent':'ready'"); note = await cdp.js("document.querySelector('#stage .note b')?.textContent||''")
            print(f"  확정 후 상태 {rost}: {note}")
            await cdp.shot("07-confirmed")
            state = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + f"/committee-v2/api/projects/{PID}", headers={"Cookie": f"simsa_v2_session={cookie}"})).read())["data"]
            kinds = [a["member_kind"] for a in state["assignments"]]
            print(f"  서버 명단: 본위원 {kinds.count('PRIMARY')} · 예비 {kinds.count('RESERVE')} · 수신 {state['handoff'] and state['handoff']['status']}")
            assert kinds.count("PRIMARY") == PRIMARIES and kinds.count("RESERVE") == 1
            print(f"  규칙 정원(자동 반영): {state['rule']['target_count']}")
            assert state["rule"]["target_count"] == PRIMARIES
    finally:
        proc.kill()
    print("\n콘솔 오류:", console or "없음")
    print("RESULT: PASS")


asyncio.run(main())
