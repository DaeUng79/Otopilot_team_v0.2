if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
let liveCommittee,liveCandidates=[],excludeIndex=null;
const specialties=Live.boot.specialties,department=Live.boot.projects.find(p=>p.id===Live.pid).department_id;
const fullPhone=value=>{const digits=String(value||'').replace(/\D/g,'');return digits.length===11?`${digits.slice(0,3)}-${digits.slice(3,7)}-${digits.slice(7)}`:digits.length===10?`${digits.slice(0,3)}-${digits.slice(3,6)}-${digits.slice(6)}`:String(value||'');};
function rosterFilename(kind){
 const project=Live.boot.projects.find(p=>p.id===Live.pid)?.name||'프로젝트';
 const safe=project.replace(/[\\/:*?"<>|\u0000-\u001f]/g,' ').replace(/\s+/g,' ').trim().replace(/[. ]+$/,'').slice(0,80)||'프로젝트';
 return `${safe}_${kind}.xlsx`;
}
FIELDS.splice(0,FIELDS.length,...specialties.map(s=>h(s.name)));
// 통화 결과는 화면에서 완료/미완료 두 가지로 단순화(2026-10-18 사용자 요청). 서버 상태값은 그대로: 완료=AVAILABLE, 미완료=NOT_CONTACTED. 거절·부재는 [제외]로 처리.
const statusNames={NOT_CONTACTED:'미연락',AVAILABLE:'수락',UNAVAILABLE:'미연락',CALLBACK:'미연락'};
function simplifyContact(){
 if(S.stg!==2)return;
 const th=$$('#stage thead th').find(t=>t.textContent.trim()==='통화 결과');if(th)th.textContent='통화 완료';
 $$('#stage select[data-st]').forEach(sel=>{const i=sel.dataset.st,c=S.cands.find(x=>String(x.id)===i),done=c?.st==='수락';const label=document.createElement('label');label.style.cssText='display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-weight:700;min-height:40px;color:'+(done?'var(--success-60)':'var(--text-3)');label.innerHTML=`<input class="cb" type="checkbox" data-done="${i}" ${done?'checked':''} aria-label="${h(c?.name||'')} 통화 완료">${done?'완료':'미완료'}`;sel.replaceWith(label);});
 const live=S.cands.filter(c=>!c.ex),done=live.filter(c=>c.st==='수락').length;
 const chips=$('#cst');if(chips){chips.innerHTML=[['','전체'],['수락',`완료 ${done}`],['미연락',`미완료 ${live.length-done}`]].map(([v,t])=>`<button class="chip" type="button" data-s="${v}" aria-pressed="${(S.fst||'')===v}">${t}</button>`).join('');$$('#cst .chip').forEach(b=>b.onclick=()=>{S.fst=b.dataset.s;render()});}
 const why=$('#foot .why');if(why)why.innerHTML=`통화 완료 <b>${done}명</b> · 미완료 ${live.length-done}명 (본위원 5~9명 + 예비 1~3명이 필요해요)`;
 const hint=$('#stage p.muted');if(hint)hint.textContent='전화는 직접 걸어요. 참석하겠다고 하면 체크(완료), 아니면 비워 두거나 [제외]를 눌러요(자동 통화 없음).';
}
function relabelRoster(){
 if(S.stg!==3)return;
 $$('#stage .lstcard p.muted').forEach(p=>{p.textContent=p.textContent.replace(/수락 (\d+) · 거절 \d+ · 부재 \d+ · 미연락 (\d+)/,'통화 완료 $1 · 미완료 $2');});
 $$('#stage .badge').forEach(b=>{if(b.textContent==='수락')b.textContent='완료';else if(b.textContent==='미연락')b.textContent='미완료';});
 const why=$('#foot .why');if(why)why.textContent=why.textContent.replace('수락한','통화 완료한');
}
// 명단 확정: 지정 드롭다운 대신 [본위원]·[예비] 체크박스, 예비 순서는 체크한 순서대로 자동(2026-10-18 사용자 요청).
// 본위원 정원: 직접 선정(DIRECT)은 담당자가 체크한 인원(5~9명)이 곧 정원이고 확정 때 규칙을 자동으로 맞춘다.
// 풀 추첨(POOL)은 분야별 배분이 정원에 묶여 있어 규칙의 정원을 그대로 쓴다. 예비위원은 1~3명(권장 2명).
const CAP_MIN=5,CAP_MAX=9,RESERVE_MIN=1,RESERVE_MAX=3;
function simplifyRoster(){
 if(S.stg!==3||S.rost!=='none')return;
 const acc=S.cands.filter(c=>!c.ex&&c.st==='수락'),primaries=acc.filter(c=>S.pick[c.id]==='본').length,reserves=acc.filter(c=>S.pick[c.id]==='예비').length;
 if(S.mode==='DIRECT'&&primaries>=CAP_MIN&&primaries<=CAP_MAX&&S.cap!==primaries){S.cap=primaries;render();return;}
 const capLimit=S.mode==='DIRECT'?CAP_MAX:S.cap;
 const ths=$$('#stage thead th');const th=ths.find(t=>t.textContent.trim()==='지정');if(th)th.textContent='본위원 / 예비위원';const th2=ths.find(t=>t.textContent.trim()==='예비 순서');if(th2)th2.textContent='예비 순서(체크한 순)';
 $$('#stage select[data-pk]').forEach(sel=>{const id=sel.dataset.pk,c=S.cands.find(x=>String(x.id)===id),pick=S.pick[id]||'';
  const box=(kind,label,checked,disabled)=>`<label title="${disabled?(kind==='본'?`본위원은 ${capLimit}명까지예요`:`예비위원은 ${RESERVE_MAX}명까지예요`):''}" style="display:inline-flex;align-items:center;gap:6px;cursor:${disabled?'not-allowed':'pointer'};font-weight:700;color:${checked?'var(--primary-60)':disabled?'var(--gray-30)':'var(--text-3)'}"><input class="cb" type="checkbox" data-pick-kind="${kind}" data-pick-id="${id}" ${checked?'checked':''} ${disabled?'disabled':''} aria-label="${h(c?.name||'')} ${label}">${label}</label>`;
  const wrap=document.createElement('div');wrap.style.cssText='display:flex;gap:18px;align-items:center;min-height:40px';
  wrap.innerHTML=box('본','본위원',pick==='본',pick!=='본'&&primaries>=capLimit)+box('예비','예비',pick==='예비',pick!=='예비'&&reserves>=RESERVE_MAX);
  sel.replaceWith(wrap);});
 $$('#stage select[data-od]').forEach(sel=>{const span=document.createElement('span');span.className='tnum strong';span.textContent=S.ord[sel.dataset.od]?`예비 ${S.ord[sel.dataset.od]}`:'—';sel.replaceWith(span);});
 // 점검표 첫 항목(본위원 수)을 선택 방식에 맞게 다시 쓴다.
 const first=$('#stage .chk li');
 if(first&&S.mode==='DIRECT'){const ok=primaries>=CAP_MIN&&primaries<=CAP_MAX;first.className=ok?'okc':'badc';first.querySelector('.ic').textContent=ok?'✓':'!';first.querySelector('b').textContent='본위원 수 (5~9명)';first.querySelector('.muted').textContent=ok?`${primaries}명 · 이 인원이 정원이 돼요`:`${primaries}명 · 5~9명을 체크해 주세요`;}
 const fieldCheck=$$('#stage .chk li')[1];
 if(fieldCheck){
  const remaining=FIELDS.map((f,i)=>({name:f,count:S.q[i]-acc.filter(c=>S.pick[c.id]==='본'&&c.f===i).length})).filter(f=>f.count!==0);
  fieldCheck.querySelector('.muted').textContent=remaining.length?remaining.map(f=>`${f.name} ${f.count>0?`${f.count}명 더 선택`:`${-f.count}명 초과`}`).join(' · '):'필요한 분야별 본위원을 모두 선택했어요';
 }
 // 확정 버튼 활성화는 점검표 결과로 다시 정한다(원본은 고정 정원 기준).
 const blockers=$$('#stage .chk li.badc').map(li=>`${li.querySelector('b')?.textContent||''} — ${li.querySelector('.muted')?.textContent||''}`);
 const cf=$('#cf');if(cf)cf.disabled=blockers.length>0;
 const why=$('#foot .why');if(why){why.innerHTML=blockers.length?`<span class="err" style="font-weight:700">확정하려면: ${h(blockers.join(' / '))}</span>`:`본위원 ${primaries}명 + 예비 ${reserves}명 (통화 완료 ${acc.length}명 중). 확정할 수 있어요.`;}
 if(blockers.length&&acc.length<CAP_MIN+RESERVE_MIN){const note=document.createElement('p');note.className='muted';note.style.cssText='margin:8px 0 0';note.textContent=`통화 완료 ${acc.length}명으로는 본위원 ${CAP_MIN}명 + 예비 ${RESERVE_MIN}명을 채울 수 없어요. ③ 연락·초청에서 완료 인원을 늘리세요.`;$('#stage .side2')?.appendChild(note);}
}
Live.capture('[data-pick-kind]','change',(_e,el)=>{const id=el.dataset.pickId,kind=el.dataset.pickKind;
 if(el.checked){S.pick[id]=kind;if(kind==='예비')S.ord[id]=Object.keys(S.pick).filter(k=>S.pick[k]==='예비'&&k!==id).length+1;else delete S.ord[id];}
 else{S.pick[id]='';delete S.ord[id];}
 Object.keys(S.pick).filter(k=>S.pick[k]==='예비').sort((a,b)=>(S.ord[a]||99)-(S.ord[b]||99)).forEach((k,i)=>S.ord[k]=i+1);
 render();});
const originalCommitteeRender=render;
let renderedCommitteeStage=null;
render=function(){
 const sameStage=renderedCommitteeStage===S.stg;
 const scrollTop=sameStage?$('#stage .stg')?.scrollTop:undefined;
 if(S.mode==='DIRECT'&&S.stg===3)S.q=FIELDS.map((_f,i)=>S.cands.filter(c=>c.f===i&&S.pick[c.id]==='본').length);
 originalCommitteeRender();simplifyContact();simplifyRoster();relabelRoster();
 if(S.rost!=='none'){$$('#stage select,#stage input,#stage [data-ex]').forEach(e=>e.disabled=true);}
 if(S.drawn&&S.rost==='none'){
  const reset=document.createElement('button');reset.type='button';reset.className='btn';
  reset.id='reset-draw';reset.textContent='추첨 취소 · 다시 선정';
  $('#foot').append(reset);
 }
 if(scrollTop!==undefined)$('#stage .stg').scrollTop=scrollTop;
 renderedCommitteeStage=S.stg;
};
Live.capture('[data-done]','change',async(_e,el)=>{
 const n=liveCommittee.items[Number(el.dataset.done)],checked=el.checked;
 const view={fst:S.fst,ffd:S.ffd,stage:$('#stage .stg')?.scrollTop||0,list:$('#stage .box.call')?.scrollTop||0,page:window.scrollY};
 try{await Live.api('ROS-03',{project_id:Live.pid,nominee_id:n.id,version:n.version,contact_status:checked?'AVAILABLE':'NOT_CONTACTED',contact_note:n.contact_note||''});}
 finally{
  await loadCommittee(2,view);
  requestAnimationFrame(()=>{const stage=$('#stage .stg'),list=$('#stage .box.call');if(stage)stage.scrollTop=view.stage;if(list)list.scrollTop=view.list;window.scrollTo(0,view.page);});
 }
 toast(checked?'통화 완료로 저장했어요':'미완료로 바꿨어요');
});
async function loadCommittee(stage,view){
 liveCommittee=await Live.get('/committee-v2/api/projects/'+encodeURIComponent(Live.pid));
 const rule=liveCommittee.rule;
 const mode=rule?.selection_mode==='DIRECT'?'DIRECT':'POOL';
 liveCandidates=await Live.all('COM-01',{department_id:department,scope:'DEPARTMENT_POOL',active:true});
 POOLN.ok=specialties.map(s=>liveCandidates.filter(c=>c.specialty_ids.includes(s.id)).length);
 const members=liveCommittee.items.map((n,i)=>{const drawField=liveCommittee.draw_members.find(d=>d.id===n.draw_member_id)?.specialty_id;return {id:i,name:n.candidate.name,f:Math.max(0,specialties.findIndex(s=>s.id===(drawField||n.candidate.specialty_ids[0]))),phone:fullPhone(n.candidate.phone),l4:n.candidate.phone.slice(-4),st:statusNames[n.contact_status],memo:n.contact_note||'',src:mode==='DIRECT'?'직접':'추첨',ex:n.exclusion_reason};});
 const q=specialties.map(s=>liveCommittee.quotas.find(q=>q.specialty_id===s.id)?.final_count||0);
 if(!rule){const firstAvailable=POOLN.ok.findIndex(count=>count>0);if(firstAvailable>=0)q[firstAvailable]=7;}
 const picks={},orders={};for(const a of liveCommittee.assignments){const i=liveCommittee.items.findIndex(n=>n.id===a.nominee_id);picks[i]=a.member_kind==='PRIMARY'?'본':'예비';orders[i]=a.reserve_order;}
 S={...base(),mode,cap:rule?.target_count||7,q,saved:!!rule,drawn:!!liveCommittee.draw,cands:members,stg:stage??(liveCommittee.roster?3:rule?2:0),pick:picks,ord:orders,rost:liveCommittee.roster?(liveCommittee.handoff?.status==='SENT'?'ready':'sent'):'none'};
 if(view){S.fst=view.fst;S.ffd=view.ffd;}
 DIRPOOL.splice(0,DIRPOOL.length,...liveCandidates.map(c=>[h(c.name),Math.max(0,specialties.findIndex(s=>s.id===c.specialty_ids[0])),c.phone.slice(-4)]));render();
}
await loadCommittee();
// 선정 방식을 바꾸면 이전 방식으로 등록한 사업 후보(통화 결과·제외 기록 포함)는 지워진다(DRAW-01 clear_nominees).
// 추첨 뒤·명단 확정 뒤에는 서버가 거부한다. 담당자가 확인창에서 동의했을 때만 보낸다. (2026-10-18)
Live.capture('#save','click',async()=>{
 const rule=liveCommittee.rule,mode=S.mode==='POOL'?'POOL_RANDOM':'DIRECT',switching=!!rule&&rule.selection_mode!==mode,count=liveCommittee.items.length;
 if(switching&&count&&!confirm(`선정 방식을 '${S.mode==='POOL'?'풀에서 추첨':'직접 선정'}'으로 바꾸면 지금까지 등록한 사업 후보 ${count}명과 통화 결과·제외 기록이 지워져요.

계속할까요?`))return;
 const saved=await Live.api('DRAW-01',{project_id:Live.pid,selection_mode:mode,target_count:S.cap,reserve_count:rule?.reserve_count||0,quotas:S.mode==='POOL'?specialties.map((s,i)=>({specialty_id:s.id,final_count:S.q[i]})).filter(q=>q.final_count>0):[],version:rule?.version||0,clear_nominees:switching});
 await loadCommittee(0);
 toast(saved?.cleared_nominees?`선정 규칙을 저장했어요 · 이전 후보 ${saved.cleared_nominees}명을 정리했어요`:'선정 규칙을 저장했어요');
});
Live.capture('#draw','click',async()=>{await Live.api('DRAW-02',{project_id:Live.pid,rule_version:liveCommittee.rule.version});await loadCommittee(1);toast('3배수 명단을 저장했어요');});
Live.capture('#reset-draw','click',async()=>{
 if(!confirm('현재 추첨을 취소하고 다시 선정할까요? 추첨 기록은 보존되지만 이 추첨의 후보·통화 기록·본위원·예비 선택은 초기화됩니다. 명단 확정 전까지만 가능합니다.'))return;
 const rule=liveCommittee.rule;
 await Live.api('DRAW-01',{project_id:Live.pid,selection_mode:rule.selection_mode,
  target_count:rule.target_count,reserve_count:rule.reserve_count,
  quotas:liveCommittee.quotas.map(q=>({specialty_id:q.specialty_id,final_count:q.final_count})),
  version:rule.version,clear_nominees:true});
 await loadCommittee(0);toast('기존 추첨을 취소했어요. 규칙과 후보를 조정한 뒤 다시 선정할 수 있어요.');
});
Live.capture('#dl','click',()=>Live.api('DRAW-03',{project_id:Live.pid,draw_id:liveCommittee.draw.id},rosterFilename('선정명단')));
Live.capture('[data-st],[data-memo]','change',async(_e,el)=>{const i=Number(el.dataset.st??el.dataset.memo),n=liveCommittee.items[i];await Live.api('ROS-03',{project_id:Live.pid,nominee_id:n.id,version:n.version,contact_status:el.dataset.st!==undefined?Object.keys(statusNames).find(k=>statusNames[k]===el.value):n.contact_status,contact_note:el.dataset.memo!==undefined?el.value:n.contact_note||''});await loadCommittee(2);toast('통화 결과를 저장했어요');});
Live.capture('[data-ex]','click',(_e,el)=>{$('#p').style.width='';excludeIndex=Number(el.dataset.ex);exclude(excludeIndex);});
Live.capture('#xo','click',async()=>{const n=liveCommittee.items[excludeIndex];await Live.api('ROS-04',{project_id:Live.pid,nominee_id:n.id,version:n.version,reason:$('#xr').value+($('#xm').value?' · '+$('#xm').value:'')});closeLayer($('#p'));await loadCommittee(2);toast('후보를 제외했어요');});
Live.capture('[data-restore]','click',async(_e,el)=>{
 const n=liveCommittee.items[Number(el.dataset.restore)];
 const view={fst:S.fst,ffd:S.ffd,stage:$('#stage .stg')?.scrollTop||0,list:$('#stage .box.call')?.scrollTop||0};
 await Live.api('ROS-04',{project_id:Live.pid,nominee_id:n.id,version:n.version,reason:null});
 await loadCommittee(2,view);
 const stage=$('#stage .stg'),list=$('#stage .box.call');
 if(stage)stage.scrollTop=view.stage;if(list)list.scrollTop=view.list;
 toast('후보 제외를 취소했어요.');
});
// ROS-02 사업 후보 추가: 넓은 창에서 검색 + 여러 명 체크 → 한 번에 저장 (2026-10-18 사용자 요청)
let pickSet=new Set(),pickQuery='';
const fieldNames=c=>c.specialty_ids.map(id=>specialties.find(s=>s.id===id)?.name||id).join(', ');
function renderPick(){
 const have=new Set(liveCommittee.items.map(n=>n.candidate_id)),q=pickQuery.trim();
 const rows=liveCandidates.map((c,i)=>({c,i})).filter(({c})=>!q||[c.name,c.organization_name,c.position||'',fieldNames(c)].join(' ').includes(q));
 $('#p-body tbody').innerHTML=rows.length?rows.map(({c,i})=>{const added=have.has(c.id);return `<tr style="${added?'color:var(--text-3)':''}"><td style="width:48px"><input class="cb" type="checkbox" data-pick="${i}" ${added?'disabled checked':pickSet.has(i)?'checked':''} aria-label="${h(c.name)} 선택"></td><td class="strong">${h(c.name)}</td><td>${h(c.organization_name)}${c.position?` <span class="muted">${h(c.position)}</span>`:''}</td><td>${h(fieldNames(c))}</td><td class="tnum">${h(fullPhone(c.phone))}</td><td>${added?'<span class="badge success">✓ 추가됨</span>':''}</td></tr>`;}).join(''):'<tr><td colspan="6" class="muted" style="text-align:center;height:80px">맞는 위원이 없어요</td></tr>';
 const visible=rows.filter(({c})=>!have.has(c.id)).length,picked=pickSet.size;
 $('#pick-count').textContent=`${q?`검색 ${rows.length}명 · `:''}추가 가능 ${visible}명${picked?` · 선택 ${picked}명`:''}`;
 const go=$('#addm');if(go){go.disabled=!picked;go.textContent=picked?`선택 ${picked}명 추가`:'위원을 선택하세요';}
 const all=$('#pick-all');if(all){all.checked=visible>0&&rows.every(({c,i})=>have.has(c.id)||pickSet.has(i));all.disabled=!visible;}
}
Live.capture('#addc','click',()=>{addCand();pickSet=new Set();pickQuery='';$('#p').style.width='min(960px,100vw)';
 $('#p-body').innerHTML=`<p class="muted" style="margin-bottom:12px">부서 풀에서 여러 명을 골라 한 번에 사업 후보로 추가합니다. 신규 위원은 위원 풀 화면에서 '이 사업 직접 등록'으로 넣으세요.</p>
  <div class="cfg-row" style="margin-bottom:10px;gap:12px"><label class="sr-only" for="pick-q">검색</label><input id="pick-q" type="search" placeholder="이름·소속·직위·분야 검색" style="max-width:320px"><span class="muted" id="pick-count"></span><label style="margin-left:auto;display:flex;gap:8px;align-items:center;cursor:pointer"><input class="cb" type="checkbox" id="pick-all">보이는 위원 모두 선택</label></div>
  <div class="box" style="max-height:62vh"><table><thead><tr><th></th><th>이름</th><th>소속</th><th>분야</th><th>휴대전화</th><th style="width:96px"></th></tr></thead><tbody></tbody></table></div>`;
 $('#p-foot').innerHTML='<button class="btn" type="button" id="xc">닫기</button><button class="btn primary" type="button" id="addm" disabled>위원을 선택하세요</button>';
 renderPick();setTimeout(()=>$('#pick-q')?.focus(),80);
});
Live.capture('#p #xc','click',()=>{closeLayer($('#p'));$('#p').style.width='';render();});
Live.capture('#p [data-pick]','change',(_e,el)=>{const i=Number(el.dataset.pick);el.checked?pickSet.add(i):pickSet.delete(i);renderPick();});
Live.capture('#pick-all','change',(_e,el)=>{const have=new Set(liveCommittee.items.map(n=>n.candidate_id)),q=pickQuery.trim();
 liveCandidates.forEach((c,i)=>{if(have.has(c.id))return;if(q&&![c.name,c.organization_name,c.position||'',fieldNames(c)].join(' ').includes(q))return;el.checked?pickSet.add(i):pickSet.delete(i);});renderPick();});
document.addEventListener('input',e=>{if(e.target.id==='pick-q'){pickQuery=e.target.value;renderPick();}});
Live.capture('#addm','click',async()=>{
 const picks=[...pickSet];if(!picks.length)throw Error('위원을 선택하세요.');
 let done=0;const failed=[];
 for(const i of picks){const c=liveCandidates[i];try{await Live.api('ROS-02',{project_id:Live.pid,candidate_id:c.id});done++;}catch(error){failed.push(`${c.name}: ${error.message}`);}}
 closeLayer($('#p'));$('#p').style.width='';await loadCommittee(2);
 toast(`${done}명을 사업 후보로 추가했어요${failed.length?` · 실패 ${failed.length}명`:''}`);
 if(failed.length)throw Error(failed.join(' / '));
});
Live.capture('#dlg-ok','click',async()=>{
 const members=Object.entries(S.pick).filter(([_i,p])=>p).map(([i,p])=>({nominee_id:liveCommittee.items[Number(i)].id,version:liveCommittee.items[Number(i)].version,member_kind:p==='본'?'PRIMARY':'RESERVE',reserve_order:p==='예비'?S.ord[i]:null}));
 const primaries=members.filter(m=>m.member_kind==='PRIMARY').length,reserves=members.length-primaries;
 let rule=liveCommittee.rule;
 // 직접 선정: 체크한 본위원 수가 규칙의 정원과 다르면 규칙을 먼저 맞춘다(DRAW-01).
 if(rule.selection_mode==='DIRECT'&&rule.target_count!==primaries){rule=await Live.api('DRAW-01',{project_id:Live.pid,selection_mode:'DIRECT',target_count:primaries,reserve_count:reserves,quotas:[],version:rule.version});}
 await Live.api('ROS-05',{project_id:Live.pid,rule_version:rule.version,members,reserve_count:reserves});closeAll();await loadCommittee(3);toast(`본위원 ${primaries}명 · 예비 ${reserves}명으로 명단을 확정했어요`);
});
Live.capture('#rf','click',()=>loadCommittee(3));
Live.capture('#dlr','click',()=>Live.api('ROS-06',{project_id:Live.pid,roster_id:liveCommittee.roster.id},rosterFilename('확정명단')));
