// PM-01 detail · PRJ-03/04/05. Original drawer and confirmation dialog only.
if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
let liveDetail=(await Live.api('PRJ-05',{project_id:Live.pid})).project;
const livePaint=()=>{Object.assign(D,{name:liveDetail.name,owner:liveDetail.contact_name,pos:liveDetail.contact_position,tel:liveDetail.contact_phone,mail:liveDetail.contact_email,org:liveDetail.contact_organization,dept:liveDetail.contact_department,date:liveDetail.evaluation_date||''});paint();};
livePaint();
const liveLocked=!!liveDetail.evaluation_status||['EVALUATING','COMPLETED','CANCELLED'].includes(liveDetail.status);
$('#b-del').disabled=liveLocked;$('#lockn').hidden=!liveLocked;
const editProject=$('#b-edit').onclick;$('#b-edit').onclick=()=>{editProject();$('#e-lock').hidden=!liveLocked;['e-name','e-org','e-date'].forEach(id=>$('#'+id).disabled=liveLocked);};
$('#t-st').textContent=liveDetail.status==='COMPLETED'?'✓ 완료':liveDetail.status==='EVALUATING'?'● 평가 중':'○ 준비';
async function refreshOverview(){
 const state=await Live.get('/committee-v2/api/projects/'+encodeURIComponent(Live.pid));
 $('#sync').hidden=true;$('#docs').textContent='—';$('#docs-b').textContent='문서 연계 대상';$('#docs-bar').style.width='0%';
 const items=$$('.sum li');items[1].querySelector('.v').textContent=state.assignments.length?`${state.assignments.length}명 확정`:'아직 안 했어요';items[1].querySelector('.st').textContent=state.assignments.length?'✓ 확정':'○ 대기';
 items[2].querySelector('.v').textContent=liveDetail.evaluation_status==='FINALIZED'?'최종 제출 완료':`${liveDetail.submitted} / ${liveDetail.participants}명 제출`;items[2].querySelector('.st').textContent=liveDetail.evaluation_status==='FINALIZED'?'✓ 완료':'○ 대기';
}
await refreshOverview();Live.capture('#b-sync','click',refreshOverview);
renderSteps($('#steps'),['current','open','open','open','open','open']);
Live.capture('#f-edit','submit',async()=>{
  liveDetail=await Live.api('PRJ-03',{project_id:Live.pid,version:liveDetail.version,name:$('#e-name').value.trim(),contact_name:$('#e-owner').value.trim(),contact_position:$('#e-pos').value.trim(),contact_organization:$('#e-org').value.trim(),contact_department:liveDetail.contact_department,contact_phone:$('#e-tel').value.trim(),contact_email:$('#e-mail').value.trim(),evaluation_date:$('#e-date').value});
  livePaint();closeLayer($('#p'));toast('사업 정보를 저장했어요.');
});
Live.capture('#dlg-ok','click',async()=>{await Live.api('PRJ-04',{project_id:Live.pid,version:liveDetail.version,reason:$('#d-why').value.trim()});Live.go('PM-01');});
