// EV-05 · VIEW-04 · CHAT-01·02
// 항목별 비교: 평가항목을 고르면 업체별 근거를 나란히 보여 준다. 담당자 확정 근거 → 확정 전 제안 → 제안서에서 자동으로 찾은 후보 순이고, 없으면 빈 상태를 명시한다.
// 문서 도우미(공통 chat.js)의 출처 칩은 이 화면의 슬라이드로 연다.
import { get, post, request } from '../common/api.js';
import { open as openChat, setOpenPageHandler } from '../common/chat.js';
import { messageFor } from '../common/errors.js';
import { mountReader } from '../common/reader.js';
import { fromScaled } from '../common/score.js';
import { participantGate, requireAttendance, requireLogin, screenHref } from '../common/session.js';
import { esc, mountShell, showState, toast } from '../common/shell.js';

const $ = (s) => document.querySelector(s);
let me = null, CRIT = [], SCORABLE = [], PROPOSALS = [], sel = null;
const cache = {};
const summaryCache = {};
const summaryPending = {};
const readers = {};
let slOpen = false, lastBtn = null;

const base = () => `/projects/${encodeURIComponent(me.project.id)}/sessions/${encodeURIComponent(me.session.id)}`;

function headingHtml(c, tag = '') {
  const criterion = String(c.description || '').split(/\r?\n\s*[-•]\s+/)[0].trim();
  return `<div class="cp-hd"><h2>${esc(c.title)} <small>(${fromScaled(c.max_score)}점)</small></h2>${tag}</div>` +
    (criterion ? `<p class="cp-criterion">${esc(criterion)}</p>` : '');
}

function renderList() {
  const divisions = CRIT.filter((c) => !c.is_scorable);
  const item = (c) => `<button type="button" class="cp-it" data-c="${esc(c.id)}"${c.id === sel ? ' aria-current="true"' : ''}><span class="nm">${esc(c.title)}</span><span class="pt">${fromScaled(c.max_score)}점</span></button>`;
  let h = '<h2>평가항목 · 확정 평가표</h2>';
  if (divisions.length) {
    divisions.forEach((d) => {
      const children = SCORABLE.filter((c) => c.parent_id === d.id);
      if (children.length) h += `<h3>${esc(d.title)}</h3>${children.map(item).join('')}`;
    });
    h += SCORABLE.filter((c) => !c.parent_id || !divisions.some((d) => d.id === c.parent_id)).map(item).join('');
  } else h += SCORABLE.map(item).join('');
  $('#list').innerHTML = h;
}

async function evidence(cid) {
  if (cache[cid]) return cache[cid];
  const { data } = await get(`${base()}/comparisons?criterion_id=${encodeURIComponent(cid)}`);
  cache[cid] = data;
  return data;
}

async function renderCols() {
  const c = SCORABLE.find((x) => x.id === sel);
  const scroll = $('#scroll');
  scroll.innerHTML = headingHtml(c) + '<p class="evr-wait">근거를 불러오는 중…</p>';
  let ev;
  try { ev = await evidence(sel); } catch (e) { scroll.innerHTML += `<p class="ev-note error">${esc(messageFor(e))}</p>`; return; }
  if (sel !== c.id) return;
  const byP = Object.fromEntries((ev.columns || []).map((col) => [col.session_proposal_id, col]));
  const TAG = { confirmed: '<span class="cp-tag">담당자 확정 근거</span>', mixed: '<span class="cp-tag wait">일부 자동 추천 · 확정 전</span>',
    suggested: '<span class="cp-tag wait">담당자 확정 전 제안</span>', auto: '', none: '<span class="cp-tag wait">관련 내용 없음</span>' };
  const tag = TAG[ev.mode] ?? '<span class="cp-tag wait">근거 연결 준비 중</span>';
  const summary = summaryCache[c.id];
  scroll.innerHTML = headingHtml(c, tag) +
    (ev.note && ev.mode !== 'auto' ? `<p class="ev-note info" style="margin-bottom:14px">${esc(ev.note)}</p>` : '') +
    `<div class="cp-cols" data-count="${PROPOSALS.length}">${PROPOSALS.map((p) => {
      const m = byP[p.session_proposal_id];
      const items = m && m.matches && m.matches.length ? m.matches : (m && m.excerpt ? m.excerpt.map((l) => ({ excerpt: l, page: m.page })) : []);
      if (!items.length) return `<article class="cp-col cp-none"><h3>${esc(p.display_name)}</h3><p>관련 내용을 찾지 못했어요</p><button type="button" class="cp-link" data-open="${esc(p.session_proposal_id)}" data-p="1" data-toc="1">목차에서 직접 보기</button></article>`;
      const pages = [...new Set(items.map((it) => Number(it.page)).filter((n) => Number.isInteger(n) && n > 0))].sort((a, b) => a - b);
      const result = summary?.summaries?.[p.session_proposal_id];
      const text = result === '관련 제안 내용을 확인하기 어렵습니다.' ? '아래 페이지를 참고 하시기 바랍니다' : result || (summary?.error ? 'AI 정리를 불러오지 못했어요. 아래 원문 쪽을 확인해 주세요.' : summary ? '아래 페이지를 참고 하시기 바랍니다' : '제안 내용을 정리하는 중…');
      return `<article class="cp-col"><h3>${esc(p.display_name)}</h3><p class="cp-summary">${esc(text)}</p>${summary?.error ? `<button type="button" class="cp-retry" data-retry="${esc(c.id)}">다시 정리하기</button>` : ''}<div class="cp-pages" role="group" aria-label="${esc(p.display_name)} 관련 쪽">${pages.map((n) => `<button type="button" class="ev-btn ghost sm" data-open="${esc(p.session_proposal_id)}" data-p="${n}">${n}쪽 열기</button>`).join('') || '<span>쪽 정보 없음</span>'}</div></article>`;
    }).join('')}</div>`;
  try { history.replaceState(null, '', `?project=${encodeURIComponent(me.project.id)}&c=${encodeURIComponent(sel)}`); } catch { /* */ }
  if (!summary && !summaryPending[c.id] && (ev.columns || []).length) {
    summaryPending[c.id] = post(`${base()}/comparisons/summary`, { criterion_id: c.id })
      .then(({ data }) => { summaryCache[c.id] = data; })
      .catch((error) => { summaryCache[c.id] = { error: messageFor(error) }; })
      .finally(() => { delete summaryPending[c.id]; if (sel === c.id) renderCols(); });
  }
}

