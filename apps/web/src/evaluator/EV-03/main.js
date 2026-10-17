// EV-03 · VIEW-01~03 · DOC-05
// 제안요청서 읽기. 사업은 세션에서 오고, 자료는 /api/v2/evaluator/projects/{p}/documents/rfp/… 로만 받는다.
import { get, request } from '../common/api.js';
import { messageFor } from '../common/errors.js';
import { mountReader } from '../common/reader.js';
import { requireAttendance, requireLogin } from '../common/session.js';
import { mountShell, showState } from '../common/shell.js';

async function main() {
  const reader = document.getElementById('reader');
  showState(reader, 'loading', '제안요청서를 불러오고 있어요');
  const me = await requireLogin();
  mountShell(document.getElementById('hd'), { active: 'rfp', me });
  if (!requireAttendance(me)) return;
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
