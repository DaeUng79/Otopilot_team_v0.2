// EV-03 · VIEW-01~03 · DOC-05
// 제안요청서 읽기. 사업은 세션에서 오고, 자료는 /api/v2/evaluator/projects/{p}/documents/rfp/… 로만 받는다.
import { get, request } from '../common/api.js';
import { setOpenPageHandler } from '../common/chat.js';
import { messageFor } from '../common/errors.js';
import { mountReader } from '../common/reader.js';
import { requireAttendance, requireLogin } from '../common/session.js';
import { mountShell, showState } from '../common/shell.js';

let me = null, slideOpen = false, activeProposalId = null, lastTrigger = null;
const proposalReaders = new Map();
const $ = (selector) => document.querySelector(selector);

function closeProposalPage() {
  if (!slideOpen) return;
  slideOpen = false;
  activeProposalId = null;
  $('#sl').classList.remove('on');
  $('#sl').setAttribute('aria-hidden', 'true');
  $('#sl-scrim').classList.remove('on');
  if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
}

async function openProposalPage(vendor, page, trigger) {
  if (!vendor || !Number.isInteger(page) || page < 1 || page > vendor.pageCount) return;
  lastTrigger = trigger;
  $('#sl-t').textContent = `${vendor.name} 제안서 · ${page}쪽`;
  $('#sl').classList.add('on');
  $('#sl').setAttribute('aria-hidden', 'false');
  $('#sl-scrim').classList.add('on');
  slideOpen = true;
  activeProposalId = vendor.id;
  for (const holder of proposalReaders.values()) holder.wrap.hidden = true;

  let holder = proposalReaders.get(vendor.id);
  if (!holder) {
    const wrap = document.createElement('div');
    wrap.className = 'cp-rd';
    $('#sl-bd').appendChild(wrap);
    const reader = document.createElement('div');
    wrap.appendChild(reader);
    showState(reader, 'loading', `${vendor.name} 제안서를 불러오고 있어요`);
    holder = { wrap, reader: null };
    proposalReaders.set(vendor.id, holder);
    try {
      const base = `/projects/${encodeURIComponent(me.project.id)}/sessions/${encodeURIComponent(me.session.id)}/proposals/${encodeURIComponent(vendor.id)}`;
      const { data } = await get(base);
      if (!data.pages.length) {
        showState(reader, 'empty', '제안서 쪽이 아직 없어요', '문서 변환이 끝나면 읽을 수 있어요.');
      } else {
        reader.innerHTML = '';
        const version = encodeURIComponent(data.document.source_version || '');
        const isPdf = /\.pdf$/i.test(data.document.filename || '');
        holder.reader = mountReader(reader, data, {
          label: `${vendor.name} 제안서`,
          loadPage: (n) => get(`${base}/pages/${n}`).then((response) => response.data),
          svgUrl: (n) => `/api/v2/evaluator${base}/pages/${n}/${isPdf ? 'png' : 'svg'}?v=${version}`,
          download: () => request('GET', `${base}/source`, { raw: true }),
        }, { single: true, startPage: page, keysWhen: () => slideOpen });
      }
    } catch (error) {
      showState(reader, 'error', '제안서를 불러오지 못했어요', messageFor(error));
    }
  }
  if (!slideOpen || activeProposalId !== vendor.id) return;
  holder.wrap.hidden = false;
  if (holder.reader) holder.reader.go(page);
  $('#sl-x').focus();
}

async function main() {
  const reader = document.getElementById('reader');
  showState(reader, 'loading', '제안요청서를 불러오고 있어요');
  me = await requireLogin();
  mountShell(document.getElementById('hd'), { active: 'rfp', me });
  if (!requireAttendance(me)) return;
  $('#sl-x').addEventListener('click', closeProposalPage);
  $('#sl-scrim').addEventListener('click', closeProposalPage);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && slideOpen) { event.preventDefault(); closeProposalPage(); }
  });
  setOpenPageHandler(openProposalPage);
  const base = `/projects/${encodeURIComponent(me.project.id)}/documents/rfp`;
  try {
    const { data } = await get(base);
    document.title = `${data.document.title} · 심사임당`;
    if (!data.pages.length) {
      showState(reader, 'empty', '제안요청서 쪽이 아직 없어요', '문서 변환이 끝나면 읽을 수 있어요.');
      return;
    }
    reader.innerHTML = '';
    const version = encodeURIComponent(data.document.source_version || '');
    mountReader(reader, data, {
      label: '제안요청서',
      loadPage: (n) => get(`${base}/pages/${n}`).then((r) => r.data),
      svgUrl: (n) => `/api/v2/evaluator${base}/pages/${n}/svg?v=${version}`,
      download: () => request('GET', `${base}/source`, { raw: true }),
    });
  } catch (e) {
    const missing = e.status === 404;
    showState(reader, 'error', missing ? '제안요청서 파일이 없어요' : '제안요청서를 불러오지 못했어요',
      missing ? e.message : messageFor(e));
  }
}

main().catch((e) => {
  showState(document.getElementById('reader'), 'error', '제안요청서를 불러오지 못했어요', messageFor(e));
});
