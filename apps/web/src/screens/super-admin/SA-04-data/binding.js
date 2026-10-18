// SA-04 is mixed ownership: the committee pool is Lex6won's COM-01 data.
// Document uploads/retention remain separate; never simulate a successful save.
const departments=Live.boot.departments,projects=Live.boot.projects;
const candidateGroups=await Promise.all(departments.map(async department=>({department,items:await Live.all('COM-01',{department_id:department.id,scope:'DEPARTMENT_POOL',active:true})})));
R.splice(0,R.length,...candidateGroups.flatMap(({department,items})=>items.map(c=>[
 c.organization_name,c.department_name||'—',c.name,h(c.position||'—'),h(c.specialty_ids.map(id=>Live.boot.specialties.find(s=>s.id===id)?.name||id).join(', ')),
 department.organization_name+' · '+department.name,c.participation_count||0,
])));
pools.splice(0,pools.length,...new Set(R.map(r=>r[5])));
PROJ.splice(0,PROJ.length,...projects.map(p=>p.name));
F=[];
for(const project of projects){
 const {sessions}=await Live.get('/api/v2/result-sessions/'+encodeURIComponent(project.id));
 for(const session of sessions.filter(s=>s.status==='FINALIZED')){
  const result=await Live.api('RES-01',{session_id:session.id});
  F.push({...mk(project.name,'결과 자료','—',project.name+'_평가결과.html','HTML',(result.session.closed_at||'').slice(0,10),'보관',{src:'SYSTEM'}),sessionId:session.id});
 }
}
const retentionReason='보관 기간·폐기 승인 절차가 아직 정해지지 않아 사용할 수 없습니다. 자료는 삭제되지 않습니다.';
$('#b-up').textContent='결과 첨부자료 등록';
$('#b-up').title='외부에서 작성한 회의록·스캔본 등을 보관하는 메뉴입니다. 평가 점수 제출 메뉴가 아닙니다.';
$('#why').className='spec-note';$('#why').textContent='보관·폐기: 보관 기간과 승인 절차 확정 대기';
$('#why').style.order='3';$('#why').style.flexBasis='100%';$('#acts').style.flexWrap='wrap';
$$('#acts button[disabled]').forEach(button=>{button.title=retentionReason;button.setAttribute('aria-describedby','why');});
$('.demo-in .muted').textContent=retentionReason;
const originalMaterialDraw=draw;
draw=function(){
 originalMaterialDraw();
 if(tab==='files')$$('#rows [data-e]').forEach(button=>{button.textContent='결과 다운로드';button.setAttribute('aria-label',F[Number(button.dataset.e)].file+' 다운로드');});
};
const originalMaterialTabs=tabs;
tabs=function(value){
 originalMaterialTabs(value);
 if(value==='pool')$('#tb .spec-note').textContent='위원 풀 · 원준석(Lex6won) 담당 / 부서에서 등록한 실제 후보를 조회합니다.';
 else {$('#sub').textContent='시스템 확정 결과를 조회합니다. 제안요청서·제안서 파일 보관은 문서 모듈 연계 대상입니다.';$('#none strong').textContent='확정된 결과 자료가 없습니다';$('#none p').textContent='위원장이 최종 제출하면 이 목록에 표시됩니다.';}
};
tabs(location.hash==='#pool'?'pool':'files');
Live.capture('#rows [data-e]','click',(_event,button)=>Live.api('RES-05',{session_id:F[Number(button.dataset.e)].sessionId},'평가결과.html'));
const showUploadGuide=$('#b-up').onclick;
$('#b-up').onclick=()=>{
 showUploadGuide();$('#p-up-t').textContent='결과 첨부자료 등록 안내';
 $('#f-up .note div').textContent='회의록·서명 스캔본 등 외부에서 만든 결과 파일을 따로 보관하는 기능입니다. 위원장 최종 제출 결과는 자동으로 목록에 표시됩니다. 첨부파일 저장은 문서 모듈 연결 전이므로 아직 등록할 수 없습니다.';
 const submit=$('[form="f-up"][type="submit"]');submit.disabled=true;submit.title='첨부파일 보관 기능 연결 후 사용할 수 있습니다.';
};
Live.capture('#f-up,#f-ed','submit',()=>{throw Error('첨부파일 보관·교체 기능은 문서 모듈 연결 대기 중입니다. 등록하거나 변경한 파일은 없습니다.');});
