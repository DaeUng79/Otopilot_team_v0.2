// PM-03 · CRT-01~05
// 원본 화면의 상태(phase/T/LIMIT)와 렌더러를 그대로 두고, 값만 서버(문서 DB)에서 채운다.
if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
const criteriaUrl='/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria';
let criteriaState=null,currentVersion=null,criteriaTimer=null,pendingApprove=false,descriptionByCode={};
async function getJson(url,options){const response=await fetch(url,{credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web',...(options?.json!==undefined?{'Content-Type':'application/json'}:{})},method:options?.method||'GET',body:options?.json!==undefined?JSON.stringify(options.json):undefined});const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error?.message||'요청을 처리하지 못했습니다.');return body.data;}
function treeFromItems(items){
  uid=0;descriptionByCode={};const nodes={},roots=[];
  for(const item of items){descriptionByCode[item.code]=item.description;const node=N(item.code,item.title,item.points,item.source_page,item.source_page!=null?'제안요청서':'',[]);nodes[item.code]=node;if(item.parent_code&&nodes[item.parent_code])nodes[item.parent_code].kids.push(node);else roots.push(node);}
  roots.forEach(r=>{if(r.kids.length)r.pt=0;});return roots;
}
function treeFromAi(rows,page){
  uid=0;descriptionByCode={};const roots=[];
  for(const row of rows){const division=row.evaluation_division||'평가부문';let parent=roots.find(r=>r.t===division);if(!parent){parent=N(String(roots.length+1),division,0,page,'',[]);roots.push(parent);}
    const code=`${parent.code}.${parent.kids.length+1}`;descriptionByCode[code]=(row.evaluation_criteria||'')+((row.evaluation_elements||[]).map(e=>'\n- '+e).join(''));parent.kids.push(N(code,row.evaluation_item||'평가항목',Number(row.score||0),page,'',[]));}
  return roots;
}
function itemsFromTree(){return flat().map((r,i)=>({code:String(r.n.code).trim(),parent_code:r.par?String(r.par.code).trim():null,title:r.n.t,description:descriptionByCode[String(r.n.code).trim()]||null,max_score:r.n.kids.length?0:Number(r.n.pt||0),source_page:r.n.pg==null?null:Number(r.n.pg),sort_order:i}));}
function applyState(){
  const versions=criteriaState.versions||[],latest=versions[versions.length-1]||null,draft=criteriaState.draft||{};
  currentVersion=latest;clearTimeout(criteriaTimer);
  if(latest&&latest.status==='APPROVED'){T=treeFromItems(latest.items);LIMIT=latest.total_points;phase='locked';ack=latest.ack?'done':'wait';}
  else if(latest&&latest.status==='DRAFT'){T=treeFromItems(latest.items);LIMIT=latest.total_points;phase='edit';}
  else if(!criteriaState.rfp){phase='none';T=[];}
  else if(['queued','running'].includes(draft.status)||['queued','running'].includes(criteriaState.requirements?.status)){phase='gen';criteriaTimer=setTimeout(loadCriteria,5000);}
  else if(draft.status==='failed'||criteriaState.requirements?.status==='failed'){phase='genfail';}
  else if(draft.status==='done'&&draft.result){LIMIT=draft.result.total_score;T=treeFromAi(draft.result.rows,null);phase='ready';}
  else phase='none';
  paint();
}
async function loadCriteria(){criteriaState=await getJson(criteriaUrl);applyState();}
const originalPaint=paint;
paint=function(){
  originalPaint();
  $('#demo').hidden=true;
  const empty=$('#card .empty');
  if(empty&&!criteriaState?.rfp){empty.querySelector('h2').textContent='제안요청서가 아직 없어요';empty.querySelector('p').textContent='문서 단계에서 제안요청서(HWPX)를 먼저 등록하면 평가표를 만들 수 있어요.';empty.querySelector('.row').innerHTML='<a class="btn primary" href="../../PM-02/design/documents.html">문서 단계로</a>';}
  else if(empty&&['none','genfail','reqwait'].includes(phase)){
    const row=empty.querySelector('.row');
    if(!criteriaState?.ai_ready){const gen=row.querySelector('[data-act="gen"]');if(gen){gen.disabled=true;gen.title='OpenAI 설정(.env의 OPENAI_API_KEY)이 없어 AI 초안을 만들 수 없어요';}}
    const manual=document.createElement('button');manual.type='button';manual.className='btn';manual.dataset.act='template';manual.textContent='서식으로 직접 작성';row.appendChild(manual);
    const notice=document.createElement('p');notice.className='muted';notice.style.marginTop='8px';notice.textContent=criteriaState?.ai_ready?'AI 초안은 제안요청서 요구사항 추출 → 평가기준 생성 순서로 몇 분 걸릴 수 있어요. 바로 작성하려면 [서식으로 직접 작성]을 누르세요.':'[서식으로 직접 작성]은 정성 80점 기본 서식(8항목)을 복사본으로 열어요.';empty.appendChild(notice);
    if(phase==='genfail'){const err=criteriaState?.draft?.error||criteriaState?.requirements?.error;if(err)empty.querySelector('p').textContent=err;}
  }
  if(phase==='ready'&&criteriaState?.draft?.result){const note=$('#card .notebar .note span');if(note)note.innerHTML=`AI가 만든 초안이에요. 아직 사람이 확인하지 않았어요. 출처: <b>${h(criteriaState.draft.result.reference_filename||'요구사항 총괄표')}</b> · 기술 배점 ${h(String(LIMIT))}점`;const strip=$('#card .strip .src');if(strip)strip.textContent=`AI 초안 · ${criteriaState.draft.result.template_source==='request_document'?'제안요청서 평가표를 읽었어요':'요구사항 총괄표로 만들었어요'}`;}
  if(phase==='edit'){const strip=$('#card .strip .src');if(strip)strip.textContent='복사본을 고치는 중이에요 · 근거 쪽은 제안요청서의 쪽 번호예요';}
  if(phase==='locked'&&currentVersion){const bar=$('#card .lockbar .muted');if(bar)bar.textContent=`승인 번호 ${currentVersion.approval_no} · ${(currentVersion.approved_at||'').slice(0,16).replace('T',' ')}`;
    if(currentVersion.frozen){const lb=$('#card .lockbar span:nth-child(2)');if(lb)lb.textContent='확정했어요. 평가 회차가 이 평가표를 쓰고 있어 고칠 수 없어요.';}
    else{const lb=$('#card .lockbar');if(lb&&!lb.querySelector('[data-act="reopen"]')){const b=document.createElement('button');b.type='button';b.className='btn';b.dataset.act='reopen';b.textContent='새 검토 시작(재승인)';lb.appendChild(b);}}}
};
await loadCriteria();
Live.capture('[data-act="gen"]','click',async()=>{await getJson(criteriaUrl+'/jobs',{method:'POST',json:{force:phase==='genfail'}});await loadCriteria();toast('AI 초안을 만드는 중이에요. 몇 분 걸릴 수 있어요');});
Live.capture('[data-act="refresh"]','click',async()=>{await loadCriteria();toast(phase==='gen'?'아직 만드는 중이에요':phase==='locked'&&ack==='wait'?'아직 평가 쪽 수신 확인을 기다리고 있어요':'최신 상태예요');});
Live.capture('[data-act="review"]','click',async()=>{await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts',{method:'POST',json:{source:'ai'}});await loadCriteria();agreed=false;toast('복사본을 만들었어요. AI 초안은 그대로 두었어요');});
Live.capture('[data-act="template"],[data-act="reopen"]','click',async()=>{await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts',{method:'POST',json:{source:'template'}});await loadCriteria();agreed=false;toast('기본 서식 복사본을 열었어요. 항목·배점·근거 쪽을 고친 뒤 확정하세요');});
async function saveDraft(){
  const items=itemsFromTree();
  currentVersion=await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts/'+encodeURIComponent(currentVersion.id),{method:'PUT',json:{version:currentVersion.version,items,total_points:LIMIT}});
}
Live.capture('#b-ok','click',async()=>{
  if(phase!=='edit'||!currentVersion)return;
  const I=issues();if(I.count||!agreed)throw Error(I.sumMsg||'고칠 곳을 먼저 확인하세요.');
  await saveDraft();pendingApprove=true;
  confirmDlg({title:'평가표를 확정할까요?',body:'확정하면 항목과 배점을 고칠 수 없어요. 확정한 평가표가 평가 쪽에 전달돼요.',ok:'확정',danger:false});
});
Live.capture('#dlg-cancel','click',()=>{pendingApprove=false;closeAll();});
Live.capture('#dlg-ok','click',async()=>{
  if(!pendingApprove)return;pendingApprove=false;
  const result=await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts/'+encodeURIComponent(currentVersion.id)+'/approve',{method:'POST',json:{version:currentVersion.version,confirmed:true}});
  closeAll();await loadCriteria();
  const status=result.ack?.status;toast(status==='APPLIED'||status==='DUPLICATE'?'평가표를 확정했고 평가 쪽에서 받았어요':'평가표를 확정했어요. 평가 쪽 수신 상태: '+(status||'대기'));
});
