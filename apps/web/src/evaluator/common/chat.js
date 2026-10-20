// 공통 · EvalChat: 오른쪽 아래 떠 있는 문서 도우미 (CHAT-01·02). v2/위원/_eval.js 의 EvalChat 이식.
// 답변은 POST /api/v2/evaluator/projects/{p}/sessions/{s}/chat/stream 에서 순차적으로 받는다(서버가 chatbot.py 로 업체별 제안서 전체를 물어본다). 문서 DB·API 키가 없어 503 이면 "준비 중" 상태를 보여 준다.
// 대화는 저장하지 않는다. 사업·문서 버전이 바뀌면(회차 id 변경) 초기화한다.
import { get, postStream } from './api.js';
import { messageFor } from './errors.js';
import { screenHref } from './session.js';
import { esc, toast } from './shell.js';

// 질문 예시는 시안의 'A·B·C사'가 아니라 실제로 선택한 업체 이름으로 만든다
// (2026-10-18 사용자 보고: 업체가 A·B사뿐인데 예시를 누르면 답변에 C사가 나옴).
function suggestions() {
  const picked = CH.all.filter((v) => CH.sel.includes(v.id));
  const names = (picked.length ? picked : CH.all).map((v) => v.name);
  const who = names.length ? names.join('·') : '업체';
  return [names.length > 1 ? `${who} 보안 대책 비교` : `${who} 보안 대책 알려줘`, '일정 관리 방법 알려줘'];
}
const CH = { built: false, isOpen: false, all: [], sel: [], msgs: [], busy: false, streaming: false,
  controller: null, runId: 0, me: null, offline: false, offlineReason: '', last: null };

export let onOpenPage = null;
export function setOpenPageHandler(fn) { onOpenPage = fn; }

const hhmm = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
const cq = (s) => document.querySelector(`.evc ${s}`);
const base = () => `/projects/${encodeURIComponent(CH.me.project.id)}/sessions/${encodeURIComponent(CH.me.session.id)}`;

async function loadVendors() {
  if (CH.all.length) return;
  try {
    const { data } = await get(`${base()}/proposals`);
    CH.all = data.proposals.map((p) => ({ id: p.session_proposal_id, code: p.display_code, name: p.display_name, pageCount: p.page_count }));
  } catch { CH.all = []; }
  CH.sel = CH.all.map((v) => v.id);
  if (CH.built) { renderVendors(); if (!CH.msgs.length) renderList(); }
}

function openPage(vendorId, page, btn) {
  const v = CH.all.find((x) => x.id === vendorId);
  if (!v || !Number.isInteger(page) || page < 1) return;
  if (onOpenPage) { onOpenPage(v, page, btn); return; }
  const url = new URL(screenHref('EV-04'), location.origin);
  url.searchParams.set('v', v.code);
  url.searchParams.set('p', String(page));
  window.open(url.href, '_blank', 'noopener');
}

function answerHtml(text, vendorId, vendorName, pages) {
  const valid = new Set((pages || []).map(Number));
  const citation = /\[(\d{1,4})(?:\s*[~\-–]\s*(\d{1,4}))?쪽\]/g;
  let html = '', from = 0, match;
  while ((match = citation.exec(text || ''))) {
    html += esc(text.slice(from, match.index)).replace(/\n/g, '<br>');
    const page = Number(match[1]);
    const label = match[0];
    html += valid.has(page)
      ? `<button type="button" class="evc-pg evc-cite" data-v="${esc(vendorId)}" data-p="${page}" aria-label="${esc(vendorName)} 제안서 ${page}쪽 열기">${esc(label)}</button>`
      : esc(label);
    from = citation.lastIndex;
  }
  return html + esc((text || '').slice(from)).replace(/\n/g, '<br>');
}

function msgHtml(m) {
  if (m.role === 'u') return `<div class="evc-m u"><div class="evc-b">${esc(m.text).replace(/\n/g, '<br>')}</div><time>${m.t}</time></div>`;
  const secs = m.vs.map((vid) => {
    const v = CH.all.find((x) => x.id === vid) || { code: '?', name: '업체' };
    const a = m.ans[vid];
    if (!a || !a.text) return `<section class="evc-vs ev-vt-${esc(v.code)} none"><h4><i></i>${esc(v.name)}</h4><p>${esc((a && a.error) || (a && a.streaming ? '답변 작성 중…' : '이 문서에서 관련 내용을 찾지 못했어요'))}</p></section>`;
    const pages = (a.pages || []).filter((p) => Number.isInteger(p) && p > 0 && Number.isInteger(v.pageCount) && p <= v.pageCount);
    const sourceLabel = a.page_source === 'candidate' ? '관련 쪽 후보' : '출처';
    const sources = a.streaming ? '' : pages.length
      ? `<div class="evc-src">${sourceLabel}${pages.map((p) => `<button type="button" class="evc-pg" data-v="${esc(vid)}" data-p="${p}" aria-label="${esc(v.name)} 제안서 ${p}쪽 열기">p.${p}</button>`).join('')}</div>`
      : '<div class="evc-src">출처 쪽 미확인</div>';
    return `<section class="evc-vs ev-vt-${esc(v.code)}"><h4><i></i>${esc(v.name)}</h4><p>${answerHtml(a.text, vid, v.name, pages)}</p>${sources}</section>`;
  }).join('');
  const any = m.vs.some((vid) => m.ans[vid] && m.ans[vid].text);
  return `<div class="evc-m a"><div class="evc-b"><p class="evc-lead">${any ? '선택한 업체별로 정리했어요.' : (m.lead || '관련 내용을 찾지 못했어요. 다르게 물어봐 주세요.')}</p>${secs}</div><time>${m.t}</time></div>`;
}

