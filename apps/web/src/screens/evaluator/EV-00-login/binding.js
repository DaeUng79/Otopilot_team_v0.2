// EV-00 · AUTH-02. Project identity comes from the existing invitation URL.
var liveProject=Live.query.get('project_id')||Live.query.get('id');
const demoEvaluator=Live.config.demo?Live.config.demo_accounts?.evaluators?.[0]:null;
nm.value=demoEvaluator?.name||'';ph.value=demoEvaluator?.last4||'';
document.querySelector('.kick').textContent=liveProject?'사업 초청 링크로 입장합니다':'초청받은 평가 사업에 입장합니다';
document.querySelector('h1').textContent='평가위원 입장';
show('');
Live.capture('#f','submit',async()=>{
  try{await Live.evaluatorLogin(document.getElementById('f'),nm.value.trim(),ph.value,liveProject);}
  catch(error){show(error.message);}
});
