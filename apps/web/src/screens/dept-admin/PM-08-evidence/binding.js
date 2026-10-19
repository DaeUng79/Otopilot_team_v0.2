// PM-08 · PRO-04 · PRO-05 — 근거 연결. 실제 사업·승인 평가표·업체·제안서로 화면을 채운다 (2026-10-18).
// 후보 제안(PRO-04)·확정(PRO-05)은 문서 모듈(오대웅 담당) 연결 전이라 버튼을 끄고 이유를 보여 준다.
// 이전에는 연결 코드가 없어 시안의 가상 업체(하늘정보·누리시스템·한빛소프트)와 가상 연결이 실제 데이터처럼 보였다.
if(!Live.pid)throw Error('사업 목록에서 사업을 선택하세요.');
const projectUrl='/api/v2/projects/'+encodeURIComponent(Live.pid);
const notConnected='근거 후보 제안·확정(PRO-04·05)은 문서 모듈 연결 전이라 아직 쓸 수 없어요. 그때까지 평가위원 비교 화면은 자동 추천(담당자 확정 전)으로 표시돼요.';
const [detail,criteriaState,proposalData]=await Promise.all([
  Live.api('PRJ-05',{project_id:Live.pid}),
  Live.get(projectUrl+'/criteria').catch(()=>null),
  Live.get(projectUrl+'/proposals').catch(()=>({uploads:[]})),
]);
// 평가표: 최신 APPROVED 버전의 채점 항목(말단)만. 없으면 빈 상태.
const versions=criteriaState?.versions||[];
const approved=[...versions].reverse().find(v=>v.status==='APPROVED')||null;
const approvedItems=approved?.items||[];
const leafItems=approvedItems.filter(item=>item.is_scorable||!approvedItems.some(other=>other.parent_code===item.code));
ITEMS.splice(0,ITEMS.length,...leafItems.map(item=>[item.code,item.title,item.points??item.max_score,(item.description||item.title)+(item.source_page!=null?' (제안요청서 '+item.source_page+'쪽)':'')]));
// 업체: PRJ-05 업체 순서대로, 업체별 최신 READY 제안서 차수.
const latestProposal={};
for(const upload of proposalData.uploads||[]){if(upload.status!=='READY')continue;const current=latestProposal[upload.vendor_id];if(!current||upload.upload_revision>current.upload_revision)latestProposal[upload.vendor_id]=upload;}
VEND.splice(0,VEND.length,...(detail.vendors||[]).map(vendor=>{const upload=latestProposal[vendor.id];const label=upload?'v'+upload.upload_revision:'없음';return {code:vendor.display_code+'사',name:vendor.legal_name,doc:label,latest:label,pdf:false,noDoc:!upload,format:upload?.format||''};}));
nv=VEND.length;sel=0;D={};ITEMS.forEach((_,i)=>{D[i]=VEND.map(()=>[]);});
$('.items .sub').innerHTML=(approved?'승인된 평가표 · 승인 번호 '+h(approved.approval_no)+' · 채점 항목 '+ITEMS.length+'개':'승인된 평가표 없음')+' · 확정 <b class="tnum" id="gdone"></b>';
$('#demo')?.remove();
function vendorSections(){
  if(!VEND.length)return '<div class="vmsg">등록된 업체가 없어요. 문서 단계에서 업체와 제안서를 먼저 등록해 주세요.</div>';
  return VEND.map(v=>`<section class="vsec" aria-label="${h(v.code)}"><div class="vh"><span class="code">${h(v.code)}</span><b>${h(v.name)}</b><span class="badge ${v.noDoc?'':'success'}">${v.noDoc?'제안서 없음':'제안서 '+h(v.doc)+(v.format?' · '+h(v.format):'')}</span></div><div class="vmsg">${v.noDoc?'이 업체의 제안서가 아직 등록되지 않았어요. 문서 단계에서 올려 주세요.':h(notConnected)}</div></section>`).join('');
}
const originalEvidencePaint=paint;
paint=function(){
  if(!ITEMS.length){
    $('#ilist').innerHTML='<li><div class="vmsg">승인된 평가표가 없어요. 3단계 평가항목에서 평가표를 확정하면 항목이 여기에 나와요.</div></li>';
    $('#gdone').textContent='0 / 0개 항목';
    $('#panel').innerHTML='<div class="ph"><div class="t"><h2>승인된 평가표가 없어요</h2><div class="rq">3단계 평가항목에서 평가표를 확정하면 항목별로 업체 제안서의 근거를 연결할 수 있어요.</div></div><div class="acts"><button class="btn primary" type="button" id="b-sug" disabled title="'+h(notConnected)+'">항목 연결 제안 받기</button></div></div><div class="pb">'+vendorSections()+'</div>';
    return;
  }
  originalEvidencePaint();
  const suggest=$('#b-sug');if(suggest){suggest.disabled=true;suggest.title=notConnected;}
  $$('#panel .vsec').forEach((section,index)=>{
    const vendor=VEND[index],message=$('.vmsg',section);if(!vendor||!message)return;
    message.textContent=vendor.noDoc?'이 업체의 제안서가 아직 등록되지 않았어요. 문서 단계에서 올려 주세요.':notConnected;
    const badge=$('.vh .badge',section);if(badge&&vendor.noDoc)badge.textContent='제안서 없음';
  });
};
paint();
