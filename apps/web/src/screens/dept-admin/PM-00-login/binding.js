// PM-00 · AUTH-01: original form, validation message and navigation.
$('#uid').value=Live.config.demo?Live.config.demo_accounts?.department||'':'';
$('#upw').value=Live.config.demo?Live.config.demo_accounts?.password||'':'';
Live.capture('#f-login','submit',async()=>{
  const actor=await Live.api('AUTH-01',{username:$('#uid').value.trim(),password:$('#upw').value});
  if(actor.must_change_password){Live.go('SA-00',{change:'1'});return;}
  msg();Live.go(actor.role==='SUPER_ADMIN'?'SA-01':'PM-01');
});