/* 슬라이드: 업체별 읽기 화면을 한 번씩만 만든다 */
async function ensure(pid) {
  if (readers[pid]) return readers[pid];
  const p = PROPOSALS.find((x) => x.session_proposal_id === pid);
  const w = document.createElement('div'); w.className = 'cp-rd'; w.id = `rd-${pid}`; w.hidden = true; $('#sl-bd').appendChild(w);
  const el = document.createElement('div'); w.appendChild(el);
  showState(el, 'loading', `${p.display_name} 제안서를 불러오고 있어요`);
  const holder = { wrap: w, reader: null };
  readers[pid] = holder;
  try {
    const { data } = await get(`${base()}/proposals/${encodeURIComponent(pid)}`);
    if (!data.pages.length) {
      showState(el, 'empty', '제안서 쪽이 아직 없어요', '문서 변환이 끝나면 읽을 수 있어요.');
      return holder;
    }
    el.innerHTML = '';
    const version = encodeURIComponent(data.document.source_version || '');
    const isPdf = /\.pdf$/i.test(data.document.filename || '');
    holder.reader = mountReader(el, data, {
      label: `${p.display_name} 제안서`,
      loadPage: (n) => get(`${base()}/proposals/${encodeURIComponent(pid)}/pages/${n}`).then((r) => r.data),
      svgUrl: (n) => `/api/v2/evaluator${base()}/proposals/${encodeURIComponent(pid)}/pages/${n}/${isPdf ? 'png' : 'svg'}?v=${version}`,
      download: () => request('GET', `${base()}/proposals/${encodeURIComponent(pid)}/source`, { raw: true }),
    }, { note: '', single: true, keysWhen: () => slOpen });
  } catch (e) { showState(el, 'error', '제안서를 불러오지 못했어요', messageFor(e)); }
  return holder;
}
async function openSlide(pid, page, toc, btn) {
  lastBtn = btn || document.activeElement;
  const p = PROPOSALS.find((x) => x.session_proposal_id === pid);
  Object.values(readers).forEach((r) => { r.wrap.hidden = true; });
  $('#sl-t').textContent = `${p.display_name} 제안서 · ${page}쪽`;
  $('#sl').classList.add('on'); $('#sl').setAttribute('aria-hidden', 'false'); $('#sl-scrim').classList.add('on'); slOpen = true;
  const holder = await ensure(pid);
  holder.wrap.hidden = false;
  if (holder.reader) holder.reader.go(page);
  setTimeout(() => $('#sl-x').focus(), 60);
  if (toc) toast('왼쪽 목차 띠에 마우스를 올리면 고를 수 있어요');
}
function closeSlide() {
  if (!slOpen) return false;
  slOpen = false;
  $('#sl').classList.remove('on'); $('#sl').setAttribute('aria-hidden', 'true'); $('#sl-scrim').classList.remove('on');
  if (lastBtn && document.contains(lastBtn)) lastBtn.focus();
  return true;
}

async function main() {
  me = await requireLogin();
  mountShell($('#hd'), { active: 'proposals', me });
  if (!requireAttendance(me)) return;
  $('#to-proposals').href = screenHref('EV-04');
  const gate = participantGate(me);
  if (!gate.ok) { showState($('#scroll'), 'empty', '아직 비교 화면을 볼 수 없어요', gate.reason); $('#list').innerHTML = ''; return; }
  const { data } = await get(`${base()}/criteria`);
  CRIT = data.criteria.items; SCORABLE = CRIT.filter((c) => c.is_scorable); PROPOSALS = data.proposals;
  const q = new URLSearchParams(location.search);
  sel = SCORABLE.some((c) => c.id === q.get('c')) ? q.get('c') : (SCORABLE[0] && SCORABLE[0].id);
  if (!sel) { showState($('#scroll'), 'empty', '평가항목이 없어요', '담당자가 평가표를 확정하면 여기에서 비교할 수 있어요.'); return; }
  renderList(); renderCols();
  $('#list').addEventListener('click', (e) => { const b = e.target.closest('[data-c]'); if (b) { sel = b.dataset.c; renderList(); renderCols(); } });
  $('#scroll').addEventListener('click', (e) => {
    const b = e.target.closest('[data-open]');
    if (b) { openSlide(b.dataset.open, +b.dataset.p, !!b.dataset.toc, b); return; }
    const retry = e.target.closest('[data-retry]');
    if (retry) { delete summaryCache[retry.dataset.retry]; renderCols(); }
  });
  $('#sl-x').addEventListener('click', closeSlide);
  $('#sl-scrim').addEventListener('click', closeSlide);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && slOpen) { e.preventDefault(); closeSlide(); } });
  setOpenPageHandler((v, page, btn) => { if (v) openSlide(v.id, page, false, btn); });
  if (q.get('chat')) openChat(q.get('chat') !== '1' ? q.get('chat') : null);
}

main().catch((e) => showState($('#scroll'), 'error', '비교 화면을 열지 못했어요', messageFor(e)));
