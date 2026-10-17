// PM-01 · PRJ-01/02/05. Use the original renderer, row, drawer and inputs.
const liveProjectStatus=s=>({EVALUATING:'평가 중',COMPLETED:'완료'}[s]||'준비');
const liveProjectRows=async()=>{
  const first=await Live.api('PRJ-01',{page:1,page_size:100});let items=first.items;
  for(let page=2;items.length<first.total;page++){const next=await Live.api('PRJ-01',{page,page_size:100});if(!next.items.length)break;items=items.concat(next.items);}
  P=items.map(r=>({id:r.id,name:r.name,owner:r.contact_name,date:r.evaluation_date||'',step:r.workflow_step||1,s:liveProjectStatus(r.status),doc:'none',ev:r.status==='COMPLETED'?'ok':'none'}));
  empty=false;render();
};
await liveProjectRows();
// The original edit drawer already uses a date input. Reuse that field style at registration.
const scheduleLabel=document.createElement('label');scheduleLabel.className='field';scheduleLabel.textContent='평가일정 (평가일)';
const scheduleInput=document.createElement('input');scheduleInput.id='n-date';scheduleInput.type='date';scheduleLabel.append(scheduleInput);$('#n-name').closest('label').after(scheduleLabel);
$('#b-new').addEventListener('click',()=>{scheduleInput.value='';});
const liveDept=Live.boot.departments.find(d=>d.id===Live.boot.actor.department_id);
if(liveDept){$('#n-org').value=liveDept.organization_name;$('#n-dept').value=liveDept.name;$('#f-dept').options[0].textContent=liveDept.name;document.querySelector('.side .role').textContent=liveDept.name;}
Live.capture('#f-new','submit',async()=>{
  const row=await Live.api('PRJ-02',{department_id:Live.boot.actor.department_id,name:$('#n-name').value.trim(),evaluation_date:$('#n-date').value,contact_organization:$('#n-org').value.trim(),contact_department:$('#n-dept').value.trim(),contact_position:$('#n-pos').value.trim(),contact_name:$('#n-owner').value.trim(),contact_phone:$('#n-tel').value.trim(),contact_email:$('#n-mail').value.trim()});
  await Live.reload();Live.selectProject(row.id);closeLayer($('#p'));await liveProjectRows();toast('사업을 저장했어요.');
});
Live.capture('#rows tr','click',async(e,tr)=>{
  Live.selectProject(tr.dataset.id);
  if(e.target.closest('[data-m]')){openMats(tr.dataset.id);return;}
  Live.go('PM-01-overview',{id:tr.dataset.id});
});
Live.capture('#rows tr','keydown',async(e,tr)=>{if(e.key==='Enter'||e.key===' '){Live.selectProject(tr.dataset.id);Live.go('PM-01-overview',{id:tr.dataset.id});}});
