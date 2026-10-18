// 공통 · 세션 확인·게이트·로그아웃. 세션은 HttpOnly 쿠키에 있고 화면은 /auth/me 결과만 안다.
import { get, post, setCsrfToken } from './api.js';

const PROJECT_KEY = 'ev.project';
const CSRF_KEY = 'ev.csrf';
let meCache = null;

const store = {
  get: (k) => { try { return sessionStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { sessionStorage.setItem(k, v); } catch { /* 저장 못 해도 동작 */ } },
  del: (k) => { try { sessionStorage.removeItem(k); } catch { /* */ } },
};

export function projectIdFromUrl() {
  const q = new URLSearchParams(location.search);
  return q.get('project_id') || q.get('project');
}

export function knownProjectId() {
  return projectIdFromUrl() || store.get(PROJECT_KEY);
}

export function rememberProject(id) {
  if (id) store.set(PROJECT_KEY, id);
}

export function rememberCsrf(token) {
  if (token) { store.set(CSRF_KEY, token); setCsrfToken(token); }
}

export function loginHref() { return screenHref('EV-00'); }

export function screenHref(folder) {
  const names = {'EV-00':'login','EV-01':'attendance','EV-03':'rfp','EV-04':'proposals','EV-05':'compare','EV-06':'scoring','EV-07':'chair'};
  const p = knownProjectId();
  return `/app/evaluator/${folder}/design/${names[folder]}.html` + (p ? '?project_id=' + encodeURIComponent(p) : '');
}

/** 현재 주체 요약. 401 이면 로그인 화면으로 보낸다. */
export async function requireLogin() {
  setCsrfToken(store.get(CSRF_KEY));
  try {
    const { data } = await get('/auth/me');
    meCache = data;
    rememberProject(data.project.id);
    return data;
  } catch (error) {
    if (error.status === 401) {
      store.del(CSRF_KEY);
      location.replace(loginHref());
      await new Promise(() => {}); // 이동 중 렌더링 중단
    }
    throw error;
  }
}

export function cachedMe() { return meCache; }

export const isAttended = (me) => !!(me && me.attendance && me.attendance.status === 'CONFIRMED');
export const isParticipant = (me) => !!(me && me.participant);
export const isChair = (me) => !!(me && me.chair);
export const sessionStatus = (me) => (me && me.session ? me.session.status : null);
export const resultsOpen = (me) => ['ALL_SUBMITTED', 'FINALIZED'].includes(sessionStatus(me));

/** 참석 확인 전이면 EV-01 로 보낸다. */
export function requireAttendance(me) {
  if (isAttended(me)) return true;
  location.replace(screenHref('EV-01'));
  return false;
}

/** 실제 참여자가 아니면 이유를 돌려준다(화면이 안내 표시). */
export function participantGate(me) {
  if (!me.session) return { ok: false, reason: '평가회차가 아직 준비되지 않았어요. 담당자가 평가를 시작하면 열려요.' };
  if (!me.participant) {
    return { ok: false, reason: me.principal.member_kind === 'RESERVE'
      ? '예비위원은 참여 확정 뒤에 볼 수 있어요. 담당자가 확정하면 열려요.'
      : '실제 평가 참여자로 확정되지 않았어요. 담당자에게 문의해 주세요.' };
  }
  if (!['OPEN', 'ALL_SUBMITTED', 'FINALIZED'].includes(me.session.status)) {
    return { ok: false, reason: '평가가 아직 시작되지 않았어요. 담당자가 시작하면 열려요.' };
  }
  return { ok: true, reason: '' };
}

export async function logout() {
  try { await fetch('/api/v2/actions/AUTH-03', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-Simsa-Client':'v2-web'},body:'{}'}); } catch { /* 세션이 이미 없어도 화면은 초기화 */ }
  meCache = null;
  store.del(CSRF_KEY);
  location.href = loginHref();
}
