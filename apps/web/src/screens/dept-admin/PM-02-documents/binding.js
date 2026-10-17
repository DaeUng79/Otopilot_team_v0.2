if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
let vendorRows=[],vendorDelete=null;
async function loadVendors(){const data=await Live.api('PRJ-05',{project_id:Live.pid});vendorRows=data.vendors;S=blankState();S.inUse=['EVALUATING','COMPLETED'].includes(data.project.status);S.v=vendorRows.map(v=>({code:v.display_code,name:v.legal_name,ord:v.sort_order,fx:S.inUse,s:'none',toc:'none',entries:[],err:'',revs:[]}));paint();}
await loadVendors();
Live.capture('#f-inl','submit',async()=>{await Live.api('PRJ-06',{project_id:Live.pid,display_code:nextCode(),legal_name:$('#i-name').value.trim(),sort_order:S.v.length+1});adding=false;await loadVendors();toast('업체를 등록했어요');});
Live.capture('#f-add','submit',async()=>{const vendor=editV?vendorRows[S.v.indexOf(editV)]:null;await Live.api('PRJ-06',{project_id:Live.pid,...(vendor?{vendor_id:vendor.id,version:vendor.version}:{}),display_code:$('#a-code').value.trim(),legal_name:$('#a-name').value.trim(),sort_order:Number($('#a-ord').value)});closeLayer($('#add'));await loadVendors();toast('업체 정보를 저장했어요');});
Live.capture('[data-vdel],#a-del','click',(_e,el)=>{vendorDelete=el.id==='a-del'?vendorRows[S.v.indexOf(editV)]:vendorRows[Number(el.dataset.vdel)];confirmDlg({title:'업체를 삭제할까요?',body:'평가에 사용 중인 업체는 삭제할 수 없습니다.',ok:'삭제',danger:true});});
Live.capture('#dlg-ok','click',async()=>{if(!vendorDelete)return;await Live.api('PRJ-07',{project_id:Live.pid,vendor_id:vendorDelete.id,version:vendorDelete.version});vendorDelete=null;closeAll();await loadVendors();toast('업체를 삭제했어요');});
const externalDocument=()=>{throw Error('문서 업로드·파싱·목차는 오대웅 담당 연결 대상입니다. 이 작업에서는 구현하지 않습니다.');};
Live.capture('[data-up],[data-retry],[data-toc],[data-hist],[data-view],[data-dl],[data-del],[data-refresh],#toc-ok,#hist-del','click',externalDocument);
Live.capture('[data-drop]','drop',externalDocument);Live.capture('#file','change',externalDocument);
