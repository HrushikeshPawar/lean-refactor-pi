/* Static Arena graph viewer. The loopback server supplies graph.json; snapshots set GRAPH_SNAPSHOT. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let data, byId = new Map(), coords = new Map(), selected = localStorage.getItem('arena-selected'),
      view = null, dragging = null, lastRevision = '', collapsed = new Set(), chartSpecs = [];
  const graph = $('graph'), wrap = $('graph-wrap'), minimap = $('minimap');
  const NODE_R = 21, STEP_X = 90, STEP_Y = 100;

  function status(node) { return node.status || 'fail'; }
  function best(node) { return node.evaluations.findLast(e => e.mode === 'full' && Object.keys(e.result.compat || {}).length === 3 && Object.values(e.result.compat).every(v => v.passed)) || node.evaluations.at(-1); }
  function nodeLabel(node) { return `#${node.index} ${node.id.slice(0,8)}`; }
  function numberForId(id) { return byId.has(id) ? `#${byId.get(id).index}` : String(id ?? '?').slice(0,8); }
  function layout() {
    const depths = new Map(), layers = new Map();
    const hidden = new Set(), visit = id => { for(const child of byId.get(id)?.children || []) if(!hidden.has(child)){hidden.add(child);visit(child)} };
    for(const id of collapsed)visit(id);
    for (const node of data.nodes) {
      if (hidden.has(node.id)) continue;
      const depth = node.parents.length ? 1 + Math.max(...node.parents.map(p => depths.get(p) ?? -1)) : 0;
      depths.set(node.id, depth);
      if (!layers.has(depth)) layers.set(depth, []);
      layers.get(depth).push(node);
    }
    coords = new Map();
    const widest=Math.max(1,...[...layers.values()].map(nodes=>nodes.length));
    for (const [depth, nodes] of layers) {
      nodes.sort((a,b) => {
        const bary = n => n.parents.length ? n.parents.reduce((s,p) => s + (coords.get(p)?.x ?? 0), 0) / n.parents.length : n.index * STEP_X;
        return bary(a) - bary(b) || a.index - b.index;
      });
      const offset=(widest-nodes.length)*STEP_X/2;
      nodes.forEach((n,i) => coords.set(n.id, {x: 45 + offset + i * STEP_X, y: 45 + depth * STEP_Y}));
    }
    const width = 90 + (widest - 1) * STEP_X;
    const height = 90 + Math.max(0, ...[...depths.values()]) * STEP_Y;
    graph.dataset.width = width; graph.dataset.height = height;
    if (!view) focusOn(selected && coords.has(selected) ? selected : data.milestones.at(-1)?.candidate_id ?? data.nodes.at(-1)?.id);
  }
  function focusOn(id) {
    const point = coords.get(id); if (!point) return fit();
    const aspect = Math.max(1, wrap.clientWidth) / Math.max(1, wrap.clientHeight);
    const w = Math.max(600, Math.min(1000, Number(graph.dataset.width) || 800)), h = w / aspect;
    view = {x: point.x - w / 2, y: point.y - h / 2, w, h}; applyView();
  }
  function applyView() {
    if (!view) return;
    graph.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
    if (!data) return;
    const width=Number(graph.dataset.width)||800,height=Number(graph.dataset.height)||500;
    minimap.setAttribute('viewBox',`0 0 ${width} ${height}`);
    minimap.setAttribute('preserveAspectRatio','none');
    minimap.innerHTML=[...coords.values()].map(p=>`<circle cx="${p.x}" cy="${p.y}" r="${Math.max(3,Math.min(width,height)/100)}"/>`).join('')+
      `<rect x="${view.x}" y="${view.y}" width="${view.w}" height="${view.h}"/>`;
  }
  function fit() {
    const width = Number(graph.dataset.width) || 800, height = Number(graph.dataset.height) || 500;
    const aspect = Math.max(1, wrap.clientWidth) / Math.max(1, wrap.clientHeight);
    const w = Math.max(width + 80, (height + 80) * aspect), h = w / aspect;
    view = {x: (width - w) / 2, y: (height - h) / 2, w, h}; applyView();
  }
  function nearestNode(clientX, clientY) {
    if (!coords.size) return null;
    const box=wrap.getBoundingClientRect();
    const x=view.x+(clientX-box.left)/Math.max(1,box.width)*view.w;
    const y=view.y+(clientY-box.top)/Math.max(1,box.height)*view.h;
    let nearest=null, distance=Infinity;
    for (const [id,point] of coords) {
      const current=((point.x-x)/view.w)**2+((point.y-y)/view.h)**2;
      if (current<distance) {nearest=id;distance=current;}
    }
    return nearest;
  }
  function zoom(factor, clientX, clientY) {
    const box=wrap.getBoundingClientRect();
    const screenX=clientX ?? box.left+box.width/2;
    const screenY=clientY ?? box.top+box.height/2;
    const anchor=coords.get(nearestNode(screenX,screenY));
    const w = Math.max(80, view.w * factor), h = Math.max(80, view.h * factor);
    view = {x:(anchor?.x ?? view.x+view.w/2)-w/2,
            y:(anchor?.y ?? view.y+view.h/2)-h/2,w,h}; applyView();
  }
  wrap.addEventListener('wheel', e => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.13 : 0.885, e.clientX, e.clientY); }, {passive:false});
  wrap.addEventListener('pointerdown', e => { if (e.target.closest('.node')) return; dragging = {x:e.clientX,y:e.clientY,start:{...view}}; wrap.setPointerCapture(e.pointerId); wrap.classList.add('dragging'); });
  wrap.addEventListener('pointermove', e => { if (!dragging) return; view.x = dragging.start.x - (e.clientX-dragging.x)*view.w/wrap.clientWidth; view.y = dragging.start.y - (e.clientY-dragging.y)*view.h/wrap.clientHeight; applyView(); });
  wrap.addEventListener('pointerup', () => { dragging = null; wrap.classList.remove('dragging'); });
  minimap.addEventListener('pointerdown', e => {
    e.stopPropagation(); const box=minimap.getBoundingClientRect();
    const width=Number(graph.dataset.width)||800,height=Number(graph.dataset.height)||500;
    view.x=(e.clientX-box.left)/box.width*width-view.w/2;
    view.y=(e.clientY-box.top)/box.height*height-view.h/2;
    applyView();
  });
  $('fit').onclick = fit; $('zoom-in').onclick = () => zoom(.8); $('zoom-out').onclick = () => zoom(1.25);
  $('search').oninput = renderGraph; $('filter').onchange = renderGraph; $('idea-filter').onchange = renderGraph;

  function visible(node) {
    const filter = $('filter').value, query = $('search').value.trim().toLowerCase();
    return (filter === 'all' || status(node) === filter || filter === 'auto_merge' && node.origin === 'auto_merge') &&
      ($('idea-filter').value === 'all' || node.idea_id === $('idea-filter').value) &&
      (!query || [node.id,node.hypothesis,node.proof,node.origin].some(x => String(x ?? '').toLowerCase().includes(query)));
  }
  function lineageOf(id) {
    const nodes=new Set(), edges=[], seenEdges=new Set();
    const visit=current=>{
      if(nodes.has(current)||!byId.has(current))return;
      nodes.add(current);
      const node=byId.get(current);
      for(const derivation of node.derivations?.length ? node.derivations : [{parents:node.parents}]) {
        for(const parent of derivation.parents || []) {
          visit(parent);
          const key=`${parent}:${current}`;
          if(byId.has(parent)&&!seenEdges.has(key)){seenEdges.add(key);edges.push({parent,child:current});}
        }
      }
    };
    visit(id);
    return {nodes,edges,edgeKeys:seenEdges};
  }
  function renderGraph() {
    if (!data) return;
    const milestone = new Set(data.milestones.map(m => m.candidate_id));
    const lineage=selected&&byId.has(selected)?lineageOf(selected):{nodes:new Set(),edgeKeys:new Set()};
    const edges = [], boxes = [];
    for (const node of data.nodes) {
      if (!coords.has(node.id)) continue;
      const p = coords.get(node.id), dim = visible(node) ? '' : ' dim';
      const derivations = node.derivations?.length ? node.derivations : [{parents:node.parents}];
      derivations.forEach((d,i) => d.parents.forEach(parent => {
        const a = coords.get(parent); if (!a) return;
        const focus = lineage.edgeKeys.has(`${parent}:${node.id}`) ? ' lineage' : '';
        const faded = selected && !focus ? ' unrelated' : '';
        const ay=a.y+NODE_R, cy=p.y-NODE_R, bend=Math.max(18,(cy-ay)*.48);
        edges.push(`<path class="edge${i ? ' alternate' : ''}${focus}${faded}${dim}" d="M${a.x},${ay} C${a.x},${ay+bend} ${p.x},${cy-bend} ${p.x},${cy}"/>`);
      }));
      boxes.push(`<g class="node ${esc(status(node))}${node.origin === 'auto_merge' ? ' auto_merge' : ''}${milestone.has(node.id) ? ' best' : ''}${lineage.nodes.has(node.id) && selected !== node.id ? ' ancestor' : ''}${selected === node.id ? ' selected' : ''}${selected && !lineage.nodes.has(node.id) ? ' unrelated' : ''}${dim}" data-id="${node.id}" transform="translate(${p.x},${p.y})"><title>${esc(nodeLabel(node))} · ${esc(node.tokens ?? '?')} tokens · ${esc(status(node))} · idea ${esc(node.idea_id ?? 'legacy')}${node.origin === 'auto_merge' ? ' · automatic merge' : ''}</title>${node.origin === 'auto_merge' ? '<circle class="merge-ring" r="27"/><text class="merge-badge" x="20" y="-20">⊕</text>' : ''}<circle class="node-body" r="${NODE_R}"/><text class="node-number" text-anchor="middle" dominant-baseline="central">#${esc(node.index)}</text></g>`);
    }
    graph.innerHTML = edges.join('') + boxes.join(''); applyView();
    graph.querySelectorAll('.node').forEach(el => el.addEventListener('click', () => select(el.dataset.id)));
  }
  function diff(a,b,showAll=false) {
    const x=a.split('\n'),y=b.split('\n'),n=x.length,m=y.length;
    if (n*m > 40000) return '<p class="warning">Diff is too large for the browser; open Full proof below to inspect the candidate.</p>';
    const d=Array.from({length:n+1},()=>new Uint16Array(m+1));
    for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)d[i][j]=x[i]===y[j]?d[i+1][j+1]+1:Math.max(d[i+1][j],d[i][j+1]);
    let i=0,j=0,rows=[];
    while(i<n||j<m){
      if(i<n&&j<m&&x[i]===y[j])rows.push({kind:'same',old:++i,new:++j,text:x[i-1]});
      else if(j<m&&(i===n||d[i][j+1]>=d[i+1][j]))rows.push({kind:'add',old:'',new:++j,text:y[j-1]});
      else rows.push({kind:'del',old:++i,new:'',text:x[i-1]});
    }
    const context=new Set();
    rows.forEach((row,index)=>{if(row.kind!=='same')for(let k=Math.max(0,index-3);k<=Math.min(rows.length-1,index+3);k++)context.add(k)});
    if(!context.size)context.add(0);
    const out=[];
    for(let index=0;index<rows.length;){
      if(!showAll&&!context.has(index)){
        let end=index+1;while(end<rows.length&&!context.has(end))end++;
        out.push(`<div class="diff-fold">⋯ ${end-index} unchanged lines hidden</div>`);index=end;continue;
      }
      const row=rows[index++],sign=row.kind==='add'?'+':row.kind==='del'?'-':' ';
      out.push(`<div class="diff-row ${row.kind}"><span class="diff-gutter">${row.old}</span><span class="diff-gutter">${row.new}</span><span class="diff-sign">${sign}</span><span class="diff-text">${esc(row.text)}</span></div>`);
    }
    return out.join('');
  }
  function detail() {
    const node = byId.get(selected);
    if (!node) { $('detail').innerHTML='<p class="empty">Select a graph node, chart point, or frontier item.</p>'; return; }
    const evaluated = best(node)?.result || {}, derived = node.derivations || [];
    const ancestry=lineageOf(node.id);
    const reference=[...ancestry.nodes].map(id=>byId.get(id)).find(item=>item.origin==='reference');
    const root=reference || [...ancestry.nodes].map(id=>byId.get(id)).sort((a,b)=>a.index-b.index)[0];
    const relations = derived.map((d,i) => `<div>${i ? 'Alternate derivation' : 'Recorded parents'}: ${d.parents.length ? d.parents.map(p => `<button data-go="${esc(p)}">${esc(byId.get(p) ? nodeLabel(byId.get(p)) : p.slice(0,8))}</button>`).join(' ') : 'root'}${d.merge?.base ? ` · base <button data-go="${esc(d.merge.base)}">${esc(d.merge.base.slice(0,8))}</button>` : ''}</div>`).join('');
    const options = [...new Set(derived.flatMap(d => d.parents))].map(p => `<option value="${esc(p)}">Parent ${esc(byId.get(p)?.index ?? p.slice(0,8))}</option>`).join('') + (node.merge?.base ? `<option value="${esc(node.merge.base)}">Common base</option>` : '');
    $('detail').innerHTML = `<div class="card"><h2>${esc(nodeLabel(node))} ${node.origin === 'auto_merge' ? '⊕ automatic merge' : ''}</h2><div class="tags"><span class="tag ${node.status === 'full' ? 'good' : node.status === 'fail' ? 'bad' : ''}">${esc(status(node))}</span><span class="tag">${esc(node.tokens ?? '?')} tokens</span><span class="tag">${esc(node.heartbeat ?? '?')} heartbeats</span><span class="tag">${esc(node.local_proxy?.toFixed?.(2) ?? '—')} provisional score</span>${node.idea_id?`<span class="tag">${esc(node.idea_id)}</span>`:''}</div><details class="node-details"><summary>Reasoning and relationships</summary><code>${esc(node.id)}</code><p>${esc(node.hypothesis || (node.origin === 'auto_merge' ? 'Deterministic combination of disjoint edits' : 'No hypothesis recorded'))}</p><div class="row">${relations}</div><p class="muted">Children: ${node.children.length ? node.children.map(c => `<button data-go="${esc(c)}">#${esc(byId.get(c)?.index)}</button>`).join(' ') : 'none'} · Decision: ${esc(node.decision)}</p><button id="collapse">${collapsed.has(node.id)?'Expand descendants':'Collapse descendants'}</button></details></div>
      <div class="card"><h3>Diff and merge provenance</h3>${options ? `<div class="diff-controls"><select id="diff-parent">${options}</select><label><input type="checkbox" id="diff-all"> Show unchanged lines</label></div><div class="diff" id="diff"></div>` : '<p class="muted">Recorded root</p>'}${node.merge ? `<details><summary>Exact base-relative edit ranges</summary><pre>${esc(JSON.stringify(node.merge.edits,null,2))}</pre></details>` : ''}<button id="open-lineage" class="modal-link" type="button">Open lineage diffs from ${reference?'original source':'earliest recorded ancestor'} · ${ancestry.edges.length} edges ↗</button></div>
      <div class="card proof-card"><div class="proof-head"><h3>Full proof · ${esc(node.tokens ?? '?')} tokens</h3><button id="open-proof" type="button">Open in modal ↗</button></div><details><summary>Show inline proof</summary><pre>${esc(node.proof)}</pre></details></div>
      <div class="card"><h3>All evaluations</h3>${node.evaluations.map(e => `<div class="feed-row"><strong>#${e.number} ${esc(e.mode)}</strong><span>${esc(e.result.tokens ?? '?')} tokens · ${esc(e.result.heartbeat ?? '?')} heartbeats · ${esc(e.result.local_proxy?.toFixed?.(2) ?? '—')} proxy</span>${Object.entries(e.result.compat || {}).map(([v,r]) => `<span class="tag ${r.passed ? 'good' : 'bad'}">${esc(v)} ${r.passed ? 'pass' : 'fail'}</span>`).join('')}<button type="button" class="feedback-toggle" aria-expanded="false">Complete Lean feedback ▸</button><div class="feedback-body" hidden>${Object.entries(e.result.compat || {}).map(([v,r])=>`<h4>${esc(v)}</h4><pre>${esc(r.diagnostics ?? r.error ?? '')}</pre>`).join('')}${e.result.error ? `<pre>${esc(e.result.error)}</pre>` : ''}${!Object.keys(e.result.compat || {}).length&&!e.result.error?'<p class="muted">No Lean diagnostic was recorded for this evaluation.</p>':''}</div></div>`).join('')}</div>`;
    $('detail').querySelectorAll('[data-go]').forEach(el => el.onclick=()=>select(el.dataset.go));
    $('collapse').onclick=()=>{collapsed.has(node.id)?collapsed.delete(node.id):collapsed.add(node.id);view=null;layout();renderGraph();detail()};
    $('detail').querySelectorAll('.feedback-toggle').forEach(button=>button.onclick=()=>{
      const body=button.nextElementSibling,open=body.hidden;
      body.hidden=!open;button.setAttribute('aria-expanded',String(open));
      button.textContent=`Complete Lean feedback ${open?'▾':'▸'}`;
    });
    const selector=$('diff-parent'); if(selector){const update=()=>{$('diff').innerHTML=diff(byId.get(selector.value)?.proof ?? '',node.proof,$('diff-all').checked)};selector.onchange=update;$('diff-all').onchange=update;update()}
    $('open-proof').onclick=()=>openCode(`Full proof · ${nodeLabel(node)}`,`<pre class="full-code">${esc(node.proof)}</pre>`);
    $('open-lineage').onclick=()=>{
      const cumulative=root&&root.id!==node.id?`<h3>${esc(nodeLabel(root))} → ${esc(nodeLabel(node))} · cumulative</h3><div class="diff">${diff(root.proof,node.proof)}</div>`:'<p class="muted">This is the earliest recorded proof.</p>';
      const steps=ancestry.edges.map(({parent,child})=>{
        const from=byId.get(parent),to=byId.get(child);
        return `<details class="lineage-step" open><summary>${esc(nodeLabel(from))} → ${esc(nodeLabel(to))}${to.origin==='auto_merge'?' · ⊕ merge':''}</summary><div class="diff">${diff(from.proof,to.proof)}</div></details>`;
      }).join('');
      openCode(`Lineage diffs · ${nodeLabel(node)}`,`<p class="muted">${reference?'Pinned original source':'Earliest recorded ancestor'} to current · ${ancestry.edges.length} recorded parent edges, including merge branches</p>${cumulative}<h3>Step-by-step changes</h3>${steps}`);
    };
  }
  function openCode(title,content) {
    const dialog=$('code-dialog');
    $('code-dialog-body').innerHTML=`<div class="modal-head"><h2>${esc(title)}</h2><button id="close-code" type="button" aria-label="Close details">✕</button></div>${content}`;
    $('close-code').onclick=()=>dialog.close();dialog.showModal();
  }
  $('code-dialog').addEventListener('click',e=>{if(e.target===$('code-dialog'))e.target.close()});
  function select(id) { selected=id; localStorage.setItem('arena-selected',id); if(coords.has(id))focusOn(id); renderGraph(); detail(); renderCharts(); }

  function chart(spec,index) {
    const {title,key,unit}=spec,points=spec.rows.filter(r=>Number.isFinite(r[key]));
    if(!points.length)return `<button type="button" class="chart"><span class="chart-title">${esc(title)}</span><span class="muted">No data yet</span></button>`;
    const values=points.map(p=>p[key]),min=Math.min(...values),max=Math.max(...values),range=max-min||1;
    const xs=points.map((p,i)=>p.number ?? i),xMin=Math.min(...xs),xMax=Math.max(...xs);
    const xy=points.map((p,i)=>({p,x:20+(xs[i]-xMin)*310/Math.max(1,xMax-xMin),y:78-(p[key]-min)*55/range}));
    const line=xy.map((v,i)=>`${i?'L':'M'}${v.x.toFixed(1)},${v.y.toFixed(1)}`).join(' ');
    const last=xy.at(-1);
    const embedded=unit==='$'&&points.some(p=>p.pi_embedded_usd>0)?`<path class="series embedded" d="${xy.map((v,i)=>`${i?'L':'M'}${v.x.toFixed(1)},${(78-(v.p.pi_embedded_usd-min)*55/range).toFixed(1)}`).join(' ')}"/>`:'';
    return `<button type="button" class="chart" data-chart="${index}" aria-label="Open enlarged ${esc(title)} chart"><span class="chart-head"><span class="chart-title">${esc(title)}</span><strong>${unit==='$'?'$':''}${esc(last.p[key].toFixed(2))}${unit==='$'?'':esc(unit)}</strong></span><svg viewBox="0 0 350 100" aria-hidden="true"><path class="chart-baseline" d="M20 79H332"/><path class="series" d="${line}"/>${embedded}<circle class="chart-end" cx="${last.x}" cy="${last.y}" r="4"/></svg><span class="chart-foot">${points.length} observations <span>Click to inspect ↗</span></span></button>`;
  }
  function openChart(index) {
    const spec=chartSpecs[index];if(!spec)return;
    const points=spec.rows.filter(r=>Number.isFinite(r[spec.key]));
    const values=points.map(p=>p[spec.key]),min=Math.min(...values),max=Math.max(...values),range=max-min||1;
    const xs=points.map((p,i)=>p.number ?? i),xMin=Math.min(...xs),xMax=Math.max(...xs);
    const xy=points.map((p,i)=>({p,x:65+(xs[i]-xMin)*800/Math.max(1,xMax-xMin),y:300-(p[spec.key]-min)*260/range}));
    const path=xy.map((v,i)=>`${i?'L':'M'}${v.x.toFixed(1)},${v.y.toFixed(1)}`).join(' ');
    const embedded=spec.unit==='$'&&points.some(p=>p.pi_embedded_usd>0)?`<path class="modal-series embedded" d="${xy.map((v,i)=>`${i?'L':'M'}${v.x.toFixed(1)},${(300-(v.p.pi_embedded_usd-min)*260/range).toFixed(1)}`).join(' ')}"/>`:'';
    const grid=Array.from({length:5},(_,i)=>{
      const y=40+i*65,value=max-i*range/4;
      return `<path d="M65 ${y}H865"/><text x="57" y="${y+4}" text-anchor="end">${esc(value.toFixed(2))}</text>`;
    }).join('');
    const dots=xy.map(({p,x,y},i)=>`<circle class="modal-dot${p.candidate_id===selected?' selected':''}${p.is_best?' best':''}" cx="${x}" cy="${y}" r="3.5"><title>#${esc(p.number ?? i+1)} · ${esc(p[spec.key])}${esc(spec.unit)}${p.candidate_id?' · '+esc(p.candidate_id.slice(0,8)):''}</title></circle>`).join('');
    const table=points.map((p,i)=>`<tr ${p.candidate_id?`data-candidate="${esc(p.candidate_id)}"`:''}><td>${esc(p.number ?? i+1)}</td><td>${p.candidate_id?`#${esc(byId.get(p.candidate_id)?.index ?? '?')} ${esc(p.candidate_id.slice(0,8))}`:'cost event'}</td><td>${spec.unit==='$'?'$':''}${esc(p[spec.key].toFixed(4))}${spec.unit==='$'?'':esc(spec.unit)}</td><td>${p.pi_embedded_usd===undefined?'—':'$'+esc(p.pi_embedded_usd.toFixed(4))}</td><td>${esc(p.status ?? p.mode ?? p.kind ?? '—')}</td><td>${esc(p.tokens ?? '—')}</td><td>${esc(p.heartbeat ?? '—')}</td><td>${esc(p.local_proxy?.toFixed?.(2) ?? '—')}</td><td>${p.outstanding_usd===undefined?'—':esc(p.outstanding_usd.toFixed(4))}</td><td>${p.committed_usd===undefined?'—':esc(p.committed_usd.toFixed(4))}</td><td>${p.ts?esc(new Date(p.ts*1000).toLocaleString()):'—'}</td></tr>`).join('');
    const caption=spec.key==='spent_usd'?'Settled spend rises monotonically. Pending reservations and committed total are listed below.':'Click a candidate row to inspect its proof.';
    $('chart-dialog-body').innerHTML=`<div class="modal-head"><div><h2>${esc(spec.title)}</h2><p class="muted">${points.length} observations · ${esc(caption)} ${embedded?'· solid: ledger, dashed: Pi embedded estimate':''}</p></div><button id="close-chart" type="button" aria-label="Close chart">✕</button></div><svg class="modal-chart" viewBox="0 0 900 340" role="img" aria-label="${esc(spec.title)} full series"><g class="modal-grid">${grid}</g><path class="modal-series" d="${path}"/>${embedded}${dots}<text class="axis-label" x="65" y="331">${esc(xMin)}</text><text class="axis-label" x="865" y="331" text-anchor="end">${esc(xMax)}</text></svg><div class="chart-table-wrap"><table class="chart-table"><thead><tr><th>Point</th><th>Candidate</th><th>Value</th><th>Pi estimate</th><th>Status / mode</th><th>Tokens</th><th>Heartbeats</th><th>Proxy</th><th>Pending $</th><th>Committed $</th><th>Time</th></tr></thead><tbody>${table}</tbody></table></div>`;
    const dialog=$('chart-dialog');$('close-chart').onclick=()=>dialog.close();
    $('chart-dialog-body').querySelectorAll('[data-candidate]').forEach(row=>row.onclick=()=>{dialog.close();select(row.dataset.candidate)});
    dialog.showModal();
  }
  $('chart-dialog').addEventListener('click',e=>{if(e.target===$('chart-dialog'))e.target.close()});
  function renderCharts() {
    const bestIds=new Set(data.milestones.map(m=>m.candidate_id));
    const rows=data.timeline.map(r=>({...r,is_best:bestIds.has(r.candidate_id)}));
    chartSpecs=[
      {title:'Provisional score · 3/3 only',rows:rows.filter(r=>r.status==='full'),key:'local_proxy',unit:''},
      {title:'Proof tokens',rows:rows.filter(r=>r.status!=='fail'),key:'tokens',unit:''},
      {title:'Primary heartbeats',rows:rows.filter(r=>r.status!=='fail'),key:'heartbeat',unit:''},
      {title:'Settled API spend USD',rows:data.cost_timeline||[],key:'spent_usd',unit:'$'},
    ];
    $('charts').innerHTML=chartSpecs.map(chart).join('');
    $('charts').querySelectorAll('[data-chart]').forEach(el=>el.onclick=()=>openChart(Number(el.dataset.chart)));
  }
  function renderMeta() {
    $('run-label').textContent=`${data.theorem || ''} · ${data.run_id} · ${data.nodes.length} recorded nodes`;
    const full=data.nodes.filter(n=>n.status==='full').length, autos=data.nodes.filter(n=>n.origin==='auto_merge').length;
    const tested=(data.ideas||[]).filter(idea=>idea.attempts).length;
    $('metrics').innerHTML=[['3/3',full],['Ideas tested',`${tested}/${data.ideas?.length||0}`],['Evaluations',data.evaluations],['Auto merges',autos],['Merge checks',data.merge_checks.length]].map(([k,v])=>`<span class="metric">${esc(k)} <b>${esc(v)}</b></span>`).join('');
    const previous=$('idea-filter').value;
    $('idea-filter').innerHTML='<option value="all">All ideas</option>'+(data.ideas||[]).map(idea=>`<option value="${esc(idea.id)}">${esc(idea.title)}</option>`).join('');
    $('idea-filter').value=(data.ideas||[]).some(idea=>idea.id===previous)?previous:'all';
    $('idea-filter').hidden=!(data.ideas||[]).length;
    $('frontier').innerHTML=(data.ideas?.length ? data.ideas.map((idea,i)=>`<div class="idea-row${i===0?' scheduled':''}"><div><strong>${i===0?'NEXT · ':''}${esc(idea.title)}</strong><span class="muted"> · ${esc(idea.idea_kind)} · ${esc(idea.attempts)} nodes · ${esc(idea.probes)} scratch probes</span></div><p>${esc(idea.next_action)}</p><button data-go="${esc(idea.seed_candidate_id)}">Start from ${esc(numberForId(idea.seed_candidate_id))}</button>${idea.best_tokens!=null?`<span class="muted">Best ${esc(idea.best_tokens)} tokens</span>`:''}</div>`).join('') : (data.frontier||[]).slice(0,8).map(r=>`<div class="frontier-row"><button data-go="${r.candidate_id}">${esc(numberForId(r.candidate_id))}</button><span>${esc(r.status)} · priority ${esc(r.priority_total)} · ${esc(r.tokens ?? '?')} tokens</span></div>`).join(''))||'<p class="muted">No eligible seeds yet.</p>';
    $('frontier').querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>select(el.dataset.go));
    $('worker').innerHTML=`<span class="tag">${esc(data.worker?.state ?? 'not running')}</span> <span class="muted">${data.worker?.updated_at ? esc(new Date(data.worker.updated_at*1000).toLocaleTimeString()) : ''}</span>${data.worker?.detail?.candidate_id ? `<span>${esc(numberForId(data.worker.detail.candidate_id))}</span>` : ''}${data.worker?.detail?.error ? `<pre>${esc(data.worker.detail.error)}</pre>` : ''}`;
    const embedded=data.cost_report?.pi_embedded_estimate;
    $('cost-note').hidden=!(embedded&&embedded.priced_entries&&!embedded.missing_entries);
    if(!$('cost-note').hidden) $('cost-note').innerHTML=`Ledger-priced observed tokens <strong>$${esc(data.cost.spent_usd.toFixed(4))}</strong> · Pi embedded estimate <strong>$${esc(embedded.usd.toFixed(4))}</strong>. The two use different configured prices; neither is a provider invoice.`;
    $('merge-feed').innerHTML=data.merge_checks.slice(-25).reverse().map(c=>`<div class="feed-row">${c.candidate_id?`<button data-go="${esc(c.candidate_id)}">merge ${esc(numberForId(c.candidate_id))}</button>`:`<span class="muted">skip</span>`}<span>${esc(c.parents?.map(numberForId).join(' + '))}</span><span class="muted">${esc(c.reason || (c.full_passed?'3/3 valid':c.fast_passed?'primary valid':'Lean failed'))}</span></div>`).join('')||'<p class="muted">No pair checks yet.</p>';
    $('merge-feed').querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>select(el.dataset.go));
  }
  async function refresh() {
    try {
      const response=window.GRAPH_SNAPSHOT ? {ok:true,json:async()=>window.GRAPH_SNAPSHOT} : await fetch('/graph.json',{cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const next=await response.json(),revision=`${next.ledger_events}:${next.cost_timeline?.length}:${next.worker?.updated_at}`;
      $('live').textContent=window.GRAPH_SNAPSHOT?'Saved snapshot':`Live · ${new Date().toLocaleTimeString()}`;$('live').classList.add('ok');
      if(revision===lastRevision)return;
      lastRevision=revision;data=next;byId=new Map(data.nodes.map(n=>[n.id,n]));layout();renderGraph();detail();renderCharts();renderMeta();
    } catch(error) {$('live').textContent=`Disconnected · ${error.message}`;$('live').classList.remove('ok')}
  }
  refresh(); if(!window.GRAPH_SNAPSHOT)setInterval(refresh,2500);
})();
