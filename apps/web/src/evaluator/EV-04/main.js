// EV-04 · VIEW-01~03
// 제안서 업체별 읽기: 업체(표시 코드)를 고르고 그 업체 제안서를 목차로 읽는다. 자료는 회차에 고정된 문서만.
import { get, request } from '../common/api.js';
import { close as closeChat, setOpenPageHandler } from '../common/chat.js';
import { messageFor } from '../common/errors.js';
import { mountReader } from '../common/reader.js';
import { participantGate, requireAttendance, requireLogin, screenHref } from '../common/session.js';
import { esc, mountShell, showState } from '../common/shell.js';

const $ = (s) => document.querySelector(s);
const vs = $('#vs'), body = $('#body');
let me = null, proposals = [], cur = null;
const readers = {};

const base = () => `/projects/${encodeURIComponent(me.project.id)}/sessions/${encodeURIComponent(me.session.id)}/proposals`;

async function ensure(p) {
  if (readers[p.session_proposal_id]) return readers[p.session_proposal_id];
  const w = document.createElement('div'); w.className = 'pp-rd'; w.id = `rd-${p.session_proposal_id}`; w.hidden = true; body.appendChild(w);
  const el = document.createElement('div'); w.appendChild(el);
  showState(el, 'loading', `${p.display_name} 제안서를 불러오고 있어요`);
  const holder = { el, reader: null, wrap: w };
  readers[p.session_proposal_id] = holder;
  try {
    const { data } = await get(`${base()}/${encodeURIComponent(p.session_proposal_id)}`);
    if (!data.pages.length) { showState(el, 'empty', '제안서 쪽이 아직 없어요', '문서 변환이 끝나면 읽을 수 있어요.'); return holder; }
    el.innerHTML = '';
    const version = encodeURIComponent(data.document.source_version || '');
    const q = new URLSearchParams(location.search);
    holder.reader = mountReader(el, data, {
      label: `${p.display_name} 제안서`,
      loadPage: (n) => get(`${base()}/${encodeURIComponent(p.session_proposal_id)}/pages/${n}`).then((r) => r.data),
      svgUrl: (n) => `/api/v2/evaluator${base()}/${encodeURIComponent(p.session_proposal_id)}/pages/${n}/${p.format === 'PDF' ? 'png' : 'svg'}?v=${version}`,
      download: () => request('GET', `${base()}/${encodeURIComponent(p.session_proposal_id)}/source`, { raw: true }),
    }, {
      note: '평가 시작 때 고정된 제안서예요 · A사 표시는 화면용이에요 · 파일 안의 회사명은 지워지지 않을 수 있어요',
      startPage: q.get('v') === p.display_code && +q.get('p') ? +q.get('p') : 1,
      keysWhen: () => cur === p.session_proposal_id,
    });
  } catch (e) {
    showState(el, 'error', `${p.display_name} 제안서를 불러오지 못했어요`, messageFor(e));
  }
  return holder;
}

async function show(id, page = null) {
  cur = id;
  const p = proposals.find((x) => x.session_proposal_id === id);
  [...vs.children].forEach((b) => b.setAttribute('aria-selected', String(b.dataset.v === id)));
  for (const key of Object.keys(readers)) readers[key].wrap.hidden = key !== id;
  const holder = await ensure(p);
  holder.wrap.hidden = cur !== id;
  if (cur !== id) return;
  if (page && holder.reader) holder.reader.go(page);
  try {
    const q = new URLSearchParams({ project_id: me.project.id, v: p.display_code });
    if (page) q.set('p', String(page));
    history.replaceState(null, '', `?${q}`);
  } catch { /* */ }
}

async function main() {
  me = await requireLogin();
  mountShell($('#hd'), { active: 'proposals', me });
  if (!requireAttendance(me)) return;
  $('#to-compare').href = screenHref('EV-05');
  const gate = participantGate(me);
  if (!gate.ok) { showState(body, 'empty', '아직 제안서를 볼 수 없어요', gate.reason); vs.innerHTML = ''; return; }
  const { data } = await get(base());
  proposals = data.proposals;
  if (!proposals.length) { showState(body, 'empty', '등록된 업체가 없어요', '담당자가 업체와 제안서를 고정하면 여기에서 읽을 수 있어요.'); return; }
  body.innerHTML = '';
  vs.innerHTML = proposals.map((p) => `<button type="button" class="pp-v" role="tab" data-v="${esc(p.session_proposal_id)}" aria-selected="false">${esc(p.display_name)}<small>${p.available ? `${p.page_count}쪽` : '문서 없음'}</small></button>`).join('');
  vs.addEventListener('click', (e) => { const b = e.target.closest('[data-v]'); if (b) show(b.dataset.v); });
  setOpenPageHandler(async (vendor, page) => {
    const proposal = proposals.find((p) => p.session_proposal_id === vendor?.id);
    if (!proposal || page > proposal.page_count) return;
    await show(proposal.session_proposal_id, page);
    closeChat(false);
  });
  const q = new URLSearchParams(location.search);
  const start = proposals.find((p) => p.display_code === q.get('v')) || proposals[0];
  const requestedPage = Number(q.get('p'));
  await show(start.session_proposal_id, Number.isInteger(requestedPage) && requestedPage >= 1 && requestedPage <= start.page_count ? requestedPage : null);
}

main().catch((e) => showState(body, 'error', '제안서를 불러오지 못했어요', messageFor(e)));
