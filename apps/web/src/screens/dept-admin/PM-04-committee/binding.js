if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
let liveCommittee,liveCandidates=[],excludeIndex=null;
const specialties=Live.boot.specialties,department=Live.boot.projects.find(p=>p.id===Live.pid).department_id;
FIELDS.splice(0,FIELDS.length,...specialties.map(s=>h(s.name)));
const statusNames={NOT_CONTACTED:'미연락',AVAILABLE:'수락',UNAVAILABLE:'거절',CALLBACK:'부재'};
const originalCommitteeRender=render;
render=function(){if(S.mode==='DIRECT'&&S.stg===3)S.q=FIELDS.map((_f,i)=>S.cands.filter(c=>c.f===i&&S.pick[c.id]==='본').length);originalCommitteeRender();if(S.rost!=='none'){$$('#stage select,#stage input,#stage [data-ex]').forEach(e=>e.disabled=true);}};
async function loadCommittee(stage){
 liveCommittee=await Live.get('/committee-v2/api/projects/'+encodeURIComponent(Live.pid));
 const rule=liveCommittee.rule;
 const mode=rule?.selection_mode==='DIRECT'?'DIRECT':'POOL';
 liveCandidates=await Live.all('COM-01',{department_id:department,scope:'DEPARTMENT_POOL',active:true});
 POOLN.ok=specialties.map(s=>liveCandidates.filter(c=>c.specialty_ids.includes(s.id)).length);
 const members=liveCommittee.items.map((n,i)=>{const drawField=liveCommittee.draw_members.find(d=>d.id===n.draw_member_id)?.specialty_id;return {id:i,name:n.candidate.name,f:Math.max(0,specialties.findIndex(s=>s.id===(drawField||n.candidate.specialty_ids[0]))),l4:n.candidate.phone.slice(-4),st:statusNames[n.contact_status],memo:n.contact_note||'',src:mode==='DIRECT'?'직접':'추첨',ex:n.exclusion_reason};});
 const q=specialties.map(s=>liveCommittee.quotas.find(q=>q.specialty_id===s.id)?.final_count||0);if(!rule)q[0]=7;
 const picks={},orders={};for(const a of liveCommittee.assignments){const i=liveCommittee.items.findIndex(n=>n.id===a.nominee_id);picks[i]=a.member_kind==='PRIMARY'?'본':'예비';orders[i]=a.reserve_order;}
 S={...base(),mode,cap:rule?.target_count||7,q,saved:!!rule,drawn:!!liveCommittee.draw,cands:members,stg:stage??(liveCommittee.roster?3:rule?2:0),pick:picks,ord:orders,rost:liveCommittee.roster?(liveCommittee.handoff?.status==='SENT'?'ready':'sent'):'none'};
 DIRPOOL.splice(0,DIRPOOL.length,...liveCandidates.map(c=>[h(c.name),Math.max(0,specialties.findIndex(s=>s.id===c.specialty_ids[0])),c.phone.slice(-4)]));render();
}
await loadCommittee();
Live.capture('#save','click',async()=>{await Live.api('DRAW-01',{project_id:Live.pid,selection_mode:S.mode==='POOL'?'POOL_RANDOM':'DIRECT',target_count:S.cap,reserve_count:liveCommittee.rule?.reserve_count||0,quotas:S.mode==='POOL'?specialties.map((s,i)=>({specialty_id:s.id,final_count:S.q[i]})).filter(q=>q.final_count>0):[],version:liveCommittee.rule?.version||0});await loadCommittee(0);toast('선정 규칙을 저장했어요');});
Live.capture('#draw','click',async()=>{await Live.api('DRAW-02',{project_id:Live.pid,rule_version:liveCommittee.rule.version});await loadCommittee(1);toast('3배수 명단을 저장했어요');});
Live.capture('#dl','click',()=>Live.api('DRAW-03',{project_id:Live.pid,draw_id:liveCommittee.draw.id},'선정명단.xlsx'));
Live.capture('[data-st],[data-memo]','change',async(_e,el)=>{const i=Number(el.dataset.st??el.dataset.memo),n=liveCommittee.items[i];await Live.api('ROS-03',{project_id:Live.pid,nominee_id:n.id,version:n.version,contact_status:el.dataset.st!==undefined?Object.keys(statusNames).find(k=>statusNames[k]===el.value):n.contact_status,contact_note:el.dataset.memo!==undefined?el.value:n.contact_note||''});await loadCommittee(2);toast('통화 결과를 저장했어요');});
Live.capture('[data-ex]','click',(_e,el)=>{excludeIndex=Number(el.dataset.ex);exclude(excludeIndex);});
Live.capture('#xo','click',async()=>{const n=liveCommittee.items[excludeIndex];await Live.api('ROS-04',{project_id:Live.pid,nominee_id:n.id,version:n.version,reason:$('#xr').value+($('#xm').value?' · '+$('#xm').value:'')});closeLayer($('#p'));await loadCommittee(2);toast('후보를 제외했어요');});
Live.capture('#addc','click',()=>{addCand();$('#p-body p').textContent='부서 풀에서 사업 후보로 추가합니다. 신규 위원은 왼쪽 위원 풀에서 이 사업 직접 등록을 선택하세요.';
 $('#p-body tbody').innerHTML=liveCandidates.map((candidate,i)=>`<tr><td class="strong">${h(candidate.name)}</td><td>${FIELDS[Math.max(0,specialties.findIndex(s=>s.id===candidate.specialty_ids[0]))]}</td><td class="tnum">010-****-${h(candidate.phone.slice(-4))}</td><td style="text-align:right">${liveCommittee.items.some(n=>n.candidate_id===candidate.id)?'<span class="badge success">✓ 추가됨</span>':`<button class="btn sm" type="button" data-a="${i}">추가</button>`}</td></tr>`).join('');
});
Live.capture('#p [data-a]','click',async(_e,el)=>{const n=liveCandidates[Number(el.dataset.a)];await Live.api('ROS-02',{project_id:Live.pid,candidate_id:n.id});closeLayer($('#p'));await loadCommittee(2);});
Live.capture('#dlg-ok','click',async()=>{
 const members=Object.entries(S.pick).filter(([_i,p])=>p).map(([i,p])=>({nominee_id:liveCommittee.items[Number(i)].id,version:liveCommittee.items[Number(i)].version,member_kind:p==='본'?'PRIMARY':'RESERVE',reserve_order:p==='예비'?S.ord[i]:null}));
 await Live.api('ROS-05',{project_id:Live.pid,rule_version:liveCommittee.rule.version,members,reserve_count:members.filter(m=>m.member_kind==='RESERVE').length});closeAll();await loadCommittee(3);toast('위원 명단을 확정했어요');
});
Live.capture('#rf','click',()=>loadCommittee(3));
Live.capture('#dlr','click',()=>Live.api('ROS-06',{project_id:Live.pid,roster_id:liveCommittee.roster.id},'확정명단.xlsx'));
