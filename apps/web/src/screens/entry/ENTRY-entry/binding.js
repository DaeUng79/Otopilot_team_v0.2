// ENTRY · AUTH-01/02. Original three choices and in-place login stay intact.
Live.capture('[data-role]','click',(_event,button)=>Live.go({admin:'SA-00',biz:'PM-00',eval:'EV-00'}[button.dataset.role],Live.query.has('project_id')?{project_id:Live.query.get('project_id')}:{}));
Live.capture('#f','submit',async()=>{
  const kind=cur?.dataset.role,inputs=[...f.querySelectorAll('input')];
  if(!kind)return;
  if(kind==='eval'){
    try{await Live.evaluatorLogin(f,inputs[0].value.trim(),inputs[1].value,Live.query.get('project_id'));}
    catch(error){msg.textContent=error.message;msg.classList.add('show');}
  }else{
    const actor=await Live.api('AUTH-01',{username:inputs[0].value.trim(),password:inputs[1].value});Live.go(actor.must_change_password?'SA-00':actor.role==='SUPER_ADMIN'?'SA-01':'PM-01',actor.must_change_password&&actor.role==='DEPARTMENT_ADMIN'?{role:'department'}:{});
  }
});
