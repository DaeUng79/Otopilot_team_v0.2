// SA-00 · AUTH-01. Existing login form and error message.
reset();
if(Live.config.local_login_accounts||Live.config.demo_accounts){
  const account=Live.config.local_login_accounts||Live.config.demo_accounts;
  $('#uid').value=account.super;
  $('#upw').value=account.password;
}
Live.capture('#f-login','submit',async()=>{
  try{const actor=await Live.api('AUTH-01',{username:$('#uid').value.trim(),password:$('#upw').value});if(actor.must_change_password){view('first');return;}Live.go(actor.role==='SUPER_ADMIN'?'SA-01':'PM-01');}
  catch(error){msg('wrong',error.message,'');}
});
Live.capture('#f-first','submit',async()=>{if($('#np1').value!==$('#np2').value)throw Error('두 비밀번호가 다릅니다.');await Live.api('AUTH-04',{current_password:$('#upw').value,new_password:$('#np1').value});reset();toast('비밀번호를 변경했어요. 새 비밀번호로 로그인하세요.');});
Live.capture('#f-acct','submit',async()=>{if($('#a1').value!==$('#a2').value)throw Error('두 비밀번호가 다릅니다.');await Live.api('AUTH-04',{current_password:$('#a0').value,new_password:$('#a1').value});reset();toast('비밀번호를 변경했어요. 다시 로그인하세요.');});
Live.capture('#acct-logout','click',async()=>{await Live.api('AUTH-03');Live.go('ENTRY');});
function showAccountPage(){
  stack.slice().forEach(l=>closeLayer(l.el));
  view('app');
  const actor=Live.boot.actor,values=$$('#acct .kv dd');
  values[0].textContent=actor.username;values[1].textContent=actor.role==='SUPER_ADMIN'?'총괄관리자':'부서관리자';values[2].textContent='현재 로그인';
  const main=$('#v-app .main'),head=$('.head',main),card=$('.card',main),form=$('#f-acct'),foot=$('#acct footer');
  $('h1',head).textContent='내 계정';$('.sub',head).textContent='로그인 정보를 확인하고 비밀번호를 바꿀 수 있어요.';
  $$('#v-app nav a').forEach(a=>a.removeAttribute('aria-current'));$$('#v-app [data-account]').forEach(a=>a.setAttribute('aria-current','page'));
  ['a0','a1','a2'].forEach(i=>{$('#'+i).value='';sh(i+'-e','');});
  form.style.cssText='display:flex;flex-direction:column;gap:20px;padding:24px 32px;max-width:560px;width:100%;box-sizing:border-box';
  foot.style.cssText='padding:16px 32px;border-top:1px solid var(--line);display:flex;gap:8px;flex-wrap:wrap;align-items:center;max-width:560px;width:100%;box-sizing:border-box';
  const close=$('[data-close]',foot);
  if(close){const back=document.createElement('button');back.type='button';back.className='btn';back.textContent='대시보드로';back.dataset.href='../../SA-01/design/dashboard.html';close.replaceWith(back);}
  card.replaceChildren(form,foot);card.style.overflow='auto';
  $('#acct').remove();
  setTimeout(()=>$('#a0').focus(),60);
}
if(location.hash==='#account'&&Live.boot)showAccountPage();
