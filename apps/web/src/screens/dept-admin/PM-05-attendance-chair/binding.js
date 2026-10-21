// Keep the original five-step renderer and confirmation dialogs.
if(!Live.pid)throw Error('사업 목록에서 사업을 선택해 주세요.');
let liveAttendance,liveSession,pendingAction=null,attendanceTimer=null,attendanceSignature='',attendancePollBusy=false,selectionWasEdited=false;
const originalAttendanceRender=render;
lockChecks=function(){const selected=[...selSet()].map(i=>liveAttendance.assignments[i]),n=selected.length,fields=new Set(selected.flatMap(a=>a.specialties.map(f=>f.id))),required=new Set(liveAttendance.assignments.filter(a=>a.member_kind==='PRIMARY').flatMap(a=>a.specialties.map(f=>f.id))),covered=[...required].filter(f=>fields.has(f)).length;return [{ok:n>=MIN,t:`최소 인원 ${MIN}명 이상`,s:`선택 ${n}명`},{ok:n<=CAP,t:`정원 ${CAP}명 이하`,s:`선택 ${n}명`},{ok:covered===required.size,t:'분야별 1명 이상',s:covered===required.size?`${required.size}개 분야 확인`:`${covered}/${required.size}개 분야 확인`}];};
render=function(){originalAttendanceRender();const title=document.querySelector('.project-title,.ph h1');if(title)title.textContent=Live.boot.projects.find(p=>p.id===Live.pid)?.name||'';if(cur()===0){const notes=$$('#main .chk li');if(notes[0])notes[0].querySelector('span:last-child').lastChild.textContent=`본위원 ${liveAttendance.assignments.filter(a=>a.member_kind==='PRIMARY').length}명 · 예비 ${liveAttendance.assignments.filter(a=>a.member_kind==='RESERVE').length}명`;if(notes[1]&&S.recv)notes[1].querySelector('span:last-child').lastChild.textContent=`승인 평가표 ${liveAttendance.criteria.length}개 수신`;}
 $$('[data-sel]').forEach(cb=>{const change=cb.onchange;cb.onchange=event=>{selectionWasEdited=true;change.call(cb,event);};});
 // 참석 확인과 선택 기준을 함께 반영한다.
 const confirmed=liveAttendance.assignments.filter(a=>a.attendance_status==='CONFIRMED').length;
 if(S.prepared&&!S.locked&&cur()<=2){const bar=$('#main .toolbar');if(bar&&!bar.querySelector('.att-ready')){const ready=lockChecks().every(check=>check.ok),tip=document.createElement('span');tip.className='badge '+(ready?'primary att-ready':'att-ready');tip.textContent=ready?'선정 기준 충족 · 실제 평가인원을 확정하면 위원장을 지정할 수 있어요':`참석 확인 ${confirmed}/${CAP}명 · 2초마다 자동 갱신`;bar.appendChild(tip);}}
};
async function loadAttendance(snapshot){
 const previousAssignments=liveAttendance?.assignments||[];
 const previousConfirmed=new Set(previousAssignments.filter(a=>a.attendance_status==='CONFIRMED').map(a=>a.id));
 const previousSelected=new Set([...(S?.sel||[])].map(i=>previousAssignments[i]?.id).filter(Boolean));
 if(!snapshot)await Live.reload();
 liveAttendance=snapshot||await Live.api('ATT-02',{project_id:Live.pid});liveSession=liveAttendance.sessions.find(s=>s.status!=='CANCELLED');
 const members=liveAttendance.assignments;CAP=liveSession?.target_count||members.filter(a=>a.member_kind==='PRIMARY').length||7;MIN=liveSession?.minimum_attendees||Math.min(5,CAP);
 FIELDS.splice(0,FIELDS.length,...members.map(a=>h(a.specialties.map(f=>f.name).join(', ')||'—')));NAMES.splice(0,NAMES.length,...members.map((a,i)=>[h(a.name_snapshot),a.member_kind==='PRIMARY'?'본':`예비 ${a.reserve_order||i+1}`,i]));ATT.ok=members.map(a=>a.attendance_status==='CONFIRMED'?1:0);
 const participants=liveAttendance.participants.filter(p=>p.session_id===liveSession?.id),chair=participants.find(p=>p.id===liveSession?.chair_participant_id);
 let keepSel=null;
 if(selectionWasEdited&&!participants.length){
  const selected=new Set(members.filter(a=>a.attendance_status==='CONFIRMED'&&previousSelected.has(a.id)).map(a=>a.id));
  for(const a of members){if(selected.size>=CAP)break;if(a.attendance_status==='CONFIRMED'&&!previousConfirmed.has(a.id))selected.add(a.id);}
  keepSel=new Set(members.flatMap((a,i)=>selected.has(a.id)?[i]:[]));
 }
 S={recv:!!liveAttendance.criteria.length&&!!liveAttendance.rosters.length,prepared:!!liveSession,refreshed:true,locked:participants.length>0,chair:chair?members.findIndex(a=>a.id===chair.assignment_id):null,started:!!liveSession&&liveSession.status!=='PREPARING',scn:'ok',sel:participants.length?new Set(participants.map(p=>members.findIndex(a=>a.id===p.assignment_id))):keepSel,pick:S?.pick??null};render();
 attendanceSignature=attendanceState();
}
await loadAttendance();
if(!liveSession){const missing=[];if(!liveAttendance.rosters.length)missing.push('평가위원 선정 화면에서 초청 명단 확정');if(!liveAttendance.criteria.length)missing.push('평가항목 화면에서 평가표 확정');const hint=document.querySelector('#main .err');if(hint&&missing.length)hint.textContent=missing.join(' 및 ')+' 후 회차를 준비할 수 있습니다.';}
// 위원이 참석 확인을 누르면 담당자 화면에 자동으로 나타나도록 2초마다 새로 읽는다(평가 시작 전까지).
function attendanceState(){return JSON.stringify([liveAttendance.assignments.map(a=>a.attendance_status),liveAttendance.participants.length,liveSession?.status,liveSession?.chair_participant_id]);}
attendanceTimer=setInterval(async()=>{if(document.hidden||pendingAction||attendancePollBusy||(liveSession&&liveSession.status!=='PREPARING'))return;attendancePollBusy=true;try{const snapshot=await Live.api('ATT-02',{project_id:Live.pid});const next=JSON.stringify([snapshot.assignments.map(a=>a.attendance_status),snapshot.participants.length,snapshot.sessions.find(s=>s.status!=='CANCELLED')?.status,snapshot.sessions.find(s=>s.status!=='CANCELLED')?.chair_participant_id]);if(next!==attendanceSignature)await loadAttendance(snapshot);}catch(error){/* 일시적인 통신 오류 뒤에도 다시 시도한다. */}finally{attendancePollBusy=false;}},2000);
window.addEventListener('pagehide',()=>clearInterval(attendanceTimer),{once:true});
Live.capture('[data-pre]','click',()=>{throw Error('시안 상태 전환은 실제 데이터에 적용하지 않습니다.');});
Live.capture('#b-prep','click',async()=>{await Live.api('ATT-00',{project_id:Live.pid,roster_id:liveAttendance.rosters.at(-1).id,approved_criteria_version_id:liveAttendance.criteria.at(-1).id,target_count:CAP,minimum_attendees:MIN,approve_policy:true});await loadAttendance();attendanceSignature=attendanceState();toast('평가회차를 준비했어요');});
Live.capture('#b-ref','click',async()=>{await loadAttendance();attendanceSignature=attendanceState();});
Live.capture('#b-lock,#b-chair,#b-start','click',(_e,el)=>{
 pendingAction=el.id;const label=el.id==='b-lock'?'실제 평가인원을 확정할까요?':el.id==='b-chair'?'선택한 위원을 위원장으로 지정할까요?':'평가를 시작할까요?';
 confirmDlg({title:label,body:'평가 시작 후에는 변경할 수 없습니다.',ok:'확정하기'});
});
Live.capture('#dlg-cancel','click',()=>{pendingAction=null;closeAll();});
Live.capture('#dlg-ok','click',async()=>{
 if(!pendingAction)return;const body={session_id:liveSession.id,version:liveSession.version};
 try{
  if(pendingAction==='b-lock'){body.attendance_ids=[...S.sel].map(i=>liveAttendance.assignments[i].attendance_id);await Live.api('ATT-03',body);}
  if(pendingAction==='b-chair'){body.participant_id=liveAttendance.participants.find(p=>p.session_id===liveSession.id&&p.assignment_id===liveAttendance.assignments[S.pick]?.id)?.id;await Live.api('ATT-04',body);}
  if(pendingAction==='b-start')await Live.api('ATT-05',body);
 }finally{pendingAction=null;}
 closeAll();await loadAttendance();attendanceSignature=attendanceState();toast('저장했어요');
});
