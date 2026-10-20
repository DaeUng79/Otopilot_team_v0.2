let liveScore,liveReview,liveSignature;
const sessionId=Live.boot.sessions.find(s=>s.status!=='CANCELLED')?.id;
if(!Live.evaluatorState().canScore){V=[];CRIT=[];MAXPTS=0;S.vals={};S.ops={};S.saved={};S.savedOps={};S.submitted=true;render();$('.sc-ctx').textContent=Live.boot.projects[0]?.name||'';const waiting=Live.evaluatorState().session?.status==='OPEN'?'평가인원에 포함되지 않았습니다. 담당자에게 확인하세요.':'평가 시작 전 · 담당자의 참석 인원 확정·위원장 지정·평가 시작을 기다리고 있습니다.';$('#chip').textContent='평가 시작 전';bar.querySelector('.sc-done-note').textContent=waiting;document.documentElement.dataset.waitingEvaluation='true';EvalShell.mount($('#hd'),{active:'scoring',project:Live.boot.projects[0]?.name,user:Live.boot.actor.name,chat:false});Live.finish();return;}
const originalScoreRender=render;
check=function(c,raw){if(raw===''||raw==null)return '';const n=Number(raw),scaled=Math.round(n*10000);if(!Number.isFinite(n)||n<0||n>c.pts)return `0~${c.pts}점 사이로 써 주세요`;if(Math.abs(n*10000-scaled)>0.00001||scaled%c.step!==0)return `${c.step/10000}점 단위로 써 주세요`;return '';};
render=function(){originalScoreRender();$('.sc-ctx').textContent=Live.boot.projects[0]?.name||'';root.querySelectorAll('[data-c]').forEach(el=>el.step=critOf(el.dataset.c).step/10000);const guide=root.querySelector('.sc-guide');if(guide)guide.textContent+=' 점수 칸에서는 방향키로 이동할 수 있어요.';};
root.addEventListener('keydown',e=>{
 const input=e.target.closest?.('.sc-score input[data-k]');
 if(!input||input.disabled||e.altKey||e.ctrlKey||e.metaKey||e.isComposing||!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))return;
 const rows=[...root.querySelectorAll('.sc-tbl tbody tr')],row=input.closest('tr'),rowIndex=rows.indexOf(row);
 const cells=[...row.querySelectorAll('.sc-score input[data-k]')],columnIndex=cells.indexOf(input);
 const nextRow=e.key==='ArrowUp'?rowIndex-1:e.key==='ArrowDown'?rowIndex+1:rowIndex;
 const nextColumn=e.key==='ArrowLeft'?columnIndex-1:e.key==='ArrowRight'?columnIndex+1:columnIndex;
 const target=rows[nextRow]?.querySelectorAll('.sc-score input[data-k]')[nextColumn];
 e.preventDefault();
 if(target&&!target.disabled)target.focus();
});
async function loadScores(){
 await Live.reload();
 liveScore=await Live.api('SCO-01',{session_id:sessionId});
 V=liveScore.sheets.map(s=>s.display_code);CRIT=(liveScore.sheets[0]?.entries||[]).map(e=>({id:e.criterion_id,name:esc(e.title),pts:e.max_score_snapshot/10000,step:e.score_step}));MAXPTS=CRIT.reduce((a,c)=>a+c.pts,0);
 D={NAME:Object.fromEntries(V.map(v=>[v,esc(v)])),MATCH:Object.fromEntries(CRIT.map(c=>[c.id,Object.fromEntries(V.map(v=>[v,null]))]))};
 V.forEach(v=>{DOTS[v]=DOTS[v]||['#256ef4','#ecf2fe'];});
 S={vals:{},ops:{},saved:{},savedOps:{},savedAt:'',fail:false,failed:false,submitted:liveScore.sheets.length>0&&liveScore.sheets.every(s=>s.status==='SUBMITTED'),submittedAt:'',errs:{},signed:null,opOpen:false};
 for(const sh of liveScore.sheets){S.ops[sh.display_code]=sh.opinion||'';for(const e of sh.entries)S.vals[key(sh.display_code,e.criterion_id)]=e.score===null?'':String(e.score/10000);}
 S.saved={...S.vals};S.savedOps={...S.ops};render();
 EvalShell.setChair(liveScore.participant.id===liveScore.session.chair_participant_id);EvalShell.mount($('#hd'),{active:'scoring',project:Live.boot.projects[0]?.name,user:Live.boot.actor.name,chat:false});
 if(!liveScore.sheets.length)throw Error('담당자가 평가를 시작한 뒤 점수를 입력할 수 있습니다.');
}
await loadScores();
save=async function(){
 if(invalidN())throw Error('점수 범위와 간격을 확인하세요.');
 for(const sh of liveScore.sheets){const result=await Live.api('SCO-02',{session_id:sessionId,sheet_id:sh.id,version:sh.version,opinion:S.ops[sh.display_code]||'',entries:sh.entries.map(e=>({criterion_id:e.criterion_id,score:S.vals[key(sh.display_code,e.criterion_id)]===''?null:Math.round(Number(S.vals[key(sh.display_code,e.criterion_id)])*10000),comment:e.comment}))});sh.version=result.version;for(const e of sh.entries)S.saved[key(sh.display_code,e.criterion_id)]=S.vals[key(sh.display_code,e.criterion_id)];S.savedOps[sh.display_code]=S.ops[sh.display_code]||'';}
 S.savedAt=now();S.failed=false;S.signed=null;liveSignature=null;refresh();toast('평가표를 저장했어요');return true;
};
Live.capture('[data-a="save"],[data-g="save"]','click',async()=>{try{await save();if(layer)stepCheck();}catch(e){S.failed=true;refresh();throw e;}});
document.addEventListener('keydown',async e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();e.stopImmediatePropagation();if(S.submitted)return;try{await save();}catch(error){S.failed=true;refresh();Live.message(error.message);}}},true);
Live.capture('[data-a="submit"]','click',async()=>{liveReview=await Live.api('SCO-03',{session_id:sessionId});stepCheck();});
Live.capture('.ev-modal [data-g="next"]','click',async()=>{
 if(layer?.querySelector('#pad')){
  if(!pad?.hasInk())throw Error('서명을 입력해 주세요.');
  liveSignature=await Live.api('SCO-04',{session_id:sessionId,purpose:'EVALUATION',payload_sha256:liveReview.payload_sha256,image:layer.querySelector('#pad').toDataURL('image/png'),consent:true,consent_text_version:'signature-v2'});S.signed=hash();stepConfirm();
 }else{if(dirtyN()||invalidN()||empties().length)throw Error('모든 점수를 저장하고 확인하세요.');liveReview=await Live.api('SCO-03',{session_id:sessionId});stepSign();}
});
Live.capture('.ev-modal [data-g="go"]','click',async()=>{if(!liveSignature)throw Error('서명이 필요합니다.');await Live.api('SCO-05',{session_id:sessionId,signature_id:liveSignature.id,payload_sha256:liveReview.payload_sha256});closeLayer(true);await loadScores();toast('평가를 제출했어요');});
