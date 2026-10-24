const cards=document.querySelector('#agent-cards'),status=document.querySelector('#agent-status'),search=document.querySelector('#agent-search');
let agents=[],limit=12;
const industry=document.querySelector('#agent-industry'),businessFunction=document.querySelector('#agent-function'),more=document.querySelector('#agent-more');
const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(){
  const query=search.value.trim().toLowerCase();
  const terms=query.split(/\s+/).filter(Boolean);
  const matches=agents.filter(a=>(!industry.value||a.industry===industry.value)&&(!businessFunction.value||a.function===businessFunction.value)&&terms.every(term=>[a.title,a.description,a.industry,a.function,...a.tags,...a.providers].join(' ').toLowerCase().includes(term)));
  const visible=matches.slice(0,limit);
  status.textContent=`Showing ${visible.length} of ${matches.length} matching starters · ${agents.length} in the library`;
  more.hidden=visible.length>=matches.length;
  cards.innerHTML=visible.map(a=>`<article class="agent-card"><div class="agent-card-meta"><span>${esc(a.industry)}</span><span>v${esc(a.version)}</span></div><h2>${esc(a.title)}</h2><div class="agent-function">${esc(a.function)}</div><p>${esc(a.description)}</p><div class="agent-tags">${a.tags.map(t=>`<span>${esc(t)}</span>`).join('')}</div><a class="btn primary" href="${esc(a.download)}" download>↓ Download code pack <span>ZIP · ${Math.ceil(a.size_bytes/1024)} KB</span></a><small>Includes source, configuration, .env.example, sample data and tests.</small></article>`).join('')||'<div class="empty"><b>No matching agents.</b>Try documents, invoices, support, OpenAI or Anthropic.</div>';
}
const resetLimit=()=>{limit=12;render()};
search.addEventListener('input',resetLimit);industry.addEventListener('change',resetLimit);businessFunction.addEventListener('change',resetLimit);
more.addEventListener('click',()=>{limit+=12;render()});
document.querySelector('#agent-reset').addEventListener('click',()=>{search.value='';industry.value='';businessFunction.value='';resetLimit()});
fetch('agents.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error();return r.json()}).then(data=>{agents=data;document.querySelector('#library-coverage').textContent=`${agents.length} starters · ${new Set(agents.map(a=>a.industry)).size} industry categories · ${new Set(agents.map(a=>a.function)).size} business functions`;for(const [select,key] of [[industry,'industry'],[businessFunction,'function']])for(const value of [...new Set(agents.map(a=>a[key]))].sort()){const option=document.createElement('option');option.value=value;option.textContent=value;select.append(option)}render()}).catch(()=>{status.textContent='The library could not load. Refresh the page to try again.'});
