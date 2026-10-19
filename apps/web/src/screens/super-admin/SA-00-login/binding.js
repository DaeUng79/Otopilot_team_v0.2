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
Live.capture('#f-acct','submit',async()=>{if($('#a1').value!==$('#a2').value)throw Error('두 비밀번호가 다릅니다.');await Live.api('AUTH-04',{current_password:$('#a0').value,new_password:$('#a1').value});closeLayer($('#acct'));reset();toast('비밀번호를 변경했어요. 다시 로그인하세요.');});
Live.capture('#acct-logout','click',async()=>{await Live.api('AUTH-03');Live.go('ENTRY');});
if(location.hash==='#account'&&Live.boot){view('app');const values=$$('#acct .kv dd');values[0].textContent=Live.boot.actor.username;values[1].textContent=Live.boot.actor.role==='SUPER_ADMIN'?'총괄관리자':'부서관리자';values[2].textContent='현재 로그인';openAcct();}
