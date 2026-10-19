// PM-01 · PRJ-01/02/05. Use the original renderer, row, drawer and inputs.
const liveProjectStatus=s=>({EVALUATING:'평가 중',COMPLETED:'완료',UNKNOWN:'미기록'}[s]||'준비');
const liveProjectRows=async()=>{
  const first=await Live.api('PRJ-01',{page:1,page_size:100});let items=first.items;
  for(let page=2;items.length<first.total;page++){const next=await Live.api('PRJ-01',{page,page_size:100});if(!next.items.length)break;items=items.concat(next.items);}
  P=items.map(r=>({id:r.id,name:r.name,owner:r.contact_name,date:r.evaluation_date||'',step:r.workflow_step||1,s:liveProjectStatus(r.status),doc:'none',ev:r.status==='COMPLETED'?'ok':'none'}));
  empty=false;render();
};
await liveProjectRows();
const statusSelect=$('#f-st');
statusSelect.options[0].textContent='전체선택';
const evaluatingOption=Array.from(statusSelect.options).find(option=>option.textContent==='평가 중');
if(evaluatingOption){evaluatingOption.value='평가 중';evaluatingOption.textContent='평가';}
statusSelect.add(new Option('삭제','삭제'));
let deletedRows=[];
const activeHeader=$('table thead').innerHTML;
const activeRender=render;
render=function(keep){
  if(fs!=='삭제'){$('table thead').innerHTML=activeHeader;activeRender(keep);return;}
  if(keep!==true)pg=1;
  const search=q.toLocaleLowerCase();
  const filtered=deletedRows.filter(row=>(row.name+' '+row.contact_name+' '+row.deletion_reason).toLocaleLowerCase().includes(search));
  const pages=Math.max(1,Math.ceil(filtered.length/PS));if(pg>pages)pg=pages;
  const shown=filtered.slice((pg-1)*PS,pg*PS);
  $('#count').textContent=filtered.length+'개 삭제 사업'+(filtered.length?' · '+pg+'/'+pages+'쪽':'');
  $('table').hidden=!filtered.length;
  const blank=$('#none');blank.hidden=filtered.length>0;
  if(!filtered.length)blank.innerHTML='<div class="ico" aria-hidden="true">⌫</div><strong>삭제된 사업이 없어요</strong><p>검색어를 바꾸거나 [초기화]를 눌러 보세요.</p>';
  $('table thead').innerHTML='<tr><th>사업명</th><th>담당자</th><th>삭제일</th><th>삭제 전 상태</th><th>삭제 사유</th><th>상세</th></tr>';
  $('#rows').innerHTML=shown.map(row=>`<tr tabindex="0" data-deleted-id="${h(row.id)}" aria-label="${h(row.name)} 삭제 기록 열기"><td class="strong nm">${h(row.name)}</td><td>${h(row.contact_name||'미등록')}</td><td class="tnum">${h(row.deleted_at.slice(0,10))}</td><td><span class="badge">${h(liveProjectStatus(row.status))}</span></td><td>${h(row.deletion_reason)}</td><td><button class="btn sm" type="button">기록 보기</button></td></tr>`).join('');
  $$('#rows tr[data-deleted-id]').forEach(row=>{
    const open=async()=>{
      try{
        const detail=await Live.api('PRJ-09',{deleted_project_id:row.dataset.deletedId});
        $('#pm-t').textContent='삭제된 사업 기록';
        $('#pm-body').innerHTML=`<dl class="kv"><dt>사업명</dt><dd>${h(detail.name)}</dd><dt>삭제 전 상태</dt><dd>${h(liveProjectStatus(detail.status))}</dd><dt>삭제일</dt><dd>${h(detail.deleted_at.slice(0,10))}</dd><dt>삭제 사유</dt><dd>${h(detail.deletion_reason)}</dd><dt>담당자</dt><dd>${h(detail.contact_name)}</dd><dt>소속 / 부서</dt><dd>${h(detail.contact_organization)} / ${h(detail.contact_department)}</dd><dt>전화</dt><dd>${h(detail.contact_phone)}</dd><dt>이메일</dt><dd>${h(detail.contact_email||'없음')}</dd><dt>평가일</dt><dd>${h(detail.evaluation_date||'미등록')}</dd></dl>`;
        const categories=[['current_status','사업 관련 현황'],['background_and_need','추진 배경과 필요성'],['scope','사업 범위·주요 과업']];
        $('#pm-body').innerHTML+=`<h3>삭제 당시 사업 요약</h3>${categories.map(([key,label])=>`<section><h4>${label}</h4>${detail.business_summary?.[key]?.length?`<ul>${detail.business_summary[key].map(item=>`<li>${h(item.text)}${item.pages?.length?` · 원문 ${item.pages.map(h).join(', ')}쪽`:''}</li>`).join('')}</ul>`:'<p class="muted">보관된 요약이 없습니다.</p>'}</section>`).join('')}`;
        openLayer($('#pm'),'.x');
      }catch(error){Live.message(error.message);}
    };
    row.addEventListener('click',open);
    row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});
  });
  let buttons=`<button type="button" data-p="${pg-1}" ${pg<2?'disabled':''} aria-label="이전 쪽">‹</button>`;
  for(let index=1;index<=pages;index++)buttons+=`<button type="button" data-p="${index}" ${index===pg?'aria-current="page"':''}>${index}</button>`;
  buttons+=`<button type="button" data-p="${pg+1}" ${pg>=pages?'disabled':''} aria-label="다음 쪽">›</button>`;
  $('#pager').innerHTML=buttons;$('#pager').hidden=!filtered.length;
  $$('#pager button').forEach(button=>button.onclick=()=>{pg=+button.dataset.p;render(true)});
};
statusSelect.addEventListener('change',async()=>{if(statusSelect.value==='삭제'){try{deletedRows=await Live.all('PRJ-08');render();}catch(error){Live.message(error.message);}}});
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
Live.capture('#rows tr:not([data-deleted-id])','click',async(e,tr)=>{
  Live.selectProject(tr.dataset.id);
  if(e.target.closest('[data-m]')){openMats(tr.dataset.id);return;}
  Live.go('PM-01-overview',{id:tr.dataset.id});
});
Live.capture('#rows tr:not([data-deleted-id])','keydown',async(e,tr)=>{if(e.key==='Enter'||e.key===' '){Live.selectProject(tr.dataset.id);Live.go('PM-01-overview',{id:tr.dataset.id});}});
