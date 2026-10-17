const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = '/committee-v2/api';
const params = new URLSearchParams(location.search);
let bootstrap, projectState, candidates = [], page = 1, preview, busy = false;
let activeTab = params.get('view') === 'pool' ? 'pool' : 'selection';
const selected = new Map();
const retryKeys = new Map();
const contacts = {NOT_CONTACTED:'미연락',AVAILABLE:'참여 가능',UNAVAILABLE:'참여 불가',CALLBACK:'재연락'};

function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
async function task(work) {
  if (busy) return;
  busy = true;
  const buttons = [...document.querySelectorAll('button')].map((b) => [b, b.disabled]);
  buttons.forEach(([b]) => { b.disabled = true; });
  document.body.classList.add('busy');
  try { await work(); }
  catch (error) { message(error.message || '요청을 처리하지 못했습니다.', true); }
  finally {
    busy = false; buttons.forEach(([b, disabled]) => { b.disabled = disabled; });
    document.body.classList.remove('busy'); syncButtons();
  }
}
async function request(path, body, options = {}) {
  const method = options.method || (body === undefined ? 'GET' : 'POST');
  const multipart = body instanceof FormData;
  const fingerprint = options.fingerprint || path + ':' + JSON.stringify(body);
  const key = retryKeys.get(fingerprint) || crypto.randomUUID();
  if (method === 'POST') retryKeys.set(fingerprint, key);
  let response;
  try {
    response = await fetch(api + path, {
      method, credentials:'same-origin', headers:{'X-Committee-Client':'v2-web',
        ...(method === 'POST' ? {'Idempotency-Key':key} : {}),
        ...(body !== undefined && !multipart ? {'Content-Type':'application/json'} : {})},
      ...(body !== undefined ? {body:multipart ? body : JSON.stringify(body)} : {}),
    });
  } catch { throw new Error('서버 연결을 확인하세요. 같은 작업을 다시 누르면 동일한 요청키로 재시도합니다.'); }
  if (response.status < 500) retryKeys.delete(fingerprint);
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    if (response.status === 401) {
      $('login-panel').hidden = false; $('workspace').hidden = true; $('logout').hidden = true;
    }
    throw new Error(failure.error?.message || failure.detail || `요청 실패 (${response.status})`);
  }
  if (options.download) {
    const blob = await response.blob(), url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = options.download; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); return;
  }
  return (await response.json()).data;
}
const action = (id, body, options) => request('/actions/' + id, body, options);
const projectId = () => $('project').value;
const departmentId = () => $('department').value;
const specialtyName = (id) => bootstrap.specialties.find((s) => s.id === id)?.name || id;
const scoped = () => ({department_id:departmentId(), scope:$('scope').value,
  ...($('scope').value === 'PROJECT' ? {project_id:projectId()} : {})});
