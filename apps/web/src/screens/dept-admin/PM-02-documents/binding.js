// PM-02 · PRJ-06·07 · DOC-01~06 · PRO-01~03
if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
let vendorRows=[],vendorDelete=null;
async function loadVendors(){const data=await Live.api('PRJ-05',{project_id:Live.pid});vendorRows=data.vendors;S=blankState();S.inUse=['EVALUATING','COMPLETED'].includes(data.project.status);S.v=vendorRows.map(v=>({code:v.display_code,name:v.legal_name,ord:v.sort_order,fx:S.inUse,s:'none',toc:'none',entries:[],err:'',revs:[]}));paint();}
await loadVendors();
Live.capture('#f-inl','submit',async()=>{await Live.api('PRJ-06',{project_id:Live.pid,display_code:nextCode(),legal_name:$('#i-name').value.trim(),sort_order:S.v.length+1});adding=false;await loadVendors();toast('업체를 등록했어요');});
Live.capture('#f-add','submit',async()=>{const vendor=editV?vendorRows[S.v.indexOf(editV)]:null;await Live.api('PRJ-06',{project_id:Live.pid,...(vendor?{vendor_id:vendor.id,version:vendor.version}:{}),display_code:$('#a-code').value.trim(),legal_name:$('#a-name').value.trim(),sort_order:Number($('#a-ord').value)});closeLayer($('#add'));await loadVendors();toast('업체 정보를 저장했어요');});
Live.capture('[data-vdel],#a-del','click',(_e,el)=>{vendorDelete=el.id==='a-del'?vendorRows[S.v.indexOf(editV)]:vendorRows[Number(el.dataset.vdel)];confirmDlg({title:'업체를 삭제할까요?',body:'평가에 사용 중인 업체는 삭제할 수 없습니다.',ok:'삭제',danger:true});});
Live.capture('#dlg-ok','click',async()=>{if(!vendorDelete)return;await Live.api('PRJ-07',{project_id:Live.pid,vendor_id:vendorDelete.id,version:vendorDelete.version});vendorDelete=null;closeAll();await loadVendors();toast('업체를 삭제했어요');});
// PM-02 · DOC-01/02/05: integrated HWPX parsing and SQLite storage.
const projectUrl='/api/v2/projects/'+encodeURIComponent(Live.pid);
const rfpUrl=projectUrl+'/rfp';
let rfpUploads=[],rfpArchived=[],proposalUploads=[],requirementState=null,requirementTimer=null;
const fmtSize=b=>(b/1048576).toFixed(1)+'MB',fmtAt=t=>new Date(t).toLocaleString('ko-KR');
async function getJson(url,options){const response=await fetch(url,{credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web',...(options?.json!==undefined?{'Content-Type':'application/json'}:{})},method:options?.method||'GET',body:options?.json!==undefined?JSON.stringify(options.json):options?.body});const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error?.message||'요청을 처리하지 못했습니다.');return body.data;}
async function downloadUrl(url,filename){const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw Error('파일을 내려받지 못했습니다.');const object=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=object;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(object),1000);}
const REQ={none:['','요약 전','제안요청서는 저장됐습니다. 요구사항 요약을 시작하지 못했습니다.'],queued:['info','대기','제안요청서는 저장됐습니다. 요구사항 요약을 기다리고 있습니다.'],running:['info','처리 중','제안요청서는 저장됐습니다. 요구사항을 요약하고 있습니다.'],failed:['danger','실패','제안요청서는 저장됐지만 요구사항 요약에 실패했습니다. API 키와 통신 상태를 확인한 뒤 다시 시도해 주세요.'],done:['success','완료','제안요청서 저장과 요구사항 요약이 끝났습니다.']};
const originalPaint=paint;
paint=()=>{
  originalPaint();
  if(S.rfp.revs.length){
    $('#rfp .fa [data-retry="rfp"]')?.remove();
    const badge=$('#rfp .rfp-head .badge');
    const st=REQ[requirementState?.status]||REQ.none;
    if(badge){badge.className='badge '+st[0];badge.textContent=requirementState?.status==='done'?'✓ 완료':requirementState?.status==='failed'?'! 요약 실패':'⟳ 요약 중';}
    const message=$('#rfp .msg');
    if(message&&requirementState?.status==='failed'){
      message.className='msg bad';message.textContent=st[2]+(requirementState.error?' '+requirementState.error:'');
    }
  }
  const status=$('#m-xr');
  if(status&&S.rfp.revs.length){const st=REQ[requirementState?.status]||REQ.none;status.innerHTML=`<div class="mrow"><span class="badge ${st[0]}">${st[1]}</span><span class="tx">${st[2]}${requirementState?.error?' · '+h(requirementState.error):''}</span>${['none','failed'].includes(requirementState?.status||'none')?'<button class="tl pri" type="button" data-retry="rfp">'+(requirementState?.status==='failed'?'다시 시도':'요구사항 요약')+'</button>':''}<button class="tl" type="button" data-refresh>새로고침</button></div>`;}
  if(S.rfp.revs.length){
    const actions=$('#rfp .fa');
    if(actions){
      const ready=requirementState?.status==='done';
      const requirements=document.createElement('button');
      requirements.type='button';requirements.className='btn';requirements.dataset.previewRequirements='';
      requirements.textContent='요구사항 요약';requirements.disabled=!ready;
      if(!ready)requirements.title='요구사항 요약 처리가 끝나면 사용할 수 있습니다.';
      actions.appendChild(requirements);
      const preview=document.createElement('button');
      preview.type='button';preview.className='btn';preview.dataset.previewRfp='';
      preview.textContent='제안요청서 확인';preview.disabled=!ready;
      if(!ready)preview.title='요구사항 요약 처리가 끝나면 사용할 수 있습니다.';
      actions.appendChild(preview);
    }
    const view=$('[data-view="rfp"]');if(view){view.textContent='제안요청서 확인';view.disabled=requirementState?.status!=='done';}
    const replace=$('#rfp [data-up="rfp"]');if(replace)replace.textContent='파일 재등록';
  }
  // The prototype's TOC confirmation and synthetic state controls are not persisted.
  $('#demo').hidden=true;
};
function rfpRevision(n){return rfpUploads.find(u=>u.revision===n)}
async function loadRfp(){
  const data=await getJson(rfpUrl);
  rfpUploads=data.uploads;rfpArchived=data.archived||[];
  S.rfp={s:rfpUploads.length?'run':'none',toc:'none',entries:[],err:'',revs:rfpUploads.map(u=>
    rv(u.revision,u.filename,fmtAt(u.uploaded_at),fmtSize(u.byte_size)))};
  requirementState=rfpUploads.length?await getJson(projectUrl+'/requirements').catch(error=>({status:'failed',error:'처리 상태를 확인하지 못했습니다. 통신 상태를 확인하고 새로고침해 주세요. '+error.message})):null;
  if(rfpUploads.length)S.rfp.s=requirementState?.status==='done'?'done':requirementState?.status==='failed'?'fail':'run';
  paint();
  clearTimeout(requirementTimer);
  if(['queued','running'].includes(requirementState?.status))requirementTimer=setTimeout(()=>loadRfp().catch(error=>Live.message(error.message)),5000);
}
// PRO-01~03: 업체별 제안서. 업체 줄(S.v[i]) ↔ vendorRows[i] ↔ 문서 DB 업로드(vendor_id).
function proposalsOf(i){return proposalUploads.filter(u=>u.vendor_id===vendorRows[i].id&&u.status!=='ARCHIVED');}
async function loadProposals(){
  proposalUploads=(await getJson(projectUrl+'/proposals')).uploads;
  S.v.forEach((v,i)=>{const list=proposalsOf(i);v.revs=list.map(u=>rv(u.upload_revision,u.filename,fmtAt(u.created_at),fmtSize(u.byte_size||0),u.page_count?`${u.format} · ${u.page_count}쪽`:u.format));v.s=list.length?'done':'none';v.err='';});
  paint();
}
const originalLoadVendors=loadVendors;
loadVendors=async()=>{await originalLoadVendors();await loadRfp();await loadProposals();};
await loadRfp();await loadProposals();
Live.capture('[data-up="rfp"]','click',()=>{target='rfp';$('#file').accept='.hwpx';$('#file').value='';$('#file').click();});
Live.capture('[data-up]:not([data-up="rfp"])','click',(_e,el)=>{target=el.dataset.up;$('#file').accept='.hwpx,.hwp,.pdf,.pptx';$('#file').value='';$('#file').click();});
async function uploadRfp(file){
  if(!file)return;
  if(!file.name.toLowerCase().endsWith('.hwpx'))throw Error('HWPX 파일만 올릴 수 있습니다.');
  if(file.size>50*1024*1024)throw Error('50MB 이하의 파일을 올려 주세요.');
  const form=new FormData();form.append('file',file);
  const previousRequirementState=requirementState;
  requirementState=null;
  S.rfp.s='run';S.rfp.err='';paint();
  try{
    const response=await fetch(rfpUrl,{method:'POST',credentials:'same-origin',
      headers:{'X-Simsa-Client':'v2-web'},body:form});
    const body=await response.json();
    if(!response.ok)throw Error(body.error?.message||'문서를 저장하지 못했습니다.');
    await loadRfp();toast('제안요청서를 저장하고 요구사항 요약을 시작했어요.');
  }catch(error){requirementState=previousRequirementState;S.rfp.s=rfpUploads.length?(requirementState?.status==='done'?'done':'fail'):'none';S.rfp.err=error.message;paint();throw error;}
}
async function uploadProposal(index,file){
  if(!file)return;const vendor=vendorRows[index],row=S.v[index];
  if(!/\.(hwpx|hwp|pdf|pptx)$/i.test(file.name))throw Error('HWPX·HWP·PDF·PPTX 파일만 올릴 수 있습니다.');
  if(file.size>50*1024*1024)throw Error('50MB 이하의 파일을 올려 주세요.');
  const form=new FormData();form.append('file',file);
  row.s='run';row.err='';paint();
  try{
    const response=await fetch(projectUrl+'/vendors/'+encodeURIComponent(vendor.id)+'/proposals',{method:'POST',credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web'},body:form});
    const body=await response.json();
    if(!response.ok)throw Error(body.error?.message||'제안서를 저장하지 못했습니다.');
    await loadProposals();
    const ack=body.data.ack?.status;
    toast(`${row.code} 제안서 v${body.data.upload_revision}을 저장했어요 · ${body.data.pages}쪽 · 평가 연결 ${ack==='APPLIED'||ack==='DUPLICATE'?'완료':ack||'대기'}`);
  }catch(error){row.s=proposalsOf(index).length?'done':'none';row.err=error.message;paint();throw error;}
}
Live.capture('#file','change',event=>target==='rfp'?uploadRfp(event.target.files?.[0]):uploadProposal(Number(target),event.target.files?.[0]));
Live.capture('[data-drop="rfp"]','drop',event=>{const file=event.dataTransfer?.files?.[0];if(!file)return;return uploadRfp(file);});
Live.capture('[data-drop]:not([data-drop="rfp"])','drop',(event,el)=>{const file=event.dataTransfer?.files?.[0];if(!file)return;return uploadProposal(Number(el.dataset.drop),file);});
Live.capture('[data-hist]','click',(_e,el)=>openHist(el.dataset.hist));
async function downloadRfp(revision){
  const upload=rfpRevision(revision);if(!upload)throw Error('등록된 문서가 없습니다.');
  await downloadUrl(rfpUrl+'/'+revision+'/download',upload.filename);
}
async function downloadProposal(index,revision){
  const list=proposalsOf(index),upload=revision?list.find(u=>u.upload_revision===revision):list[0];
  if(!upload)throw Error('등록된 제안서가 없습니다.');
  await downloadUrl(projectUrl+'/proposals/'+encodeURIComponent(upload.id)+'/download',upload.filename);
}
Live.capture('[data-dl]','click',(_e,el)=>el.dataset.dl==='rfp'?downloadRfp(rfpUploads[0]?.revision):downloadProposal(Number(el.dataset.dl)));
Live.capture('[data-rv]','click',(_event,button)=>{
  const revision=Number(button.closest('li')?.querySelector('.vn')?.textContent.replace('v',''));
  return histObj===S.rfp?downloadRfp(revision):downloadProposal(S.v.indexOf(histObj),revision);
});
function showParsed(title,data){
  $('#toc-t').textContent=title;
  $('#toc-note').textContent='저장된 문단과 표의 텍스트입니다. 정확한 서식은 원본 파일로 확인하세요.'+(data.warnings?.length?` · 파서 경고 ${data.warnings.length}건`:'');
  $('#toc-ok').hidden=true;$('#toc-left').textContent='';
  $('#toc-list').tabIndex=0;
  $('#toc-list').replaceChildren(...data.blocks.map(block=>{
    const item=document.createElement('li');
    item.textContent=(block.pages?.length?`[${block.pages[0]}쪽] `:'')+(block.type==='table'
      ?block.rows.map(row=>row.map(cell=>cell.text).join(' | ')).join('\n')
      :block.text);
    item.style.whiteSpace='pre-wrap';return item;
  }));
  openLayer($('#toc'),'#toc-list');
}
async function showParsedRfp(){
  const upload=rfpUploads[0];if(!upload)throw Error('등록된 문서가 없습니다.');
  showParsed('제안요청서 파싱 원문',await getJson(rfpUrl+'/'+upload.revision+'/source'));
}
async function showParsedProposal(index){
  const upload=proposalsOf(index)[0];if(!upload)throw Error('등록된 제안서가 없습니다.');
  showParsed(`${S.v[index].code} 제안서 파싱 원문 · ${upload.filename}`,await getJson(projectUrl+'/proposals/'+encodeURIComponent(upload.id)+'/source'));
}
Live.capture('[data-toc="rfp"]','click',showParsedRfp);
function openRfpPreview(){
  if(requirementState?.status!=='done')return;
  location.href='/app/dept-admin/PM-02/design/rfp-preview.html?project_id='+encodeURIComponent(Live.pid);
}
Live.capture('[data-preview-rfp],[data-view="rfp"]','click',openRfpPreview);
Live.capture('[data-preview-requirements]','click',()=>{
  location.href='/app/dept-admin/PM-02/design/requirements-preview.html?project_id='+encodeURIComponent(Live.pid);
});
Live.capture('[data-toc]:not([data-toc="rfp"]),[data-view]:not([data-view="rfp"])','click',(_e,el)=>showParsedProposal(Number(el.dataset.toc??el.dataset.view)));
// DOC-06·PRO-03: 보관 처리(목록 제외). 원본·스냅샷·과거 평가 참조는 서버가 보존한다.
function archiveDialog(key){
  const isRfp=key==='rfp',index=Number(key);
  if(!isRfp&&!proposalsOf(index).length)throw Error('등록된 제안서가 없습니다.');
  askReason({title:isRfp?'제안요청서 등록을 삭제할까요?':`${S.v[index].code} 제안서를 삭제할까요?`,body:'목록에서 빠지고 이력은 감사 기록에 남아요. 이미 시작한 평가 자료는 바뀌지 않아요.',block:'',onOk:async()=>{
    const reason=$('#rdlg-r').value.trim();
    try{
      if(isRfp)await getJson(rfpUrl+'/'+rfpUploads[0].revision,{method:'DELETE',json:{reason}});
      else await getJson(projectUrl+'/proposals/'+encodeURIComponent(proposalsOf(index)[0].id),{method:'DELETE',json:{reason}});
      closeLayer($('#hist'));await loadRfp();await loadProposals();toast('목록에서 뺐어요 · 원본과 이력은 보존돼요');
    }catch(error){Live.message(error.message);}
  }});
}
Live.capture('[data-del]','click',(_e,el)=>archiveDialog(el.dataset.del));
Live.capture('#hist-del','click',()=>archiveDialog(histObj===S.rfp?'rfp':String(S.v.indexOf(histObj))));
// DOC-03·04: 요구사항 추출 상태·재시도. 추출은 AI(OpenAI) 설정이 있을 때 동작한다.
Live.capture('[data-refresh]','click',async()=>{await loadRfp();toast(requirementState?.status==='done'?'최신 상태예요':'상태를 새로 읽었어요');});
Live.capture('[data-retry]','click',async()=>{await getJson(projectUrl+'/requirements/jobs',{method:'POST',json:{force:requirementState?.status==='failed'}});await loadRfp();toast('요구사항 요약을 시작했어요. 몇 분 걸릴 수 있어요');});
Live.capture('#toc-ok','click',()=>{throw Error('목차 수정은 아직 연결되지 않았습니다. 저장된 파싱 원문을 확인하세요.');});
