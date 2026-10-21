// PM-07 · COM-01..07. Only original table, drawer, Excel preview and buttons.
// Remove prototype candidates before the first API await can paint them.
const livePoolEmptyMarkup=$('#none').innerHTML;
P=[];render();
$('#none').innerHTML='<div class="ico" aria-hidden="true">…</div><strong>위원 풀을 불러오는 중이에요</strong>';
const liveDeptId=Live.boot.actor.department_id||Live.boot.projects.find(p=>p.id===Live.pid)?.department_id;
if(!liveDeptId)throw Error('사업 또는 소속 부서를 먼저 선택하세요.');
const liveSpecialties=Live.boot.specialties,liveRows=new Map();let liveEdit=null,liveDelete=null,livePreview=null;
const poolProjectState=Live.pid?await Live.get('/committee-v2/api/projects/'+encodeURIComponent(Live.pid)):null;
const canRegisterDirect=poolProjectState?.rule?.selection_mode==='DIRECT'&&!poolProjectState.roster;
let liveSpecialtyTouched=false;const originalPoolForm=form;
form=function(row){
 liveSpecialtyTouched=false;originalPoolForm(row);
 // This drawer only: keep original fields/handlers, reorder into compact pairs.
 const grid=$('#p .fgrid2'),scopeField=$('#p #f-sc').parentElement;
 grid.classList.add('committee-registration');scopeField.classList.add('registration-scope');grid.prepend(scopeField);
 const projectScope=$('#p #f-sc [data-s=proj]');if(!liveEdit&&!canRegisterDirect){projectScope.disabled=true;projectScope.title=Live.pid?'평가위원 선정에서 직접 선정 규칙을 먼저 저장하세요. 확정된 명단에는 추가할 수 없습니다.':'사업을 선택한 뒤 직접 등록할 수 있습니다.';$('#ferr').textContent=projectScope.title;}
 if(liveEdit){const selected=liveSpecialties.find(s=>s.id===liveEdit.specialty_ids[0]);if(selected)document.querySelector('#p select#f-field').value=selected.name;}
};
const registrationStyles=document.createElement('link');registrationStyles.rel='stylesheet';registrationStyles.href='/src/screens/dept-admin/PM-07-pool/registration.css';document.head.append(registrationStyles);
Live.capture('#p select#f-field','change',()=>{liveSpecialtyTouched=true;});
FIELDS.splice(0,FIELDS.length,...liveSpecialties.map(s=>s.name));
const liveScope=sc=>({department_id:liveDeptId,scope:sc==='proj'?'PROJECT':'DEPARTMENT_POOL',...(sc==='proj'?{project_id:Live.pid}:{})});
const liveReloadPool=async()=>{
  const result=[];liveRows.clear();
  for(const sc of ['dept',...(Live.pid?['proj']:[])]){
    const first=await Live.api('COM-01',{...liveScope(sc),active:true,page:1,page_size:200});let items=first.items;
    for(let page=2;items.length<first.total;page++){const next=await Live.api('COM-01',{...liveScope(sc),active:true,page,page_size:200});if(!next.items.length)break;items=items.concat(next.items);}
    for(const c of items){liveRows.set(c.id,c);result.push({id:c.id,scope:sc,name:c.name,org:c.organization_name,dept:c.department_name||'',pos:c.position||'',field:c.specialty_ids.map(id=>liveSpecialties.find(s=>s.id===id)?.name||'').join(', '),tel:c.phone,email:c.email||'',n:c.participation_count||0});}
  }
  P=result;render();$('#none').innerHTML=livePoolEmptyMarkup;
};
try{await liveReloadPool();}
catch(error){$('#none').innerHTML='<div class="ico" aria-hidden="true">!</div><strong>위원 풀을 불러오지 못했어요</strong><p>'+Live.escape(error.message)+'</p>';throw error;}
document.querySelector('.side .role').textContent=Live.boot.departments.find(d=>d.id===liveDeptId)?.name||'';
const liveFilter=document.querySelector('#f-field');
liveFilter.innerHTML=['전체',...FIELDS].map((f,i)=>`<button class="chip" type="button" data-f="${i?h(f):''}" aria-pressed="${i===0}">${h(f)}</button>`).join('');
liveFilter.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{ff=c.dataset.f;liveFilter.querySelectorAll('.chip').forEach(x=>x.setAttribute('aria-pressed',String(x===c)));render();});
Live.capture('#b-add','click',()=>{liveEdit=null;form(null);});
Live.capture('#rows tr','click',(e,tr)=>{liveEdit=liveRows.get(tr.dataset.id);openDetail(tr.dataset.id);});
Live.capture('#rows tr','keydown',(e,tr)=>{liveEdit=liveRows.get(tr.dataset.id);openDetail(tr.dataset.id);});
Live.capture('#b-save','click',async()=>{
  const value=k=>document.querySelector('#p #f-'+k).value.trim();
  const sc=document.querySelector('#f-sc [aria-pressed=true]').dataset.s;
  const field=document.querySelector('#p select#f-field').value;
  const specialty=liveSpecialties.find(s=>s.name===field);if(!specialty)throw Error('분야를 선택하세요.');
  const data={name:value('name'),organization_name:value('org'),department_name:value('dept')||null,position:value('pos')||null,phone:value('tel')||liveEdit?.phone||'',email:value('email')||null,specialty_ids:liveEdit&&!liveSpecialtyTouched?liveEdit.specialty_ids:[specialty.id]};
  await Live.api(liveEdit?'COM-06':'COM-05',liveEdit?{...data,candidate_id:liveEdit.id,version:liveEdit.version}:{...data,...liveScope(sc)});
  closeLayer($('#p'));await liveReloadPool();setScope(sc);toast('위원 정보를 저장했어요.');
});
Live.capture('#b-del','click',()=>{liveDelete=liveEdit;confirmDlg({title:'위원을 삭제할까요?',body:'비활성으로 바뀌며 기존 확정 명단은 보존됩니다.',ok:'삭제',danger:true});});
Live.capture('#dlg-ok','click',async()=>{if(!liveDelete)return;await Live.api('COM-07',{candidate_id:liveDelete.id,version:liveDelete.version});closeLayer($('#dlg'));closeLayer($('#p'));liveDelete=null;await liveReloadPool();toast('비활성으로 바꿨어요.');});
Live.capture('#b-tpl','click',()=>Live.api('COM-02',{},'위원_등록_양식.xlsx'));
Live.capture('#pick input','change',async(e,el)=>{
  const file=el.files[0];if(!file)return;const data=new FormData();data.append('file',file);for(const [key,value] of Object.entries(liveScope(scope)))data.append(key,value);
  const response=await fetch('/committee-v2/api/imports/preview',{method:'POST',credentials:'same-origin',headers:{'X-Committee-Client':'v2-web','Idempotency-Key':crypto.randomUUID()},body:data});const result=await response.json();if(!response.ok)throw Error(result.error?.message||'파일을 확인하세요.');
  livePreview=result.data;
  // 정상 줄(items)과 서버가 거른 줄(errors: 중복·오류)을 엑셀 행 순서대로 한 표에 보여 준다 (2026-10-18).
  // 전에는 items만 표에 넣고 check()를 항상 '정상'으로 바꿔 "오류 0 · 중복 0"으로 보였고, 거른 줄은 아래 문구에만 남았다.
  // 검증은 서버(COM-03) 결과만 쓴다. 원본 렌더러(show)는 그대로 두고 줄 번호만 실제 엑셀 행으로 바꾼다.
  const specialtyName=id=>liveSpecialties.find(s=>s.id===id)?.name||'';
  const valid=livePreview.items.map(c=>Object.assign([c.name,c.phone,c.organization_name,c.department_name||'',c.position||'',c.specialty_ids.map(specialtyName).join(', '),c.email||''],{live:{k:'ok',m:'',row:c.row}}));
  const rejected=(livePreview.errors||[]).map(r=>Object.assign([r.name||'',r.phone||'',r.organization||'',r.department||'',r.position||'',r.specialty||'',r.email||''],{live:{k:r.code==='DUPLICATE_PHONE'?'dup':'err',m:r.message,row:r.row}}));
  const lines=[...valid,...rejected].sort((a,b)=>(a.live.row||0)-(b.live.row||0));
  XLS.splice(0,XLS.length,...lines);
  check=r=>r.live||{k:'ok',m:''};document.querySelector('#p #demo').onclick();
  $$('#prev .xl-tbl tbody tr').forEach((tr,i)=>{const row=lines[i]?.live?.row;if(row)tr.firstElementChild.textContent=row;});
  $('#prev .xl-sum b').textContent=file.name;
  // 서버는 오류·중복이 하나라도 있으면 등록을 거부한다(COM-04 IMPORT_ERRORS). 원본 문구 "정상 N명만 등록돼요"는 그 규칙과 달라 바꾼다.
  const dup=rejected.filter(r=>r.live.k==='dup').length,err=rejected.length-dup,note=$('#prev .xl-act .muted');
  if(note)note.innerHTML=livePreview.can_commit?`정상 ${valid.length}명을 등록해요.<br>같은 요청은 한 번만 등록돼요.`:`오류 ${err}줄 · 중복 ${dup}줄이 있어 아직 등록할 수 없어요. 엑셀에서 해당 줄을 고치거나 지운 뒤 다시 미리보기 하세요.<br>정상 ${valid.length}명도 그때 함께 등록돼요.`;
  $('#xl-go').disabled=!livePreview.can_commit;$('#xl-go').title=livePreview.can_commit?'':'오류·중복 줄이 있으면 등록할 수 없어요.';
  $('#xl-res').textContent='';
});
Live.capture('#p #demo','click',()=>{throw Error('실제 엑셀 파일을 선택하세요. 예시 파일 버튼은 DB에 연결하지 않습니다.');});
Live.capture('#xl-go','click',async()=>{if(!livePreview?.can_commit)throw Error('파일 검증을 먼저 완료하세요.');const saved=await Live.api('COM-04',{preview_id:livePreview.id,version:livePreview.version});$('#xl-go').disabled=true;$('#xl-go').textContent='등록 완료';$('#xl-res').textContent=saved.count+'명을 저장했어요.';livePreview=null;await liveReloadPool();});
