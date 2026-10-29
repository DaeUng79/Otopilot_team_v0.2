let originalProjectRows=new Map();
// User-approved correction: type the department name instead of selecting a mock option.
const departmentInput=document.createElement('input');departmentInput.id='n-dept';departmentInput.type='text';departmentInput.placeholder='부서명을 입력하세요';departmentInput.maxLength=200;departmentInput.setAttribute('aria-describedby','n-dept-e');$('#n-dept').replaceWith(departmentInput);
// 사업 등록 창에 평가일 입력 추가 (2026-10-18 사용자 요청). 수정 창의 '평가일 (평가조건)'과 같은 날짜 칸이며, 비워 두면 '아직 안 정함'으로 등록된다.
const dateField=document.createElement('label');dateField.className='field';dateField.innerHTML='<span>평가일 <span class="hint">(선택 · 나중에 수정 가능)</span></span><input id="n-date" type="date" aria-describedby="n-date-e"><span class="err" id="n-date-e" hidden></span>';
$('#n-mail').closest('label').after(dateField);
const originalNewProject=$('#b-new').onclick;
$('#b-new').onclick=()=>{originalNewProject();$('#n-date').value='';};
async function loadProjects(){
 const [list,rfpSummary]=await Promise.all([Live.all('PRJ-01'),Live.get('/api/v2/admin/rfp-summary')]);
 // 준비 상태는 문서 DB의 실제 등록 데이터로만 정한다: 보관 처리를 뺀 최신 제안요청서(project_rfp_uploads)와
 // READY 제안서가 있는 업체 수. 결과 자료(UPLOADED_RESULT)는 제안요청서로 치지 않는다.
 // 상세(showProject)와 같은 규칙: 제안서 있음 → '문서 준비됨', 제안요청서만 → '제안요청서 등록됨', 없음 → '제안요청서 없음'.
 const rfpByProject=new Map(rfpSummary.uploads.map(upload=>[upload.project_id,upload]));
 const proposalVendors=new Map((rfpSummary.proposals||[]).map(p=>[p.project_id,p.vendor_count]));
 originalProjectRows=new Map(list.map(r=>[r.id,r]));
 D.splice(0,D.length,...Live.boot.departments.map(d=>d.name));$('#f-dept').innerHTML='<option value="">부서 전체</option>'+D.map(d=>`<option>${h(d)}</option>`).join('');
 if(fd&&!D.includes(fd))fd='';$('#f-dept').value=fd;
 P=list.map(r=>{const rfp=rfpByProject.get(r.id)||null,vendors=proposalVendors.get(r.id)||0;return {id:r.id,name:r.name,org:r.contact_organization,dept:r.contact_department,owner:r.contact_name,pos:r.contact_position,tel:'',mail:'',date:r.evaluation_date||'',s:r.status==='COMPLETED'?'완료':r.status==='EVALUATING'?'평가 중':'준비',sub:r.submitted,N:r.participants,doc:vendors?'ok':rfp?'rfp':'none',rfp,ev:r.status==='COMPLETED'?'ok':'none'};});
 for(const p of P){hist[p.id]=[];}render(true);
}
async function showProject(id){const [detail,rfpData,proposalData]=await Promise.all([Live.api('PRJ-05',{project_id:id}),Live.get('/api/v2/projects/'+encodeURIComponent(id)+'/rfp'),Live.get('/api/v2/projects/'+encodeURIComponent(id)+'/proposals')]),r=detail.project;originalProjectRows.set(id,r);cur=P.find(p=>p.id===id);const rfp=rfpData.uploads[0]||null,proposals=proposalData.uploads.filter(u=>u.status==='READY');Object.assign(cur,{tel:r.contact_phone,mail:r.contact_email,rfp,proposals,doc:proposals.length?'ok':rfp?'rfp':'none'});render(true);Live.selectProject(id);paint(cur,false);openLayer($('#p'),'.x');}
await loadProjects();
// [조회]: 서버에서 사업 목록과 문서 준비 상태를 다시 읽는다. 부서·상태·검색어 조건은 유지된다 (2026-10-18 사용자 요청).
const queryButton=document.createElement('button');queryButton.type='button';queryButton.className='btn';queryButton.id='b-query';queryButton.textContent='조회';queryButton.title='서버에서 사업 목록과 문서 준비 상태를 다시 읽습니다. 거르기 조건은 유지됩니다.';
$('#b-reset').before(queryButton);
Live.capture('#b-query','click',async()=>{await loadProjects();toast('사업 목록을 새로 읽었어요');});
Live.capture('#rows tr','click',(_e,el)=>showProject(el.dataset.id));Live.capture('#rows tr','keydown',(_e,el)=>showProject(el.dataset.id));
Live.capture('#f-new','submit',async()=>{const department=$('#n-dept').value.trim(),evaluationDate=$('#n-date').value;if(!department)throw Error('부서명을 입력하세요.');await Live.api('PRJ-02',{name:$('#n-name').value.trim(),contact_organization:$('#n-org').value.trim(),contact_department:department,contact_position:$('#n-pos').value.trim(),contact_name:$('#n-owner').value.trim(),contact_phone:$('#n-tel').value.trim(),contact_email:$('#n-mail').value.trim(),...(evaluationDate?{evaluation_date:evaluationDate}:{})});closeLayer($('#pn'));await Live.reload();await loadProjects();toast(evaluationDate?'사업을 등록했어요 · 평가일 '+evaluationDate:'사업을 등록했어요 · 평가일은 나중에 정할 수 있어요');});
Live.capture('#b-save','click',async()=>{const r=originalProjectRows.get(cur.id);await Live.api('PRJ-03',{project_id:r.id,version:r.version,name:$('#x-name').value,contact_organization:$('#x-org').value,contact_department:r.contact_department,contact_position:$('#x-pos').value,contact_name:$('#x-owner').value,contact_phone:$('#x-tel').value,contact_email:$('#x-mail').value,evaluation_date:$('#x-date').value});await loadProjects();closeLayer($('#p'));toast('사업 정보를 저장했어요');});
Live.capture('#dlg-ok','click',async()=>{const reason=$('#d-why').value.trim();if(!reason)throw Error('삭제 사유를 입력하세요.');const r=originalProjectRows.get(cur.id);await Live.api('PRJ-04',{project_id:r.id,version:r.version,reason});closeLayer($('#dlg'));closeLayer($('#p'));await Live.reload();await loadProjects();toast('사업을 삭제했어요');});
Live.capture('[data-dl]','click',async(_e,el)=>{
 if(el.dataset.dl.startsWith('제안요청서/')&&cur.rfp){
  const url='/api/v2/projects/'+encodeURIComponent(cur.id)+'/rfp/'+cur.rfp.revision+'/download';
  const response=await fetch(url,{credentials:'same-origin'});
  if(!response.ok)throw Error('제안요청서 원본 파일을 내려받지 못했습니다.');
  const objectUrl=URL.createObjectURL(await response.blob()),link=document.createElement('a');
  link.href=objectUrl;link.download=cur.rfp.filename;link.click();
  setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);return;
 }
 if(el.dataset.dl.startsWith('결과/')){
  const states=(await Live.get('/api/v2/result-sessions/'+encodeURIComponent(cur.id))).sessions;
  const session=states.find(s=>s.status==='FINALIZED');
  if(!session)throw Error('위원장이 최종 제출한 결과가 아직 없습니다.');
  const name=cur.name.replace(/[\\/:*?"<>|]/g,'_').trim();
  if(el.dataset.dl.endsWith('.xlsx'))return Live.api('RES-05',{session_id:session.id,format:'xlsx'},name+'_제안서평가_집계표.xlsx');
  return Live.api('RES-05',{session_id:session.id},name+'_평가결과_보고서.html');
 }
 if(el.dataset.dl.startsWith('제안서/')){
  // PRO-02: 업체별 최신 READY 제안서 원본
  const uploads=(await Live.get('/api/v2/projects/'+encodeURIComponent(cur.id)+'/proposals')).uploads.filter(u=>u.status==='READY');
  if(!uploads.length)throw Error('등록된 제안서가 없습니다.');
  const seen=new Set();
  for(const u of uploads){if(seen.has(u.vendor_id))continue;seen.add(u.vendor_id);
   const response=await fetch('/api/v2/projects/'+encodeURIComponent(cur.id)+'/proposals/'+encodeURIComponent(u.id)+'/download',{credentials:'same-origin'});
   if(!response.ok)throw Error('제안서 원본 파일을 내려받지 못했습니다.');
   const objectUrl=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=objectUrl;link.download=u.filename;link.click();setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);}
  return;
 }
 throw Error('이 파일은 아직 내려받을 수 없습니다.');
});
const openId=location.hash.startsWith('#open=')?decodeURIComponent(location.hash.slice(6)):'';if(openId&&P.some(p=>p.id===openId))await showProject(openId);
