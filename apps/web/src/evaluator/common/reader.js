// 공통 · EvalReader: 목차 띠 · 두 쪽/한 쪽 · 쪽 넘김/쪽 이동 · 원본 내려받기 · 원본 쪽 SVG(실패 시 파싱 대체).
// src/screens/evaluator/EV-03-rfp/main.js 의 mountReader 를 분리해 문서 종류와 API 를 매개변수로 받는다. EV-03·EV-04·EV-05 가 같이 쓴다.
import { esc, toast } from './shell.js';

const READ_MODE_KEY = 'ev.readMode';
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* 저장 못 해도 읽기는 가능 */ } },
};

function paragraphClass(text) {
  const t = text.trim();
  if (/^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s/.test(t)) return 'h1';
  if (/^(\d+\.|[가-힣]\.)\s/.test(t) && t.length <= 40) return 'h2';
  if (/^□/.test(t)) return 'b1';
  if (/^[○◦ㅇ]/.test(t)) return 'b2';
  if (/^-/.test(t)) return 'b3';
  if (/^[※*]/.test(t)) return 'note';
  return '';
}

function tableHtml(rows) {
  const body = rows.map((r) => '<tr>' + r.map((c) =>
    `<td${c.rs > 1 ? ` rowspan="${c.rs}"` : ''}${c.cs > 1 ? ` colspan="${c.cs}"` : ''}>${esc(c.text)}</td>`).join('') + '</tr>').join('');
  return `<div class="evr-tbl-w"><table class="evr-tbl"><tbody>${body}</tbody></table></div>`;
}

export function blocksHtml(page, docLabel = '문서') {
  if (!page.blocks.length) return '<p class="evr-blank">이 쪽에는 글이 없어요 (그림이나 빈 쪽일 수 있어요)</p>';
  let more = false;
  const html = page.blocks.map((b) => {
    if (b.continues) more = true;
    if (b.type === 'paragraph') {
      const cls = page.n === 1 && !b.continues && b.text.length <= 40 ? 'cover' : paragraphClass(b.text);
      return `<p${cls ? ` class="${cls}"` : ''}>${esc(b.text)}</p>`;
    }
    if (b.type === 'table') return tableHtml(b.rows);
    if (b.type === 'image') return `<img class="evr-img" src="${esc(b.src)}" alt="${esc(docLabel)} 그림" loading="lazy">`;
    return '';
  }).join('');
  return html + (more ? '<p class="evr-more">다음 쪽에 이어져요</p>' : '');
}

/**
 * el 안에 읽기 화면을 만든다.
 * data: {document:{title, filename, page_count, has_source, source_version}, pages:[{n,label}], toc:[{t,lv,page,seen,adjusted,printed}]}
 * io:   {loadPage(n) → Promise<page>, svgUrl(n) → string|null, download() → Promise<Response>, label}
 * opts: {note, startPage, onPage(p), single}
 */
