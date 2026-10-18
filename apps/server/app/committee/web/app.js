const prefix = '/api/v1/committee';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const state = {candidates:[],projects:[],pid:sessionStorage.getItem('committee-project')||'',draw:null,
  selected:new Set(),reserves:new Set(),health:{},query:'',busy:false,edit:null,preview:null,
  loaded:false,dirty:false,selectionDirty:false,savedSelections:new Map(),notes:new Map()};
let toastTimer,pendingNavigation=false;
const page=()=>location.hash.slice(1).split('?')[0]||'pool';
const authPid=()=>new URLSearchParams(location.hash.split('?')[1]||'').get('project')||'';
const project=()=>state.projects.find(p=>p.id===state.pid);
const nameOf=c=>c.name||`성명 미기재 (연번 ${c.source_serial||'없음'})`;
const phoneMask=phone=>phone?`${phone.slice(0,3)}-****-${phone.slice(-4)}`:'미기재';
const pills=fields=>fields.map(f=>`<span class="pill">${esc(f)}</span>`).join('');
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4000);}
function clearError(){$('error').hidden=true;$('error').textContent='';}
function showError(error){$('error').textContent=error.message||String(error);$('error').hidden=false;$('error').scrollIntoView({block:'nearest'});}
async function api(path,method='GET',body){
  const form=body instanceof FormData;
  const response=await fetch(prefix+path,{method,credentials:'same-origin',headers:{'X-Committee-Client':'local-ui',...(!form&&body!==undefined?{'Content-Type':'application/json'}:{})},body:body===undefined?undefined:form?body:JSON.stringify(body)});
  const data=await response.json().catch(()=>({detail:'서버 응답을 읽을 수 없습니다.'}));
  if(!response.ok){const error=new Error(Array.isArray(data.detail)?'입력한 항목을 확인하세요.':data.detail||'요청에 실패했습니다.');error.status=response.status;throw error;}
  return data;
}
async function act(fn){
  if(state.busy)return;state.busy=true;clearError();$('content').setAttribute('aria-busy','true');
  const controls=[...document.querySelectorAll('button,input,select,textarea')],prior=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true);
  try{await fn();}catch(error){showError(error);}finally{
    state.busy=false;$('content').removeAttribute('aria-busy');controls.forEach((c,i)=>{if(c.isConnected)c.disabled=prior[i];});
    if(pendingNavigation){pendingNavigation=false;queueMicrotask(()=>act(render));}
  }
}
function head(step,title,text,action=''){return `<div class="page-head"><div><p class="eyebrow">${esc(step)}</p><h1 tabindex="-1">${title}</h1><p class="subtle">${text}</p></div><div class="head-actions">${action}</div></div>`;}
function empty(title,text,href,label){return `<section class="card empty"><h2>${title}</h2><p class="subtle">${text}</p><a class="button primary" href="#${href}">${label}</a></section>`;}
function go(next){state.dirty=false;location.hash=next;}
function rememberSelection(){state.savedSelections.set(state.pid,{selected:[...state.selected],reserves:[...state.reserves],dirty:state.selectionDirty});}
function setProject(pid){rememberSelection();state.pid=pid;const saved=state.savedSelections.get(pid);state.selected=new Set(saved?.selected||[]);state.reserves=new Set(saved?.reserves||[]);state.selectionDirty=!!saved?.dirty;sessionStorage.setItem('committee-project',pid);}
async function load(){
  [state.candidates,state.projects]=await Promise.all([api('/candidates'),api('/projects')]);
  if(!state.projects.some(p=>p.id===state.pid))setProject(state.projects[0]?.id||'');
  $('project-picker').innerHTML=state.projects.length?state.projects.map(p=>`<option value="${p.id}" ${p.id===state.pid?'selected':''}>${esc(p.name)}</option>`).join(''):'<option value="">프로젝트 없음</option>';
  state.draw=state.pid?await api(`/projects/${state.pid}/draw`):null;
  if(state.draw?.finalized_at){state.selected=new Set(state.draw.final_ids);state.reserves=new Set(state.draw.reserve_ids);state.selectionDirty=false;}
  else{const allowed=state.draw?.contacts.filter(c=>c.status==='참여 가능').map(c=>c.candidate_id)||[];state.selected=new Set([...state.selected].filter(id=>allowed.includes(id)));state.reserves=new Set([...state.reserves].filter(id=>allowed.includes(id)));}
}
async function render(){
  const current=page(),auth=current==='auth';document.body.classList.toggle('evaluator-view',auth);
  if(!auth&&!state.loaded){await api('/local/session','POST');state.loaded=true;await load();}
  const nav=['candidate','import'].includes(current)?'pool':['proposal','draw','projects'].includes(current)?'projects':current;
  document.querySelectorAll('[data-page]').forEach(a=>{a.classList.toggle('active',a.dataset.page===nav);if(a.dataset.page===nav)a.setAttribute('aria-current','step');else a.removeAttribute('aria-current');});
  const views={pool:renderPool,candidate:renderCandidate,import:renderImport,projects:renderProjects,proposal:renderProposal,draw:renderDraw,final:renderFinal,assignment:renderAssignment,auth:renderAuth};
  await (views[current]||renderPool)();document.querySelector('h1')?.focus({preventScroll:true});
}
function renderPool(){
  const active=state.candidates.filter(c=>c.active).length;
  $('content').innerHTML=head('01 · 평가위원 풀','평가위원을 등록하세요','엑셀로 한 번에 등록하거나 한 명씩 직접 입력할 수 있습니다.','<a class="button" href="#candidate" id="new-candidate">한 명 등록</a><a class="button primary" href="#import">엑셀 등록</a>')+
    `<section class="card"><div class="card-head"><div><h2>후보 ${state.candidates.length}명</h2><p class="subtle">추첨 가능 ${active}명 · 정보 보완 ${state.candidates.length-active}명</p></div><label><span class="sr-only">후보 검색</span><input id="query" type="search" placeholder="이름·소속·분야 검색" value="${esc(state.query)}"></label></div><div id="pool-table"></div></section><div class="page-next"><a class="button primary" href="#projects">다음 · 제안서 등록</a></div>`;
  $('new-candidate').onclick=()=>state.edit=null;$('query').oninput=e=>{state.query=e.target.value;poolTable();};poolTable();
}
function poolTable(){
  const rows=state.candidates.filter(c=>[nameOf(c),c.organization,c.specialty].join(' ').includes(state.query.trim()));
  $('pool-table').innerHTML=rows.length?`<div class="table-wrap"><table><thead><tr><th>이름·소속</th><th>분야</th><th>휴대전화</th><th>상태</th><th><span class="sr-only">수정</span></th></tr></thead><tbody>${rows.map(c=>`<tr><td><strong>${esc(nameOf(c))}</strong><span class="subtle">${esc(c.organization)}</span></td><td>${pills(c.fields)}</td><td>${phoneMask(c.phone)}</td><td><span class="pill ${c.active?'green':'amber'}">${c.active?'추첨 가능':'정보 보완'}</span></td><td><button data-edit="${c.id}" aria-label="${esc(nameOf(c))} 정보 수정">수정</button></td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">표시할 후보가 없습니다.</p>';
  document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{state.edit=state.candidates.find(c=>c.id===b.dataset.edit);go('candidate');});
}
function renderCandidate(){
  const c=state.edit,input=(name,label,required=false,type='text')=>`<label class="field">${label}<input name="${name}" type="${type}" ${required?'required':''} maxlength="${name==='email'?254:200}" value="${esc(c?.[name]||'')}"></label>`;
  $('content').innerHTML=head('01 · 평가위원 풀',c?'평가위원 정보 수정':'평가위원 한 명 등록','이름·소속·분야를 입력하세요. 로그인에는 휴대전화 또는 이메일이 필요합니다.')+
    `<form id="candidate-form" class="card narrow card-body"><div class="field-grid">${input('name','이름',true)}${input('organization','소속',true)}${input('specialty','전문분야 (복수 분야는 쉼표로 구분)',true)}${input('phone','휴대전화',false,'tel')}${input('email','이메일',false,'email')}</div><details class="optional-fields"><summary>추가 정보</summary><div class="field-grid">${input('position','직위')}${input('category','구분')}${input('region','근무 지역')}${input('department','부서')}${input('birth_date','생년월일')}${input('memo','비고')}</div></details><label class="check-label"><input name="enabled" type="checkbox" ${c?.enabled===false?'':'checked'}>추첨 대상에 포함</label><div class="form-actions"><a class="button" href="#pool">취소</a><button class="primary" type="submit">저장</button></div></form>`;
  const form=$('candidate-form');form.oninput=()=>state.dirty=true;form.onsubmit=e=>{e.preventDefault();const data=new FormData(form),body=Object.fromEntries(data);body.enabled=data.has('enabled');act(async()=>{await api(c?`/candidates/${c.id}`:'/candidates',c?'PUT':'POST',c?{...body,expected_version:c.version}:body);state.dirty=false;state.edit=null;await load();go('pool');toast('평가위원을 저장했습니다.');});};
}
function renderImport(){
  $('content').innerHTML=head('01 · 평가위원 풀','엑셀로 등록하세요','부서 서식을 선택한 뒤 미리보기를 확인하고 저장합니다.')+
    `<section class="card narrow card-body"><form id="import-form"><label class="field">엑셀 파일 (.xlsx · 8MB 이하)<input name="file" type="file" accept=".xlsx" required></label><details class="optional-fields"><summary>암호가 있는 엑셀인가요?</summary><label class="field">파일 열기 암호<input name="password" type="password" autocomplete="off" maxlength="256"></label></details><div class="form-actions"><a class="button" href="#pool">취소</a><button class="primary" type="submit">미리보기</button></div></form><div id="import-preview"></div></section>`;
  const form=$('import-form');form.onsubmit=e=>{e.preventDefault();const data=new FormData(form);act(async()=>{state.preview=null;$('import-preview').innerHTML='';state.preview=await api('/imports/preview','POST',data);form.elements.password.value='';showPreview();});};
}
function showPreview(){
  const p=state.preview;
  $('import-preview').innerHTML=`<hr><h2>총 ${p.total}명</h2><p>추첨 가능 ${p.active}명 · 정보 보완 ${p.drafts}명</p>${p.conflict_rows.length?`<p class="notice warning">기존 휴대전화 중복: ${p.conflict_rows.map(esc).join(', ')}행. 파일을 수정해 다시 올려주세요.</p>`:''}<details class="optional-fields"><summary>행별 확인</summary><div class="result-table table-wrap"><table><thead><tr><th>행</th><th>이름</th><th>소속</th><th>확인 사항</th></tr></thead><tbody>${p.rows.map(c=>`<tr><td>${c.source_row}</td><td>${esc(c.name)||'미기재'}</td><td>${esc(c.organization)}</td><td>${esc(c.warnings.join(' · '))||'등록 가능'}</td></tr>`).join('')}</tbody></table></div></details><button id="commit-import" class="primary" ${p.conflict_rows.length?'disabled':''}>${p.total}명 저장</button>`;
  $('commit-import').onclick=()=>act(async()=>{await api(`/imports/${p.id}/commit`,'POST');state.preview=null;await load();go('pool');toast('엑셀의 후보를 저장했습니다.');});
}
function renderProjects(){
  $('content').innerHTML=head('02 · 제안서·추첨','평가할 제안서를 등록하세요','제안서를 등록하면 프로젝트가 자동으로 만들어집니다.','<a class="button primary" href="#proposal">제안서 등록</a>')+
    (state.projects.length?`<section class="card"><div class="project-list">${state.projects.map(p=>`<button class="project-item" data-project="${p.id}"><span><strong>${esc(p.name)}</strong><small>${p.configured?`${p.target}명 · ${esc(p.fields.join(', '))}`:'위원 수·분야 선택 전'}</small></span><span>이어서 준비 →</span></button>`).join('')}</div></section>`:empty('아직 등록된 제안서가 없습니다.','PDF 제안서를 등록하고 위원 수와 분야를 선택하세요.','proposal','제안서 등록'));
  document.querySelectorAll('[data-project]').forEach(b=>b.onclick=()=>act(async()=>{setProject(b.dataset.project);await load();go(state.draw?.finalized_at?'assignment':state.draw?'final':'draw');}));
}
function renderProposal(){
  $('content').innerHTML=head('02 · 제안서 등록','제안서를 선택하세요','등록 후 위원 수와 분야를 선택합니다.')+
    `<form id="proposal-form" class="card narrow card-body"><label class="field">제안서 (PDF · 8MB 이하)<input name="file" type="file" accept=".pdf,application/pdf" required></label><label class="field">프로젝트 이름 <span class="optional">비워두면 파일명을 사용합니다</span><input name="name" maxlength="200" placeholder="예: 정보화사업 제안서 평가"></label><div class="form-actions"><a class="button" href="#projects">취소</a><button class="primary" type="submit">등록하고 다음</button></div></form>`;
  const form=$('proposal-form');form.oninput=()=>state.dirty=true;form.onsubmit=e=>{e.preventDefault();const data=new FormData(form);act(async()=>{const p=await api('/proposals','POST',data);setProject(p.id);state.dirty=false;await load();go('draw');toast('제안서를 저장하고 프로젝트를 만들었습니다.');});};
}
async function renderDraw(){
  const p=project();$('content').innerHTML=head('02 · 3배수 추첨','위원 수와 분야를 선택하세요',p?esc(p.name):'평가할 제안서를 먼저 등록하세요.');
  if(!p){$('content').innerHTML+=empty('프로젝트가 필요합니다.','제안서 등록부터 시작하세요.','projects','프로젝트 보기');return;}
  if(state.draw){$('content').innerHTML+=empty(`${state.draw.shortlist.length}명 추첨 완료`,'추첨 명단은 저장되어 있습니다. 참석 일정을 확인한 뒤 최종위원을 선택하세요.','final','최종·예비위원 선택');return;}
  const fields=[...new Set([...state.candidates.flatMap(c=>c.fields),...p.fields])].sort();
  $('content').innerHTML+=`<form id="draw-form" class="card narrow card-body"><label class="field">최종 평가위원 수<select name="target">${[7,8,9].map(n=>`<option value="${n}" ${n===p.target?'selected':''}>${n}명</option>`).join('')}</select></label><fieldset><legend>전문분야 <span class="optional">여러 분야 선택 가능</span></legend><div class="chips">${fields.map(f=>`<label class="chip"><input type="checkbox" name="fields" value="${esc(f)}" ${p.fields.includes(f)?'checked':''}>${esc(f)}</label>`).join('')||'<p>인력풀에 전문분야를 먼저 등록하세요.</p>'}</div></fieldset><div id="live-count" class="notice spaced" aria-live="polite"></div><p class="subtle">선택 분야 전체에서 중복 없이 추첨합니다. 최종 예비위원 3명은 다음 단계에서 고릅니다.</p><label class="check-label"><input name="reviewed" type="checkbox" required>선정 분야와 후보 자격을 확인했습니다.</label><div class="form-actions"><a class="button" href="#projects">프로젝트 목록</a><button id="draw-submit" class="primary" type="submit">3배수 추첨</button></div></form>`;
  const form=$('draw-form');const update=()=>{const data=new FormData(form),selected=new Set(data.getAll('fields')),target=Number(data.get('target')),count=state.candidates.filter(c=>c.active&&c.fields.some(f=>selected.has(f))).length;
    $('live-count').innerHTML=`<strong>추첨 대상 ${count}명 → 1차 명단 ${target*3}명</strong><p>${count<target*3?`${target*3-count}명이 부족합니다. 분야를 추가하거나 후보 정보를 보완하세요.`:'추첨할 수 있습니다.'}</p>`;$('draw-submit').disabled=count<target*3||!selected.size;$('draw-submit').textContent=`${target*3}명 랜덤 추첨`;};
  form.onchange=()=>{state.dirty=true;update();};update();
  form.onsubmit=e=>{e.preventDefault();const data=new FormData(form);act(async()=>{const fresh=await api(`/projects/${p.id}/criteria`,'PUT',{fields:data.getAll('fields'),target:Number(data.get('target')),expected_version:project().version});state.projects=state.projects.map(v=>v.id===p.id?fresh:v);await api(`/projects/${p.id}/draw`,'POST',{reviewed:true});state.dirty=false;await load();go('final');toast('추첨 명단을 저장했습니다.');});};
}
function renderFinal(){
  const p=project(),draw=state.draw;$('content').innerHTML=head('03 · 최종·예비위원 선정','참석 확인 후 위원을 선택하세요',p?`${esc(p.name)} · 최종 ${p.target}명과 예비 3명을 선택합니다.`:'먼저 3배수 명단을 추첨하세요.');
  if(!draw){$('content').innerHTML+=empty('추첨 명단이 필요합니다.','프로젝트의 위원 수와 분야를 선택해 추첨하세요.','draw','추첨으로 이동');return;}
  if(draw.finalized_at){$('content').innerHTML+=empty(`최종 ${draw.final_ids.length}명 · 예비 ${draw.reserve_ids.length}명 확정`,'최종위원의 로그인 준비가 끝났습니다.','assignment','로그인 준비 확인');return;}
  $('content').innerHTML+=`<div class="selection-bar"><div><strong>최종 ${state.selected.size}/${p.target}명 · 예비 ${state.reserves.size}/3명</strong><p class="subtle">참석 가능으로 저장한 후보를 클릭해 선택하세요.</p></div><button id="finalize" class="primary" ${state.selected.size!==p.target||state.reserves.size!==3||[...state.notes.keys()].some(k=>k.startsWith(p.id+':'))?'disabled':''}>명단 확정</button></div><section class="committee-list">${draw.shortlist.map((c,index)=>{const contact=draw.contacts.find(v=>v.candidate_id===c.id),live=draw.current_candidates.find(v=>v.id===c.id)||c,eligible=contact.status==='참여 가능'&&live.active,note=state.notes.get(p.id+':'+c.id)?.note??contact.note;return `<article class="member-card ${state.selected.has(c.id)?'chosen':state.reserves.has(c.id)?'reserve':''}"><div class="member-info"><span class="member-number">${index+1}</span><div><h2>${esc(live.name)}</h2><p>${esc(live.organization)}</p><div>${pills(live.fields)}</div><p>${esc(live.phone||live.email||'연락처 보완 필요')}</p></div></div><div class="member-controls"><label class="field">일정 확인<select data-contact="${c.id}" aria-label="${esc(live.name)} 일정 확인">${['미연락','참여 가능','참여 불가','연락 불가','제척'].map(s=>`<option ${contact.status===s?'selected':''}>${s}</option>`).join('')}</select></label><div class="role-buttons" role="group" aria-label="${esc(live.name)} 선정"><button data-role="final" data-id="${c.id}" aria-pressed="${state.selected.has(c.id)}" ${!eligible||!live.auth_ready?'disabled':''}>최종</button><button data-role="reserve" data-id="${c.id}" aria-pressed="${state.reserves.has(c.id)}" ${!eligible?'disabled':''}>예비</button></div></div><details class="member-note" ${state.notes.has(p.id+':'+c.id)?'open':''}><summary>통화 메모${note?' 있음':''}</summary><form data-note-form="${c.id}"><label class="field">메모<input name="note" maxlength="2000" value="${esc(note)}"></label><button type="submit">메모 저장</button></form></details></article>`;}).join('')}</section>`;
  document.querySelectorAll('[data-contact]').forEach(el=>el.onchange=()=>{const cid=el.dataset.contact,status=el.value,contact=draw.contacts.find(c=>c.candidate_id===cid);if(state.notes.has(p.id+':'+cid)){el.value=contact.status;showError(new Error('작성 중인 메모를 먼저 저장하세요.'));return;}if(status==='제척'&&!contact.note){el.value=contact.status;showError(new Error('통화 메모에 제척 사유를 먼저 저장하세요.'));return;}act(async()=>{try{await api(`/projects/${p.id}/contacts/${cid}`,'PUT',{status,note:contact.note,expected_version:contact.version});await load();renderFinal();toast('일정 확인을 저장했습니다.');}catch(error){el.value=contact.status;throw error;}});});
  document.querySelectorAll('[data-note-form]').forEach(form=>{const cid=form.dataset.noteForm,key=p.id+':'+cid,contact=draw.contacts.find(c=>c.candidate_id===cid);form.oninput=()=>{const base=state.notes.get(key)||contact;state.notes.set(key,{note:form.elements.note.value,version:base.version});$('finalize').disabled=true;};form.onsubmit=e=>{e.preventDefault();const note=new FormData(form).get('note'),version=state.notes.get(key)?.version??contact.version;act(async()=>{await api(`/projects/${p.id}/contacts/${cid}`,'PUT',{status:contact.status,note,expected_version:version});state.notes.delete(key);await load();renderFinal();toast('메모를 저장했습니다.');});};});
  document.querySelectorAll('[data-role]').forEach(b=>b.onclick=()=>{const id=b.dataset.id,set=b.dataset.role==='final'?state.selected:state.reserves,other=b.dataset.role==='final'?state.reserves:state.selected,limit=b.dataset.role==='final'?p.target:3;if(set.has(id))set.delete(id);else{if(set.size>=limit){showError(new Error(`${b.dataset.role==='final'?'최종':'예비'}위원은 ${limit}명까지 선택하세요.`));return;}set.add(id);other.delete(id);}state.selectionDirty=true;rememberSelection();clearError();renderFinal();});
  $('finalize').onclick=()=>act(async()=>{await api(`/projects/${p.id}/finalize`,'POST',{candidate_ids:[...state.selected],reserve_ids:[...state.reserves],expected_version:draw.version});state.selectionDirty=false;await load();go('assignment');toast('최종·예비위원을 확정했습니다.');});
}
function renderAssignment(){
  const p=project(),draw=state.draw;$('content').innerHTML=head('04 · 위원 로그인 준비','평가일에는 이 화면으로 접속하세요',p?esc(p.name):'최종위원을 먼저 선정하세요.');
  if(!draw?.finalized_at){$('content').innerHTML+=empty('최종·예비위원 선정이 필요합니다.','최종위원을 확정하면 로그인 주소가 준비됩니다.','final','위원 선정으로 이동');return;}
  const link=`${state.health.login_origin||location.origin}/#auth?project=${encodeURIComponent(p.id)}`,names=ids=>ids.map(id=>`<span class="pill">${esc(draw.current_candidates.find(c=>c.id===id)?.name||'')}</span>`).join('');
  $('content').innerHTML+=`<section class="card narrow card-body"><span class="pill green">로그인 준비 완료</span><h2 class="spaced">최종위원 ${draw.final_ids.length}명</h2><div class="chips">${names(draw.final_ids)}</div><h3 class="spaced">예비위원 ${draw.reserve_ids.length}명</h3><div class="chips">${names(draw.reserve_ids)}</div><p class="subtle">예비위원은 로그인 대상에 포함되지 않습니다.</p><hr><label class="field">PC·태블릿에 열어 둘 로그인 주소<input id="login-link" readonly value="${esc(link)}"></label><div class="form-actions"><button id="copy-link">주소 복사</button><a class="button primary" href="${esc(link)}" target="_blank" rel="noopener">위원 로그인 열기</a></div><p class="subtle spaced">${state.health.login_origin?'같은 내부망의 PC·태블릿에서 이 주소로 접속하세요.':'현재 이 PC에서 시험할 수 있습니다. 다른 기기에서는 내부망 테스트 설정 후 접속하세요.'}</p></section>`;
  $('copy-link').onclick=()=>act(async()=>{try{await navigator.clipboard.writeText(link);toast('로그인 주소를 복사했습니다.');}catch{$('login-link').select();toast('주소를 선택했습니다. Ctrl+C로 복사하세요.');}});
}
async function renderAuth(){
  const pid=authPid();$('content').innerHTML='<div class="login-brand">심사임당 <span>평가위원 접속</span></div>';
  if(!pid){$('content').innerHTML+=`<section class="card auth-panel card-body"><h1>접속 주소를 확인해 주세요</h1><p>담당자가 안내한 프로젝트 로그인 주소를 사용하세요.</p></section>`;return;}
  let info;try{info=await api(`/auth/project?project_id=${encodeURIComponent(pid)}`);}catch(error){$('content').innerHTML+=`<section class="card auth-panel card-body"><h1>접속 준비를 확인해 주세요</h1><p>${esc(error.message)}</p></section>`;return;}
  try{const me=await api(`/auth/me?project_id=${encodeURIComponent(pid)}`);showLoggedIn(me);return;}catch(error){if(![403,503].includes(error.status))throw error;}
  $('content').innerHTML+=`<section class="card auth-panel card-body"><span class="pill amber">테스트 로그인</span><h1 class="spaced">평가위원 로그인</h1><p class="project-title">${esc(info.name)}</p><form id="login-form"><label class="field">이름<input name="name" required maxlength="100" autocomplete="off" placeholder="등록된 이름"></label><label class="field">휴대전화 또는 이메일<input name="contact" required maxlength="254" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="등록된 연락처"></label><button class="primary full-width" type="submit" ${state.health.verification_mode!=='demo'?'disabled':''}>확인하고 로그인</button></form><p class="subtle spaced">${state.health.verification_mode==='demo'?'등록 정보가 일치하는 최종위원만 접속합니다. 실제 문자·본인인증은 테스트 후 연결됩니다.':'담당자에게 테스트 로그인 활성화를 요청하세요.'}</p></section>`;
  const form=$('login-form');form.onsubmit=e=>{e.preventDefault();const data=new FormData(form);act(async()=>{await api('/auth/demo-login','POST',{project_id:pid,name:data.get('name'),contact:data.get('contact')});showLoggedIn(await api(`/auth/me?project_id=${encodeURIComponent(pid)}`));});};
}
function showLoggedIn(me){
  $('content').innerHTML=`<div class="login-brand">심사임당 <span>평가위원 접속</span></div><section class="card auth-panel card-body"><span class="pill green">테스트 로그인 완료</span><h1 class="spaced">${esc(me.name)} 위원님</h1><p class="project-title">${esc(me.project_name)}</p><div class="notice"><strong>평가 준비가 완료되었습니다.</strong><p>평가 화면은 준비 중입니다. 담당자의 안내를 기다려 주세요.</p></div><button id="logout" class="full-width spaced">로그아웃 · 다음 위원</button><p class="subtle spaced">공용 PC에서는 사용 후 로그아웃하세요. 15분 후 자동 만료됩니다.</p></section>`;
  $('logout').onclick=()=>act(async()=>{await api('/auth/logout','POST');await renderAuth();});
}
$('project-picker').onchange=e=>{const pid=e.target.value;act(async()=>{setProject(pid);await load();if(page()==='draw')await render();else go('draw');});};
document.addEventListener('click',e=>{const link=e.target.closest('a[href^="#"]');if(link&&state.dirty&&!window.confirm('저장하지 않은 입력이 있습니다. 이 화면을 나갈까요?'))e.preventDefault();});
window.addEventListener('hashchange',()=>{clearError();state.dirty=false;if(state.busy)pendingNavigation=true;else act(render);});
window.addEventListener('beforeunload',e=>{if(state.dirty||state.selectionDirty||state.notes.size){e.preventDefault();e.returnValue='';}});
async function start(){try{state.health=await api('/health');$('mode').textContent=state.health.demo_data?'합성자료 테스트':'부서 자료 · 로컬 테스트';await render();}catch(error){showError(error);}}
void start();