function renderList() {
  const box = cq('.evc-list');
  if (!box) return;
  let h = '';
  if (CH.offline) {
    h = `<div class="evc-empty"><div class="evc-hi" aria-hidden="true">🔌</div><b>문서 도우미 준비 중</b><p>${esc(CH.offlineReason || '챗봇 서비스가 아직 연결되지 않았어요. 제안서는 [제안서] 탭에서 직접 읽을 수 있어요.')}</p></div>`;
  } else if (!CH.msgs.length) {
    h = `<div class="evc-empty"><div class="evc-hi" aria-hidden="true">💬</div><b>무엇이 궁금하세요?</b><p>제안서 안에서 찾아 업체별로 나란히 알려드려요.</p><div class="evc-sug">${suggestions().map((q) => `<button type="button" class="evc-sq" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div></div>`;
  } else h = CH.msgs.map(msgHtml).join('');
  if (CH.busy && !CH.streaming) h += '<div class="evc-m a"><div class="evc-b evc-typing" role="status" aria-label="답변을 찾는 중"><i></i><i></i><i></i></div></div>';
  box.innerHTML = h;
  box.scrollTop = box.scrollHeight;
  cq('.evc-reset').disabled = !CH.msgs.length;
}

function renderVendors() {
  const host = cq('.evc-vendors');
  if (!host) return;
  host.innerHTML = '<span id="evc-vl">물어볼 업체</span>' + CH.all.map((v) =>
    `<button type="button" class="evc-vc ev-vt-${esc(v.code)}" data-v="${esc(v.id)}" aria-pressed="${CH.sel.includes(v.id)}"><i></i>${esc(v.name)}</button>`).join('');
}

function syncSend() { const ta = cq('.evc-in'); if (ta) cq('.evc-send').disabled = !ta.value.trim() || CH.busy || CH.offline; }

async function ask(text) {
  text = (text || '').trim();
  if (!text || CH.busy || CH.offline) return;
  if (!CH.sel.length) { toast('물어볼 업체를 하나 이상 골라 주세요'); return; }
  CH.msgs.push({ role: 'u', text, t: hhmm() });
  CH.busy = true; renderList();
  const ta = cq('.evc-in'); ta.value = ''; ta.style.height = ''; syncSend();
  const vs = CH.sel.slice();
  const history = CH.msgs.filter((m) => m.role === 'u').slice(-6, -1).map((m) => m.text);
  const answer = { role: 'a', vs, ans: Object.fromEntries(vs.map((id) => [id, { text: '', streaming: true }])), t: hhmm() };
  CH.msgs.push(answer);
  const controller = new AbortController(), runId = ++CH.runId;
  CH.controller = controller;
  let frame = 0;
  const scheduleRender = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; if (runId === CH.runId) renderList(); }); };
  try {
    await postStream(`${base()}/chat/stream`, { vendors: vs, question: text, history }, (event) => {
      if (runId !== CH.runId) return;
      if (event.type === 'delta' || event.type === 'replace') {
        const current = answer.ans[event.vendor];
        if (!current) return;
        current.text = event.type === 'replace' ? event.text : current.text + event.text;
        CH.streaming = true;
        scheduleRender();
      } else if (event.type === 'answer' && answer.ans[event.vendor]) {
        answer.ans[event.vendor] = event.answer;
        CH.streaming = true;
        scheduleRender();
      }
    }, { signal: controller.signal });
  } catch (e) {
    if (runId !== CH.runId || controller.signal.aborted) return;
    if (e.status === 503) { CH.offline = true; CH.offlineReason = messageFor(e); }
    else {
      answer.lead = messageFor(e);
      for (const id of vs) if (answer.ans[id]?.streaming) answer.ans[id] = { text: null, error: messageFor(e) };
    }
  } finally {
    if (frame) cancelAnimationFrame(frame);
    if (runId === CH.runId) { CH.busy = false; CH.streaming = false; CH.controller = null; renderList(); syncSend(); }
  }
}

function build() {
  const root = document.createElement('div');
  root.className = 'evc';
  root.innerHTML =
    '<button type="button" class="evc-fab" aria-haspopup="dialog" aria-expanded="false" aria-controls="evc-win" aria-label="문서 도우미 열기"><svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path fill="currentColor" d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-4.4 3.7A.6.6 0 0 1 3.6 20.2V17H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><circle cx="8" cy="10.5" r="1.2" fill="#fff"/><circle cx="12" cy="10.5" r="1.2" fill="#fff"/><circle cx="16" cy="10.5" r="1.2" fill="#fff"/></svg><span class="evc-tip" aria-hidden="true">문서에 질문</span></button>' +
    '<section class="evc-win" id="evc-win" role="dialog" aria-label="문서 도우미" hidden>' +
    `<header class="evc-hd"><div class="evc-ti"><b>문서 도우미</b><span>${esc(CH.me.project.name)}</span></div>` +
    '<button type="button" class="evc-reset" title="대화 초기화">대화 초기화</button><button type="button" class="evc-x" aria-label="닫기">✕</button></header>' +
    '<div class="evc-vendors" role="group" aria-labelledby="evc-vl"></div>' +
    '<div class="evc-list" role="log" aria-live="polite" aria-label="대화"></div>' +
    '<p class="evc-note">이 사업 문서 안에서만 답해요 · 대화는 저장하지 않아요</p>' +
    '<form class="evc-form"><textarea class="evc-in" rows="1" placeholder="궁금한 점을 입력하세요" aria-label="질문 입력 (Enter 보내기, Shift+Enter 줄바꿈)"></textarea><button type="submit" class="evc-send" aria-label="보내기"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor" d="M3.4 20.4 21 12 3.4 3.6l-.1 6.5L15 12 3.3 13.9l.1 6.5Z"/></svg></button></form></section>';
  document.body.appendChild(root);
  const fab = root.querySelector('.evc-fab'), win = root.querySelector('.evc-win'), ta = root.querySelector('.evc-in');
  fab.addEventListener('click', () => (CH.isOpen ? close(true) : open()));
  root.querySelector('.evc-x').addEventListener('click', () => close(true));
  root.querySelector('.evc-reset').addEventListener('click', () => { CH.runId += 1; CH.controller?.abort(); CH.controller = null; CH.busy = false; CH.streaming = false; CH.msgs = []; renderList(); syncSend(); toast('대화를 초기화했어요', 1600); ta.focus(); });
  root.querySelector('.evc-form').addEventListener('submit', (e) => { e.preventDefault(); ask(ta.value); });
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(ta.value); } });
  ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 110)}px`; syncSend(); });
  win.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); } });
  win.addEventListener('click', (e) => {
    const q = e.target.closest('[data-q]'); if (q) { ask(q.dataset.q); return; }
    const g = e.target.closest('.evc-pg'); if (g) { openPage(g.dataset.v, +g.dataset.p, g); return; }
    const v = e.target.closest('.evc-vc');
    if (v) {
      const i = CH.sel.indexOf(v.dataset.v);
      if (i >= 0) CH.sel.splice(i, 1); else CH.sel.push(v.dataset.v);
      CH.sel = CH.all.map((x) => x.id).filter((x) => CH.sel.includes(x));
      renderVendors();
      if (!CH.msgs.length) renderList();
      const nb = cq(`.evc-vc[data-v="${v.dataset.v}"]`); if (nb) nb.focus();
    }
  });
  document.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || !CH.isOpen) return; setTimeout(() => { if (!e.defaultPrevented && CH.isOpen && !document.querySelector('.ev-scrim')) close(true); }, 0); });
  CH.built = true;
  renderVendors(); renderList(); syncSend();
}

