// PM-03 · CRT-01~05
// 원본 화면의 상태(phase/T/LIMIT)와 렌더러를 그대로 두고, 값만 서버(문서 DB)에서 채운다.
if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
const criteriaUrl='/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria';
let criteriaState=null,currentVersion=null,criteriaTimer=null,pendingApprove=false,pendingNewDraft=false,descriptionByCode={};
let criteriaSubmitting=false,generationPending=false;
let criteriaView='current',reviewSnapshot=null,openingTemplate=false;
let parsedSource=null;
async function getJson(url,options){const response=await fetch(url,{credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web',...(options?.json!==undefined?{'Content-Type':'application/json'}:{})},method:options?.method||'GET',body:options?.json!==undefined?JSON.stringify(options.json):undefined});const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error?.message||'요청을 처리하지 못했습니다.');return body.data;}
function sourcePage(blocks,title,score){
  const compact=value=>String(value||'').replace(/[^\p{L}\p{N}]/gu,'').toLowerCase();
  const target=compact(title);if(!target||!Number.isFinite(Number(score)))return null;
  const points=new RegExp(`[（(]\\s*${Number(score)}\\s*점\\s*[)）]`);
  for(const block of blocks){
    const pages=(block.pages||[]).filter(Number.isInteger);if(!pages.length)continue;
    const texts=block.type==='table'?(block.rows||[]).flat().map(cell=>cell.text):[block.text];
    const fragments=texts.flatMap(text=>String(text||'').split(/(?=[∘○◦•∙●])/u));
    if(fragments.some(text=>compact(text).includes(target)&&points.test(text)))return {source_page:pages[0],source_page_end:pages.at(-1)===pages[0]?null:pages.at(-1)};
  }
  return null;
}
async function enrichSourcePages(state){
  const result=state.draft?.result,rfp=state.rfp;
  if(!rfp||!result)return;
  const scoring=result.scoring_rows||splitScoredRows(result.rows||[]);
  result.scoring_rows=scoring;
  const versions=state.versions||[];
  const missing=scoring.some(row=>row.source_page==null)||versions.some(version=>version.status==='DRAFT'&&version.items.some(item=>item.is_scorable&&item.source_page==null));
  if(!missing)return;
  if(parsedSource?.revision!==rfp.revision){
    try{parsedSource=await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/rfp/'+encodeURIComponent(rfp.revision)+'/source');}
    catch(error){state.source_page_error=error.message;return;}
  }
  for(const row of scoring)if(row.source_page==null)Object.assign(row,sourcePage(parsedSource.blocks,row.evaluation_item,row.score)||{});
  for(const version of versions)if(version.status==='DRAFT')for(const item of version.items)
    if(item.is_scorable&&item.source_page==null){
      const matching=scoring.find(row=>row.evaluation_item===item.title&&Number(row.score)===Number(item.points)&&row.source_page!=null);
      Object.assign(item,matching?{source_page:matching.source_page,source_page_end:matching.source_page_end}:sourcePage(parsedSource.blocks,item.title,item.points)||{});
    }
}
function pageLabel(source){return source.source_page==null?null:String(source.source_page)+(source.source_page_end!=null?'~'+source.source_page_end:'');}
function treeFromItems(items){
  uid=0;descriptionByCode={};const nodes={},roots=[];
  for(const item of items){descriptionByCode[item.code]=item.description;const node=N(item.code,item.title,item.points,pageLabel(item),item.source_page!=null?'제안요청서':'',[]);nodes[item.code]=node;if(item.parent_code&&nodes[item.parent_code])nodes[item.parent_code].kids.push(node);else roots.push(node);}
  roots.forEach(r=>{if(r.kids.length)r.pt=0;});return roots;
}
function splitScoredRows(rows){
  return rows.flatMap(row=>{
    const parts=String(row.evaluation_item||'').split(/(?:^|\s)[∘○◦•∙●]\s*/u).map(part=>part.trim()).filter(Boolean);
    if(parts.length<2)return [row];
    const details=parts.map(part=>{
      const point=part.match(/[（(]\s*(\d+)\s*점\s*[)）]/u);
      return point?{title:part.slice(0,point.index).trim(),score:Number(point[1]),note:part.slice(point.index+point[0].length).trim()}:null;
    });
    if(details.some(part=>!part?.title)||details.reduce((sum,part)=>sum+part.score,0)!==Number(row.score))return [row];
    return details.map((part,index)=>({...row,row_id:`${row.row_id||''}-${String(index+1).padStart(2,'0')}`,
      evaluation_item:part.title,score:part.score,
      evaluation_criteria:[part.note,row.evaluation_criteria].filter(Boolean).join('\n')}));
  });
}
function treeFromAi(rows,page){
  uid=0;descriptionByCode={};const roots=[];
  for(const row of splitScoredRows(rows)){const division=row.evaluation_division||'평가부문';let parent=roots.find(r=>r.t===division);if(!parent){parent=N(String(roots.length+1),division,0,page,'',[]);roots.push(parent);}
    const code=`${parent.code}.${parent.kids.length+1}`;descriptionByCode[code]=(row.evaluation_criteria||'')+((row.evaluation_elements||[]).map(e=>'\n- '+e).join(''))+(row.score_bands?'\n원문 배점기준: '+Object.entries(row.score_bands).map(([k,v])=>`${k} ${v}점`).join(' / '):'')+(row.requirement_codes?.length?'\n연결 요구사항: '+row.requirement_codes.join(', '):'');parent.kids.push(N(code,row.evaluation_item||'평가항목',Number(row.score||0),pageLabel(row),row.source_block_id?'파싱 원문':'',[]));}
  return roots;
}
function itemsFromTree(){return flat().map((r,i)=>{const pages=String(r.n.pg||'').split('~').map(Number);return {code:String(r.n.code).trim(),parent_code:r.par?String(r.par.code).trim():null,title:r.n.t,description:descriptionByCode[String(r.n.code).trim()]||null,max_score:r.n.kids.length?0:Number(r.n.pt||0),source_page:r.n.pg==null?null:pages[0],source_page_end:pages.length>1?pages[1]:null,sort_order:i};});}
function applyState(){
  const versions=criteriaState.versions||[],latest=versions[versions.length-1]||null,draft=criteriaState.draft||{};
  const keepEditing=criteriaView==='current'&&phase==='edit'&&currentVersion?.id===latest?.id&&currentVersion?.version===latest?.version;
  const savedReview=reviewSnapshot?.id===latest?.id&&reviewSnapshot?.version===latest?.version?reviewSnapshot:null;
  const editedTree=keepEditing?T:savedReview?.tree;
  currentVersion=latest;clearTimeout(criteriaTimer);
  if(criteriaView==='current'&&latest&&latest.status==='APPROVED'){T=treeFromItems(latest.items);LIMIT=latest.total_points;phase='locked';ack=latest.ack?'done':'wait';}
  else if(criteriaView==='current'&&latest&&latest.status==='DRAFT'){
    T=editedTree||treeFromItems(latest.items);LIMIT=latest.total_points;phase='edit';
    if(savedReview&&!keepEditing){descriptionByCode={...savedReview.descriptions};uid=savedReview.uid;}
    const pages=new Map(latest.items.map(item=>[item.code,pageLabel(item)]));
    for(const {n} of flat())if(!n.kids.length&&n.pg==null&&pages.get(n.code)!=null)n.pg=pages.get(n.code);
  }
  else if(!criteriaState.rfp){phase='none';T=[];}
  else if(draft.status==='done'&&draft.result){LIMIT=draft.result.total_score;T=treeFromAi(draft.result.scoring_rows||draft.result.rows,null);phase='ready';}
  else if(draft.status==='failed'){phase='genfail';}
  else if(['queued','running'].includes(draft.status)){phase='gen';criteriaTimer=setTimeout(()=>loadCriteria().catch(error=>Live.message(error.message)),5000);}
  else if(criteriaState.requirements?.status!=='done'){
    phase='reqwait';
    if(['queued','running'].includes(criteriaState.requirements?.status))
      criteriaTimer=setTimeout(()=>loadCriteria().catch(error=>Live.message(error.message)),5000);
  }
  else phase='none';
  if(['queued','running'].includes(draft.status)&&!criteriaTimer)
    criteriaTimer=setTimeout(()=>loadCriteria().catch(error=>Live.message(error.message)),5000);
  paint();
  if(generationPending&&phase==='ready'){
    generationPending=false;toast('AI 초안이 준비됐어요. 평가항목과 배점을 검토해 주세요.');
  }else if(generationPending&&phase==='genfail'){
    generationPending=false;toast('AI 초안을 만들지 못했어요. 실패 이유를 확인하고 다시 시도해 주세요.');
  }else if(generationPending&&['edit','locked'].includes(phase)&&['done','failed'].includes(draft.status)){
    generationPending=false;
    toast(draft.status==='done'?'새 AI 초안이 준비됐어요. 새 검토를 시작할 수 있습니다.':'AI 초안을 다시 만들지 못했어요. 실패 이유를 확인해 주세요.');
  }
}
async function loadCriteria(){criteriaState=await getJson(criteriaUrl);await enrichSourcePages(criteriaState);applyState();}
const originalPaint=paint;
paint=function(){
  originalPaint();
  $('#demo').hidden=true;
  const card=$('#card');
  card.setAttribute('aria-busy',phase==='gen'?'true':'false');
  const empty=$('#card .empty');
  let announcement='';
  if(empty&&phase==='gen'){
    empty.classList.add('generating');
    const analyzing=['queued','running'].includes(criteriaState?.requirements?.status);
    const queued=analyzing?criteriaState?.requirements?.status==='queued':criteriaState?.draft?.status==='queued';
    const title=criteriaSubmitting?'AI 초안 생성 요청 중입니다':analyzing
      ?queued?'1/2 제안요청서 요구사항 분석을 준비하고 있습니다':'1/2 제안요청서 요구사항을 분석하고 있습니다'
      :queued?'2/2 평가항목 초안 생성을 준비하고 있습니다':'2/2 평가항목과 배점 초안을 만들고 있습니다';
    empty.querySelector('h2').textContent=title;
    empty.querySelector('p').textContent=criteriaSubmitting?'요청을 보내고 있습니다. 잠시만 기다려 주세요.':'몇 분 걸릴 수 있습니다. 상태는 자동으로 확인하며, 다른 화면으로 이동해도 작업은 계속됩니다.';
    const refresh=empty.querySelector('[data-act="refresh"]');if(refresh)refresh.disabled=criteriaSubmitting;
    if(!criteriaSubmitting){
      const steps=document.createElement('div');steps.className='ai-progress-steps';steps.setAttribute('aria-hidden','true');
      steps.innerHTML=`<span class="${analyzing?'active':'done'}">1 요구사항 분석</span><span class="${analyzing?'':'active'}">2 평가항목 초안 생성</span>`;
      empty.querySelector('p').after(steps);
    }
    announcement=title;
  }
  if(empty&&!criteriaState?.rfp){empty.querySelector('h2').textContent='제안요청서가 아직 없어요';empty.querySelector('p').textContent='문서 단계에서 제안요청서(HWPX)를 먼저 등록하면 평가표를 만들 수 있어요.';empty.querySelector('.row').innerHTML='<a class="btn primary" href="../../PM-02/design/documents.html">문서 단계로</a>';}
  else if(empty&&['none','genfail','reqwait'].includes(phase)){
    const row=empty.querySelector('.row');
    if(!criteriaState?.ai_ready){const gen=row.querySelector('[data-act="gen"]');if(gen){gen.disabled=true;gen.title='OpenAI 설정(.env의 OPENAI_API_KEY)이 없어 AI 초안을 만들 수 없어요';}}
    if(phase==='genfail'){
      const err=criteriaState?.draft?.error||criteriaState?.requirements?.error;
      empty.querySelector('p').textContent='잠시 뒤 다시 생성해 주세요. 검토 메뉴에서는 기본 서식을 사용할 수 있습니다.';
      if(err){const detail=document.createElement('p');detail.className='muted';detail.textContent='실패 이유: '+err;empty.querySelector('p').after(detail);}
      announcement='AI 초안 생성에 실패했습니다.';
    }else if(phase==='reqwait'){
      const requirements=criteriaState?.requirements||{};
      if(requirements.status==='needs_review'){
        empty.querySelector('h2').textContent='요구사항 명세서를 먼저 검토·확정해 주세요';
        const p=empty.querySelector('p');p.textContent='서술형 요구사항의 원문 근거와 평가 활용 범위를 확인한 뒤 평가표를 생성할 수 있습니다. ';
        const link=document.createElement('a');link.href='/app/dept-admin/PM-02/design/requirements-preview.html?project_id='+encodeURIComponent(Live.pid);link.textContent='명세서 검토하기';p.append(link);
      }else if(requirements.status==='failed'){
        empty.querySelector('h2').textContent='제안요청서 요구사항 분석에 실패했어요';
        empty.querySelector('p').textContent='문서 단계에서 실패 이유를 확인하고 다시 분석해 주세요.';
      }else if(['queued','running'].includes(requirements.status)){
        empty.querySelector('h2').textContent='제안요청서 요구사항을 분석하고 있습니다';
        empty.querySelector('p').textContent='분석이 끝나면 AI 초안을 만들 수 있습니다. 상태는 자동으로 확인합니다.';
        announcement='제안요청서 요구사항을 분석하고 있습니다.';
      }
    }
  }
  if(phase==='ready'&&criteriaState?.draft?.result){const note=$('#card .notebar .note span');if(note)note.innerHTML=`AI 초안이 준비됐습니다. 평가항목과 배점을 검토해 주세요. 출처: <b>${h(criteriaState.draft.result.reference_filename||'요구사항 총괄표')}</b> · 기술 배점 ${h(String(LIMIT))}점`;const strip=$('#card .strip .src');if(strip)strip.textContent=`AI 초안 · ${criteriaState.draft.result.template_source==='request_document'?'제안요청서 평가표를 읽었어요':'요구사항 총괄표로 만들었어요'}`;announcement='AI 초안이 준비됐습니다. 평가항목과 배점을 검토해 주세요.';}
  if(phase==='edit'){const strip=$('#card .strip .src');if(strip)strip.textContent='복사본을 고치는 중이에요 · 근거 쪽은 제안요청서의 쪽 번호예요';}
  if(phase==='locked'&&currentVersion){const bar=$('#card .lockbar .muted');if(bar)bar.textContent=`승인 번호 ${currentVersion.approval_no} · ${(currentVersion.approved_at||'').slice(0,16).replace('T',' ')}`;
    if(currentVersion.frozen){const lb=$('#card .lockbar span:nth-child(2)');if(lb)lb.textContent='확정했어요. 평가 회차가 이 평가표를 쓰고 있어 고칠 수 없어요.';}
    else{const lb=$('#card .lockbar');if(lb&&!lb.querySelector('[data-act="reopen"]')){const b=document.createElement('button');b.type='button';b.className='btn';b.dataset.act='reopen';b.textContent='새 검토 시작(재승인)';lb.appendChild(b);}}}
  if(['edit','locked'].includes(phase)&&criteriaState?.draft?.status==='done'&&criteriaState.draft.result&&
      (phase==='locked'||currentVersion?.draft_result_id!==criteriaState.draft.result._id)){
    const templateReview=phase==='edit'&&!currentVersion?.draft_result_id;
    const bar=document.createElement('div');bar.className='criteria-restart';
    const restart=document.createElement('button');restart.type='button';restart.className='btn primary';restart.dataset.act='new-ai-review';restart.textContent=templateReview?'AI 초안 반영':'AI 초안으로 새 검토 시작';bar.appendChild(restart);
    card.appendChild(bar);
  }
  if(phase==='ready'){
    const foot=card.querySelector('.foot');
    if(foot){const regenerate=document.createElement('button');regenerate.type='button';regenerate.className='btn';regenerate.dataset.act='regenerate';regenerate.textContent=criteriaSubmitting?'생성 요청 중…':'AI 초안 다시 생성';regenerate.disabled=criteriaSubmitting||!criteriaState?.ai_ready;foot.insertBefore(regenerate,foot.querySelector('button'));}
  }
  const mapping=criteriaState?.draft?.result?.requirement_mapping;
  card.querySelector('[data-spec-mapping]')?.remove();
  if(mapping?.length&&['ready','edit','locked'].includes(phase)){
    const panel=document.createElement('details');panel.dataset.specMapping='';panel.style.padding='16px';
    const summary=document.createElement('summary');summary.textContent=`요구사항 ↔ 평가항목 연결 (${mapping.length}건 · 미연결 ${mapping.filter(m=>!m.row_ids.length).length}건)`;panel.append(summary);
    const rows=criteriaState.draft.result.rows||[];
    for(const link of mapping){const p=document.createElement('p');
      const linked=rows.filter(row=>link.row_ids.includes(row.row_id));
      const codes=linked.flatMap(row=>row.requirement_codes||[]);
      p.textContent=`${link.code||link.requirement_id} → ${linked.map(row=>row.evaluation_item).join(', ')||'미연결 · 검토 필요'}: ${link.reason}`;panel.append(p);}
    const note=document.createElement('p');note.textContent='최신 AI 초안 기준의 연결입니다. 검토본의 항목을 수정하면 연결 근거도 함께 확인해 주세요. 연결이 없는 요구사항에는 점수를 자동 추가하지 않습니다.';panel.append(note);card.append(panel);
  }
  const live=$('#criteria-progress');if(live.textContent!==announcement)live.textContent=announcement;
};
await loadCriteria();
Live.capture('[data-act="view-draft"]','click',()=>{
  if(phase==='edit'&&currentVersion)reviewSnapshot={id:currentVersion.id,version:currentVersion.version,tree:T,descriptions:{...descriptionByCode},uid};
  criteriaView='draft';applyState();
});
Live.capture('[data-act="view-current"]','click',async()=>{
  if(openingTemplate||criteriaView==='current'&&currentVersion)return;
  if(!currentVersion){
    if(!criteriaState?.rfp){toast('제안요청서를 먼저 등록해 주세요.');return;}
    openingTemplate=true;
    try{await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts',{method:'POST',json:{source:'template'}});
      criteriaView='current';agreed=false;await loadCriteria();toast('기본 서식 검토본을 열었어요.');}
    finally{openingTemplate=false;}
    return;
  }
  criteriaView='current';applyState();
});
Live.capture('[data-act="gen"]','click',async()=>{
  const force=phase==='genfail',previousPhase=phase;
  criteriaSubmitting=true;phase='gen';paint();
  try{
    criteriaState=await getJson(criteriaUrl+'/jobs',{method:'POST',json:{force}});
    criteriaSubmitting=false;generationPending=true;applyState();
    if(phase==='gen')toast('AI 초안 생성 요청을 받았어요. 진행 상태를 자동으로 확인합니다.');
    else if(phase==='reqwait'){generationPending=false;toast('제안요청서 요구사항 분석이 끝난 뒤 초안을 만들 수 있어요.');}
  }catch(error){criteriaSubmitting=false;phase=previousPhase;paint();throw error;}
});
Live.capture('[data-act="regenerate"]','click',async()=>{
  if(criteriaSubmitting||['queued','running'].includes(criteriaState?.draft?.status))return;
  criteriaSubmitting=true;paint();
  try{
    criteriaState=await getJson(criteriaUrl+'/jobs',{method:'POST',json:{force:true}});
    criteriaSubmitting=false;generationPending=true;applyState();
    toast('AI 초안 재생성을 시작했어요. 현재 평가표는 그대로 유지됩니다.');
  }catch(error){criteriaSubmitting=false;paint();throw error;}
});
function confirmAiReview(){
  pendingNewDraft=true;
  confirmDlg({title:currentVersion?.status==='DRAFT'?'AI 초안을 검토본에 반영할까요?':'AI 초안으로 새 검토를 시작할까요?',body:currentVersion?.status==='DRAFT'?'현재 검토본은 이력에 보관되고 새 AI 초안의 복사본이 열립니다. 저장하지 않은 화면 수정은 사라집니다.':'기존 확정본은 보존되고 새 AI 초안의 검토본이 열립니다. 진행 중인 평가 회차는 기존 확정본을 계속 사용합니다.',ok:'AI 초안 반영'});
}
Live.capture('[data-act="new-ai-review"]','click',confirmAiReview);
Live.capture('[data-act="refresh"]','click',async()=>{await loadCriteria();toast(phase==='gen'?'아직 만드는 중이에요':phase==='locked'&&ack==='wait'?'아직 평가 쪽 수신 확인을 기다리고 있어요':'최신 상태예요');});
Live.capture('[data-act="review"]','click',async()=>{
  if(currentVersion&&['DRAFT','APPROVED'].includes(currentVersion.status)){confirmAiReview();return;}
  await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts',{method:'POST',json:{source:'ai'}});
  agreed=false;criteriaView='current';await loadCriteria();toast('AI 초안을 검토본으로 복사했어요.');
});
Live.capture('[data-act="template"]','click',async()=>{await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts',{method:'POST',json:{source:'template'}});criteriaView='current';await loadCriteria();agreed=false;toast('기본 서식 검토본을 열었어요.');});
Live.capture('[data-act="reopen"]','click',()=>{criteriaView='draft';applyState();toast('초안 생성 단계로 이동했어요. 새 검토에 사용할 초안을 선택해 주세요.');});
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
Live.capture('#dlg-cancel','click',()=>{pendingApprove=false;pendingNewDraft=false;closeAll();});
Live.capture('#dlg-ok','click',async()=>{
  if(pendingNewDraft){
    pendingNewDraft=false;
    await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts',{method:'POST',json:{source:'ai',restart:true}});
    closeAll();agreed=false;reviewSnapshot=null;criteriaView='current';await loadCriteria();toast('새 AI 초안의 검토본을 열었어요.');return;
  }
  if(!pendingApprove)return;pendingApprove=false;
  const result=await getJson('/api/v2/projects/'+encodeURIComponent(Live.pid)+'/criteria-drafts/'+encodeURIComponent(currentVersion.id)+'/approve',{method:'POST',json:{version:currentVersion.version,confirmed:true}});
  closeAll();await loadCriteria();
  const status=result.ack?.status;toast(status==='APPLIED'||status==='DUPLICATE'?'평가표를 확정했고 평가 쪽에서 받았어요':'평가표를 확정했어요. 평가 쪽 수신 상태: '+(status||'대기'));
});
