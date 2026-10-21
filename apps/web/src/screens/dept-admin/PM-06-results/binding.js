if(!Live.pid)throw Error('사업 목록에서 사업을 선택해 주세요.');
const resultSessions=(await Live.get('/api/v2/result-sessions/'+encodeURIComponent(Live.pid))).sessions;
let resultSession=resultSessions.find(s=>s.status!=='CANCELLED');
let resultData=resultSession?await Live.api('RES-01',{session_id:resultSession.id}):{participant_count:0,submitted_count:0};
N=resultData.participant_count;SUB=resultData.submitted_count;pendingMembers=(resultData.pending_members||[]).map(member=>member.name);st=resultData.session?.status==='FINALIZED'?'final':N>0&&SUB===N?'preview':'before';
calc=function(){return (resultData.items||[]).map(item=>{const inputs=resultData.inputs.filter(i=>i.session_proposal_id===item.session_proposal_id);return {name:h(item.display_code),s:inputs.map(i=>i.total_score/10000),imx:inputs.findIndex(i=>i.exclusion==='HIGHEST'),imn:inputs.findIndex(i=>i.exclusion==='LOWEST'),avg:Number(item.average_decimal),rank:item.rank};});};
const originalResultsRender=render;
function formatSubmittedAt(value){
  if(!value)return '';
  const date=new Date(value);
  if(Number.isNaN(date.getTime()))return '';
  return new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date)+' (한국 시간)';
}
render=function(){originalResultsRender();if(st==='final'){const badge=$('.facts .badge');if(badge){const submittedAt=formatSubmittedAt(resultData.session.closed_at);badge.textContent='✓ 위원장 최종 제출'+(submittedAt?' · '+submittedAt:'');}$$('.rk tbody tr').forEach((tr,i)=>{tr.querySelector('.no').textContent=resultData.items[i].rank+'위';});}const progress=$('.prog i');if(!N&&progress)progress.style.width='0%';};
render();
const resultTimer=setInterval(async()=>{
  if(document.hidden)return;
  try{
    const sessions=(await Live.get('/api/v2/result-sessions/'+encodeURIComponent(Live.pid))).sessions;
    const nextSession=sessions.find(s=>s.status!=='CANCELLED');
    if(!nextSession)return;
    const next=await Live.api('RES-01',{session_id:nextSession.id});
    const names=(next.pending_members||[]).map(member=>member.name);
    if(nextSession.id!==resultSession?.id||next.submitted_count!==SUB||next.session?.status!==resultData.session?.status||JSON.stringify(names)!==JSON.stringify(pendingMembers)){
      resultSession=nextSession;resultData=next;N=next.participant_count;SUB=next.submitted_count;pendingMembers=names;
      st=next.session?.status==='FINALIZED'?'final':N>0&&SUB===N?'preview':'before';render();
    }
  }catch{clearInterval(resultTimer);}
},5000);
window.addEventListener('pagehide',()=>clearInterval(resultTimer),{once:true});
Live.capture('[data-pre]','click',()=>{throw Error('실제 제출 상태로만 표시합니다.');});
// RES-05: 담당자는 공식 집계표(xlsx)와 결재·보고용 평가결과 보고서(HTML, 서명 증빙 별첨 포함). 같은 액션에 format만 다르다.
Live.capture('#dl','click',async()=>{await Live.api('RES-05',{session_id:resultSession.id,format:'xlsx'},reportName('xlsx'));await Live.api('RES-05',{session_id:resultSession.id},reportName('html'));toast('집계표(xlsx)와 평가결과 보고서(html)를 내려받았어요');});
