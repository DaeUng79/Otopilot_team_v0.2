// PM-00 · AUTH-01: original form, validation message and navigation.
const localAccounts=Live.config.local_login_accounts||Live.config.demo_accounts;
$('#uid').value=localAccounts?.department||'';
$('#upw').value=localAccounts?.password||'';
if(Live.config.local_login_accounts){
  const choices=document.createElement('div');
  choices.style.cssText='display:flex;gap:8px;flex-wrap:wrap';
  for(const [label,username] of [['기본 부서',localAccounts.department],['다른 부서',localAccounts.other_department]]){
    const button=document.createElement('button');
    button.type='button';button.className='btn';button.textContent=label;
    button.addEventListener('click',()=>{$('#uid').value=username;$('#upw').value=localAccounts.password;});
    choices.append(button);
  }
  $('#f-login .seed').before(choices);
}
Live.capture('#f-login','submit',async()=>{
  const actor=await Live.api('AUTH-01',{username:$('#uid').value.trim(),password:$('#upw').value});
  if(actor.must_change_password){Live.go('SA-00',{change:'1'});return;}
  msg();Live.go(actor.role==='SUPER_ADMIN'?'SA-01':'PM-01');
});
