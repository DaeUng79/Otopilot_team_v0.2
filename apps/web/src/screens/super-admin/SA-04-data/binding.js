// SA-04 · MAT-01~03 · COM-01
// 자료 탭: 문서 DB(제안요청서·제안서·결과 자료)와 평가 DB(확정 결과)를 한 목록으로. 위원 풀 탭: 원준석(Lex6won) COM-01 데이터.
const departments=Live.boot.departments,projects=Live.boot.projects;
async function loadPool(){
 const candidateGroups=await Promise.all(departments.map(async department=>({department,items:await Live.all('COM-01',{department_id:department.id,scope:'DEPARTMENT_POOL',active:true})})));
 R.splice(0,R.length,...candidateGroups.flatMap(({department,items})=>items.map(c=>[
  c.organization_name,c.department_name||'—',c.name,h(c.position||'—'),h(c.specialty_ids.map(id=>Live.boot.specialties.find(s=>s.id===id)?.name||id).join(', ')),
  department.organization_name+' · '+department.name,c.participation_count||0,
 ])));
 pools.splice(0,pools.length,...new Set(R.map(r=>r[5])));
}
await loadPool();
PROJ.splice(0,PROJ.length,...projects.map(p=>p.name));
const projectById=new Map(projects.map(p=>[p.id,p]));
let materialItems=[];
const KIND={RFP:'제안요청서',PROPOSAL:'제안서',UPLOADED_RESULT:'결과 자료',GENERATED_REPORT:'결과 자료',SYSTEM:'결과 자료'};
// 내부 구분값(UPLOADED_RESULT·SYSTEM_RESULT)은 화면에 보이지 않게 한글 명칭만 쓴다 (2026-10-18 사용자 요청). 저장 값은 그대로.
SRC.UPLOAD='<span class="badge primary">별도 등록 자료</span>';SRC.SYSTEM='<span class="badge info">시스템 취합본</span>';
async function loadMaterials(){
 const data=await Live.get('/api/v2/materials');
 materialItems=[];F.length=0;
 for(const item of data.items){
  const project=projectById.get(item.project_id);if(!project)continue;
  const co=item.kind==='PROPOSAL'?(item.display_code?item.display_code+'사 · ':'')+(item.legal_name||''):'—';
  const row=mk(project.name,KIND[item.kind]||item.label,co,item.filename,(item.byte_size/1048576).toFixed(1)+' MB',(item.date||'').slice(0,10),'보관',{ver:item.revision,desc:item.description||'',src:item.kind==='UPLOADED_RESULT'?'UPLOAD':item.kind==='GENERATED_REPORT'?'SYSTEM':null});
  row.download=item.download;row.item=item;row.material=item.kind==='UPLOADED_RESULT'||item.kind==='GENERATED_REPORT'?item:null;
  F.push(row);materialItems.push(row);
 }
 for(const session of data.results){
  const project=projectById.get(session.project_id);if(!project)continue;
  const row=mk(project.name,'결과 자료','—',project.name+'_제안서평가_집계표.xlsx','XLSX',(session.closed_at||'').slice(0,10),'보관',{src:'SYSTEM',desc:'위원장 최종 제출 결과(시스템 취합본) · 서명 증빙 HTML 포함'});
  row.sessionId=session.session_id;F.push(row);
 }
}
await loadMaterials();
// [보관 규칙 설정]·[폐기]는 기획(화면카드 SA-04, 10-16)에서 "칸과 버튼 자리만, 동작은 규칙 확정 뒤"로 둔 자리표시자라
// 화면에서 뺀다 (2026-10-18 사용자 요청). 보관 규칙이 정해지면 그때 액션 ID와 함께 다시 붙인다. 자료는 삭제되지 않는다.
$$('#acts button[disabled]').forEach(button=>button.remove());
$('#why')?.remove();
$('details.demo')?.remove();
const originalMaterialDraw=draw;
draw=function(){
 originalMaterialDraw();
 if(tab==='files')$$('#rows [data-e]').forEach(button=>{const row=F[Number(button.dataset.e)];
  const wrap=document.createElement('span');wrap.style.display='inline-flex';wrap.style.gap='6px';
  const dl=document.createElement('button');dl.type='button';dl.className='btn sm';dl.dataset.dl=button.dataset.e;dl.textContent=row.sessionId?'집계표 다운로드':'내려받기';dl.setAttribute('aria-label',row.file+' 내려받기');
  wrap.appendChild(dl);
  if(row.sessionId){const html=document.createElement('button');html.type='button';html.className='btn sm';html.dataset.dlhtml=button.dataset.e;html.textContent='평가결과 보고서(HTML)';wrap.appendChild(html);}
  // [수정 / 파일 교체]는 모든 행에 둔다 (2026-10-18 사용자 요청). 제안요청서·제안서는 새 파일을 올리면 새 차수(v+1),
  // 결과 자료는 설명·파일을 바꾼 새 버전(MAT-03), 시스템 취합본은 설명만. 위원장 최종 제출 집계표는 바꿀 수 없어 비활성.
  button.textContent='수정 / 파일 교체';
  const edit=button.cloneNode(true);
  if(row.sessionId){edit.disabled=true;edit.title='위원장이 최종 제출한 결과는 수정할 수 없어요. 확정 점수·서명은 보존돼요.';edit.setAttribute('aria-disabled','true');}
  else if(row.item?.kind==='RFP'||row.item?.kind==='PROPOSAL')edit.title='새 파일을 올리면 새 차수로 등록되고 이전 차수는 이력에 남아요.';
  wrap.appendChild(edit);
  if(row.material&&row.material.kind==='UPLOADED_RESULT'){
   // 결과 자료로 올라간 HWPX는 제안요청서로 옮길 수 있다 (2026-10-18). 원본은 그대로, 제안요청서 차수로 등록한 뒤 결과 자료 목록에서만 뺀다.
   if(/\.hwpx$/i.test(row.file)){const move=document.createElement('button');move.type='button';move.className='btn sm';move.dataset.torfp=button.dataset.e;move.textContent='제안요청서로 옮기기';move.title='이 파일을 이 사업의 제안요청서로 등록하고 결과 자료 목록에서 뺍니다. 원본은 지우지 않습니다.';move.setAttribute('aria-label',row.file+' 제안요청서로 옮기기');wrap.appendChild(move);}
  }
  button.replaceWith(wrap);
 });
};
const originalMaterialTabs=tabs;
tabs=function(value){
 originalMaterialTabs(value);
 if(value==='pool')$('#tb .spec-note').textContent='위원 풀 · 원준석(Lex6won) 담당 / 부서에서 등록한 실제 후보를 조회합니다.';
 else {$('#sub').textContent='모든 사업의 제안요청서·제안서(업체별 최신)·결과 자료를 조회·등록하고 내려받습니다.';$('#none strong').textContent='자료가 없습니다';$('#none p').textContent='사업담당자가 문서를 등록하거나 위원장이 최종 제출하거나 [자료 등록]으로 올리면 이 목록에 표시됩니다.';}
 // [조회]: 서버에서 목록을 다시 읽는다. 검색어·유형·부서 조건은 유지된다 (2026-10-18 사용자 요청).
 const query=document.createElement('button');query.type='button';query.className='btn';query.id='b-q';query.textContent='조회';query.title='서버에서 목록을 다시 읽습니다. 검색어와 거르기 조건은 유지됩니다.';
 ($('#b-rs')||$('#tb .search')).after(query);
};
Live.capture('#b-q','click',async()=>{if(tab==='files')await loadMaterials();else await loadPool();draw();toast(tab==='files'?'자료 목록을 새로 읽었어요':'위원 풀을 새로 읽었어요');});
Live.capture('#rows [data-torfp]','click',async(_event,button)=>{
 const row=F[Number(button.dataset.torfp)],item=row.material;if(!item)throw Error('옮길 자료를 찾을 수 없습니다.');
 if(!confirm(`'${row.file}'을(를) '${row.proj}'의 제안요청서로 옮길까요?\n\n원본 파일은 그대로 두고 제안요청서로 등록한 뒤, 결과 자료 목록에서만 뺍니다. 전체 사업 화면의 준비 상태에 바로 반영됩니다.`))return;
 const response=await fetch('/api/v2/projects/'+encodeURIComponent(item.project_id)+'/result-files/'+encodeURIComponent(item.id)+'/register-as-rfp',{method:'POST',credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web'}});
 const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error?.message||'제안요청서로 옮기지 못했습니다.');
 await loadMaterials();draw();toast('제안요청서 v'+body.data.rfp.revision+'으로 옮겼어요 · 전체 사업 화면에도 반영돼요');
});
tabs(location.hash==='#pool'?'pool':'files');
async function downloadRow(row){const response=await fetch(row.download,{credentials:'same-origin'});if(!response.ok)throw Error('파일을 내려받지 못했습니다.');const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=row.file;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
Live.capture('#rows [data-dl]','click',(_event,button)=>{const row=F[Number(button.dataset.dl)];return row.sessionId?Live.api('RES-05',{session_id:row.sessionId,format:'xlsx'},row.file):downloadRow(row);});
Live.capture('#rows [data-dlhtml]','click',(_event,button)=>Live.api('RES-05',{session_id:F[Number(button.dataset.dlhtml)].sessionId},'평가결과_보고서.html'));
// 수정 창을 행 종류에 맞춘다: 제안요청서·제안서는 파일만(새 차수), 결과 자료는 설명+파일, 시스템 취합본은 설명만(원본 openEd가 처리).
const originalOpenEd=openEd;
openEd=function(index){
 originalOpenEd(index);
 const row=F[index],kind=row.item?.kind,replaceOnly=kind==='RFP'||kind==='PROPOSAL';
 const descField=$('#e-desc').closest('label'),fileField=$('#e-file').closest('label'),note=$('#p-ed .note div');
 descField.hidden=replaceOnly;fileField.hidden=kind==='GENERATED_REPORT';
 $('#p-ed-t').textContent=replaceOnly?'파일 교체 · '+(kind==='RFP'?'제안요청서':'제안서'):'수정 / 파일 교체';
 if(replaceOnly){
  $('#e-file').disabled=false;$('#e-file').accept=kind==='RFP'?UPLOAD_KINDS.RFP.accept:UPLOAD_KINDS.PROPOSAL.accept;
  $('#e-fh').textContent=kind==='RFP'?'HWPX만 · 고르면 새 차수(v'+(row.ver+1)+')로 등록돼요':'HWPX·HWP·PDF·PPTX · 고르면 새 차수(v'+(row.ver+1)+')로 등록돼요';
  note.innerHTML='저장하면 <b>새 차수</b>가 등록되고 이전 차수는 이력에 남아요. 평가가 시작된 사업은 바꿀 수 없어요.';
 }else{
  $('#e-file').accept=UPLOAD_KINDS.RESULT.accept;
  note.innerHTML='저장하면 <b>새 버전</b>이 만들어져요. 확정 점수·서명은 바뀌지 않아요.';
 }
};
Live.capture('#rows [data-e]','click',(_event,button)=>{if(button.disabled)return;openEd(Number(button.dataset.e));});
// 자료 등록 (2026-10-18 수정): 유형을 골라 각자의 저장소로 보낸다. 이전에는 [결과 첨부자료 등록] 버튼 하나뿐이어서
// 제안요청서 파일도 결과 자료(managed_result_files · UPLOADED_RESULT)로 저장됐고, 전체 사업(SA-03) 화면은
// project_rfp_uploads만 읽어 "제안요청서 없음"으로 표시됐다. 저장 값·표·기존 자료는 바꾸지 않는다.
//  - 제안요청서      → DOC-01 POST /api/v2/projects/{id}/rfp                      (PM-02·SA-03과 같은 표 project_rfp_uploads)
//  - 업체별 제안서   → PRO-01 POST /api/v2/projects/{id}/vendors/{vendor_id}/proposals (project_proposal_uploads)
//  - 평가결과 첨부자료 → MAT-02 POST /api/v2/projects/{id}/result-files              (managed_result_files · UPLOADED_RESULT)
const UPLOAD_KINDS={
 RFP:{label:'제안요청서',accept:'.hwpx',note:'제안요청서는 사업담당자 문서 화면(PM-02)과 같은 저장소에 등록되어 <b>전체 사업</b> 화면의 준비 상태에 바로 반영됩니다. HWPX만 올릴 수 있고, 평가가 시작된 사업에는 올릴 수 없습니다.'},
 PROPOSAL:{label:'업체별 제안서',accept:'.hwpx,.hwp,.pdf,.pptx',note:'업체별 제안서는 사업에 등록된 업체를 골라 올립니다. 업체가 없으면 사업담당자 문서 화면(PM-02)에서 먼저 업체를 등록해 주세요.'},
 RESULT:{label:'평가결과 첨부자료 (회의록·스캔본 등)',accept:'.pdf,.hwpx,.hwp,.xlsx,.docx,.pptx,.png,.jpg,.jpeg,.zip,.html',note:'직접 등록한 평가결과 자료는 <span class="badge primary">별도 등록 자료</span>로 표시되며, 시스템에서 취합한 평가결과와 구분하여 관리됩니다. 제안요청서는 이 유형이 아니라 <b>제안요청서</b> 유형으로 올려 주세요.'},
};
const KIND_PROMPT='자료 유형에 따라 저장되는 곳이 다릅니다. 제안요청서는 전체 사업 화면의 준비 상태에, 업체별 제안서는 업체 목록에, 평가결과 첨부자료는 결과 자료에 표시됩니다.';
$('#b-up').textContent='자료 등록';
$('#b-up').title='제안요청서·업체별 제안서·평가결과 첨부자료를 사업과 유형을 골라 등록합니다. 평가 점수 제출 메뉴가 아닙니다.';
$('#p-up-t').textContent='자료 등록';
const projField=$('#u-proj').closest('label'),titleField=$('#u-title').closest('label'),descField=$('#u-desc').closest('label');
const kindField=document.createElement('label');kindField.className='field';
kindField.innerHTML='자료 유형<select id="u-kind" aria-describedby="u-kind-e"><option value="">자료 유형을 골라 주세요</option>'+Object.entries(UPLOAD_KINDS).map(([k,v])=>`<option value="${k}">${h(v.label)}</option>`).join('')+'</select><span class="err" id="u-kind-e" hidden></span>';
const vendorField=document.createElement('label');vendorField.className='field';vendorField.hidden=true;
vendorField.innerHTML='업체<select id="u-vendor" aria-describedby="u-vendor-e"><option value="">업체를 골라 주세요</option></select><span class="err" id="u-vendor-e" hidden></span>';
projField.after(kindField);kindField.after(vendorField);
let vendorRows=[];
async function loadVendorOptions(){
 const projectId=$('#u-proj').value,select=$('#u-vendor');
 vendorRows=projectId?((await Live.api('PRJ-05',{project_id:projectId})).vendors||[]).filter(v=>!v.deleted_at):[];
 select.innerHTML='<option value="">'+(vendorRows.length?'업체를 골라 주세요':projectId?'이 사업에 등록된 업체가 없습니다':'먼저 사업을 골라 주세요')+'</option>'+vendorRows.map(v=>`<option value="${h(v.id)}">${h(v.display_code)}사 · ${h(v.legal_name)}</option>`).join('');
}
async function applyUploadKind(){
 const kind=$('#u-kind').value,spec=UPLOAD_KINDS[kind];
 vendorField.hidden=kind!=='PROPOSAL';titleField.hidden=kind!=='RESULT';descField.hidden=kind!=='RESULT';
 $('#u-file').accept=spec?spec.accept:'';
 $('#p-up .note div').innerHTML=spec?spec.note:KIND_PROMPT;
 if(kind==='PROPOSAL')await loadVendorOptions();
}
const originalUpload=$('#b-up').onclick;
$('#b-up').onclick=()=>{originalUpload();$('#u-proj').innerHTML='<option value="">사업을 골라 주세요</option>'+projects.map(p=>`<option value="${h(p.id)}">${h(p.name)}</option>`).join('');$('#u-kind').value='';applyUploadKind();};
Live.capture('#u-kind','change',applyUploadKind);
Live.capture('#u-proj','change',async()=>{if($('#u-kind').value==='PROPOSAL')await loadVendorOptions();});
Live.capture('#f-up','submit',async()=>{
 const projectId=$('#u-proj').value,kind=$('#u-kind').value,spec=UPLOAD_KINDS[kind],file=$('#u-file').files[0];
 if(!projectId)throw Error('사업을 골라 주세요.');if(!spec)throw Error('자료 유형을 골라 주세요.');if(!file)throw Error('올릴 파일을 골라 주세요.');
 const extensions=spec.accept.split(',');
 if(!extensions.some(ext=>file.name.toLowerCase().endsWith(ext)))throw Error(extensions.map(ext=>ext.slice(1).toUpperCase()).join('·')+' 파일만 올릴 수 있습니다.');
 if(file.size>50*1024*1024)throw Error('50MB 이하의 파일을 올려 주세요.');
 const form=new FormData();form.append('file',file);
 const base='/api/v2/projects/'+encodeURIComponent(projectId);
 let url,done;
 if(kind==='RFP'){url=base+'/rfp';done=body=>'제안요청서 v'+body.data.revision+'을 등록했어요 · 전체 사업 화면의 준비 상태에도 반영돼요';}
 else if(kind==='PROPOSAL'){
  const vendorId=$('#u-vendor').value;if(!vendorId)throw Error('업체를 골라 주세요.');
  const vendor=vendorRows.find(v=>v.id===vendorId);url=base+'/vendors/'+encodeURIComponent(vendorId)+'/proposals';
  done=body=>{const ack=body.data.ack?.status;return (vendor?vendor.display_code+'사 ':'')+'제안서 v'+body.data.upload_revision+'을 등록했어요 · 평가 연결 '+(ack==='APPLIED'||ack==='DUPLICATE'?'완료':ack||'대기');};
 }else{
  const title=$('#u-title').value.trim();if(!title)throw Error('제목을 적어 주세요.');
  form.append('title',title);form.append('description',$('#u-desc').value.trim());url=base+'/result-files';
  done=()=>'결과 자료를 등록했어요 · 별도 등록 자료로 표시돼요';
 }
 const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web'},body:form});
 const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error?.message||'자료를 등록하지 못했습니다.');
 closeLayer($('#p-up'));await loadMaterials();tabs('files');toast(done(body));
});
// 수정 / 파일 교체 저장. 제안요청서·제안서 → 새 차수 업로드(DOC-01·PRO-01), 결과 자료 → MAT-03 새 버전. 확정 점수·서명은 바뀌지 않는다.
Live.capture('#f-ed','submit',async()=>{
 const row=cur,item=row?.item;
 if(!item)throw Error('위원장이 최종 제출한 결과는 여기서 수정할 수 없습니다.');
 if(item.kind==='RFP'||item.kind==='PROPOSAL'){
  const spec=item.kind==='RFP'?UPLOAD_KINDS.RFP:UPLOAD_KINDS.PROPOSAL,file=$('#e-file').files[0];
  if(!file)throw Error('교체할 새 파일을 골라 주세요.');
  const extensions=spec.accept.split(',');
  if(!extensions.some(ext=>file.name.toLowerCase().endsWith(ext)))throw Error(extensions.map(ext=>ext.slice(1).toUpperCase()).join('·')+' 파일만 올릴 수 있습니다.');
  if(file.size>50*1024*1024)throw Error('50MB 이하의 파일을 올려 주세요.');
  const form=new FormData();form.append('file',file);
  const base='/api/v2/projects/'+encodeURIComponent(item.project_id);
  const url=item.kind==='RFP'?base+'/rfp':base+'/vendors/'+encodeURIComponent(item.vendor_id)+'/proposals';
  const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web'},body:form});
  const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error?.message||'파일을 교체하지 못했습니다.');
  closeLayer($('#p-ed'));await loadMaterials();draw();
  toast(item.kind==='RFP'?'제안요청서 v'+body.data.revision+'으로 교체했어요 · 이전 차수는 이력에 남아요':(item.display_code?item.display_code+'사 ':'')+'제안서 v'+body.data.upload_revision+'으로 교체했어요 · 이전 차수는 이력에 남아요');
  return;
 }
 if(!row.material)throw Error('이 자료는 여기서 수정할 수 없습니다.');
 const form=new FormData();form.append('version',String(row.material.version));form.append('description',$('#e-desc').value.trim());
 const file=$('#e-file').files[0];if(file)form.append('file',file);
 const response=await fetch('/api/v2/projects/'+encodeURIComponent(row.material.project_id)+'/result-files/'+encodeURIComponent(row.material.id)+'/revisions',{method:'POST',credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web'},body:form});
 const body=await response.json();if(!response.ok)throw Error(body.error?.message||'자료를 수정하지 못했습니다.');
 closeLayer($('#p-ed'));await loadMaterials();draw();toast('v'+body.data.revision_no+'으로 저장했어요 · 확정 점수·서명은 바뀌지 않아요');
});