export function mountReader(el, data, io, opts = {}) {
  const toc = data.toc || [];
  const TOT = data.pages.length;
  const labels = new Map(data.pages.map((p) => [p.n, p.label]));
  const title = data.document.title;
  const st = { p: 1, mode: opts.single ? 'single' : (store.get(READ_MODE_KEY) === 'single' ? 'single' : 'spread'), chipK: 0, token: 0 };
  const cache = new Map();
  const ordered = toc.filter((t) => t.page).sort((a, b) => a.page - b.page);
  // 현재 절: 펼침 보기에서는 펼쳐진 두 쪽(p, p+1) 안에서 시작하는 마지막 절.
  const secOf = (p) => {
    const last = st.mode === 'spread' ? Math.min(TOT, p + 1) : p;
    return ordered.reduce((s, t) => (t.page <= last ? t : s), null);
  };
  const STEP = () => (st.mode === 'spread' ? 2 : 1);
  const norm = (p) => {
    p = Math.max(1, Math.min(TOT, p));
    return st.mode === 'spread' && p % 2 === 0 ? p - 1 : p;
  };
  const pct = (x) => `${(x / TOT * 100).toFixed(2)}%`;

  el.classList.add('evr');
  el.innerHTML =
    '<nav class="evr-strip" aria-label="목차 띠"><button type="button" class="evr-strip-label" aria-haspopup="true">목차</button>' +
    '<div class="evr-track" aria-hidden="true"></div><div class="evr-pop" role="region" aria-label="전체 목차"><h3>목 차</h3>' +
    (toc.length ? toc.map((t, i) => {
      // 쪽이 있는 항목은 모두 연다. "확인 필요" 배지는 쓰지 않는다 (2026-10-18 사용자 요청).
      const un = !t.page;
      const tip = t.assumed ? `목차의 쪽 번호(${t.printed})로 찾은 쪽이에요`
        : t.adjusted ? `목차의 쪽 번호(${t.printed})와 본문이 달라 제목으로 찾은 쪽이에요` : '';
      return `<button type="button" class="evr-toc-item${t.lv === 2 ? ' lv2' : ''}${un ? ' is-unseen' : ''}" data-i="${i}"${un ? ' aria-disabled="true"' : ''}${tip ? ` title="${esc(tip)}"` : ''}>` +
        `<span class="t">${esc(t.t)}</span><span class="here" hidden>지금</span><span class="dots"></span>` +
        (t.page ? `<span class="pn">${t.page}</span>` : '') + '</button>';
    }).join('') : '<p class="evr-blank">이 문서에는 목차가 없어요</p>') +
    '</div></nav>' +
    '<div class="evr-main"><div class="evr-top"></div><div class="evr-stage"><div class="evr-bookw"><div class="evr-book"></div>' +
    '<button type="button" class="evr-side l" data-pg="-1" aria-label="앞 쪽"><span aria-hidden="true">‹</span><span class="lb" aria-hidden="true">앞 쪽</span></button>' +
    '<button type="button" class="evr-side r" data-pg="1" aria-label="뒤 쪽"><span aria-hidden="true">›</span><span class="lb" aria-hidden="true">뒤 쪽</span></button>' +
    '</div></div><div class="evr-foot"><span class="note"></span><span class="fr">' +
    `<label class="evr-go"><span>쪽 이동</span><input type="text" inputmode="numeric" autocomplete="off" maxlength="4" placeholder="${Math.min(TOT, 27)}" aria-label="이동할 쪽 번호 (1부터 ${TOT})"><span>쪽 · Enter</span></label>` +
    '<span class="err" role="alert"></span><span class="evr-keys">옆 버튼이나 ← → 키</span></span></div></div>';

  const $ = (s) => el.querySelector(s);
  const strip = $('.evr-strip'), track = $('.evr-track'), top = $('.evr-top'), book = $('.evr-book'), bookw = $('.evr-bookw');
  const goIn = $('.evr-go input'), goErr = $('.evr-foot .err'), note = $('.evr-foot .note');
  const items = [...el.querySelectorAll('.evr-toc-item')];
  note.textContent = opts.note || '평가 시작 때 고정된 버전이에요';

  track.innerHTML = '<i class="rail"></i><i class="fill"></i>' +
    toc.filter((t) => t.page).map((t) => `<i class="tick" style="top:${pct(t.page - 1)}"></i>`).join('') +
    '<i class="cur"></i><span class="now"></span>';
  const fill = track.querySelector('.fill'), cur = track.querySelector('.cur'), now = track.querySelector('.now');

  function loadPage(n) {
    if (n < 1 || n > TOT) return Promise.resolve(null);
    if (!cache.has(n)) {
      const req = io.loadPage(n).catch((e) => { cache.delete(n); throw e; });
      cache.set(n, req);
    }
    return cache.get(n);
  }

  function pageShell(p) {
    if (p > TOT) return '<section class="evr-page is-empty" aria-hidden="true"></section>';
    const label = labels.get(p);
    const foot = `${p}${label != null && label !== p ? `<small>문서 쪽번호 ${label}</small>` : ''}`;
    return `<section class="evr-page" aria-label="${p}쪽" data-p="${p}">` +
      '<div class="evr-tx"><p class="evr-wait">원본 쪽을 불러오는 중…</p></div>' +
      `<div class="evr-pn">${foot}</div></section>`;
  }

  async function showParsed(sec, p, token, message) {
    sec.classList.remove('is-rendered');
    try {
      const page = await loadPage(p);
      if (token === st.token && sec.isConnected) {
        sec.innerHTML = (message ? `<p class="evr-render-fallback" role="status">${esc(message)}</p>` : '') + blocksHtml(page, io.label || '문서');
        sec.scrollTop = 0;
      }
    } catch {
      if (token === st.token && sec.isConnected) sec.innerHTML = '<p class="evr-blank">이 쪽을 불러오지 못했어요. 잠시 뒤 다시 넘겨 주세요.</p>';
    }
  }

  function fillPage(p, token) {
    const sec = book.querySelector(`.evr-page[data-p="${p}"] .evr-tx`);
    if (!sec) return;
    const svg = data.document.has_source && io.svgUrl ? io.svgUrl(p) : null;
    if (!svg) { showParsed(sec, p, token, data.document.has_source ? '' : '원본 파일이 없어 파싱된 내용으로 표시합니다.'); return; }
    const image = document.createElement('img');
    image.className = 'evr-page-svg';
    image.alt = `${p}쪽 원본 문서`;
    image.decoding = 'async';
    image.onload = () => { if (token === st.token && sec.isConnected) sec.classList.add('is-rendered'); };
    image.onerror = () => { if (token === st.token && sec.isConnected) showParsed(sec, p, token, '원본 쪽 렌더링을 쓸 수 없어 파싱된 내용으로 표시합니다.'); };
    image.src = svg;
    sec.replaceChildren(image);
  }

  function topHtml() {
    const last = st.mode === 'spread' ? Math.min(TOT, st.p + 1) : st.p;
    const s = secOf(st.p);
    const loc = last > st.p ? `${st.p}–${last}` : `${st.p}`;
    return `<b>${esc(title)}</b>${s ? `<span class="d">·</span><span>${esc(s.t)}</span>` : ''}` +
      `<span class="d">·</span><span class="mono" aria-live="polite">${loc} / ${TOT}쪽</span><span class="sp"></span>` +
      `<span class="evr-seg" role="group" aria-label="보기 방식"><button type="button" data-mode="spread" aria-pressed="${st.mode === 'spread'}">두 쪽</button>` +
      `<button type="button" data-mode="single" aria-pressed="${st.mode === 'single'}">한 쪽</button></span>` +
      (io.download ? '<button type="button" class="ev-btn ghost sm" data-download>원본 내려받기</button>' : '');
  }

  function update(anim) {
    st.p = norm(st.p);
    st.token += 1;
    el.classList.toggle('is-single', st.mode === 'single');
    book.innerHTML = st.mode === 'spread' ? pageShell(st.p) + pageShell(st.p + 1) : pageShell(st.p);
    top.innerHTML = topHtml();
    const n = STEP();
    fill.style.height = pct(st.p - 1 + n);
    cur.style.top = pct(st.p - 1);
    cur.style.height = pct(n);
    now.style.top = pct(st.p - 1 + n / 2);
    now.textContent = `${st.p}쪽`;
    const s = secOf(st.p);
    items.forEach((b) => {
      const on = s === toc[+b.dataset.i];
      b.classList.toggle('is-current', on);
      b.querySelector('.here').hidden = !on;
      if (on) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
    });
    el.querySelector('.evr-side.l').disabled = st.p <= 1;
    el.querySelector('.evr-side.r').disabled = st.p + STEP() > TOT;
    if (anim) { book.classList.remove('t-fwd', 't-back', 't-jump'); void book.offsetWidth; book.classList.add(`t-${anim}`); }
    const token = st.token;
    for (let i = 0; i < n; i += 1) fillPage(st.p + i, token);
    if (opts.onPage) opts.onPage(st.p);
  }

  function go(p, o = {}) {
    const q = norm(p), d = q - st.p;
    st.p = q;
    goErr.textContent = '';
    update(d !== 0 ? (o.jump ? 'jump' : d > 0 ? 'fwd' : 'back') : null);
    bookw.querySelector('.evr-chip')?.remove();
    if (o.jump && Math.abs(d) > STEP()) {
      // 목차에서 눌러 왔으면 누른 항목의 이름과 쪽을 그대로 알린다.
      const s = o.entry || secOf(st.p), k = ++st.chipK, chip = document.createElement('div');
      chip.className = 'evr-chip';
      chip.setAttribute('role', 'status');
      chip.textContent = `${s ? `${s.t} · ` : ''}${o.entry ? o.entry.page : st.p}쪽으로 이동`;
      bookw.appendChild(chip);
      setTimeout(() => { if (st.chipK === k && chip.parentNode) chip.remove(); }, 2300);
    }
  }

  async function download(btn) {
    if (!data.document.has_source) { toast('원본 파일이 없어요. 담당자에게 알려 주세요'); return; }
    btn.disabled = true;
    try {
      const res = await io.download();
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = data.document.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast(e && (e.status === 401 || e.status === 403) ? '내려받을 권한이 없어요. 담당자에게 문의해 주세요' : '원본을 내려받지 못했어요. 잠시 뒤 다시 눌러 주세요');
    } finally {
      btn.disabled = false;
    }
  }

  el.addEventListener('click', (e) => {
    const t = e.target.closest('[data-pg],[data-i],[data-mode],[data-download]');
    if (!t || !el.contains(t)) return;
    if (t.dataset.pg) go(st.p + (+t.dataset.pg) * STEP());
    else if (t.dataset.i != null) {
      const it = toc[+t.dataset.i];
      if (!it.page) { toast('이 항목은 연결된 쪽이 없어요'); return; }
      go(it.page, { jump: true, entry: it });
      strip.classList.add('hush');
      if (strip.contains(document.activeElement)) document.activeElement.blur();
    } else if (t.dataset.mode) {
      st.mode = t.dataset.mode;
      if (!opts.single) store.set(READ_MODE_KEY, st.mode);
      update(null);
      top.querySelector(`[data-mode="${st.mode}"]`)?.focus();
    } else if ('download' in t.dataset) download(t);
  });
  goIn.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const n = parseInt(goIn.value, 10);
    if (!(n >= 1 && n <= TOT)) { goErr.textContent = `1–${TOT} 사이 숫자를 넣어 주세요`; return; }
    go(n, { jump: true });
  });
  goIn.addEventListener('input', () => { goErr.textContent = ''; });
  strip.addEventListener('pointerleave', () => strip.classList.remove('hush'));
  el.addEventListener('pointerover', (e) => { if (strip.classList.contains('hush') && !e.target.closest('.evr-strip')) strip.classList.remove('hush'); });
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && strip.matches(':hover, :focus-within')) {
      strip.classList.add('hush');
      if (strip.contains(document.activeElement)) document.activeElement.blur();
      e.stopPropagation();
    }
  });
  const keyHandler = (e) => {
    if (e.target.matches?.('input,textarea,select')) return;
    if (opts.keysWhen && !opts.keysWhen()) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); go(st.p + STEP()); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); go(st.p - STEP()); }
  };
  document.addEventListener('keydown', keyHandler);

  go(opts.startPage || 1);
  return {
    go: (p) => go(p, { jump: true }),
    setMode: (m) => { st.mode = m === 'single' ? 'single' : 'spread'; update(null); },
    get page() { return st.p; },
    total: TOT,
    destroy: () => document.removeEventListener('keydown', keyHandler),
  };
}
