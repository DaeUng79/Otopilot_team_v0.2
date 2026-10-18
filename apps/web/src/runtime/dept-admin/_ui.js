/* 사업담당자 화면 공통 도우미 (시안용). 오른쪽 칸·알림·단계 막대 그리기. */
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const h=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let toastT;function toast(m){const t=$('#toast');if(!t)return;t.textContent=m;t.classList.add('on');clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove('on'),3200)}
const stack=[];
function openLayer(el,focusSel){const sc=el.classList.contains('dlg')?$('#scrim2'):$('#scrim');stack.push({el,sc,from:document.activeElement});sc.classList.add('on');el.classList.add('on');
  setTimeout(()=>{const f=(focusSel&&$(focusSel,el))||el.querySelector('input:not([disabled]),select,button:not([disabled])');f&&f.focus()},60)}
function closeLayer(el){const i=stack.findIndex(l=>l.el===el);if(i<0)return;const l=stack.splice(i,1)[0];l.el.classList.remove('on');l.sc.classList.remove('on');
  if(l.from&&document.contains(l.from)&&l.from.focus)l.from.focus()}
function closeAll(){stack.slice().forEach(l=>closeLayer(l.el))}
document.addEventListener('keydown',e=>{
  if(!stack.length)return;const top=stack[stack.length-1].el;
  if(e.key==='Escape'){e.preventDefault();closeLayer(top)}
  if(e.key==='Tab'){const f=$$('input:not([disabled]),select,button:not([disabled]),[tabindex="0"]',top).filter(x=>x.offsetParent!==null||x===document.activeElement);
    if(!f.length)return;const a=f[0],z=f[f.length-1];if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}}
});
['scrim','scrim2'].forEach(id=>{const s=document.getElementById(id);s&&s.addEventListener('click',()=>{const l=stack.filter(x=>x.sc.id===id).pop();l&&closeLayer(l.el)})});
function bindCommon(){
  $$('[data-close]').forEach(b=>b.addEventListener('click',()=>closeLayer(b.closest('.drawer,.dlg'))));
  $$('[data-href]').forEach(b=>b.addEventListener('click',()=>{location.href=b.dataset.href}));
  $$('[data-account]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();toast('내 계정(비밀번호 바꾸기)은 총괄관리자 화면과 같은 방식이에요')}));
}
document.addEventListener('DOMContentLoaded',bindCommon);
function rowKey(tr,fn){tr.addEventListener('click',fn);tr.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fn()}})}
function confirmDlg({title,body,ok,danger=false,onOk}){const d=$('#dlg');$('#dlg-t').textContent=title;$('#dlg-b').textContent=body;const b=$('#dlg-ok');b.textContent=ok;b.className='btn '+(danger?'danger':'primary');
  b.onclick=()=>{closeLayer(d);onOk&&onOk()};openLayer(d,'#dlg-cancel')}

/* 단계 막대: states = 길이 6, 'done' | 'current' | 'open' | 'locked' */
const STEP_NAMES=['사업 정보','문서','평가항목','평가위원','참석·위원장','결과'];
const STEP_URL=['../../PM-01/design/overview.html','../../PM-02/design/documents.html','../../PM-03/design/criteria.html','../../PM-04/design/committee.html','../../PM-05/design/attendance.html','../../PM-06/design/results.html'];
function renderSteps(el,states){
  el.innerHTML=states.map((s,i)=>{const name=STEP_NAMES[i];
    if(s==='locked')return `<button type="button" class="step is-locked" aria-disabled="true" title="앞 단계를 먼저 끝내 주세요"><span class="n" aria-hidden="true">🔒</span><span>${name}</span><span class="sr-only">. 앞 단계를 먼저 끝내 주세요</span></button>`;
    const cls=s==='done'?' is-done':s==='current'?' is-current':'';
    return `<a class="step${cls}" href="${STEP_URL[i]}"${s==='current'?' aria-current="step"':''}><span class="n" aria-hidden="true">${s==='done'?'✓':i+1}</span><span>${name}</span>${s==='done'?'<span class="sr-only">(끝)</span>':''}</a>`}).join('');
  $$('.is-locked',el).forEach(b=>b.onclick=()=>toast('앞 단계를 먼저 끝내 주세요'));
}
