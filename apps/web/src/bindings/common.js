/* Behavior only. Original design markup, CSS and visual renderers stay authoritative. */
window.Live=(()=>{
  let boot=null,config=null,screen='',pid='',busy=false,activeRole='';
  const nativeFetch=window.fetch.bind(window);
  // Each tab identifies its screen role while the browser keeps separate role cookies.
  window.fetch=(input,init={})=>{
    const url=new URL(input instanceof Request?input.url:String(input),location.href);
    if(url.origin!==location.origin||!(/^\/api\/v2(?:\/|$)/.test(url.pathname)||/^\/committee-v2\/api(?:\/|$)/.test(url.pathname)))
      return nativeFetch(input,init);
    const role=screen==='SA-00'?(activeRole|| (query.get('role')==='department'?'DEPARTMENT_ADMIN':'SUPER_ADMIN')):screen.startsWith('SA')?'SUPER_ADMIN':screen.startsWith('PM')?'DEPARTMENT_ADMIN':screen.startsWith('EV')?'EVALUATOR':'';
    if(!role)return nativeFetch(input,init);
    const headers=new Headers(init.headers||input.headers);
    headers.set('X-Simsa-Role',role);
    return nativeFetch(input,{...init,headers});
  };
  const keys=new Map();
  const query=new URLSearchParams(location.search);
  const paths={ENTRY:'entry/design/entry.html','PM-00':'dept-admin/PM-00/design/login.html','PM-01':'dept-admin/PM-01/design/projects.html','PM-01-overview':'dept-admin/PM-01/design/overview.html','SA-00':'super-admin/SA-00/design/login.html','SA-01':'super-admin/SA-01/design/dashboard.html','EV-00':'evaluator/EV-00/design/login.html','EV-01':'evaluator/EV-01/design/attendance.html','EV-03':'evaluator/EV-03/design/rfp.html'};
  const go=(key,extra={})=>{location.href='/app/'+paths[key]+(Object.keys(extra).length?'?'+new URLSearchParams(extra):'');};
  async function evaluatorLogin(form,name,last4,project){
    const choice=form.querySelector('[data-login-project]');
    const result=await api('AUTH-02',{name,last4,...((project||choice?.value)?{project_id:project||choice.value}:{})});
    if(!result.selection_required){
      const state=await reload();
      go(state.attendance?.[0]?.status==='CONFIRMED'?'EV-03':'EV-01');
      return;
    }
    let label=choice?.parentElement;
    if(!label){label=document.createElement('label');label.className='ev-field field';label.textContent='초청받은 평가 사업';const select=document.createElement('select');select.dataset.loginProject='true';select.required=true;const inputStyle=getComputedStyle(form.querySelector('input'));for(const property of ['height','border','borderRadius','padding','backgroundColor','fontSize','fontWeight','width'])select.style[property]=inputStyle[property];label.append(select);form.insertBefore(label,form.querySelector('button[type=submit]'));}
    const select=label.querySelector('select');select.replaceChildren(new Option('평가할 사업을 선택하세요',''),...result.projects.map(p=>new Option(p.name+(p.evaluation_date?' · '+p.evaluation_date:''),p.id)));
    form.querySelectorAll('input').forEach(el=>el.addEventListener('input',()=>label.remove(),{once:true}));
    select.focus();message('여러 사업에 초청되어 있습니다. 평가할 사업을 선택한 뒤 로그인하세요.');
  }
  function evaluatorState(){
    const session=boot?.sessions?.find(s=>s.status!=='CANCELLED');
    const participant=boot?.participants?.find(p=>p.session_id===session?.id);
    return {session,participant,isChair:!!participant&&participant.id===session?.chair_participant_id,canScore:!!participant&&['OPEN','ALL_SUBMITTED','FINALIZED'].includes(session?.status)};
  }
  function syncShell(){
    if(!window.EvalShell||boot?.actor.role!=='EVALUATOR')return;
    const state=evaluatorState();EvalShell.setChair(state.isChair);EvalShell.setReserve(boot.member_kind==='RESERVE');EvalShell.setUnlocked(['ALL_SUBMITTED','FINALIZED'].includes(state.session?.status));
  }
  function projectHeader(){
    if(!screen.startsWith('PM'))return;const project=boot?.projects.find(p=>p.id===pid);if(!project)return;
    const title=document.querySelector('.pj-title h1');if(title)title.textContent=project.name;
    const date=document.querySelector('.pj-act .hint');if(date)date.textContent='평가일 '+(project.evaluation_date||'아직 안 정함');
    const role=document.querySelector('.side .role');if(role)role.textContent=boot.departments.find(d=>d.id===project.department_id)?.name||'';
    const badge=document.querySelector('.pj-title .badge');if(badge){badge.textContent=({COMPLETED:'✓ 완료',EVALUATING:'● 평가 중',CANCELLED:'취소'}[project.status]||'○ 준비');badge.className='badge '+({COMPLETED:'success',EVALUATING:'primary'}[project.status]||'');}
  }
  const message=m=>{if(window.EvalShell)EvalShell.toast(m,6000);else if(typeof toast==='function')toast(m);else {const el=document.getElementById('toast')||document.getElementById('msg');if(el){el.textContent=m;el.hidden=false;if(el.id==='toast'){el.classList.add('on');setTimeout(()=>el.classList.remove('on'),6000);}}else console.error(m);}};
  async function get(url){const r=await fetch(url,{credentials:'same-origin'});const b=await r.json();if(!r.ok)throw Error(b.error?.message||'로그인이 필요합니다.');return b.data;}
  async function api(action,body={},download=false){
    const mark=action+JSON.stringify(body),key=keys.get(mark)||crypto.randomUUID();keys.set(mark,key);
    const r=await fetch('/api/v2/actions/'+action,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Simsa-Client':'v2-web','Idempotency-Key':key},body:JSON.stringify(body)});
    if(r.status<500)keys.delete(mark);
    if(!r.ok){const b=await r.json();throw Error(b.error?.message||'요청을 처리하지 못했습니다.');}
    if(download){const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=typeof download==='string'?download:'평가결과.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
    return (await r.json()).data;
  }
  async function reload(){boot=await get('/api/v2/bootstrap');return boot;}
  async function all(action,body={}){const result=[];for(let page=1;;page++){const data=await api(action,{...body,page,page_size:100});result.push(...data.items);if(result.length>=data.total||!data.items.length)return result;}}
  function selectProject(id){if(!boot?.projects.some(p=>p.id===id))throw Error('접근할 수 없는 사업입니다.');pid=id;sessionStorage.setItem('simsa.original.project',id);}
  function capture(selector,event,fn){document.addEventListener(event,async e=>{
    const el=e.target.closest(selector);if(!el||event==='keydown'&&!['Enter',' '].includes(e.key))return;e.preventDefault();e.stopImmediatePropagation();if(busy){message('이전 요청을 처리 중입니다. 완료 후 다시 선택하세요.');return;}
    busy=true;el.setAttribute('aria-busy','true');try{await fn(e,el);}catch(error){message(error.message);}finally{busy=false;el.removeAttribute('aria-busy');}
  },true);}
  async function begin(key){screen=key;document.documentElement.inert=true;config=await get('/api/v2/config');
    try{await reload();}catch{boot=null;}
    const publicPage=['ENTRY','SA-00','PM-00','EV-00'].includes(key);
    if(!publicPage&&!boot){go(key.startsWith('EV')?'EV-00':key.startsWith('SA')?'SA-00':'PM-00',query.has('project_id')?{project_id:query.get('project_id')}:{});throw Error('로그인이 필요합니다.');}
    if(!publicPage){if(boot.must_change_password){go('SA-00',{change:'1',...(boot.actor.role==='DEPARTMENT_ADMIN'?{role:'department'}:{})});throw Error('임시 비밀번호로 로그인한 뒤 비밀번호를 변경하세요.');}const role=boot.actor.role;if(key.startsWith('SA')&&role!=='SUPER_ADMIN'||key.startsWith('PM')&&role==='EVALUATOR'||key.startsWith('EV')&&role!=='EVALUATOR')throw Error('해당 역할로 로그인하세요.');}
    if(boot){const wanted=query.get('id')||query.get('project_id')||sessionStorage.getItem('simsa.original.project');pid=boot.actor.project_id||boot.projects.find(p=>p.id===wanted)?.id||'';}
    if(key.startsWith('PM')&&typeof window.renderSteps==='function'){
      const originalSteps=window.renderSteps;
      window.renderSteps=(el,states)=>{originalSteps(el,states.map(s=>s==='current'?'current':'open'));projectHeader();};
    }
    if(window.EvalShell&&boot?.actor.role==='EVALUATOR'){
      const mount=EvalShell.mount;EvalShell.mount=(el,opts)=>{syncShell();mount(el,{...opts,project:boot.projects[0]?.name,user:boot.actor.name});};
      syncShell();
    }
    capture('[data-logout],.ev-menu a[href],a[href$="#logout"]','click',async()=>{await api('AUTH-03');sessionStorage.removeItem('simsa.original.project');go('ENTRY');});
    capture('[data-account]','click',()=>{location.href='/app/'+paths['SA-00']+(boot?.actor.role==='DEPARTMENT_ADMIN'?'?role=department':'')+'#account';});
    document.addEventListener('click',e=>{
      const el=e.target.closest('a[href],[data-href]');if(!el||el.hasAttribute('download')||el.dataset.locked||e.defaultPrevented)return;
      const raw=el.getAttribute('href')||el.dataset.href;if(!raw||raw.startsWith('#'))return;
      const url=new URL(raw,location.href);
      if(url.origin!==location.origin||!decodeURIComponent(url.pathname).startsWith('/app/'))return;
      if(pid&&decodeURIComponent(url.pathname).includes('/dept-admin/'))url.searchParams.set('id',pid);
      if(pid&&boot?.actor.role==='EVALUATOR'&&decodeURIComponent(url.pathname).includes('/evaluator/'))url.searchParams.set('project_id',pid);
      e.preventDefault();e.stopImmediatePropagation();location.href=url.href;
    },true);
    capture('.demo button,.ev-demo button,#seg button,[data-pre]','click',()=>{throw Error('실제 연결에서는 시안의 가상 상태 전환을 사용하지 않습니다.');});
    capture('.evc-form','submit',()=>{throw Error('문서 챗봇은 오대웅 담당 연결 대상입니다.');});
    capture('.evc-in','keydown',()=>{throw Error('문서 챗봇은 오대웅 담당 연결 대상입니다.');});
    capture('.evc-sq','click',()=>{throw Error('문서 챗봇은 오대웅 담당 연결 대상입니다.');});
  }
  function finish(){document.documentElement.inert=false;document.documentElement.dataset.liveScreen=screen;document.documentElement.dataset.liveReady='true';syncShell();projectHeader();
    if(screen.startsWith('EV')&&boot?.actor.role==='EVALUATOR'){
      const signature=()=>JSON.stringify(evaluatorState());let previous=signature();
      const timer=setInterval(async()=>{if(document.hidden)return;try{await reload();syncShell();const next=signature();if(next!==previous&&(document.documentElement.dataset.waitingEvaluation==='true'||screen==='EV-07'&&document.querySelector('.ch-lock')))location.reload();previous=next;}catch{clearInterval(timer);go('EV-00');}},5000);
      window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
    }
  }
  function fail(error){document.documentElement.inert=false;document.documentElement.dataset.liveError=error.message;document.querySelectorAll('form,main,#main,#stage,#sc').forEach(el=>el.inert=true);message(error.message);console.error(error);}
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  return {api,get,reload,all,selectProject,capture,message,begin,finish,fail,go,paths,escape,evaluatorLogin,evaluatorState,setRole(role){activeRole=role;},get boot(){return boot;},get config(){return config;},get pid(){return pid;},get query(){return query;}};
})();
