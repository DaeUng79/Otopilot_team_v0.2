// Keep the original five-step renderer and confirmation dialogs.
if(!Live.pid)throw Error('사업 목록에서 사업을 선택해 주세요.');
let liveAttendance,liveSession,pendingAction=null;
const originalAttendanceRender=render;
lockChecks=function(){const selected=[...selSet()].map(i=>liveAttendance.assignments[i]),n=selected.length,fields=new Set(selected.flatMap(a=>a.specialties.map(f=>f.id))),required=new Set(liveAttendance.assignments.filter(a=>a.member_kind==='PRIMARY').flatMap(a=>a.specialties.map(f=>f.id)));return [{ok:n>=MIN,t:`최소 인원 ${MIN}명 이상`,s:`선택 ${n}명`},{ok:n<=CAP,t:`정원 ${CAP}명 이하`,s:`선택 ${n}명`},{ok:[...required].every(f=>fields.has(f)),t:'분야별 1명 이상',s:`${required.size}개 분야 확인`}];};
render=function(){originalAttendanceRender();const title=document.querySelector('.project-title,.ph h1');if(title)title.textContent=Live.boot.projects.find(p=>p.id===Live.pid)?.name||'';if(cur()===0){const notes=$$('#main .chk li');if(notes[0])notes[0].querySelector('span:last-child').lastChild.textContent=`본위원 ${liveAttendance.assignments.filter(a=>a.member_kind==='PRIMARY').length}명`;if(notes[1]&&S.recv)notes[1].querySelector('span:last-child').lastChild.textContent=`승인 평가표 ${liveAttendance.criteria.length}개 수신`;}};
async function loadAttendance(){
 await Live.reload();
 liveAttendance=await Live.api('ATT-02',{project_id:Live.pid});liveSession=liveAttendance.sessions.find(s=>s.status!=='CANCELLED');
 const members=liveAttendance.assignments;CAP=liveSession?.target_count||members.filter(a=>a.member_kind==='PRIMARY').length||7;MIN=liveSession?.minimum_attendees||5;
 FIELDS.splice(0,FIELDS.length,...members.map(a=>h(a.specialties.map(f=>f.name).join(', ')||'—')));NAMES.splice(0,NAMES.length,...members.map((a,i)=>[h(a.name_snapshot),a.member_kind==='PRIMARY'?'본':`예비 ${i+1}`,i]));ATT.ok=members.map(a=>a.attendance_status==='CONFIRMED'?1:0);
 const participants=liveAttendance.participants.filter(p=>p.session_id===liveSession?.id),chair=participants.find(p=>p.id===liveSession?.chair_participant_id);
 S={recv:!!liveAttendance.criteria.length&&!!liveAttendance.rosters.length,prepared:!!liveSession,refreshed:true,locked:participants.length>0,chair:chair?members.findIndex(a=>a.id===chair.assignment_id):null,started:!!liveSession&&liveSession.status!=='PREPARING',scn:'ok',sel:participants.length?new Set(participants.map(p=>members.findIndex(a=>a.id===p.assignment_id))):null,pick:null};render();
}
await loadAttendance();
if(!liveSession){const missing=[];if(!liveAttendance.rosters.length)missing.push('평가위원 선정 화면에서 초청 명단 확정');if(!liveAttendance.criteria.length)missing.push('문서 담당 모듈의 승인 평가표 수신');const hint=document.querySelector('#main .err');if(hint&&missing.length)hint.textContent=missing.join(' 및 ')+' 후 회차를 준비할 수 있습니다.';}
Live.capture('[data-pre]','click',()=>{throw Error('시안 상태 전환은 실제 데이터에 적용하지 않습니다.');});
Live.capture('#b-prep','click',async()=>{await Live.api('ATT-00',{project_id:Live.pid,roster_id:liveAttendance.rosters.at(-1).id,approved_criteria_version_id:liveAttendance.criteria.at(-1).id,target_count:CAP,minimum_attendees:MIN,approve_policy:true});await loadAttendance();toast('평가회차를 준비했어요');});
Live.capture('#b-ref','click',loadAttendance);
Live.capture('#b-lock,#b-chair,#b-start','click',(_e,el)=>{
 pendingAction=el.id;const label=el.id==='b-lock'?'실제 평가인원을 확정할까요?':el.id==='b-chair'?'선택한 위원을 위원장으로 지정할까요?':'평가를 시작할까요?';
 confirmDlg({title:label,body:'확정 내용을 저장합니다. 평가 시작 후에는 변경할 수 없습니다.',ok:'확정하기'});
});
Live.capture('#dlg-ok','click',async()=>{
 if(!pendingAction)return;const body={session_id:liveSession.id,version:liveSession.version};
 if(pendingAction==='b-lock'){body.attendance_ids=[...S.sel].map(i=>liveAttendance.assignments[i].attendance_id);await Live.api('ATT-03',body);}
 if(pendingAction==='b-chair'){body.participant_id=liveAttendance.participants.find(p=>p.session_id===liveSession.id&&p.assignment_id===liveAttendance.assignments[S.pick]?.id)?.id;await Live.api('ATT-04',body);}
 if(pendingAction==='b-start')await Live.api('ATT-05',body);
 closeAll();pendingAction=null;await loadAttendance();toast('저장했어요');
});
