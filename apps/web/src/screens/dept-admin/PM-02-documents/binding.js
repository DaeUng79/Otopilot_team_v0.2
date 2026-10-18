if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
let vendorRows=[],vendorDelete=null;
async function loadVendors(){const data=await Live.api('PRJ-05',{project_id:Live.pid});vendorRows=data.vendors;S=blankState();S.inUse=['EVALUATING','COMPLETED'].includes(data.project.status);S.v=vendorRows.map(v=>({code:v.display_code,name:v.legal_name,ord:v.sort_order,fx:S.inUse,s:'none',toc:'none',entries:[],err:'',revs:[]}));paint();}
await loadVendors();
Live.capture('#f-inl','submit',async()=>{await Live.api('PRJ-06',{project_id:Live.pid,display_code:nextCode(),legal_name:$('#i-name').value.trim(),sort_order:S.v.length+1});adding=false;await loadVendors();toast('업체를 등록했어요');});
Live.capture('#f-add','submit',async()=>{const vendor=editV?vendorRows[S.v.indexOf(editV)]:null;await Live.api('PRJ-06',{project_id:Live.pid,...(vendor?{vendor_id:vendor.id,version:vendor.version}:{}),display_code:$('#a-code').value.trim(),legal_name:$('#a-name').value.trim(),sort_order:Number($('#a-ord').value)});closeLayer($('#add'));await loadVendors();toast('업체 정보를 저장했어요');});
Live.capture('[data-vdel],#a-del','click',(_e,el)=>{vendorDelete=el.id==='a-del'?vendorRows[S.v.indexOf(editV)]:vendorRows[Number(el.dataset.vdel)];confirmDlg({title:'업체를 삭제할까요?',body:'평가에 사용 중인 업체는 삭제할 수 없습니다.',ok:'삭제',danger:true});});
Live.capture('#dlg-ok','click',async()=>{if(!vendorDelete)return;await Live.api('PRJ-07',{project_id:Live.pid,vendor_id:vendorDelete.id,version:vendorDelete.version});vendorDelete=null;closeAll();await loadVendors();toast('업체를 삭제했어요');});
// PM-02 · DOC-01/02/05: integrated HWPX parsing and SQLite storage.
const rfpUrl='/api/v2/projects/'+encodeURIComponent(Live.pid)+'/rfp';
let rfpUploads=[];
const originalPaint=paint;
paint=()=>{
  originalPaint();
  const status=$('#m-xr');
  if(status&&S.rfp.revs.length)status.innerHTML='<div class="mrow"><span class="badge success">저장 완료</span><span class="tx">원본 파일과 파싱한 문단·표를 저장했어요.</span></div>';
  if(S.rfp.revs.length){
    const actions=$('#rfp .fa');
    if(actions){
      const preview=document.createElement('button');
      preview.type='button';preview.className='btn';preview.dataset.previewRfp='';
      preview.textContent='제안요청서 미리보기';actions.appendChild(preview);
    }
    const view=$('[data-view="rfp"]');if(view)view.textContent='미리보기';
  }
  // The prototype's TOC confirmation and synthetic state controls are not persisted.
  $('#demo').hidden=true;
  const deleteRfp=$('[data-del="rfp"]');if(deleteRfp)deleteRfp.hidden=true;
};
function rfpRevision(n){return rfpUploads.find(u=>u.revision===n)}
async function loadRfp(){
  const response=await fetch(rfpUrl,{credentials:'same-origin'});
  const body=await response.json();
  if(!response.ok)throw Error(body.error?.message||'제안요청서를 불러오지 못했습니다.');
  rfpUploads=body.data.uploads;
  S.rfp={s:rfpUploads.length?'done':'none',toc:'none',entries:[],err:'',revs:rfpUploads.map(u=>
    rv(u.revision,u.filename,new Date(u.uploaded_at).toLocaleString('ko-KR'),
       (u.byte_size/1048576).toFixed(1)+'MB'))};
  paint();
}
const originalLoadVendors=loadVendors;
loadVendors=async()=>{await originalLoadVendors();await loadRfp();};
await loadRfp();
const unsupportedDocument=()=>{throw Error('업체별 제안서와 목차 수정은 아직 연결되지 않았습니다.');};
Live.capture('[data-up="rfp"]','click',()=>{target='rfp';$('#file').accept='.hwpx';$('#file').value='';$('#file').click();});
Live.capture('[data-up]:not([data-up="rfp"])','click',unsupportedDocument);
async function uploadRfp(file){
  if(!file)return;
  if(!file.name.toLowerCase().endsWith('.hwpx'))throw Error('HWPX 파일만 올릴 수 있습니다.');
  if(file.size>50*1024*1024)throw Error('50MB 이하의 파일을 올려 주세요.');
  const form=new FormData();form.append('file',file);
  S.rfp.s='run';S.rfp.err='';paint();
  try{
    const response=await fetch(rfpUrl,{method:'POST',credentials:'same-origin',
      headers:{'X-Simsa-Client':'v2-web'},body:form});
    const body=await response.json();
    if(!response.ok)throw Error(body.error?.message||'문서를 저장하지 못했습니다.');
    await loadRfp();toast('제안요청서와 파싱 원문을 저장했어요.');
  }catch(error){S.rfp.s=rfpUploads.length?'done':'none';S.rfp.err=error.message;paint();throw error;}
}
Live.capture('#file','change',event=>target==='rfp'
  ?uploadRfp(event.target.files?.[0]):unsupportedDocument());