export function mountChat({ me }) {
  if (CH.built) return;
  if (!me || !me.session) return;
  const key = me.session.id;
  if (CH.sessionKey && CH.sessionKey !== key) { CH.msgs = []; }
  CH.sessionKey = key;
  CH.me = me;
  build();
  loadVendors();
}

export function open(question) {
  if (!CH.built) return;
  const win = cq('.evc-win'), fab = cq('.evc-fab');
  CH.last = document.activeElement;
  win.hidden = false; CH.isOpen = true;
  fab.setAttribute('aria-expanded', 'true'); fab.setAttribute('aria-label', '문서 도우미 닫기');
  document.querySelector('.evc').classList.add('open');
  if (question && typeof question === 'string') ask(question); else setTimeout(() => cq('.evc-in').focus(), 30);
}

export function close(refocus) {
  const win = cq('.evc-win');
  if (!win || !CH.isOpen) return;
  win.hidden = true; CH.isOpen = false;
  document.querySelector('.evc').classList.remove('open');
  const fab = cq('.evc-fab'); fab.setAttribute('aria-expanded', 'false'); fab.setAttribute('aria-label', '문서 도우미 열기');
  if (refocus) fab.focus();
}

export function setVendors(ids) {
  CH.sel = CH.all.map((v) => v.id).filter((id) => ids.includes(id));
  if (CH.built) { renderVendors(); if (!CH.msgs.length) renderList(); }
}
