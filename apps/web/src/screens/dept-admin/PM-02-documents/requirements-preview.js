const projectId=new URLSearchParams(location.search).get('project_id');
const state=document.getElementById('state');
const content=document.getElementById('content');
if(projectId)document.getElementById('back').href+='?project_id='+encodeURIComponent(projectId);

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

async function main(){
  if(!projectId)throw Error('사업을 선택해 주세요.');
  const response=await fetch('/api/v2/projects/'+encodeURIComponent(projectId)+'/requirements/preview',
    {credentials:'same-origin',cache:'no-store'});
  const body=await response.json();
  if(!response.ok)throw Error(body.error?.message||'요구사항을 불러오지 못했습니다.');
  const result=body.data;
  const meta=document.createElement('p');meta.className='meta';
  const status={complete:'완료',needs_review:'추출 완료 · 내용 검토 필요'}[result.status]||result.status||'완료';
  meta.textContent=`${result.filename} · 제안요청서 v${result.revision} · ${status}`;
  content.append(meta);
  const business=section('사업 현황');
  for(const [key,title] of [['current_status','현황'],['background_and_need','배경 및 필요성'],['scope','사업 범위']]){
    const heading=document.createElement('h3');heading.textContent=title;business.append(heading);
    for(const point of result.business_status[key]||[]){const line=document.createElement('div');line.className='point';line.textContent=point.text||'';business.append(line);}
  }
  renderBlocks(section('요구사항 목록'),result.requirement_list?.blocks);
  const detail=section('상세 요구사항');
  const expandable=document.createElement('details');
  const tableCount=(result.details?.blocks||[]).filter(block=>block.type==='table'&&!block.parent_block_id).length;
  const summary=document.createElement('summary');summary.textContent=`상세 내용 펼치기 (원문 표 ${tableCount}개)`;
  expandable.append(summary);detail.append(expandable);
  expandable.addEventListener('toggle',()=>{if(expandable.open&&!expandable.dataset.loaded){renderBlocks(expandable,result.details?.blocks);expandable.dataset.loaded='true';}});
  state.hidden=true;content.hidden=false;
}
main().catch(error=>{state.textContent=error.message;});