Live.capture('[data-drop="rfp"]','drop',event=>{
  const file=event.dataTransfer?.files?.[0];if(!file)return;
  return uploadRfp(file);
});
Live.capture('[data-drop]:not([data-drop="rfp"])','drop',unsupportedDocument);
Live.capture('[data-hist="rfp"]','click',()=>openHist('rfp'));
Live.capture('[data-hist]:not([data-hist="rfp"])','click',unsupportedDocument);
async function downloadRfp(revision){
  const upload=rfpRevision(revision);if(!upload)throw Error('등록된 문서가 없습니다.');
  const response=await fetch(rfpUrl+'/'+revision+'/download',{credentials:'same-origin'});
  if(!response.ok)throw Error('원본 파일을 내려받지 못했습니다.');
  const url=URL.createObjectURL(await response.blob());
  const link=document.createElement('a');link.href=url;link.download=upload.filename;link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
Live.capture('[data-dl="rfp"]','click',()=>downloadRfp(rfpUploads[0]?.revision));
Live.capture('[data-dl]:not([data-dl="rfp"])','click',unsupportedDocument);
Live.capture('[data-rv]','click',(_event,button)=>{
  const revision=Number(button.closest('li')?.querySelector('.vn')?.textContent.replace('v',''));
  return downloadRfp(revision);
});
async function showParsedRfp(){
  const upload=rfpUploads[0];if(!upload)throw Error('등록된 문서가 없습니다.');
  const response=await fetch(rfpUrl+'/'+upload.revision+'/source',{credentials:'same-origin'});
  const body=await response.json();
  if(!response.ok)throw Error(body.error?.message||'파싱 원문을 읽지 못했습니다.');
  $('#toc-t').textContent='제안요청서 파싱 원문';
  $('#toc-note').textContent='저장된 문단과 표의 텍스트입니다. 정확한 서식은 원본 파일로 확인하세요.';
  $('#toc-ok').hidden=true;$('#toc-left').textContent='';
  $('#toc-list').tabIndex=0;
  $('#toc-list').replaceChildren(...body.data.blocks.map(block=>{
    const item=document.createElement('li');
    item.textContent=block.type==='table'
      ?block.rows.map(row=>row.map(cell=>cell.text).join(' | ')).join('\n')
      :block.text;
    item.style.whiteSpace='pre-wrap';return item;
  }));
  openLayer($('#toc'),'#toc-list');
}
Live.capture('[data-toc="rfp"]','click',showParsedRfp);
function openRfpPreview(){
  location.href='/app/dept-admin/PM-02/design/rfp-preview.html?project_id='+encodeURIComponent(Live.pid);
}
Live.capture('[data-preview-rfp],[data-view="rfp"]','click',openRfpPreview);
Live.capture('[data-toc]:not([data-toc="rfp"]),[data-view]:not([data-view="rfp"])','click',unsupportedDocument);
Live.capture('[data-del],[data-retry],[data-refresh],#toc-ok,#hist-del','click',unsupportedDocument);
