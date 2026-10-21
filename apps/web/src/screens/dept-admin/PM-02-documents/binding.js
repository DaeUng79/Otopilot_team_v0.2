// PM-02 · PRJ-06·07 · DOC-01~06 · PRO-01~03
if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
let vendorRows=[],vendorDelete=null;
async function loadVendors(){const data=await Live.api('PRJ-05',{project_id:Live.pid});vendorRows=data.vendors;S=blankState();S.inUse=['EVALUATING','COMPLETED'].includes(data.project.status);S.v=vendorRows.map(v=>({code:v.display_code,name:v.legal_name,ord:v.sort_order,fx:S.inUse,s:'none',toc:'none',entries:[],err:'',revs:[]}));paint();}
await loadVendors();
Live.capture('#f-inl','submit',async()=>{const legalName=$('#i-name').value.trim();if(!legalName){addVal='';addErr='법인명을 입력해주세요';paint();$('#i-name').focus();return;}await Live.api('PRJ-06',{project_id:Live.pid,display_code:nextCode(),legal_name:legalName,sort_order:S.v.length+1});adding=false;await loadVendors();toast('업체를 등록했어요');});
$('#a-name').addEventListener('input',()=>{$('#a-name-e').hidden=true;$('#a-name').removeAttribute('aria-invalid');});
Live.capture('#f-add','submit',async()=>{const legalName=$('#a-name').value.trim();if(!legalName){$('#a-name-e').textContent='법인명을 입력해주세요';$('#a-name-e').hidden=false;$('#a-name').setAttribute('aria-invalid','true');$('#a-name').focus();return;}const vendor=editV?vendorRows[S.v.indexOf(editV)]:null;await Live.api('PRJ-06',{project_id:Live.pid,...(vendor?{vendor_id:vendor.id,version:vendor.version}:{}),display_code:$('#a-code').value.trim(),legal_name:legalName,sort_order:Number($('#a-ord').value)});closeLayer($('#add'));await loadVendors();toast('업체 정보를 저장했어요');});
Live.capture('[data-vdel],#a-del','click',(_e,el)=>{vendorDelete=el.id==='a-del'?vendorRows[S.v.indexOf(editV)]:vendorRows[Number(el.dataset.vdel)];confirmDlg({title:'업체와 제안서를 삭제할까요?',body:'이 업체의 등록 정보, 제안서 파일과 분석 결과가 모두 영구 삭제됩니다. 평가가 시작된 사업에서는 삭제할 수 없습니다.',ok:'영구 삭제',danger:true});});
Live.capture('#dlg-ok','click',async()=>{if(!vendorDelete)return;await Live.api('PRJ-07',{project_id:Live.pid,vendor_id:vendorDelete.id,version:vendorDelete.version});vendorDelete=null;closeAll();await loadVendors();toast('업체와 관련 자료를 삭제했어요');});
// PM-02 · DOC-01/02/05: integrated HWPX parsing and SQLite storage.
const projectUrl='/api/v2/projects/'+encodeURIComponent(Live.pid);
const rfpUrl=projectUrl+'/rfp';
let rfpUploads=[],rfpArchived=[],proposalUploads=[],requirementState=null,requirementTimer=null,comparisonData=null;
let analysisJobs={},analysisTimer=null,comparisonInitialized=false;
const proposalUploadState=new Map();
let rfpUploadState=null;
const autoAnalysisKey='pm02-auto-analysis:'+Live.pid;
const pendingAutoAnalysis=new Set(JSON.parse(sessionStorage.getItem(autoAnalysisKey)||'[]'));
const autoAnalysisInFlight=new Set();
function savePendingAnalysis(){sessionStorage.setItem(autoAnalysisKey,JSON.stringify([...pendingAutoAnalysis]));}
const fmtSize=b=>(b/1048576).toFixed(1)+'MB',fmtAt=t=>new Date(t).toLocaleString('ko-KR');
async function getJson(url,options){const response=await fetch(url,{credentials:'same-origin',headers:{'X-Simsa-Client':'v2-web',...(options?.json!==undefined?{'Content-Type':'application/json'}:{})},method:options?.method||'GET',body:options?.json!==undefined?JSON.stringify(options.json):options?.body});const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.error?.message||'요청을 처리하지 못했습니다.');return body.data;}
async function downloadUrl(url,filename){const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw Error('파일을 내려받지 못했습니다.');const object=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=object;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(object),1000);}
const REQ={none:['','요약 전','제안요청서는 저장됐습니다. 요구사항 요약을 시작하지 못했습니다.'],queued:['info','분석 대기','요구사항 분석을 기다리고 있습니다. 완료될 때까지 자동으로 확인합니다.'],running:['info','분석 중','요구사항을 분석 중입니다. 완료될 때까지 자동으로 확인합니다.'],failed:['danger','실패','제안요청서는 저장됐지만 요구사항 요약에 실패했습니다. API 키와 통신 상태를 확인한 뒤 다시 시도해 주세요.'],done:['success','완료','제안요청서 저장과 요구사항 요약이 끝났습니다.']};
function extractionRows(){
  return sorted().map(view=>{
    const vendor=vendorRows[S.v.indexOf(view)];
    const upload=proposalUploads.filter(p=>p.vendor_id===vendor?.id&&p.status==='READY')
      .sort((a,b)=>b.upload_revision-a.upload_revision)[0];
    const uploaded=Boolean(upload);
    const column=comparisonData?.proposals?.find(p=>p.vendor_id===vendor?.id);
    const job=analysisJobs[upload?.id]||{status:'idle'};
    let label='제안서 미등록',detail='제안서를 등록하면 분석 상태를 볼 수 있습니다.',tone='';
    if(uploaded){
      label='2차 분석 전';detail='제안서는 등록됐습니다. 2차 분석 결과가 없습니다.';
      if(pendingAutoAnalysis.has(upload.id)){
        label='분석 대기';detail='제안요청서 요구사항 요약이 끝나면 자동으로 분석을 시작합니다.';tone='info';
      }
      if(column?.status==='complete'){
        label='분석 완료';detail=`확인 ${column.confirmed}건 · 확인되지 않음 ${column.unconfirmed}건`;tone='success';
      }else if(column?.status==='partial'){
        label='분석 중';detail=`${column.processed}/${column.total}건 처리`;tone='info';
      }
    }
    if(job.status==='failed'){
      label='분석 실패';tone='danger';detail=job.error||'다시 시도해 주세요.';
    }
    const busy=['queued','running'].includes(job.status);
    const action=uploaded&&requirementState?.status==='done'&&column?.status!=='complete'
      ?`<button class="tl pri" type="button" data-analyze-upload="${h(upload.id)}" ${busy?'disabled':''}>${busy?'분석 중…':'분석하기'}</button>`:'';
    return `<div class="mrow extraction-row"><strong class="extraction-name">${h(view.code)}${view.name?` <small>${h(view.name)}</small>`:''}</strong><span class="badge ${tone}">${label}</span><span class="tx">${h(detail)}</span>${action}</div>`;
  }).join('');
}
const originalPaint=paint;
function showRfpUpload(){
  if(!rfpUploadState)return;
  const info=rfpUploadState;
  const box=document.createElement('div');box.className='filebox rfp-uploading';
  box.setAttribute('aria-busy','true');
  const name=document.createElement('div');name.className='fn';name.textContent=info.filename;
  const state=document.createElement('div');state.className='upload-state';
  state.setAttribute('role','status');state.setAttribute('aria-live','polite');
  state.textContent=info.processing?'파일 전송 완료 · 서버에서 문서 등록 중':info.percent===null?'파일 전송 중':`파일 전송 중 · ${info.percent}%`;
  const meter=document.createElement('div');meter.className='upload-meter';
  meter.setAttribute('role','progressbar');meter.setAttribute('aria-label','제안요청서 파일 전송');
  if(info.percent===null)meter.classList.add('indeterminate');
  else{
    meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax','100');
    meter.setAttribute('aria-valuenow',String(info.percent));
  }
  const fill=document.createElement('i');fill.style.width=info.percent===null?'35%':`${info.percent}%`;
  meter.append(fill);box.append(name,state,meter);
  if(rfpUploads.length){
    const note=document.createElement('div');note.className='msg';
    note.textContent='기존 파일은 새 등록이 완료될 때까지 유지됩니다.';box.append(note);
  }
  $('#rfp').replaceChildren(box);
}
function showProposalUpload(index){
  const info=proposalUploadState.get(vendorRows[index]?.id);
  const row=$(`#rows [data-drop="${index}"]`);
  if(!info||!row)return;
  row.classList.add('uploading');row.classList.remove('empty','drop');row.setAttribute('aria-busy','true');
  const name=document.createElement('b');name.textContent=info.filename;name.title=info.filename;
  const state=document.createElement('span');state.className='upload-state';
  state.textContent=info.processing?'파일 전송 완료 · 등록 정보 확인 중':info.percent===null?'파일 전송 중':`파일 전송 중 · ${info.percent}%`;
  const meter=document.createElement('div');meter.className='upload-meter';meter.setAttribute('role','progressbar');
  meter.setAttribute('aria-label',`${S.v[index].code} 제안서 파일 전송`);
  if(info.percent!==null){meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax','100');meter.setAttribute('aria-valuenow',String(info.percent));}
  const fill=document.createElement('i');fill.style.width=info.percent===null?'35%':`${info.percent}%`;
  if(info.percent===null)meter.classList.add('indeterminate');
  meter.append(fill);row.querySelector('.vi').replaceChildren(name,state,meter);
  row.querySelector('.vs').innerHTML='<span class="badge info">⟳ 등록 중</span>';
  row.querySelectorAll('.va button,.vx button').forEach(button=>button.disabled=true);
}
paint=()=>{
  originalPaint();
  if(S.rfp.revs.length){
    $('#rfp .fa [data-retry="rfp"]')?.remove();
    const badge=$('#rfp .rfp-head .badge');
    const st=REQ[requirementState?.status]||REQ.none;
    if(badge){badge.className='badge '+st[0];badge.textContent=requirementState?.status==='done'?'✓ 완료':requirementState?.status==='failed'?'! 요약 실패':'⟳ 분석 중';}
    const message=$('#rfp .msg');
    if(message&&requirementState?.status==='failed'){
      message.className='msg bad';message.textContent=st[2]+(requirementState.error?' '+requirementState.error:'');
    }
  }
  const status=$('#m-xr');
  if(status&&S.rfp.revs.length){const st=REQ[requirementState?.status]||REQ.none;
    status.innerHTML=`<div class="mrow extraction-row"><strong class="extraction-name">제안요청서</strong><span class="badge ${st[0]}">${st[1]}</span><span class="tx ${['queued','running'].includes(requirementState?.status)?'analysis-progress':''}" role="status" aria-live="polite">${st[2]}${requirementState?.error?' · '+h(requirementState.error):''}</span>${['none','failed'].includes(requirementState?.status||'none')?'<button class="tl pri" type="button" data-retry="rfp">'+(requirementState?.status==='failed'?'다시 시도':'요구사항 요약')+'</button>':''}${requirementState?.status==='done'?'<button class="tl" type="button" data-reextract>요구사항 재 추출</button>':''}</div>`+extractionRows();}
  if(S.rfp.revs.length){
    const actions=$('#rfp .fa');
    if(actions){
      const ready=requirementState?.status==='done';
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
  showRfpUpload();
  S.v.forEach((_vendor,index)=>showProposalUpload(index));
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
  if(comparisonInitialized&&requirementState?.status==='done')void flushAutoAnalysis();
  clearTimeout(requirementTimer);
  if(['queued','running'].includes(requirementState?.status))requirementTimer=setTimeout(async()=>{
    try{
      await loadRfp();
      if(comparisonInitialized&&requirementState?.status==='done')await loadComparison();
    }catch(error){Live.message(error.message);}
  },5000);
}
// PRO-01~03: 업체별 제안서. 업체 줄(S.v[i]) ↔ vendorRows[i] ↔ 문서 DB 업로드(vendor_id).
function proposalsOf(i){return proposalUploads.filter(u=>u.vendor_id===vendorRows[i].id&&u.status!=='ARCHIVED');}
async function loadProposals(){
  proposalUploads=(await getJson(projectUrl+'/proposals')).uploads;
  S.v.forEach((v,i)=>{const list=proposalsOf(i);v.revs=list.map(u=>rv(u.upload_revision,u.filename,fmtAt(u.created_at),fmtSize(u.byte_size||0),u.page_count?`${u.format} · ${u.page_count}쪽`:u.format));v.s=list.length?'done':'none';v.err='';});
  paint();
}
const originalLoadVendors=loadVendors;
loadVendors=async()=>{await originalLoadVendors();await loadRfp();await loadProposals();await loadComparison();};
await loadRfp();await loadProposals();
Live.capture('[data-up="rfp"]','click',()=>{target='rfp';$('#file').accept='.hwpx';$('#file').value='';$('#file').click();});
Live.capture('[data-up]:not([data-up="rfp"])','click',(_e,el)=>{target=el.dataset.up;$('#file').accept='.hwpx,.pdf,.pptx';$('#file').value='';$('#file').click();});
async function uploadRfp(file){
  if(!file)return;
  if(!file.name.toLowerCase().endsWith('.hwpx'))throw Error('HWPX 파일만 올릴 수 있습니다.');
  if(file.size>50*1024*1024)throw Error('50MB 이하의 파일을 올려 주세요.');
  if(rfpUploadState)throw Error('제안요청서를 등록하고 있습니다. 완료된 뒤 다시 시도해 주세요.');
  const form=new FormData();form.append('file',file);
  const previousRequirementState=requirementState;
  rfpUploadState={filename:file.name,percent:null,processing:false};
  requirementState=null;
  S.rfp.s='run';S.rfp.err='';paint();
  try{
    // XHR reports transferred bytes. Server parsing begins after the transfer reaches 100%.
    await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open('POST',rfpUrl);xhr.withCredentials=true;
      xhr.setRequestHeader('X-Simsa-Client','v2-web');
      xhr.setRequestHeader('X-Simsa-Role','DEPARTMENT_ADMIN');
      xhr.upload.onprogress=event=>{
        if(!event.lengthComputable||!rfpUploadState)return;
        rfpUploadState.percent=Math.min(100,Math.round(event.loaded/event.total*100));showRfpUpload();
      };
      xhr.upload.onload=()=>{
        if(!rfpUploadState)return;
        rfpUploadState.percent=100;rfpUploadState.processing=true;showRfpUpload();
      };
      xhr.onload=()=>{
        let body;try{body=JSON.parse(xhr.responseText);}catch{body={};}
        if(xhr.status<200||xhr.status>=300){reject(Error(body.error?.message||'문서를 저장하지 못했습니다.'));return;}
        resolve(body);
      };
      xhr.onerror=()=>reject(Error('파일을 전송하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.'));
      xhr.onabort=()=>reject(Error('파일 전송이 중단됐습니다.'));
      xhr.send(form);
    });
    comparisonData=null;await loadRfp();await loadComparison();
    rfpUploadState=null;paint();
    toast('제안요청서를 저장하고 요구사항 요약을 시작했어요.');
  }catch(error){rfpUploadState=null;requirementState=previousRequirementState;S.rfp.s=rfpUploads.length?(requirementState?.status==='done'?'done':'fail'):'none';S.rfp.err=error.message;paint();throw error;}
}
async function uploadProposal(index,file){
  if(!file)return;const vendor=vendorRows[index],row=S.v[index];
  if(/\.hwp$/i.test(file.name))throw Error('HWP 파일은 등록할 수 없습니다. HWPX·PDF·PPTX 파일을 선택해 주세요.');
  if(!/\.(hwpx|pdf|pptx)$/i.test(file.name))throw Error('HWPX·PDF·PPTX 파일만 올릴 수 있습니다.');
  if(file.size>50*1024*1024)throw Error('50MB 이하의 파일을 올려 주세요.');
  if(proposalUploadState.has(vendor.id))throw Error(`${row.code} 제안서를 등록하고 있습니다. 완료된 뒤 다시 시도해 주세요.`);
  const form=new FormData();form.append('file',file);
  proposalUploadState.set(vendor.id,{filename:file.name,percent:null,processing:false});
  row.s='run';row.err='';paint();
  try{
    // XHR exposes the bytes sent, so a large file can show real transfer progress.
    const body=await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open('POST',projectUrl+'/vendors/'+encodeURIComponent(vendor.id)+'/proposals');
      xhr.withCredentials=true;xhr.setRequestHeader('X-Simsa-Client','v2-web');
      xhr.setRequestHeader('X-Simsa-Role','DEPARTMENT_ADMIN');
      xhr.upload.onprogress=event=>{
        if(!event.lengthComputable)return;
        const info=proposalUploadState.get(vendor.id);if(!info)return;
        info.percent=Math.min(100,Math.round(event.loaded/event.total*100));showProposalUpload(index);
      };
      xhr.upload.onload=()=>{
        const info=proposalUploadState.get(vendor.id);if(!info)return;
        info.percent=100;info.processing=true;showProposalUpload(index);
      };
      xhr.onload=()=>{
        let result;try{result=JSON.parse(xhr.responseText);}catch{result={};}
        if(xhr.status<200||xhr.status>=300){reject(Error(result.error?.message||'제안서를 저장하지 못했습니다.'));return;}
        resolve(result);
      };
      xhr.onerror=()=>reject(Error('파일을 전송하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.'));
      xhr.onabort=()=>reject(Error('파일 전송이 중단됐습니다.'));
      xhr.send(form);
    });
    comparisonData=null;await loadProposals();await loadComparison();
    proposalUploadState.delete(vendor.id);paint();
    const ack=body.data.ack?.status;
    toast(`${row.code} 제안서 v${body.data.upload_revision}을 저장했어요 · ${body.data.pages}쪽 · 평가 연결 ${ack==='APPLIED'||ack==='DUPLICATE'?'완료':ack||'대기'}`);
  }catch(error){proposalUploadState.delete(vendor.id);row.s=proposalsOf(index).length?'done':'none';row.err=error.message;paint();throw error;}
  const upload=proposalsOf(index)[0];
  if(upload?.status==='READY'){
    pendingAutoAnalysis.add(upload.id);savePendingAnalysis();paint();
    if(requirementState?.status==='done')await flushAutoAnalysis();
    else toast(`${row.code} 제안서는 저장됐어요. 제안요청서 요약이 끝나면 자동 분석을 시작합니다.`);
  }
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
function openProposalPreview(index,revision){
  const list=proposalsOf(index),upload=revision?list.find(u=>u.upload_revision===revision):list[0];
  if(!upload)throw Error('등록된 제안서가 없습니다.');
  location.href='/app/dept-admin/PM-02/design/proposal-preview.html?project_id='
    +encodeURIComponent(Live.pid)+'&upload_id='+encodeURIComponent(upload.id);
}
Live.capture('[data-dl]','click',(_e,el)=>el.dataset.dl==='rfp'?downloadRfp(rfpUploads[0]?.revision):downloadProposal(Number(el.dataset.dl)));
Live.capture('[data-rv]','click',(_event,button)=>{
  const revision=Number(button.closest('li')?.querySelector('.vn')?.textContent.replace('v',''));
  return histObj===S.rfp?downloadRfp(revision):openProposalPreview(S.v.indexOf(histObj),revision);
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
  showParsed('제안요청서 파싱 결과 확인',await getJson(rfpUrl+'/'+upload.revision+'/source'));
}
async function showParsedProposal(index){
  const upload=proposalsOf(index)[0];if(!upload)throw Error('등록된 제안서가 없습니다.');
  showParsed(`${S.v[index].code} 제안서 파싱 결과 확인 · ${upload.filename}`,await getJson(projectUrl+'/proposals/'+encodeURIComponent(upload.id)+'/source'));
}
Live.capture('[data-toc="rfp"]','click',showParsedRfp);
function openRfpPreview(){
  if(requirementState?.status!=='done')return;
  location.href='/app/dept-admin/PM-02/design/rfp-preview.html?project_id='+encodeURIComponent(Live.pid);
}
Live.capture('[data-preview-rfp],[data-view="rfp"]','click',openRfpPreview);
Live.capture('[data-toc]:not([data-toc="rfp"])','click',(_e,el)=>showParsedProposal(Number(el.dataset.toc)));
Live.capture('[data-view]:not([data-view="rfp"])','click',(_e,el)=>openProposalPreview(Number(el.dataset.view)));
// DOC-06·PRO-03: 선택한 등록과 연결된 파일·분석 데이터를 영구 삭제한다.
function archiveDialog(key){
  const isRfp=key==='rfp',index=Number(key);
  if(!isRfp&&!proposalsOf(index).length)throw Error('등록된 제안서가 없습니다.');
  askReason({title:isRfp?'제안요청서를 영구 삭제할까요?':`${S.v[index].code} 제안서를 영구 삭제할까요?`,body:'파일과 연결된 분석 데이터가 삭제되며 복구할 수 없습니다. 평가가 시작된 사업의 문서는 삭제할 수 없습니다.',block:S.inUse?'평가가 시작된 사업의 문서는 삭제할 수 없습니다.':'',requireReason:false,onOk:async()=>{
    try{
      if(isRfp)await getJson(rfpUrl+'/'+rfpUploads[0].revision,{method:'DELETE'});
      else{
        const uploadId=proposalsOf(index)[0].id;
        await getJson(projectUrl+'/proposals/'+encodeURIComponent(uploadId),{method:'DELETE'});
        pendingAutoAnalysis.delete(uploadId);savePendingAnalysis();
      }
      comparisonData=null;$('#comparison-tools').hidden=true;$('#comparison-wrap').hidden=true;
      $('#business-panel').hidden=true;
      comparisonStatus.textContent='자료를 다시 확인하고 있습니다.';
      closeLayer($('#hist'));await loadRfp();await loadProposals();
      await loadComparison();
      toast('파일과 연결된 데이터를 삭제했어요.');
    }catch(error){Live.message(error.message);}
  }});
}
Live.capture('[data-del]','click',(_e,el)=>archiveDialog(el.dataset.del));
Live.capture('#hist-del','click',()=>archiveDialog(histObj===S.rfp?'rfp':String(S.v.indexOf(histObj))));
// DOC-03·04: 요구사항 추출 상태·재시도. 추출은 AI(OpenAI) 설정이 있을 때 동작한다.
Live.capture('[data-reextract]','click',async()=>{
  const previous=requirementState;
  requirementState={status:'queued'};S.rfp.s='run';paint();
  try{
    requirementState=await getJson(projectUrl+'/requirements/jobs',{method:'POST',json:{force:true}});
  }catch(error){requirementState=previous;S.rfp.s=previous?.status==='done'?'done':'fail';paint();throw error;}
  await loadRfp();
});
async function startProposalAnalysis(uploadId){
  if(['queued','running'].includes(analysisJobs[uploadId]?.status))return;
  const job=await getJson(projectUrl+'/requirements/proposal-analysis/jobs',
    {method:'POST',json:{proposal_upload_id:uploadId}});
  analysisJobs[uploadId]=job;
  paint();await loadComparison();
}
async function flushAutoAnalysis(){
  if(requirementState?.status!=='done')return;
  for(const uploadId of [...pendingAutoAnalysis]){
    if(autoAnalysisInFlight.has(uploadId))continue;
    autoAnalysisInFlight.add(uploadId);
    pendingAutoAnalysis.delete(uploadId);savePendingAnalysis();
    try{
      await startProposalAnalysis(uploadId);
      toast('새로 등록한 제안서의 2차 분석을 자동으로 시작했어요.');
    }catch(error){toast(`제안서는 저장됐지만 자동 분석을 시작하지 못했어요. ${error.message}`);}
    finally{autoAnalysisInFlight.delete(uploadId);paint();}
  }
}
Live.capture('[data-analyze-upload]','click',async(_event,button)=>{
  await startProposalAnalysis(button.dataset.analyzeUpload);
  toast('선택한 제안서의 2차 분석을 시작했어요.');
});
Live.capture('[data-retry]','click',async()=>{await getJson(projectUrl+'/requirements/jobs',{method:'POST',json:{force:requirementState?.status==='failed'}});await loadRfp();toast('요구사항 요약을 시작했어요. 몇 분 걸릴 수 있어요');});
Live.capture('#toc-ok','click',()=>{throw Error('목차 수정은 아직 연결되지 않았습니다. 저장된 파싱 원문을 확인하세요.');});

// 요구사항별 제안서 2차 분석: 완료 전 항목은 확인된 내용으로 표시하지 않는다.
const comparisonStatus=$('#comparison-status');
const comparisonCategory=$('#comparison-category');
const comparisonSearch=$('#comparison-search');
function renderBusinessStatus(data){
  const panel=$('#business-panel');
  const categories=[['current_status','현황'],['background_and_need','배경 및 필요성'],['scope','사업 범위']];
  const status=data?.status==='ready'?data.business_status||{}:{};
  const entries=categories.map(([key,title])=>({title,points:Array.isArray(status[key])?status[key].filter(point=>point?.text?.trim()):[]}));
  panel.hidden=!entries.some(entry=>entry.points.length);
  $('#business-grid').innerHTML=panel.hidden?'':entries.map(({title,points})=>
    `<div class="business-card"><h4>${title}</h4>${points.length?'<ul>'+points.map(point=>`<li>${h(point.text)}</li>`).join('')+'</ul>':'<p>추출된 내용이 없습니다.</p>'}</div>`
  ).join('');
}
function previewLink(uploadId,page){
  return '/app/dept-admin/PM-02/design/proposal-preview.html?project_id='
    +encodeURIComponent(Live.pid)+'&upload_id='+encodeURIComponent(uploadId)
    +(page?'&page='+encodeURIComponent(page):'');
}
function findingHtml(finding,column){
  if(!column)return '<span class="finding-status wait">제안서 미등록</span>';
  if(!finding)return `<span class="finding-status wait">${column.status==='not_started'?'2차 분석 전':column.status==='partial'?'분석 대기':'정리 결과 없음'}</span>`;
  if(finding.status!=='확인됨')return '<span class="finding-status wait">확인되지 않음</span>';
  const citations=(finding.evidence||[]).map(e=>{
    const page=Number(e.page)||0;
    return `<li><a href="${previewLink(column.proposal_upload_id,page)}" target="_blank" rel="noopener">${page?page+'쪽':'제안서 보기'}</a> · ${h(String(e.quote||'').slice(0,280))}${String(e.quote||'').length>280?'…':''}</li>`;
  }).join('');
  return `<span class="finding-status ok">확인됨</span><span>${h(finding.proposal_summary||'')}</span>`
    +(citations?`<details class="citation"><summary>제안서 원문 근거 ${finding.evidence.length}건</summary><ul>${citations}</ul></details>`:'');
}
function renderComparison(){
  const data=comparisonData;
  if(!data)return;
  renderBusinessStatus(data);
  if(data.status!=='ready'){
    comparisonStatus.textContent='제안요청서 요구사항 추출이 완료되면 비교 표를 볼 수 있습니다.';
    $('#comparison-tools').hidden=true;$('#comparison-wrap').hidden=true;return;
  }
  const vendors=sorted().map(v=>{
    const row=vendorRows[S.v.indexOf(v)];
    return {view:v,column:data.proposals.find(p=>p.vendor_id===row?.id)};
  });
  const total=data.categories.reduce((n,c)=>n+c.requirements.length,0);
  comparisonStatus.textContent=`${total}개 요구사항 · `+vendors.map(({view,column})=>
    `${view.code} ${column?column.status==='complete'?`확인 ${column.confirmed} · 미확인 ${column.unconfirmed}`:column.status==='partial'?`${column.processed}/${column.total}건 처리`:'2차 분석 전':'제안서 미등록'}`).join(' · ')
    +' · 확인됨은 관련 제안 문구를 찾았다는 뜻이며 요구사항 충족 판정은 아닙니다. 확인되지 않음도 내용 부재 판정이 아닙니다.';
  $('#comparison-tools').hidden=false;$('#comparison-wrap').hidden=false;
  const selected=comparisonCategory.value;
  comparisonCategory.innerHTML='<option value="">모든 요구사항 구분</option>'+data.categories.map(c=>
    `<option value="${h(c.name)}">${h(c.name)} (${c.requirements.length})</option>`).join('');
  comparisonCategory.value=data.categories.some(c=>c.name===selected)?selected:'';
  const needle=comparisonSearch.value.trim().toLowerCase();
  let visible=0;
  const rows=data.categories.filter(c=>!comparisonCategory.value||c.name===comparisonCategory.value).map(category=>{
    const requirements=category.requirements.filter(req=>!needle||
      `${req.code} ${req.title} ${req.rfp_detail}`.toLowerCase().includes(needle));
    if(!requirements.length)return '';
    visible+=requirements.length;
    return `<tr class="group-row"><th colspan="${2+vendors.length}" scope="rowgroup">${h(category.name)} · ${requirements.length}건</th></tr>`
      +requirements.map(req=>{
        const detail=String(req.rfp_detail||'');
        const short=detail.slice(0,180);
        const rfpUrl='/app/dept-admin/PM-02/design/rfp-preview.html?project_id='
          +encodeURIComponent(Live.pid)+(req.rfp_page?'&page='+encodeURIComponent(req.rfp_page):'');
        const rfpCell=`<span class="req-title">${h(req.title)}</span><span class="detail-preview">${h(short)}${detail.length>180?'…':''}</span>`
          +(detail.length>180?`<details><summary>요구사항 전체 보기</summary><div class="detail-preview">${h(detail)}</div></details>`:'')
          +(req.rfp_page?`<span class="citation"><a href="${rfpUrl}" target="_blank" rel="noopener">제안요청서 ${req.rfp_page}쪽</a></span>`:'');
        return `<tr><th scope="row">${h(req.code)}</th><td>${rfpCell}</td>`
          +vendors.map(({view,column})=>`<td>${findingHtml(req.findings[providerId(view)]||null,column)}</td>`).join('')+'</tr>';
      }).join('');
  }).join('');
  const labels=vendors.map(({view,column})=>`<th scope="col">${h(view.code)}${column?`<small> · ${h(view.name)}</small>`:''}</th>`).join('');
  const table=$('#comparison-table');
  table.style.minWidth=`${Math.max(980,440+vendors.length*300)}px`;
  table.innerHTML=`<thead><tr><th scope="col">ID</th><th scope="col">제안요청서</th>${labels}</tr></thead><tbody>`
    +(rows||`<tr><td colspan="${2+vendors.length}">검색 결과가 없습니다.</td></tr>`)
    +'</tbody>';
  comparisonStatus.textContent+=` · 표시 ${visible}건`;
}
function providerId(view){return vendorRows[S.v.indexOf(view)]?.id||'';}
async function loadComparison(){
  comparisonStatus.textContent='요구사항과 업체별 정리 결과를 불러오는 중입니다.';
  try{
    const [data,jobState]=await Promise.all([
      getJson(projectUrl+'/requirements/proposal-comparison'),
      getJson(projectUrl+'/requirements/proposal-analysis/jobs')]);
    comparisonData=data;analysisJobs=jobState.jobs||{};
    renderComparison();
    paint();
  }catch(error){comparisonStatus.textContent='비교 표를 불러오지 못했습니다. '+error.message;
    $('#business-panel').hidden=true;
    $('#comparison-tools').hidden=true;$('#comparison-wrap').hidden=true;}
  clearTimeout(analysisTimer);
  if(Object.values(analysisJobs).some(job=>['queued','running'].includes(job.status)))
    analysisTimer=setTimeout(loadComparison,5000);
}
$('#comparison-refresh').onclick=loadComparison;
comparisonCategory.onchange=renderComparison;
comparisonSearch.oninput=renderComparison;
comparisonInitialized=true;
loadComparison().then(flushAutoAnalysis);
