let originalProjectRows=new Map();
// User-approved correction: type the department name instead of selecting a mock option.
const departmentInput=document.createElement('input');departmentInput.id='n-dept';departmentInput.type='text';departmentInput.placeholder='부서명을 입력하세요';departmentInput.maxLength=200;departmentInput.setAttribute('aria-describedby','n-dept-e');$('#n-dept').replaceWith(departmentInput);
async function loadProjects(){
 const [list,rfpSummary]=await Promise.all([Live.all('PRJ-01'),Live.get('/api/v2/admin/rfp-summary')]);
 const rfpByProject=new Map(rfpSummary.uploads.map(upload=>[upload.project_id,upload]));
 originalProjectRows=new Map(list.map(r=>[r.id,r]));
 D.splice(0,D.length,...Live.boot.departments.map(d=>d.name));$('#f-dept').innerHTML='<option value="">부서 전체</option>'+D.map(d=>`<option>${h(d)}</option>`).join('');
 P=list.map(r=>{const rfp=rfpByProject.get(r.id)||null;return {id:r.id,name:r.name,org:r.contact_organization,dept:r.contact_department,owner:r.contact_name,pos:r.contact_position,tel:'',mail:'',date:r.evaluation_date||'',s:r.status==='COMPLETED'?'완료':r.status==='EVALUATING'?'평가 중':'준비',sub:r.submitted,N:r.participants,doc:rfp?'rfp':'none',rfp,ev:r.status==='COMPLETED'?'ok':'none'};});
 for(const p of P){hist[p.id]=[];}render(true);
}
async function showProject(id){const [detail,rfpData,proposalData]=await Promise.all([Live.api('PRJ-05',{project_id:id}),Live.get('/api/v2/projects/'+encodeURIComponent(id)+'/rfp'),Live.get('/api/v2/projects/'+encodeURIComponent(id)+'/proposals')]),r=detail.project;originalProjectRows.set(id,r);cur=P.find(p=>p.id===id);const rfp=rfpData.uploads[0]||null,proposals=proposalData.uploads.filter(u=>u.status==='READY');Object.assign(cur,{tel:r.contact_phone,mail:r.contact_email,rfp,proposals,doc:proposals.length?'ok':rfp?'rfp':'none'});render(true);Live.selectProject(id);paint(cur,false);openLayer($('#p'),'.x');}
await loadProjects();
Live.capture('#rows tr','click',(_e,el)=>showProject(el.dataset.id));Live.capture('#rows tr','keydown',(_e,el)=>showProject(el.dataset.id));
Live.capture('#f-new','submit',async()=>{const department=$('#n-dept').value.trim();if(!department)throw Error('부서명을 입력하세요.');await Live.api('PRJ-02',{name:$('#n-name').value.trim(),contact_organization:$('#n-org').value.trim(),contact_department:department,contact_position:$('#n-pos').value.trim(),contact_name:$('#n-owner').value.trim(),contact_phone:$('#n-tel').value.trim(),contact_email:$('#n-mail').value.trim()});closeLayer($('#pn'));await Live.reload();await loadProjects();toast('사업을 등록했어요');});
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
 if(el.dataset.dl.includes('결과')){const states=(await Live.get('/api/v2/result-sessions/'+encodeURIComponent(cur.id))).sessions,s=states.find(s=>s.status==='FINALIZED');if(s)return Live.api('RES-05',{session_id:s.id,format:'xlsx'},'제안서평가_집계표.xlsx');throw Error('위원장이 최종 제출한 결과가 아직 없습니다.');}
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
