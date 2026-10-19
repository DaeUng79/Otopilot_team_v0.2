let liveAdmins=new Map(),liveDepartments=new Map(),pendingAdminAction=null;
const permissionMap={PRJ_MANAGE:'MANAGE_PROJECTS',DOC_MANAGE:'MANAGE_DOCUMENTS',COM_MANAGE:'MANAGE_COMMITTEE',EVAL_RUN:'MANAGE_PROJECTS',RES_VIEW:'VIEW_RESULTS',ADM_ACCOUNT:'MANAGE_ADMINS'};
async function loadAdministration(){
 const [users,departments]=await Promise.all([Live.all('ADM-01'),Live.api('ADM-DEPT-LIST')]);liveAdmins=new Map(users.map(a=>[a.username,a]));liveDepartments=new Map(departments.items.map(d=>[d.code,d]));
 depts=departments.items.map(d=>({code:d.code,org:d.organization_name,name:d.name,n:d.project_count,on:!!d.active,v:d.version}));
 accts=users.map(a=>({id:a.username,nm:a.display_name,dept:departments.items.find(d=>d.id===a.department_id)?.code||null,role:a.role==='SUPER_ADMIN'?'admin':'dept',last:'—',on:!!a.active,v:a.version,pc:Object.keys(permissionMap).filter(k=>a.permissions.includes(permissionMap[k])||a.role==='SUPER_ADMIN')}));renderAll();
}
await loadAdministration();
const closePanels=()=>{stack.slice().reverse().forEach(x=>closeLayer(x.el));};
Live.capture('#f-dnew','submit',async()=>{await Live.api('ADM-DEPT-SAVE',{code:$('#dn-code').value.trim(),organization_name:$('#dn-org').value.trim(),name:$('#dn-name').value.trim()});closePanels();await loadAdministration();await Live.reload();toast('부서를 등록했어요');});
Live.capture('#de-save','click',async()=>{const d=liveDepartments.get(curD.code);await Live.api('ADM-DEPT-SAVE',{department_id:d.id,version:d.version,organization_name:$('#de-org').value.trim(),name:$('#de-name').value.trim()});closePanels();await loadAdministration();toast('부서 정보를 저장했어요');});
Live.capture('#f-anew','submit',async()=>{const d=liveDepartments.get($('#an-dept').value);if(!d)throw Error('부서를 선택하세요.');await Live.api('ADM-02',{department_id:d.id,username:$('#an-id').value.trim(),display_name:$('#an-name').value.trim(),password:$('#an-pw').value});closePanels();await loadAdministration();toast('계정을 등록했어요 · 부서관리자 기본 권한(사업·문서·위원·결과)을 부여했어요. 계정 수정에서 바꿀 수 있어요');});
Live.capture('#an-gen','click',()=>{$('#an-pw').value=Array.from(crypto.getRandomValues(new Uint8Array(12)),v=>'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'[v%54]).join('')+'7!';});
Live.capture('#ae-save','click',async()=>{const a=liveAdmins.get(curA.id);await Live.api('ADM-03',{admin_id:a.id,version:a.version,display_name:$('#ae-name').value.trim(),department_id:liveDepartments.get($('#ae-dept').value)?.id});closePanels();await loadAdministration();toast('계정 정보를 저장했어요');});
Live.capture('#ae-psave','click',async()=>{const a=liveAdmins.get(curA.id);const selected=new Set($$('#ae-perms input:checked').map(el=>permissionMap[el.value]));if(a.permissions.includes('VIEW_DASHBOARD'))selected.add('VIEW_DASHBOARD');await Live.api('ADM-05',{admin_id:a.id,version:a.version,permission_codes:[...selected]});await loadAdministration();openAEdit(a.username);toast('권한을 저장했어요');});
Live.capture('#z-on,#z-off,#z-del,#y-on,#y-off,#ae-reset','click',(_e,el)=>{pendingAdminAction=el.id;confirmDlg({title:el.textContent.trim()+' 작업을 진행할까요?',body:'변경 내용을 저장하고 해당 계정의 로그인 세션을 갱신합니다.',ok:'확인',danger:el.id!=='ae-reset'});});
Live.capture('#dlg-ok','click',async()=>{
 if(!pendingAdminAction)return;let notice='저장했어요';
 if(pendingAdminAction.startsWith('z-')){const d=liveDepartments.get(curD.code);await Live.api('ADM-DEPT-STATE',{department_id:d.id,version:d.version,state:pendingAdminAction==='z-on'?'ACTIVE':pendingAdminAction==='z-del'?'DELETED':'INACTIVE'});}
 else {const a=liveAdmins.get(curA.id);const response=await Live.api(pendingAdminAction==='y-on'?'ADM-RESTORE':pendingAdminAction==='y-off'?'ADM-04':'ADM-RESET',{admin_id:a.id,version:a.version});if(response.temporary_password)notice='임시 비밀번호: '+response.temporary_password+' · 다음 로그인에서 변경하세요.';}
 pendingAdminAction=null;closePanels();await loadAdministration();toast(notice);
});
Live.capture('#d-conf','click',()=>{throw Error('실제 저장 충돌은 서버의 버전 검사로 확인합니다.');});
