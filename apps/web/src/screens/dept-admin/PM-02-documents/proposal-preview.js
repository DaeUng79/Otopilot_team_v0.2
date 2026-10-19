import { mountReader } from '../../../evaluator/common/reader.js';
import { showState } from '../../../evaluator/common/shell.js';

const reader = document.getElementById('reader');
const query = new URLSearchParams(location.search);
const projectId = query.get('project_id');
const uploadId = query.get('upload_id');
const startPage = Number(query.get('page'));
const back = document.getElementById('back');
if (projectId) back.href += '?id=' + encodeURIComponent(projectId);

async function fetchPreview(path, raw = false) {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error?.message || '제안서를 불러오지 못했습니다.');
  }
  return raw ? response : (await response.json()).data;
}

async function main() {
  if (!projectId || !uploadId) {
    showState(reader, 'error', '제안서를 선택해 주세요', '문서 등록 화면에서 제안서를 열어 주세요.');
    return;
  }
  showState(reader, 'loading', '제안서를 불러오고 있어요');
  const base = '/api/v2/projects/' + encodeURIComponent(projectId)
    + '/proposals/' + encodeURIComponent(uploadId);
  const data = await fetchPreview(base + '/preview');
  document.title = data.document.title + ' · 제안서 확인';
  if (!data.pages.length) {
    showState(reader, 'empty', '제안서 쪽이 아직 없어요', '문서 파싱 상태를 확인해 주세요.');
    return;
  }
  reader.innerHTML = '';
  const originalPages = ['PDF', 'HWPX', 'HWP'].includes(data.format);
  mountReader(reader, data, {
    label: '제안서',
    loadPage: (n) => fetchPreview(base + '/preview/pages/' + n),
    svgUrl: data.format === 'PDF' ? (n) => base + '/preview/pages/' + n + '/png'
      : originalPages ? (n) => base + '/preview/pages/' + n + '/svg' : null,
    download: () => fetchPreview(base + '/download', true),
  }, { note: originalPages ? '등록된 제안서 · 원본 쪽 렌더링' : '원본 쪽 렌더링을 지원하지 않아 파싱된 내용을 표시합니다.',
       startPage: Number.isInteger(startPage) && startPage > 0 ? startPage : 1 });
}

main().catch((error) => {
  showState(reader, 'error', '제안서를 표시하지 못했어요', error.message);
});
