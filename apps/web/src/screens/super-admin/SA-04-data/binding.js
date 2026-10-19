// SA-04 · MAT-01~03 · COM-01
// 자료 탭: 문서 DB(제안요청서·제안서·결과 자료)와 평가 DB(확정 결과)를 한 목록으로. 위원 풀 탭: 원준석(Lex6won) COM-01 데이터.
const departments=Live.boot.departments,projects=Live.boot.projects;
const candidateGroups=await Promise.all(departments.map(async department=>({department,items:await Live.all('COM-01',{department_id:department.id,scope:'DEPARTMENT_POOL',active:true})})));
R.splice(0,R.length,...candidateGroups.flatMap(({department,items})=>items.map(c=>[
 c.organization_name,c.department_name||'—',c.name,h(c.position||'—'),h(c.specialty_ids.map(id=>Live.boot.specialties.find(s=>s.id===id)?.name||id).join(', ')),
 department.organization_name+' · '+department.name,c.participation_count||0,
])));
pools.splice(0,pools.length,...new Set(R.map(r=>r[5])));
PROJ.splice(0,PROJ.length,...projects.map(p=>p.name));
const projectById=new Map(projects.map(p=>[p.id,p]));
let materialItems=[];
const KIND={RFP:'제안요청서',PROPOSAL:'제안서',UPLOADED_RESULT:'결과 자료',GENERATED_REPORT:'결과 자료',SYSTEM:'결과 자료'};
async function loadMaterials(){
 const data=await Live.get('/api/v2/materials');
 materialItems=[];F.length=0;
 for(const item of data.items){
  const project=projectById.get(item.project_id);if(!project)continue;
  const co=item.kind==='PROPOSAL'?(item.display_code?item.display_code+'사 · ':'')+(item.legal_name||''):'—';
  const row=mk(project.name,KIND[item.kind]||item.label,co,item.filename,(item.byte_size/1048576).toFixed(1)+' MB',(item.date||'').slice(0,10),'보관',{ver:item.revision,desc:item.description||'',src:item.kind==='UPLOADED_RESULT'?'UPLOAD':item.kind==='GENERATED_REPORT'?'SYSTEM':null});
  row.download=item.download;row.material=item.kind==='UPLOADED_RESULT'||item.kind==='GENERATED_REPORT'?item:null;
  F.push(row);materialItems.push(row);
 }
 for(const session of data.results){
  const project=projectById.get(session.project_id);if(!project)continue;
  const row=mk(project.name,'결과 자료','—',project.name+'_제안서평가_집계표.xlsx','XLSX',(session.closed_at||'').slice(0,10),'보관',{src:'SYSTEM',desc:'위원장 최종 제출 결과(시스템 취합본) · 서명 증빙 HTML 포함'});
  row.sessionId=session.session_id;F.push(row);
 }
}
await loadMaterials();
const retentionReason='보관 기간·폐기 승인 절차가 아직 정해지지 않아 사용할 수 없습니다. 자료는 삭제되지 않습니다.';
$('#why').className='spec-note';$('#why').textContent='보관·폐기: 보관 기간과 승인 절차 확정 대기';
$('#why').style.order='3';$('#why').style.flexBasis='100%';$('#acts').style.flexWrap='wrap';
$$('#acts button[disabled]').forEach(button=>{button.title=retentionReason;button.setAttribute('aria-describedby','why');});
$('.demo-in .muted').textContent=retentionReason;
const originalMaterialDraw=draw;
draw=function(){
 originalMaterialDraw();
 if(tab==='files')$$('#rows [data-e]').forEach(button=>{const row=F[Number(button.dataset.e)];
  const wrap=document.createElement('span');wrap.style.display='inline-flex';wrap.style.gap='6px';
  const dl=document.createElement('button');dl.type='button';dl.className='btn sm';dl.dataset.dl=button.dataset.e;dl.textContent=row.sessionId?'집계표 다운로드':'내려받기';dl.setAttribute('aria-label',row.file+' 내려받기');
  wrap.appendChild(dl);
  if(row.sessionId){const html=document.createElement('button');html.type='button';html.className='btn sm';html.dataset.dlhtml=button.dataset.e;html.textContent='서명 증빙(HTML)';wrap.appendChild(html);}
  if(row.material&&row.material.kind==='UPLOADED_RESULT'){button.textContent='수정 / 파일 교체';wrap.appendChild(button.cloneNode(true));}
  button.replaceWith(wrap);
 });
};
const originalMaterialTabs=tabs;
tabs=function(value){
 originalMaterialTabs(value);
 if(value==='pool')$('#tb .spec-note').textContent='위원 풀 · 원준석(Lex6won) 담당 / 부서에서 등록한 실제 후보를 조회합니다.';
 else {$('#sub').textContent='모든 사업의 제안요청서·제안서(업체별 최신)·결과 자료를 조회하고 내려받습니다.';$('#none strong').textContent='자료가 없습니다';$('#none p').textContent='사업담당자가 문서를 등록하거나 위원장이 최종 제출하면 이 목록에 표시됩니다.';}
};
tabs(location.hash==='#pool'?'pool':'files');
async function downloadRow(row){const response=await fetch(row.download,{credentials:'same-origin'});if(!response.ok)throw Error('파일을 내려받지 못했습니다.');const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=row.file;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
Live.capture('#rows [data-dl]','click',(_event,button)=>{const row=F[Number(button.dataset.dl)];return row.sessionId?Live.api('RES-05',{session_id:row.sessionId,format:'xlsx'},row.file):downloadRow(row);});
Live.capture('#rows [data-dlhtml]','click',(_event,button)=>Live.api('RES-05',{session_id:F[Number(button.dataset.dlhtml)].sessionId},'평가결과_서명증빙.html'));
Live.capture('#rows [data-e]','click',(_event,button)=>{openEd(Number(button.dataset.e));});
// MAT-02: 결과 첨부자료 등록(회의록·스캔본 등). 시스템 취합본과 구분해 UPLOADED_RESULT로 보관한다.
$('#b-up').textContent='결과 첨부자료 등록';
$('#b-up').title='외부에서 작성한 회의록·스캔본 등을 보관하는 메뉴입니다. 평가 점수 제출 메뉴가 아닙니다.';
const originalUpload=$('#b-up').onclick;
$('#b-up').onclick=()=>{originalUpload();$('#u-proj').innerHTML='<option value="">사업을 골라 주세요</option>'+projects.map(p=>`<option value="${h(p.id)}">${h(p.name)}</option>`).join('');};
Live.capture('#f-up','submit',async()=>{
 const projectId=$('#u-proj').value,file=$('#u-file').files[0],title=$('#u-title').value.trim();
 if(!projectId)throw Error('사업을 골라 주세요.');if(!file)throw Error('올릴 파일을 골라 주세요.');if(!title)throw Error('제목을 적어 주세요.');
 const form=new FormData();form.append('file',file);form.append('title',title);form.append('description',$('#u-desc').value.trim());
 const response=await fetch('/api/v2/projects/'+encodeURIComponent(projectId)+'/result-files',{method:'POST',credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web'},body:form});
 const body=await response.json();if(!response.ok)throw Error(body.error?.message||'자료를 등록하지 못했습니다.');
 closeLayer($('#p-up'));await loadMaterials();tabs('files');toast('결과 자료를 등록했어요 · 직접 올린 자료로 표시돼요');
});
// MAT-03: 수정/파일 교체 → 새 버전. 확정 점수·서명은 바뀌지 않는다.
Live.capture('#f-ed','submit',async()=>{
 const row=cur;if(!row?.material)throw Error('시스템 취합본은 여기서 수정할 수 없습니다.');
 const form=new FormData();form.append('version',String(row.material.version));form.append('description',$('#e-desc').value.trim());
 const file=$('#e-file').files[0];if(file)form.append('file',file);
 const response=await fetch('/api/v2/projects/'+encodeURIComponent(row.material.project_id)+'/result-files/'+encodeURIComponent(row.material.id)+'/revisions',{method:'POST',credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web'},body:form});
 const body=await response.json();if(!response.ok)throw Error(body.error?.message||'자료를 수정하지 못했습니다.');
 closeLayer($('#p-ed'));await loadMaterials();draw();toast('v'+body.data.revision_no+'으로 저장했어요 · 확정 점수·서명은 바뀌지 않아요');
});
