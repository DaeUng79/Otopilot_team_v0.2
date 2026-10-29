const params=new URLSearchParams(location.search);
const projectId=params.get('project_id')||params.get('id');
const state=document.getElementById('state');
const content=document.getElementById('content');
if(projectId)document.getElementById('back').href+='?id='+encodeURIComponent(projectId);

function section(title){
  const element=document.createElement('section');element.className='section';
  const heading=document.createElement('h2');heading.textContent=title;element.append(heading);content.append(element);
  return element;
}
function span(value,limit){
  const number=Number(value);
  return Number.isInteger(number)&&number>1?Math.min(number,limit):1;
}
function sourceTable(block,lookup,depth=0){
  const wrapper=document.createElement('div');wrapper.className='source-table-wrap';
  const table=document.createElement('table');table.className='source-table';
  table.setAttribute('aria-label','제안요청서 원문 표');
  const tbody=document.createElement('tbody');
  for(const cells of block.table?.cells||[]){
    const row=document.createElement('tr');
    for(const cell of cells){
      const td=document.createElement('td');
      td.rowSpan=span(cell.row_span,1000);
      td.colSpan=span(cell.col_span,50);
      if(/^#[0-9a-f]{6}$/i.test(cell.background_color||''))td.style.backgroundColor=cell.background_color;
      const children=(cell.child_block_ids||[]).map(id=>lookup.get(id)).filter(Boolean);
      const hasNested=depth<4&&children.some(child=>child.type==='table');
      if(hasNested){
        for(const child of children){
          if(child.type==='table'&&child.block_id!==block.block_id)td.append(sourceTable(child,lookup,depth+1));
          else if(child.type==='paragraph'&&(child.text||'').trim()){
            const line=document.createElement('div');line.className='source-cell-line';
            line.textContent=child.text;td.append(line);
          }
        }
      }
      if(!td.hasChildNodes())td.textContent=cell.text||'';
      row.append(td);
    }
    tbody.append(row);
  }
  table.append(tbody);wrapper.append(table);
  return wrapper;
}
function renderBlocks(parent,blocks){
  let count=0;
  const lookup=new Map((blocks||[]).map(block=>[block.block_id,block]));
  const fragment=document.createDocumentFragment();
  for(const block of blocks||[]){
    if(block.parent_block_id||block.parent_cell_id)continue;
    if(block.type!=='table'&&!(block.text||'').trim())continue;
    const item=document.createElement('div');item.className='source-block';
    if(block.type==='table')item.append(sourceTable(block,lookup));
    else{const line=document.createElement('div');line.className='block';line.textContent=block.text;item.append(line);}
    const pages=block.physical_page_numbers||[];
    if(pages.length){const label=document.createElement('div');label.className='page';label.textContent=`원문 ${pages.join(', ')}쪽`;item.append(label);}
    fragment.append(item);count++;
  }
  if(count)parent.append(fragment);
  else{const empty=document.createElement('p');empty.textContent='표시할 내용이 없습니다.';parent.append(empty);}
}

const api='/api/v2/projects/'+encodeURIComponent(projectId);
async function request(path,method='GET',json){
  const response=await fetch(api+path,{method,credentials:'same-origin',cache:'no-store',
    headers:{'X-Simsa-Client':'v2-web',...(json?{'Content-Type':'application/json'}:{})},body:json?JSON.stringify(json):undefined});
  const body=await response.json();if(!response.ok)throw Error(body.error?.message||'요청을 처리하지 못했습니다.');return body.data;
}
function node(tag,text,parent){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(parent)parent.append(el);return el;}
function generationTools(){
  const box=section('분석 유형');box.classList.add('spec-tools');
  const label=node('label','처리 방식 ',box),select=node('select',undefined,label);select.setAttribute('aria-label','처리 방식');
  for(const [value,text] of [['auto','자동 판정'],['numbered','기존 요구사항 추출'],['narrative','서술형 요구사항 명세서 생성']]){const option=node('option',text,select);option.value=value;}
  const button=node('button','선택한 방식으로 다시 분석',box);button.type='button';
  button.onclick=async()=>{button.disabled=true;try{await request('/requirements/jobs','POST',{force:true,mode:select.value});state.hidden=false;state.textContent='분석을 시작했습니다. 완료 후 다시 열면 명세서를 검토할 수 있습니다.';button.textContent='분석 요청 완료';}catch(e){state.hidden=false;state.textContent=e.message;button.disabled=false;}};
}
function renderSpecification(result){
  const spec=result.specification;if(!spec)return;
  const editable=spec.status==='DRAFT';
  const box=section(editable?'AI 요구사항 명세서 · 검토 초안':'확정된 요구사항 명세서');
  node('p',`GPT-4o · 요구사항 ${spec.items.length}건 · ${editable?'검토 후 확정한 항목만 평가와 제안서 분석에 사용됩니다.':'이 버전의 요구사항을 평가와 제안서 분석에 사용합니다.'}`,box);
  if(result.approved_specification&&result.approved_specification.id!==spec.id)node('p','이전 확정본을 사용 중입니다. 새 초안을 확정하면 이후 분석에 반영됩니다.',box).className='spec-notice';
  node('p','원문 명시·원문 기반 구체화와 AI 보완 제안을 구별해 검토하세요. 확인 방법은 초안이며 원문에 없는 의무나 수치를 추가하지 마세요. 수행·검수 관리 및 참고사항은 업체 제안서 미충족 판정에서 제외됩니다.',box).className='spec-notice';
  for(const warning of spec.warnings||[])node('p',warning,box).className='spec-notice';
  const controls=[];
  for(const item of spec.items){
    const card=node('article',undefined,box);card.className='spec-item';
    node('h3',`${item.code} · ${item.title}`,card);
    node('div',({explicit:'원문 명시',derived:'원문 기반 구체화',suggested:'AI 보완 제안 · 자동 평가 제외'})[item.origin],card).className='spec-origin';
    const grid=node('div',undefined,card);grid.className='spec-grid';
    const left=node('div',undefined,grid),right=node('div',undefined,grid);
    node('h4','원문 근거',left);
    for(const ref of item.sources){node('blockquote',ref.quote,left);node('p',`원문 ${(ref.pages||[]).join(', ')||'쪽 정보 없음'}${ref.pages?.length?'쪽':''}`,left);}
    if(!item.sources.length)node('p','직접적인 원문 의무가 없는 보완 제안입니다.',left);
    const fields={};
    for(const [key,title] of [['category','분류'],['title','요구사항 명칭'],['statement','상세 요구사항'],['verification','확인 방법 초안']]){
      const label=node('label',title,right),input=node(['statement','verification'].includes(key)?'textarea':'input',undefined,label);
      input.value=item[key];input.disabled=!editable;fields[key]=input;
    }
    const usageLabel=node('label','활용 방법',right),usage=node('select',undefined,usageLabel);fields.usage=usage;
    for(const [value,text] of [['scored','점수 평가'],['checklist','필수 확인'],['delivery','수행·검수 관리'],['reference','참고사항']]){const option=node('option',text,usage);option.value=value;}
    usage.value=item.usage;usage.disabled=!editable||item.origin==='suggested';
    const includedLabel=node('label',undefined,right),included=node('input',undefined,includedLabel);included.type='checkbox';included.checked=item.included;included.disabled=!editable||item.origin==='suggested';includedLabel.append(' 명세서에 반영');fields.included=included;
    const previous=result.approved_specification?.items.find(old=>old.id===item.id);
    if(result.approved_specification?.id!==spec.id&&result.approved_specification){
      const changed=previous&&['title','statement','category','usage','included','verification'].some(key=>previous[key]!==item[key]);
      node('p',!previous?'이전 확정본에 없는 새 항목':changed?'이전 확정본에서 변경됨':'이전 확정본과 동일',card);
      if(changed)node('blockquote',`이전 확정 내용: ${previous.statement}`,card);
    }
    controls.push({item,fields});
  }
  if(editable){
    const tools=node('div',undefined,box);tools.className='spec-tools';
    const label=node('label',undefined,tools),check=node('input',undefined,label);check.type='checkbox';label.append(' 원문 근거·수량·조건과 평가 활용 범위를 검토했습니다.');
    const save=node('button','수정 내용 저장',tools),approve=node('button','명세서 확정',tools);save.type=approve.type='button';approve.disabled=true;
    check.onchange=()=>approve.disabled=!check.checked;
    const submit=async approval=>{
      save.disabled=approve.disabled=true;
      try{const items=controls.map(({item,fields})=>({id:item.id,...Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,key==='included'?input.checked:input.value]))}));
        await request('/requirements/specifications/'+encodeURIComponent(spec.id),'PUT',{version:spec.version,items,approve:approval,confirmed:check.checked});
        location.reload();
      }catch(e){state.hidden=false;state.textContent=e.message;save.disabled=false;approve.disabled=!check.checked;}
    };
    save.onclick=()=>submit(false);approve.onclick=()=>submit(true);
  }
  const history=result.specification_history||[];
  if(history.length>1){const details=node('details',undefined,box);node('summary',`명세서 생성 이력 ${history.length}건`,details);for(const v of history)node('p',`${v.created_at} · ${v.status==='APPROVED'?'확정본':'초안'} · 수정 ${v.version}회`,details);}
}
async function main(){
  if(!projectId)throw Error('사업을 선택해 주세요.');
  content.hidden=false;generationTools();
  const result=await request('/requirements/preview');
  const meta=document.createElement('p');meta.className='meta';
  const status={complete:'완료',needs_review:'추출 완료 · 내용 검토 필요'}[result.status]||result.status||'완료';
  meta.textContent=`${result.filename} · 제안요청서 v${result.revision} · ${status}`;
  content.append(meta);
  const business=section('사업 현황');
  for(const [key,title] of [['current_status','현황'],['background_and_need','배경 및 필요성'],['scope','사업 범위']]){
    const heading=document.createElement('h3');heading.textContent=title;business.append(heading);
    for(const point of result.business_status[key]||[]){const line=document.createElement('div');line.className='point';line.textContent=point.text||'';business.append(line);}
  }
  for(const warning of result.warnings||[])node('p',warning,content).className='spec-notice';
  renderSpecification(result);
  renderBlocks(section('원문에서 추출한 요구사항 목록'),result.requirement_list?.blocks);
  const detail=section('상세 요구사항');
  const expandable=document.createElement('details');
  const tableCount=(result.details?.blocks||[]).filter(block=>block.type==='table'&&!block.parent_block_id).length;
  const summary=document.createElement('summary');summary.textContent=`상세 내용 펼치기 (원문 표 ${tableCount}개)`;
  expandable.append(summary);detail.append(expandable);
  expandable.addEventListener('toggle',()=>{if(expandable.open&&!expandable.dataset.loaded){renderBlocks(expandable,result.details?.blocks);expandable.dataset.loaded='true';}});
  state.hidden=true;content.hidden=false;
}
main().catch(error=>{state.textContent=error.message;});
