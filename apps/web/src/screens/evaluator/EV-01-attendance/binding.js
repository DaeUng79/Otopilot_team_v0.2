// EV-01 · ATT-01. Retain original consent and attendance dialog.
var liveAttendance=Live.boot.attendance[0];
const attendanceProject=Live.boot.projects[0];
document.getElementById('ttl').textContent=attendanceProject.name+' 평가위원으로 참석하시겠습니까?';
document.querySelector('.when').textContent='평가일 '+(attendanceProject.evaluation_date||'담당자 확인 필요');
document.querySelector('#refuse b').textContent=attendanceProject.contact_name+' · '+attendanceProject.contact_phone;
document.getElementById('reserveNote').hidden=Live.boot.member_kind!=='RESERVE';
if(liveAttendance?.status==='CONFIRMED'){agree.checked=true;yes.disabled=false;yes.textContent='참석 확인 완료 · 입장하기';document.getElementById('hint').textContent='참석 확인을 저장했습니다.';}
EvalShell.mount(document.getElementById('hd'),{active:null,project:Live.boot.projects[0]?.name,user:Live.boot.actor.name,chat:false});
Live.capture('#yes','click',async()=>{
  if(!agree.checked)throw Error('참석 동의를 확인하세요.');
  if(liveAttendance?.status!=='CONFIRMED')await Live.api('ATT-01',{status:'CONFIRMED',consent:true,consent_version:'attendance-v2',version:liveAttendance?.version||1});
  Live.go('EV-03');
});
Live.capture('#no','click',async()=>{
  if(!agree.checked)throw Error('개인정보 동의 후 참석 여부를 알려 주세요.');
  liveAttendance=await Live.api('ATT-01',{status:'DECLINED',consent:true,consent_version:'attendance-v2',version:liveAttendance?.version||1});
  document.getElementById('ask').hidden=true;document.getElementById('refuse').hidden=false;document.getElementById('back').focus();
});
