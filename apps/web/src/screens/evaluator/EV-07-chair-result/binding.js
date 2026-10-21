const chairSession=Live.boot.sessions.find(s=>s.status!=='CANCELLED');
if(!chairSession)throw Error('평가회차가 아직 준비되지 않았습니다.');
let chairData=await Live.api('RES-01',{session_id:chairSession.id}),chairSignature=null;
if(!chairData.is_chair)throw Error('지정된 평가위원장만 결과를 확인할 수 있습니다.');
const originalChairRender=render;
shell=function(){EvalShell.setChair(true);EvalShell.setUnlocked(mode!=='before');EvalShell.mount($('#hd'),{active:'chair',project:Live.boot.projects[0]?.name,user:Live.boot.actor.name,chat:false});mounted=true;};
f1=n=>Number(n).toFixed(2);
const chairTime=iso=>{const d=new Date(iso);if(!iso||isNaN(d))return iso||'';const z=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())} 제출`;};
render=function(){
 originalChairRender();
 if(mode==='before'){const done=chairData.submitted_count;root.querySelector('h2').textContent=`제출 ${done}/${N}`;root.querySelector('.ch-prog').setAttribute('aria-label',`위원 ${N}명 중 ${done}명 제출`);root.querySelectorAll('.ch-prog i').forEach((e,i)=>e.classList.toggle('on',i<done));root.querySelector('.ch-lock small').textContent=`아직 제출하지 않은 위원이 ${N-done}명 있어요`;}
 if(mode==='after')root.querySelector('.ch-act p').textContent=`위원 ${N}명이 모두 제출했어요 (${N}/${N})`;
 // 최종 제출 카드: FINALIZED 배지 없이 제출 시각(로컬 시간)과 '이제 바꿀 수 없어요'를 각각 한 줄로 (2026-10-18 사용자 요청). 위쪽 상태 배지도 한글로.
 if(mode==='done'){const p=root.querySelector('.ch-ok p');if(p){const when=document.createElement('p');when.textContent=chairTime(submittedAt);const note=document.createElement('p');note.textContent='이제 바꿀 수 없어요';p.replaceWith(when,note);}const top=root.querySelector('.ch-top .ch-st.fin');if(top)top.textContent='최종 제출 완료';}
 if(mode==='result'||mode==='done'){
  const avg=root.querySelector('.avg th small');if(avg)avg.textContent=`최고·최저 제외 ${N-2}명`;
  root.querySelectorAll('.avg td small').forEach((el,i)=>{const r=R[V[i]];el.textContent=`(${r.sum} − ${r.mx} − ${r.mn}) ÷ ${N-2}`;});
  root.querySelector('.ch-formula b').textContent=`평균 = (합계 − 최고 − 최저) ÷ ${N-2}`;
  const rec=root.querySelectorAll('.ch-rec span');if(rec[1])rec[1].lastChild.textContent=` ${N-2}명 = 위원 ${N}명 − 최고 1 − 최저 1`;if(rec[2])rec[2].lastChild.textContent=' 평균 동점은 공동 순위, 최저·최고 동점 제외 대상은 참여자 ID 순서';
  const signedNote=root.querySelector('.ch-signed');if(signedNote)signedNote.textContent='서명을 저장했어요 · 현재 확인한 결과에만 유효해요';
 }
};
function applyChairData(){
 N=chairData.participant_count;mode=chairData.session.status==='FINALIZED'?'done':chairData.run?'result':chairData.session.status==='ALL_SUBMITTED'?'after':'before';submittedAt=chairData.session.closed_at||'';
 V=(chairData.items||[]).map(i=>i.display_code);NAME=Object.fromEntries(V.map(v=>[v,Live.escape(v)]));R={};SC={};rankOf={};
 for(const item of chairData.items||[]){const v=item.display_code,inputs=chairData.inputs.filter(i=>i.session_proposal_id===item.session_proposal_id);SC[v]=inputs.map(i=>i.total_score/10000);const hi=inputs.findIndex(i=>i.exclusion==='HIGHEST'),lo=inputs.findIndex(i=>i.exclusion==='LOWEST');R[v]={hi,lo,mx:SC[v][hi],mn:SC[v][lo],sum:SC[v].reduce((a,b)=>a+b,0),avg:Number(item.average_decimal)};rankOf[v]=item.rank;}order=V.slice();render();
}
applyChairData();
Live.capture('#agg','click',async()=>{await Live.api('RES-02',{session_id:chairSession.id});chairData=await Live.api('RES-01',{session_id:chairSession.id});applyChairData();});
Live.capture('#sg','click',async()=>{if(!checked||!pad?.hasInk())throw Error('결과를 확인하고 서명하세요.');chairSignature=await Live.api('RES-03',{session_id:chairSession.id,result_run_id:chairData.run.id,purpose:'CHAIR_RESULT',payload_sha256:chairData.payload_sha256,image:$('#pad').toDataURL('image/png'),consent:true,consent_text_version:'signature-v2'});signed=true;render();});
Live.capture('.ev-modal [data-g="go"]','click',async()=>{if(!chairSignature||!checked)throw Error('확인과 서명이 필요합니다.');await Live.api('RES-04',{session_id:chairSession.id,result_run_id:chairData.run.id,signature_id:chairSignature.id,payload_sha256:chairData.payload_sha256});closeConfirm(true);chairData=await Live.api('RES-01',{session_id:chairSession.id});applyChairData();});
function chairReportName(){
 const name=(Live.boot.projects[0]?.name||'사업').trim().replace(/[\\/:*?"<>|]/g,'_');
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(part=>[part.type,part.value]));
 return `${name}_정성평가_${parts.year}${parts.month}${parts.day}.html`;
}
Live.capture('#dl','click',()=>Live.api('RES-05',{session_id:chairSession.id},chairReportName()));
