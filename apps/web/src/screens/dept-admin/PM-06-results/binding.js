if(!Live.pid)throw Error('사업 목록에서 사업을 선택해 주세요.');
const resultSessions=(await Live.get('/api/v2/result-sessions/'+encodeURIComponent(Live.pid))).sessions;
const resultSession=resultSessions.find(s=>s.status!=='CANCELLED');
let resultData=resultSession?await Live.api('RES-01',{session_id:resultSession.id}):{participant_count:0,submitted_count:0};
N=resultData.participant_count;SUB=resultData.submitted_count;st=resultData.session?.status==='FINALIZED'?'final':'before';
calc=function(){return (resultData.items||[]).map(item=>{const inputs=resultData.inputs.filter(i=>i.session_proposal_id===item.session_proposal_id);return {name:h(item.display_code),s:inputs.map(i=>i.total_score/10000),imx:inputs.findIndex(i=>i.exclusion==='HIGHEST'),imn:inputs.findIndex(i=>i.exclusion==='LOWEST'),avg:Number(item.average_decimal),rank:item.rank};});};
const originalResultsRender=render;
render=function(){originalResultsRender();if(st==='final'){const badge=$('.facts .badge');if(badge)badge.textContent='✓ 위원장 최종 제출 '+(resultData.session.closed_at||'');$$('.rk tbody tr').forEach((tr,i)=>{tr.querySelector('.no').textContent=resultData.items[i].rank+'위';});}const progress=$('.prog i');if(!N&&progress)progress.style.width='0%';};
render();
Live.capture('[data-pre]','click',()=>{throw Error('실제 제출 상태로만 표시합니다.');});
// RES-05: 담당자는 공식 집계표(xlsx), 서명 증빙은 HTML. 같은 액션에 format만 다르다.
Live.capture('#dl','click',async()=>{await Live.api('RES-05',{session_id:resultSession.id,format:'xlsx'},'제안서평가_집계표.xlsx');await Live.api('RES-05',{session_id:resultSession.id},'평가결과_서명증빙.html');toast('집계표(xlsx)와 서명 증빙(html)을 내려받았어요');});
