// EV-02 · AUTH-03 · 공통 틀: 위 한 줄(로고 · 탭 · 사업명·이름 메뉴 · 로그아웃) + 알림. v2/위원/_eval.js EvalShell 이식, 자료는 /auth/me.
import { mountChat } from './chat.js';
import { isAttended, isChair, logout, participantGate, resultsOpen, screenHref } from './session.js';

export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const TABS = [
  { id: 'rfp', label: '제안요청서', folder: 'EV-03', need: 'attended' },
  { id: 'proposals', label: '평가항목 분석', folder: 'EV-05', need: 'participant' },
  { id: 'scoring', label: '평가하기', folder: 'EV-06', need: 'participant' },
  { id: 'chair', label: '평가결과 확인', folder: 'EV-07', chairOnly: true, need: 'results' },
];

let toastEl, toastTimer;
export function toast(msg, ms = 2600) {
  if (!toastEl) {
    toastEl = document.createElement('div');
    toastEl.className = 'ev-toast';
    toastEl.setAttribute('role', 'status');
    toastEl.setAttribute('aria-live', 'polite');
    document.body.appendChild(toastEl);
  }
  toastEl.textContent = msg;
  void toastEl.offsetWidth;
  toastEl.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('on'), ms);
}

function lockReason(tab, me) {
  if (tab.need === 'attended' && !isAttended(me)) return '참석 확인 뒤에 열려요';
  if (tab.need === 'participant') {
    const gate = participantGate(me);
    return gate.ok ? '' : gate.reason;
  }
  if (tab.need === 'results') {
    if (resultsOpen(me)) return '';
    const s = me.session || {};
    return `모든 위원이 제출하면 열려요 · 제출 ${s.submitted ?? 0}/${s.participant_count ?? 0}`;
  }
  return '';
}

/** host 에 위 한 줄을 그린다. opts: {active: 'rfp'|'proposals'|'scoring'|'chair'|null, me, chat: true|false}
 *  문서 도우미(FAB)는 실제 참여자이고 회차가 열린 화면에만 붙는다(정책 B). */
export function mountShell(host, { active = null, me, chat = true }) {
  if (chat && participantGate(me).ok) mountChat({ me });
  const tabs = TABS.filter((t) => !t.chairOnly || isChair(me)).map((t) => {
    const reason = lockReason(t, me);
    const cur = active === t.id ? ' aria-current="page"' : '';
    if (reason) {
      return `<a class="ev-tab is-locked" href="#" data-locked="${esc(reason)}" aria-disabled="true"${cur} aria-label="${esc(t.label)}, 잠김. ${esc(reason)}">` +
        `<span class="ev-lock" aria-hidden="true">🔒</span>${esc(t.label)}<span class="ev-lock-text" aria-hidden="true">잠김</span></a>`;
    }
    return `<a class="ev-tab" href="${screenHref(t.folder)}"${cur}>${esc(t.label)}</a>`;
  }).join('');
  const who = `${esc(me.principal.display_name)} ${esc(me.principal.role_label)}`;
  host.className = 'ev-hd';
  host.innerHTML =
    `<a class="ev-mark" href="${screenHref('EV-03')}" aria-label="심사임당 처음으로"><i aria-hidden="true">심</i>심사임당</a>` +
    `<nav class="ev-tabs" aria-label="평가위원 메뉴">${tabs}</nav>` +
    '<div class="ev-user"><button type="button" class="ev-user-btn" aria-haspopup="menu" aria-expanded="false">' +
    `${esc(me.project.name)} · <b>${who}</b><span aria-hidden="true">▾</span></button>` +
    '<div class="ev-menu" role="menu" hidden><button type="button" role="menuitem" data-logout>로그아웃</button></div></div>';

  if (me.session && me.session.dev) {
    let band = document.getElementById('ev-devband');
    if (!band) {
      band = document.createElement('div');
      band.id = 'ev-devband';
      band.className = 'ev-devband';
      band.setAttribute('role', 'note');
      host.parentNode.insertBefore(band, host);
    }
    band.textContent = '개발용 자료 · 실제 평가 아님 (시드 회차)';
  }

  const btn = host.querySelector('.ev-user-btn');
  const menu = host.querySelector('.ev-menu');
  const close = (focus) => {
    if (menu.hidden) return false;
    menu.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    if (focus) btn.focus();
    return true;
  };
  host.addEventListener('click', (e) => {
    const locked = e.target.closest('[data-locked]');
    if (locked) { e.preventDefault(); toast(locked.dataset.locked); return; }
    if (e.target.closest('[data-logout]')) { logout(); return; }
    if (e.target.closest('.ev-user-btn')) {
      const open = menu.hidden;
      menu.hidden = !open;
      btn.setAttribute('aria-expanded', String(open));
      if (open) menu.querySelector('[role="menuitem"]')?.focus();
    }
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('.ev-user')) close(false); });
  host.addEventListener('keydown', (e) => { if (e.key === 'Escape' && close(true)) e.stopPropagation(); });
  return { close };
}

/** 화면 본문 자리에 상태(로딩·빈 목록·오류)를 보여 준다. */
export function showState(el, kind, headline, text) {
  el.innerHTML = `<div class="evr-state" role="${kind === 'loading' ? 'status' : 'alert'}">` +
    `${kind === 'loading' ? '<div class="spin" aria-hidden="true"></div>' : ''}<h2>${esc(headline)}</h2>${text ? `<p>${esc(text)}</p>` : ''}</div>`;
}
