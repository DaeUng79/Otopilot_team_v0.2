async function loadDashboard(){
 const [summary,projects]=await Promise.all([Live.api('DASH-01'),Live.all('PRJ-01')]);
 const departments=Live.boot.departments,stage=p=>p.status==='COMPLETED'?'완료':p.status==='EVALUATING'?'평가 중':'준비';
 P.splice(0,P.length,...projects.map(p=>[p.id,p.name,departments.find(d=>d.id===p.department_id)?.name||p.contact_department,p.evaluation_date||'',stage(p)]));
 DEPTS.splice(0,DEPTS.length,...departments.map(d=>h(d.name)));$('#f-dept').innerHTML='<option value="">부서 전체</option>'+DEPTS.map(d=>`<option>${d}</option>`).join('');
 DP.splice(0,DP.length,...departments.map(d=>[h(d.name),projects.filter(p=>p.department_id===d.id).length]));
 late=false;asof=new Date().toLocaleTimeString('ko-KR');paintAsof();draw();bars();
 $$('.drow .nm').forEach((el,i)=>el.textContent=departments[i]?.name||el.textContent);
}
await loadDashboard();
Live.capture('#b-refresh','click',async()=>{await Live.reload();await loadDashboard();toast('최신 자료를 불러왔어요');});
