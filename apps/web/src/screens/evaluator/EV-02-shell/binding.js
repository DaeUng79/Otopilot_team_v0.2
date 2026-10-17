const shellSession=Live.boot.sessions.find(s=>s.status!=='CANCELLED');
let shellResult=null;if(shellSession){try{shellResult=await Live.api('RES-01',{session_id:shellSession.id});}catch{}}
S.setChair(!!shellResult?.is_chair);S.setUnlocked(['ALL_SUBMITTED','FINALIZED'].includes(shellSession?.status));S.mount($('hd'),{active:null,project:Live.boot.projects[0]?.name,user:Live.boot.actor.name});sync();
Live.capture('#roleSeg button,#lockSeg button','click',()=>{throw Error('역할과 공개 상태는 실제 평가회차를 따릅니다.');});
