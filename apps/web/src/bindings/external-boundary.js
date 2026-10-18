// Out-of-scope prototype controls must never report a simulated save as real.
const externalNotice='문서·AI·근거·챗봇은 오대웅 담당 기능입니다. 현재 화면은 원본 시안이며 실제 처리 연결 대상입니다.';
Live.capture('form','submit',()=>{throw Error(externalNotice);});
Live.capture('button:not([data-close]):not(.x):not(.ev-menu-btn):not(.ev-user-btn):not([data-href]):not([data-logout])','click',(_e,el)=>{
 if(el.closest('.ev-menu'))return;
 throw Error(externalNotice);
});
if(window.EvalShell){EvalShell.mount(document.getElementById('hd'),{active:null,project:Live.boot.projects[0]?.name,user:Live.boot.actor.name});EvalShell.toast(externalNotice,6000);}
else if(typeof toast==='function')toast(externalNotice);