function chooseTab(tab) {
  activeTab = tab;
  $('pool-panel').hidden = tab !== 'pool'; $('selection-panel').hidden = tab !== 'selection';
  $('tab-pool').classList.toggle('active', tab === 'pool');
  $('tab-selection').classList.toggle('active', tab === 'selection');
}
function syncButtons() {
  const locked = !!projectState?.roster, drawn = !!projectState?.draw;
  $('previous').disabled = busy || page <= 1;
  $('next').disabled = busy || page * 50 >= Number($('pool-count').dataset.total || 0);
  $('commit-import').disabled = busy || !preview?.can_commit;
  $('rules-fields').disabled = busy || locked || drawn;
  $('draw').disabled = busy || locked || drawn || projectState?.rule?.selection_mode !== 'POOL_RANDOM';
  $('draw').hidden = projectState?.rule?.selection_mode === 'DIRECT';
  $('export-draw').disabled = busy || !drawn;
  $('export-roster').disabled = busy || !locked;
  $('review-roster').disabled = busy || locked || !projectState?.rule;
}
function resetEditor() {
  $('candidate-form').reset(); $('candidate-form').elements.candidate_id.value = '';
  $('candidate-form').elements.version.value = '';
  $('save-candidate').textContent = '위원 등록'; $('candidate-editor').open = false;
}
function clearPreview() { preview = null; $('import-preview').replaceChildren(); $('commit-import').hidden = true; }
async function connect() {
  bootstrap = await request('/bootstrap');
  $('login-panel').hidden = true; $('workspace').hidden = false; $('logout').hidden = false;
  $('mode').textContent = (bootstrap.synthetic_data ? '로컬 시연용 합성 자료 · ' : '') +
    (bootstrap.shared_auth_connected ? '공통 관리자 로그인과 평가 명단 수신기가 연결되었습니다.' : '위원 기능은 SQLite에 실제 저장됩니다. 공통 로그인·평가 수신기는 아직 연결되지 않았습니다.');
  if (bootstrap.shared_auth_connected && params.get('shared')) $('logout').hidden = true;
  $('department').innerHTML = bootstrap.departments.map((d) => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join('');
  $('project').innerHTML = bootstrap.projects.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  const requested = params.get('project_id');
  if (requested && !bootstrap.projects.some((p) => p.id === requested)) {
    $('project').insertAdjacentHTML('afterbegin', `<option value="${esc(requested)}">연결되지 않은 사업 · ${esc(requested)}</option>`);
  }
  if (requested) $('project').value = requested;
  const project = bootstrap.projects.find((p) => p.id === projectId());
  if (project) $('department').value = project.department_id;
  $('project').disabled = !!requested;
  $('filter-specialty').innerHTML = '<option value="">전체 분야</option>' + bootstrap.specialties.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  $('candidate-specialties').innerHTML = bootstrap.specialties.map((s) => `<label><input type="checkbox" name="specialty" value="${esc(s.id)}">${esc(s.name)}</label>`).join('');
  chooseTab(activeTab); await reload();
}
async function loadPool() {
  if (!departmentId()) return;
  const query = {...scoped(), search:$('search').value, page, page_size:50};
  if ($('filter-specialty').value) query.specialty_id = $('filter-specialty').value;
  if ($('filter-active').value) query.active = $('filter-active').value === 'true';
  const data = await action('COM-01', query);
  candidates = data.items;
  $('pool-count').textContent = `총 ${data.total}명 · 현재 등록 범위: ${$('scope').selectedOptions[0].textContent}`;
  $('pool-count').dataset.total = data.total;
  $('page').textContent = `${page} / ${Math.max(1, Math.ceil(data.total / 50))} 페이지`;
  const direct = projectState?.rule?.selection_mode === 'DIRECT' && !projectState.roster;
  $('candidate-rows').innerHTML = candidates.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.organization_name)}</td><td>${c.specialty_ids.map(specialtyName).map(esc).join(', ')}</td><td>***-****-${esc(c.phone.slice(-4))}</td><td>${c.active ? '활성' : '비활성'}</td><td><button data-edit="${esc(c.id)}">수정</button> <button data-disable="${esc(c.id)}" ${!c.active ? 'disabled' : ''}>비활성화</button> ${direct && c.active ? `<button data-add="${esc(c.id)}">사업에 추가</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="6">등록된 후보가 없습니다.</td></tr>';
}
async function loadProject() {
  projectState = null;
  const exists = bootstrap.projects.some((p) => p.id === projectId());
  $('project-unavailable').hidden = exists; $('project-work').hidden = !exists;
  if (!exists) return;
  projectState = await request('/projects/' + encodeURIComponent(projectId()));
  const {rule, quotas, draw, roster, items, assignments, handoff} = projectState;
  $('selection-mode').value = rule?.selection_mode || 'POOL_RANDOM';
  $('target').value = rule?.target_count || 7; $('reserves').value = rule?.reserve_count ?? 2;
  $('quotas').innerHTML = bootstrap.specialties.map((s, i) => `<label>${esc(s.name)} 정원<input type="number" min="0" max="9" data-quota="${esc(s.id)}" value="${quotas.find((q) => q.specialty_id === s.id)?.final_count ?? (rule ? 0 : (bootstrap.specialties.length >= 3 ? [3,2,2][i] || 0 : i === 0 ? 7 : 0))}"></label>`).join('');
  toggleQuotas();
  $('rules-state').textContent = rule ? `저장된 규칙: 정위원 ${rule.target_count}명 / 예비 ${rule.reserve_count}명 · 버전 ${rule.version}${draw || roster ? ' · 변경 잠김' : ''}` : '먼저 선정 규칙을 저장하세요.';
  $('draw-state').textContent = draw ? `분야별 3배수 선정 완료 · ${items.length}명` : rule?.selection_mode === 'DIRECT' ? '직접 등록 방식입니다. 추첨 없이 후보를 등록하고 연락 결과를 기록하세요.' : '규칙 저장 후 분야별 3배수를 선정합니다. 같은 후보가 중복 선정되지 않습니다.';
  $('nominee-count').textContent = `사업 후보 ${items.length}명 · 참여 가능 ${items.filter((n) => n.contact_status === 'AVAILABLE' && !n.exclusion_reason).length}명`;
  for (const id of selected.keys()) if (!items.some((n) => n.id === id)) selected.delete(id);
  if (roster) { selected.clear(); assignments.forEach((a) => selected.set(a.nominee_id, {kind:a.member_kind, order:a.reserve_order})); }
  $('nominee-rows').innerHTML = items.map((n) => {
    const c = n.candidate, choice = selected.get(n.id) || {kind:'', order:''};
    const lock = roster || n.exclusion_reason ? 'disabled' : '';
    return `<tr data-nominee="${esc(n.id)}"><td>${esc(c.name)}<small>${esc(c.organization_name)} · ${esc(c.phone)}</small>${n.exclusion_reason ? `<small>제외: ${esc(n.exclusion_reason)}</small>` : ''}</td><td>${c.specialty_ids.map(specialtyName).map(esc).join(', ')}</td><td><select aria-label="${esc(c.name)} 연락 결과" data-contact ${lock}>${Object.entries(contacts).map(([k,v]) => `<option value="${k}" ${n.contact_status === k ? 'selected' : ''}>${v}</option>`).join('')}</select></td><td><input aria-label="${esc(c.name)} 통화 메모" data-note maxlength="1000" value="${esc(n.contact_note)}" ${lock}></td><td><button data-save-contact ${lock}>저장</button></td><td><select aria-label="${esc(c.name)} 명단 구분" data-kind ${lock}><option value="">선택 안 함</option><option value="PRIMARY" ${choice.kind === 'PRIMARY' ? 'selected' : ''}>정위원</option><option value="RESERVE" ${choice.kind === 'RESERVE' ? 'selected' : ''}>예비위원</option></select></td><td><input type="number" aria-label="${esc(c.name)} 예비 순위" data-order min="1" max="27" value="${esc(choice.order)}" ${lock || choice.kind !== 'RESERVE' ? 'disabled' : ''}></td><td><button data-exclude ${lock}>제외</button></td></tr>`;
  }).join('') || '<tr><td colspan="8">선정 또는 직접 등록 후 후보가 표시됩니다.</td></tr>';
  $('confirmed').innerHTML = roster ? `<p><strong>초청 명단 확정 완료</strong> · 정위원 ${assignments.filter((a) => a.member_kind === 'PRIMARY').length}명 / 예비 ${assignments.filter((a) => a.member_kind === 'RESERVE').length}명</p><p>${handoff?.status === 'SENT' ? '평가 모듈 수신 확인 완료' : handoff?.status === 'FAILED' ? '평가 모듈 전달 실패 · 연결 상태 확인 필요' : '평가 모듈 수신 대기 · 위원 로그인 준비 중'}</p>` : '<p>연락 결과와 정위원·예비 순위를 확인한 뒤 명단을 검토하세요.</p>';
  updateCounts();
}
async function reload() { await loadProject(); await loadPool(); syncButtons(); }
function toggleQuotas() { $('quotas').hidden = $('selection-mode').value === 'DIRECT'; $('quota-hint').hidden = $('quotas').hidden; }
function updateCounts() {
  const values = [...selected.values()];
  $('member-count').textContent = `선택: 정위원 ${values.filter((x) => x.kind === 'PRIMARY').length}명 / 예비 ${values.filter((x) => x.kind === 'RESERVE').length}명`;
}
function rosterMembers() {
  return projectState.items.filter((n) => selected.get(n.id)?.kind).map((n) => {
    const value = selected.get(n.id);
    if (n.contact_status !== 'AVAILABLE' || n.exclusion_reason || !n.candidate.active) throw new Error(`${n.candidate.name}: 참여 가능 상태로 저장된 활성 후보만 확정할 수 있습니다.`);
    return {nominee_id:n.id, version:n.version, member_kind:value.kind,
      ...(value.kind === 'RESERVE' ? {reserve_order:Number(value.order)} : {})};
  });
}

$('login-form').onsubmit = (event) => { event.preventDefault(); void task(async () => {
  await request('/session', {access_code:event.target.elements.access_code.value});
  event.target.reset(); await connect(); message('위원 기능에 연결했습니다. 변경 내용은 SQLite에 저장됩니다.');
}); };
$('logout').onclick = () => void task(async () => {
  await request('/session', undefined, {method:'DELETE'}); selected.clear(); retryKeys.clear();
  $('workspace').hidden = true; $('login-panel').hidden = false; $('logout').hidden = true; message('연결을 종료했습니다.');
});
$('tab-pool').onclick = () => chooseTab('pool'); $('tab-selection').onclick = () => chooseTab('selection');
$('direct-pool').onclick = () => { chooseTab('pool'); $('scope').value = 'PROJECT'; page = 1; void task(loadPool); };
$('refresh').onclick = () => void task(async () => { await reload(); message('최신 저장 상태를 불러왔습니다.'); });
$('project').onchange = () => void task(async () => {
  selected.clear(); clearPreview(); resetEditor(); page = 1;
  const p = bootstrap.projects.find((p) => p.id === projectId()); if (p) $('department').value = p.department_id;
  await reload();
});
$('department').onchange = () => void task(async () => { page = 1; clearPreview(); resetEditor(); await loadPool(); });
$('scope').onchange = () => void task(async () => { page = 1; clearPreview(); resetEditor(); await loadPool(); });
$('search-form').onsubmit = (event) => { event.preventDefault(); page = 1; void task(loadPool); };
$('previous').onclick = () => { page--; void task(loadPool); }; $('next').onclick = () => { page++; void task(loadPool); };
$('new-candidate').onclick = () => { resetEditor(); $('candidate-editor').open = true; $('candidate-form').elements.name.focus(); };
$('cancel-edit').onclick = resetEditor;
$('candidate-form').onsubmit = (event) => { event.preventDefault(); void task(async () => {
  const form = event.target.elements, id = form.candidate_id.value;
  const data = {name:form.name.value, organization_name:form.organization_name.value,
    department_name:form.department_name.value || null, position:form.position.value || null,
    phone:form.phone.value, email:form.email.value || null,
    specialty_ids:[...document.querySelectorAll('input[name=specialty]:checked')].map((e) => e.value)};
  if (!data.specialty_ids.length) throw new Error('전문분야를 하나 이상 선택하세요.');
  await action(id ? 'COM-06' : 'COM-05', id ? {...data,candidate_id:id,version:Number(form.version.value)} : {...data,...scoped()});
  resetEditor(); await reload(); message(id ? '위원 정보를 수정했습니다.' : '위원을 등록했습니다.');
}); };
$('candidate-rows').onclick = (event) => {
  const button = event.target.closest('button'); if (!button) return;
  const id = button.dataset.edit || button.dataset.disable || button.dataset.add;
  const c = candidates.find((c) => c.id === id); if (!c) return;
  if (button.dataset.edit) {
    resetEditor(); const form = $('candidate-form').elements;
    for (const key of ['name','organization_name','department_name','position','phone','email','version']) form[key].value = c[key] ?? '';
    form.candidate_id.value = c.id;
    document.querySelectorAll('input[name=specialty]').forEach((el) => { el.checked = c.specialty_ids.includes(el.value); });
    $('save-candidate').textContent = '수정 저장'; $('candidate-editor').open = true; form.name.focus(); return;
  }
  if (button.dataset.disable && !confirm(`${c.name} 위원을 비활성화할까요? 기존 증빙은 유지됩니다.`)) return;
  void task(async () => {
    if (button.dataset.add) await action('ROS-02', {project_id:projectId(),candidate_id:c.id});
    else await action('COM-07', {candidate_id:c.id,version:c.version});
    await reload(); message(button.dataset.add ? '사업 후보에 추가했습니다.' : '위원을 비활성화했습니다.');
  });
};
$('template').onclick = () => void task(() => action('COM-02', {}, {download:'committee-template.xlsx'}));
$('excel-file').onchange = clearPreview;
$('import-form').onsubmit = (event) => { event.preventDefault(); void task(async () => {
  clearPreview(); const file = $('excel-file').files[0];
  if (!file || file.size > 8 * 1024 * 1024) throw new Error('8MB 이하 XLSX 파일을 선택하세요.');
  const body = new FormData(); body.append('file',file); body.append('password',$('excel-password').value);
  Object.entries(scoped()).forEach(([k,v]) => body.append(k,v));
  const sha = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))].map((b) => b.toString(16).padStart(2,'0')).join('');
  preview = await request('/imports/preview', body, {fingerprint:'import:' + sha + JSON.stringify(scoped())});
  $('excel-password').value = '';
  $('import-preview').innerHTML = `<p>유효 ${preview.valid_count}명 / 오류 ${preview.errors.length}건 · 30분 안에 등록하세요.</p>` +
    preview.errors.map((e) => `<p class="notice">${esc(e.row ?? e.row_number ?? '')}행: ${esc(e.message)}</p>`).join('') +
    `<div class="table-wrap"><table><thead><tr><th>성명</th><th>소속</th><th>휴대전화</th></tr></thead><tbody>${preview.items.map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.organization_name)}</td><td>${esc(r.phone)}</td></tr>`).join('')}</tbody></table></div>`;
  $('commit-import').hidden = !preview.can_commit;
  message(preview.can_commit ? '미리보기를 확인한 뒤 검증 목록 등록을 누르세요.' : '오류를 수정한 뒤 다시 미리보기 하세요.', !preview.can_commit);
}); };
$('commit-import').onclick = () => void task(async () => {
  const result = await action('COM-04', {preview_id:preview.id,version:preview.version});
  clearPreview(); $('import-form').reset(); await reload(); message(`${result.count}명을 등록했습니다.`);
});
$('selection-mode').onchange = toggleQuotas;
$('rules-form').onsubmit = (event) => { event.preventDefault(); void task(async () => {
  const quotas = $('selection-mode').value === 'DIRECT' ? [] : [...document.querySelectorAll('[data-quota]')].map((el) => ({specialty_id:el.dataset.quota,final_count:Number(el.value)})).filter((q) => q.final_count > 0);
  if ($('selection-mode').value !== 'DIRECT' && quotas.reduce((sum,q) => sum+q.final_count,0) !== Number($('target').value)) throw new Error('분야별 정원 합계와 정위원 수가 같아야 합니다.');
  await action('DRAW-01', {project_id:projectId(),selection_mode:$('selection-mode').value,target_count:Number($('target').value),reserve_count:Number($('reserves').value),quotas,version:projectState.rule?.version || 0});
  await reload(); message('선정 규칙을 저장했습니다.');
}); };
$('draw').onclick = () => {
  if (!confirm('분야별 3배수를 선정할까요? 선정 후 규칙 변경과 재추첨은 제한됩니다.')) return;
  void task(async () => { await action('DRAW-02', {project_id:projectId(),rule_version:projectState.rule.version}); await reload(); message('분야별 3배수 선정을 완료했습니다. 통화 결과를 기록하세요.'); });
};
$('export-draw').onclick = () => void task(() => action('DRAW-03', {project_id:projectId(),draw_id:projectState.draw.id}, {download:'committee-shortlist.xlsx'}));
$('export-roster').onclick = () => void task(() => action('ROS-06', {project_id:projectId(),roster_id:projectState.roster.id}, {download:'committee-roster.xlsx'}));
$('nominee-rows').onchange = (event) => {
  if (!event.target.matches('[data-kind],[data-order]')) return;
  const row = event.target.closest('[data-nominee]'), kind = row.querySelector('[data-kind]').value;
  const order = row.querySelector('[data-order]'); order.disabled = kind !== 'RESERVE';
  selected.set(row.dataset.nominee, {kind,order:order.value}); updateCounts();
};
$('nominee-rows').onclick = (event) => {
  const button = event.target.closest('button'); if (!button) return;
  const row = button.closest('[data-nominee]'), n = projectState.items.find((n) => n.id === row.dataset.nominee);
  let reason;
  if (button.hasAttribute('data-exclude')) { reason = prompt(`${n.candidate.name} 후보 제외 사유를 입력하세요.`); if (!reason?.trim()) return; }
  void task(async () => {
    const base = {project_id:projectId(),nominee_id:n.id,version:n.version};
    if (reason) { await action('ROS-04', {...base,reason}); selected.delete(n.id); }
    else await action('ROS-03', {...base,contact_status:row.querySelector('[data-contact]').value,contact_note:row.querySelector('[data-note]').value});
    await loadProject(); message(reason ? '사업 후보에서 제외했습니다.' : '연락 결과를 저장했습니다.');
  });
};
$('review-roster').onclick = () => void task(async () => {
  const members = rosterMembers(), rule = projectState.rule;
  const primary = members.filter((m) => m.member_kind === 'PRIMARY'), reserves = members.filter((m) => m.member_kind === 'RESERVE');
  if (primary.length !== rule.target_count || reserves.length !== rule.reserve_count) throw new Error(`정위원 ${rule.target_count}명과 예비 ${rule.reserve_count}명을 선택하세요.`);
  if (reserves.map((m) => m.reserve_order).sort((a,b) => a-b).some((n,i) => n !== i+1)) throw new Error('예비 순위는 1부터 중복 없이 입력하세요.');
  $('review-content').innerHTML = `<table><thead><tr><th>구분</th><th>성명</th><th>소속</th></tr></thead><tbody>${members.map((m) => { const c = projectState.items.find((n) => n.id === m.nominee_id).candidate; return `<tr><td>${m.member_kind === 'PRIMARY' ? '정위원' : '예비 '+m.reserve_order}</td><td>${esc(c.name)}</td><td>${esc(c.organization_name)}</td></tr>`; }).join('')}</tbody></table>`;
  $('review-dialog').showModal();
});
$('close-review').onclick = () => $('review-dialog').close();
$('confirm-roster').onclick = () => void task(async () => {
  const members = rosterMembers();
  try { await action('ROS-05', {project_id:projectId(),rule_version:projectState.rule.version,members}); }
  finally { $('review-dialog').close(); }
  await reload(); message('초청 명단을 확정했습니다. 평가 모듈의 수신 확인을 기다리고 있습니다.');
});
void task(async () => { try { await connect(); } catch (error) { if (!error.message.includes('연결 코드를 입력')) throw error; } });
