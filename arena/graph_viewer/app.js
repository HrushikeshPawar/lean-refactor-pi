/* Static Arena graph viewer. The loopback server supplies graph.json; snapshots set GRAPH_SNAPSHOT. */
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>'$'+(v>=0.1?v.toFixed(3):v.toFixed(4));
(() => {
  if (/[?&]embed=1/.test(location.search)) document.body.classList.add('embed');
  const $ = id => document.getElementById(id);
  // localStorage can throw (private windows, blocked site data): every access is wrapped.
  const store = {get(k){try{return localStorage.getItem(k)}catch{return null}}, set(k,v){try{localStorage.setItem(k,v)}catch{}}};
  let data, byId = new Map(), pById = new Map(), probeItems = [], scratchItems = [], sById = new Map(), actorIds = [], probeKids = new Map(), coords = new Map(),
      selected = store.get('arena-selected') || null, hadStored = store.get('arena-selected') !== null,
      view = null, dragging = null, lastRevision = '', collapsed = new Set(), chartSpecs = [],
      hideInit = store.get('arena-hideinit') === '1', showProbes = store.get('arena-probes') !== '0', showScratch = store.get('arena-scratch') !== '0', showBest = store.get('arena-bestpath') !== '0',
      colorBy = ['route','status','actor'].includes(store.get('arena-colorby')) ? store.get('arena-colorby') : 'route',
      legendOpen = store.get('arena-legend') !== '0', hoverGroup = null,
      off = {kind: new Set(), status: new Set(), route: new Set(), actor: new Set()},
      bestPath = {nodes: new Set(), edges: new Set()}, tokenRange = [0, 1], routeById = new Map();
  const graph = $('graph'), wrap = $('graph-wrap'), minimap = $('minimap'), tip = $('node-tip');
  const STEP_X = 90, STEP_Y = 100;
  const STATUSES = [['verified','Verified 3/3'],['compiled','Compiled'],['unchecked','Not checked: below best'],['skeleton','Skeleton (sorry)'],['failed','Failed'],['unevaluated','Unevaluated']];
  const KINDS = [['candidate','Candidates'],['merge','Merges ⊕'],['probe','Probes'],['scratch','Scratch ⬡']];

  function status(node) { return node.status || 'fail'; }
  function best(node) { return node.evaluations.findLast(e => e.mode === 'full' && Object.keys(e.result.compat || {}).length === 3 && Object.values(e.result.compat).every(v => v.passed)) || node.evaluations.at(-1); }
  const shortLabel = node => node.node || `#${node.index}`;
  function nodeLabel(node) { return `${node.node || `#${node.index}`} ${node.id.slice(0,8)}`; }
  function numberForId(id) { return byId.has(id) ? (byId.get(id).node || `#${byId.get(id).index}`) : pById.has(id) ? (pById.get(id).node || `probe ${id.slice(0,6)}`) : String(id ?? '?').slice(0,8); }
  const isProbe = it => it.kind === 'probe';
  const isScratch = it => it.kind === 'scratch';
  const itemOf = id => byId.get(id) || pById.get(id) || sById.get(id);
  const allItems = () => [...data.nodes, ...(showProbes ? probeItems : []), ...(showScratch ? scratchItems : [])];
  const kidsOf = id => [...(byId.get(id)?.children || []), ...(probeKids.get(id) || []), ...scratchItems.filter(x => x.parents[0] === id).map(x => x.id)];
  function stat(it) {
    if (it.kind === 'scratch') return 'scratch';
    if (isProbe(it)) return it.status === 'skeleton' ? 'skeleton' : it.status === 'pass' ? 'compiled' : 'failed';
    // A fast (primary-toolchain) check only, no full check ever ran: the harness skips the full check below the verified best.
    if (it.status === 'primary' && !/\bsorry\b/.test(it.proof || '') && !it.evaluations?.some(e => e.mode === 'full')) return 'unchecked';
    return {full:'verified', primary:'compiled', fail:'failed'}[it.status] || 'unevaluated';
  }
  const kindOf = it => isProbe(it) ? 'probe' : isScratch(it) ? 'scratch' : it.origin === 'auto_merge' ? 'merge' : 'candidate';
  // Node size follows proof length (tokens); probes are small diamonds of a fixed size.
  function radius(it) {
    if (isProbe(it)) return 11;
    if (isScratch(it)) return 12;
    const t = it.tokens; if (t == null) return 16;
    const [lo, hi] = tokenRange; return 15 + 11 * Math.sqrt(Math.max(0, Math.min(1, (t - lo) / Math.max(1, hi - lo))));
  }
  const placeParents = it => it.parents.length ? it.parents : it.filed_under ? [it.filed_under] : [];
  function layout() {
    const depths = new Map(), layers = new Map(), hide = new Set();
    const visit = id => { for (const child of kidsOf(id)) if (!hide.has(child)) { hide.add(child); visit(child); } };
    for (const id of collapsed) visit(id);
    // Placement follows real parents, else the focus a draft was filed under (drawn dotted, not as lineage).
    // Depth is computed recursively so a node whose parent is a probe sits below it whatever the item order.
    const shown = new Map(allItems().filter(it => !hide.has(it.id)).map(it => [it.id, it]));
    const depthOf = (id, seen = new Set()) => {
      if (depths.has(id)) return depths.get(id);
      const it = shown.get(id); if (!it || seen.has(id)) return -1;
      seen.add(id);
      const ups = placeParents(it).filter(p => shown.has(p));
      const depth = ups.length ? 1 + Math.max(...ups.map(p => depthOf(p, seen))) : 0;
      depths.set(id, depth);
      return depth;
    };
    for (const node of shown.values()) {
      const depth = depthOf(node.id);
      if (!layers.has(depth)) layers.set(depth, []);
      layers.get(depth).push(node);
    }
    coords = new Map();
    const widest=Math.max(1,...[...layers.values()].map(nodes=>nodes.length));
    for (const [depth, nodes] of layers) {
      nodes.sort((a,b) => {
        const bary = n => { const ups = placeParents(n); return ups.length ? ups.reduce((s,p) => s + (coords.get(p)?.x ?? 0), 0) / ups.length : n.order * STEP_X; };
        return bary(a) - bary(b) || a.order - b.order;
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
    view = {x: point.x - w / 2, y: point.y - h / 2, w, h};
    // Keep the window on the graph: no empty space past the last layer when the graph is taller than the window.
    const W = Number(graph.dataset.width) || 800, H = Number(graph.dataset.height) || 500;
    if (h < H + 80) view.y = Math.max(-40, Math.min(view.y, H + 40 - h));
    if (w < W + 80) view.x = Math.max(-40, Math.min(view.x, W + 40 - w));
    applyView();
  }
  function applyView() {
    if (!view) return;
    graph.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
    if (!data) return;
    drawMinimap();
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
  wrap.addEventListener('wheel', e => { if (e.target.closest('.legend-panel')) return; e.preventDefault(); zoom(e.deltaY > 0 ? 1.13 : 0.885, e.clientX, e.clientY); }, {passive:false});
  wrap.addEventListener('pointerdown', e => { if (e.target.closest('.node, .legend-panel, .view-ctrl, #minimap')) return; dragging = {x:e.clientX,y:e.clientY,start:{...view},moved:false}; wrap.setPointerCapture(e.pointerId); wrap.classList.add('dragging'); });
  wrap.addEventListener('pointermove', e => { if (!dragging) return; if (Math.hypot(e.clientX-dragging.x,e.clientY-dragging.y)>4) dragging.moved=true; view.x = dragging.start.x - (e.clientX-dragging.x)*view.w/wrap.clientWidth; view.y = dragging.start.y - (e.clientY-dragging.y)*view.h/wrap.clientHeight; applyView(); });
  // A press on empty canvas that did not drag clears the selection.
  wrap.addEventListener('pointerup', () => { const click = dragging && !dragging.moved; dragging = null; wrap.classList.remove('dragging'); if (click) clearSelection(); });
  // Minimap: the whole graph (edges and status-coloured nodes) with the visible window outlined; it hides when everything is already in view.
  const MM_PAD=40;
  function mmBox(){return {W:Number(graph.dataset.width)||800,H:Number(graph.dataset.height)||500};}
  function drawMinimap() {
    const {W,H}=mmBox(),inside=view.x<=-MM_PAD/2&&view.y<=-MM_PAD/2&&view.x+view.w>=W+MM_PAD/2&&view.y+view.h>=H+MM_PAD/2;
    minimap.hidden=inside||!coords.size;if(minimap.hidden)return;
    minimap.setAttribute('viewBox',`${-MM_PAD} ${-MM_PAD} ${W+2*MM_PAD} ${H+2*MM_PAD}`);
    minimap.setAttribute('preserveAspectRatio','xMidYMid meet');
    const edges=[],dots=[];
    for(const node of allItems()){
      const p=coords.get(node.id);if(!p)continue;
      for(const parent of node.parents){const a=coords.get(parent);if(a)edges.push(`<line class="mm-edge" x1="${a.x}" y1="${a.y}" x2="${p.x}" y2="${p.y}"/>`);}
      if(isScratch(node)){dots.push(`<circle class="mm-node scratch ${scratchResult(node)}${selected===node.id?' sel':''}" cx="${p.x}" cy="${p.y}" r="${selected===node.id?14:5}"/>`);continue;}
      dots.push(`<circle class="mm-node ${esc(stat(node))}${selected===node.id?' sel':''}" cx="${p.x}" cy="${p.y}" r="${selected===node.id?16:isProbe(node)?6:11}"/>`);
    }
    minimap.innerHTML=`${edges.join('')}${dots.join('')}<rect class="mm-view" x="${view.x}" y="${view.y}" width="${view.w}" height="${view.h}"/>`;
  }
  function mmPoint(e){const ctm=minimap.getScreenCTM();return ctm?new DOMPoint(e.clientX,e.clientY).matrixTransform(ctm.inverse()):{x:0,y:0};}
  let mmDrag=false;
  const mmMove=e=>{const q=mmPoint(e);view.x=q.x-view.w/2;view.y=q.y-view.h/2;applyView();};
  minimap.addEventListener('pointerdown',e=>{e.stopPropagation();mmDrag=true;minimap.setPointerCapture(e.pointerId);mmMove(e);});
  minimap.addEventListener('pointermove',e=>{if(mmDrag)mmMove(e);});
  minimap.addEventListener('pointerup',()=>{mmDrag=false;});
  $('fit').onclick = fit; $('zoom-in').onclick = () => zoom(.8); $('zoom-out').onclick = () => zoom(1.25);
  $('search').oninput = () => { renderGraph(); renderChips(); };
  $('clear-sel').onclick = () => clearSelection();
  $('best-path').onclick = () => { showBest = !showBest; store.set('arena-bestpath', showBest ? '1' : '0'); renderChips(); renderGraph(); };

  // ---- colour, grouping and filters -------------------------------------------------------------
  const GREY = '#6f7f93';
  const routeColor = id => { const n = Number(String(id ?? '').replace(/\D/g, '')); return !id ? GREY : n <= 1 ? '#7a869a' : `hsl(${Math.round((n * 137.508) % 360)} 62% 52%)`; };
  // Colour-blind-safe set (Okabe-Ito based): green / sky blue / amber / vermillion / purple / grey differ in hue and lightness.
  const STATUS_FILL = {verified:'#1b6b4a', compiled:'#1d5f8c', unchecked:'#3d4856', skeleton:'#94640a', failed:'#9b2c25', unevaluated:'#58408a'};
  // Actor of a node: whoever made its first exact derivation (else its first attempt); probes and scratch rows carry their own actor_id.
  const UNKNOWN_ACTOR = 'unknown';
  const actorOf = it => isScratch(it) ? it.actor_id || UNKNOWN_ACTOR : isProbe(it) ? it.actor_id || UNKNOWN_ACTOR
    : (it.attempts || []).find(a => a.relation === 'exact' && a.actor_id)?.actor_id || (it.attempts || []).find(a => a.actor_id)?.actor_id || UNKNOWN_ACTOR;
  const actorColor = id => id === 'sol' ? '#e0a030' : id === UNKNOWN_ACTOR ? GREY : `hsl(${Math.round((190 + 47 * Math.max(0, actorIds.indexOf(id))) % 360)} 60% 52%)`;
  // Roles with the real model: the orchestrator is actor "sol" internally whatever model it runs.
  const actorLabel = id => {
    const m = data?.models || {}, actor = (data?.actors || []).find(a => a.actor_id === id), own = actor?.model;
    if (id === 'sol') return m.orchestrator ? `orchestrator · ${m.orchestrator}` : 'orchestrator';
    if (id === UNKNOWN_ACTOR) return id;
    const name = actor?.job ? (actor.role ? `${actor.job} ${actor.role}` : actor.job) : id;
    return own || m.worker ? `${name} · ${own || m.worker}` : name;
  };
  // The job's first task, shown as the legend tooltip.
  const actorTask = id => (data?.actors || []).find(a => a.actor_id === id)?.task || '';
  const probeLabel = p => p.node || p.index;
  const tagWidth = (label, pad) => Math.round(Math.max(30, 7.5 * String(label).length + pad));
  const hexPath = (w, h) => `M${-w / 2},0 L${-w / 2 + h / 2},${-h / 2} L${w / 2 - h / 2},${-h / 2} L${w / 2},0 L${w / 2 - h / 2},${h / 2} L${-w / 2 + h / 2},${h / 2}Z`;
  const SCRATCH_FILL = {ok:STATUS_FILL.verified, failed:STATUS_FILL.failed, other:'#44505f'};
  const scratchResult = e => e.outcome === 'success' || e.outcome === 'passed' ? 'ok' : e.outcome === 'failure' || e.outcome === 'proof_error' ? 'failed' : 'other';
  const fillOf = it => isScratch(it) ? SCRATCH_FILL[scratchResult(it)] : colorBy === 'route' ? routeColor(it.route) : colorBy === 'actor' ? actorColor(actorOf(it)) : STATUS_FILL[stat(it)];
  const clip = (text, n) => { text = String(text ?? '').replace(/\s+/g, ' ').trim(); return text.length > n ? text.slice(0, n - 1) + '…' : text; };
  const groupKey = (group, it) => group === 'route' ? (it.route || 'none') : group === 'kind' ? kindOf(it) : group === 'actor' ? actorOf(it) : stat(it);
  function visible(it) {
    if (off.kind.has(kindOf(it)) || off.actor.has(actorOf(it))) return false;
    if (!isScratch(it) && (off.status.has(stat(it)) || off.route.has(it.route || 'none'))) return false;
    const query = $('search').value.trim().toLowerCase();
    if (isScratch(it)) return !query || [it.experiment_id, it.headline, it.outcome, it.actor_id].some(x => String(x ?? '').toLowerCase().includes(query));
    return !query || [it.id, it.hypothesis, it.proof, it.origin, it.route, ...(it.headlines || [])].some(x => String(x ?? '').toLowerCase().includes(query));
  }
  const anyFilter = () => Object.values(off).some(set => set.size) || $('search').value.trim() || !showProbes || !showScratch;
  function toggleGroup(group, key, solo) {
    const set = off[group];
    if (solo) {
      const keys = group === 'route' ? [...routeById.keys(), 'none'] : group === 'actor' ? actorIds : group === 'status' ? STATUSES.map(x => x[0]) : KINDS.map(x => x[0]);
      const only = keys.every(k => k === key ? !set.has(k) : set.has(k));
      set.clear(); if (!only) keys.forEach(k => { if (k !== key) set.add(k); });
    } else set.has(key) ? set.delete(key) : set.add(key);
    renderChips(); renderLegend(); renderGraph();
  }
  function resetFilters() {
    Object.values(off).forEach(set => set.clear()); $('search').value = '';
    if (!showProbes) { showProbes = true; store.set('arena-probes', '1'); }
    if (!showScratch) { showScratch = true; store.set('arena-scratch', '1'); }
    relayout();
    renderChips(); renderLegend(); renderGraph();
  }
  function relayout() { layout(); }
  function counts(group) {
    const out = new Map();
    for (const it of data.nodes.concat(probeItems, group === 'kind' || group === 'actor' ? scratchItems : [])) { const k = groupKey(group, it); out.set(k, (out.get(k) || 0) + 1); }
    return out;
  }
  // An actor's legend line: all its canvas items, then how many are compiled nodes, probes and scratch experiments.
  function actorStats(actor) {
    const mine = data.nodes.concat(probeItems, scratchItems).filter(it => actorOf(it) === actor);
    const of = kind => mine.filter(it => kind === 'scratch' ? isScratch(it) : kind === 'probe' ? isProbe(it) : !isScratch(it) && !isProbe(it)).length;
    return `${mine.length} total · ${of('node')} compiled · ${of('probe')} probes · ${of('scratch')} scratch`;
  }
  function paintSwatches(root) { root.querySelectorAll('[data-bg]').forEach(el => { el.style.background = el.dataset.bg; }); }
  // Chips: kind and status filters. The Probes chip shows or hides the probe nodes and re-lays out the graph.
  function renderChips() {
    const k = counts('kind'), st = counts('status');
    const chip = (group, key, label, n, on, extra = '') => `<button type="button" class="chip${on ? '' : ' off'}${extra}" data-group="${group}" data-key="${key}" aria-pressed="${on}" title="Click to ${on ? 'hide' : 'show'}; shift-click to show only this">${group === 'status' ? `<i class="st-dot st-${key}"></i>` : key === 'probe' ? '<i class="probe-dot"></i>' : key === 'scratch' ? '<i class="scratch-dot"></i>' : ''}${esc(label)} <b>${n ?? 0}</b></button>`;
    $('chips').innerHTML = KINDS.map(([key, label]) => chip('kind', key, label, k.get(key), key === 'probe' ? showProbes : key === 'scratch' ? showScratch : !off.kind.has(key))).join('')
      + '<span class="chip-sep"></span>' + STATUSES.filter(([key]) => st.get(key) || off.status.has(key)).map(([key, label]) => chip('status', key, label, st.get(key), !off.status.has(key))).join('');
    $('best-path').setAttribute('aria-pressed', String(showBest)); $('best-path').disabled = !bestPath.nodes.size;
    $('reset-filters').hidden = !anyFilter();
    $('clear-sel').disabled = !selected;
  }
  $('chips').addEventListener('click', e => {
    const b = e.target.closest('.chip'); if (!b) return;
    const {group, key} = b.dataset;
    if (group === 'kind' && (key === 'probe' || key === 'scratch')) {
      if (key === 'probe') { showProbes = !showProbes; store.set('arena-probes', showProbes ? '1' : '0'); } else { showScratch = !showScratch; store.set('arena-scratch', showScratch ? '1' : '0'); }
      const sel = selected && itemOf(selected);
      if (sel && ((isProbe(sel) && !showProbes) || (isScratch(sel) && !showScratch))) { selected = null; store.set('arena-selected', ''); detail(); }
      relayout(); renderChips(); renderGraph(); renderLegend(); return;
    }
    toggleGroup(group, key, e.shiftKey);
  });
  $('reset-filters').onclick = resetFilters;
  // The legend doubles as the route / status filter: swatch = colour, click = show or hide that group,
  // shift-click = show only it, hover = spotlight it on the graph.
  function renderLegend() {
    const panel = $('legend'); if (!data) return;
    const seg = [['route','Route'],['status','Status'],['actor','Actor']].map(([id, label]) => `<button type="button" data-color="${id}" aria-pressed="${colorBy === id}">${label}</button>`).join('');
    const n = counts(colorBy);
    let rows = '';
    if (colorBy === 'route') {
      const list = (data.routes || []).slice(); if (n.get('none')) list.push({route: 'none', label: 'no route recorded'});
      rows = list.map(r => {
        const key = r.route, stats = r.route === 'none' ? '' : `${r.attempts ?? 0} att${r.best_proxy != null ? ` · best ${r.best_proxy.toFixed(1)}` : ''}`;
        const tags = `${r.original ? '<span class="lp-tag">original</span>' : ''}${r.credited ? '<span class="lp-tag good" title="credited: verified structure and new goal states">credited</span>' : r.explored ? '<span class="lp-tag" title="explored but not credited">explored</span>' : ''}`;
        return `<button type="button" class="lp-item${off.route.has(key) ? ' off' : ''}" data-group="route" data-key="${esc(key)}" aria-pressed="${!off.route.has(key)}" title="${esc(r.label || '')}"><i class="sw" data-bg="${routeColor(r.route === 'none' ? null : r.route)}"></i><span class="lp-name"><b>${esc(key)}</b> ${esc(clip(r.short_label || r.label, 44))}</span><span class="lp-stats">${tags}${esc(stats)} · ${n.get(key) ?? 0} nodes</span></button>`;
      }).join('');
    } else if (colorBy === 'actor') {
      rows = actorIds.map(key => `<button type="button" class="lp-item${off.actor.has(key) ? ' off' : ''}" title="${esc(actorTask(key))}" data-group="actor" data-key="${esc(key)}" aria-pressed="${!off.actor.has(key)}"><i class="sw" data-bg="${actorColor(key)}"></i><span class="lp-name"><b>${esc(actorLabel(key))}</b></span><span class="lp-stats">${esc(actorStats(key))}</span></button>`).join('');
    } else {
      rows = STATUSES.map(([key, label]) => `<button type="button" class="lp-item${off.status.has(key) ? ' off' : ''}" data-group="status" data-key="${key}" aria-pressed="${!off.status.has(key)}"><i class="sw" data-bg="${STATUS_FILL[key]}"></i><span class="lp-name">${esc(label)}</span><span class="lp-stats">${n.get(key) ?? 0} nodes</span></button>`).join('');
    }
    panel.innerHTML = `<div class="lp-head"><button type="button" class="lp-toggle" aria-expanded="${legendOpen}">${legendOpen ? '▾' : '▸'} Legend</button><span class="seg" role="group" aria-label="Colour nodes by">${seg}</span></div>
      <div class="lp-body"${legendOpen ? '' : ' hidden'}><div class="lp-list">${rows}</div>
      <div class="lp-key"><span><svg width="34" height="14"><circle cx="7" cy="7" r="4.5" class="k-small"/><circle cx="24" cy="7" r="6.5" class="k-big"/></svg>size = proof tokens</span>
      <span><svg width="34" height="14"><circle cx="7" cy="7" r="6" class="b-ver"/><circle cx="25" cy="7" r="6" class="b-fail"/></svg>border = result</span>
      <span><svg width="34" height="16"><rect x="3" y="2" width="28" height="12" rx="4" class="k-probe"/></svg>probe (label = model node id)</span>
      <span><svg width="64" height="16"><path d="M2,8 L6,2 L24,2 L28,8 L24,14 L6,14Z" class="k-scratch ok"/><path d="M36,8 L40,2 L58,2 L62,8 L58,14 L40,14Z" class="k-scratch failed"/></svg>scratch experiment e1, e2… (ok / failed)</span>
      <span><svg width="34" height="14"><path d="M1,7H33" class="k-scratch-edge"/></svg>scratch link (dashed; thick border = promoted)</span>
      <span><svg width="34" height="14"><path d="M1,7H33" class="k-filed-edge"/></svg>filed under focus (no parent)</span>
      <span><svg width="34" height="14"><path d="M1,7H33" class="k-best"/></svg>best path</span></div></div>`;
    paintSwatches(panel);
  }
  $('legend').addEventListener('click', e => {
    const c = e.target.closest('[data-color]');
    if (c) { colorBy = c.dataset.color; store.set('arena-colorby', colorBy); renderLegend(); renderGraph(); return; }
    if (e.target.closest('.lp-toggle')) { legendOpen = !legendOpen; store.set('arena-legend', legendOpen ? '1' : '0'); renderLegend(); return; }
    const item = e.target.closest('.lp-item'); if (item) toggleGroup(item.dataset.group, item.dataset.key, e.shiftKey);
  });
  // Spotlight: hovering a legend item dims every node outside that group without re-rendering.
  function spotlight(group, key) {
    hoverGroup = group ? {group, key} : null;
    graph.querySelectorAll('.node').forEach(g => g.classList.toggle('spot-off', !!group && g.dataset[group] !== key));
  }
  $('legend').addEventListener('mouseover', e => { const i = e.target.closest('.lp-item'); if (i) spotlight(i.dataset.group, i.dataset.key); });
  $('legend').addEventListener('mouseout', e => { if (e.target.closest('.lp-item')) spotlight(null); });

  function lineageOf(id) {
    const nodes=new Set(), edges=[], seenEdges=new Set();
    if (pById.has(id) || sById.has(id)) {
      const probe = itemOf(id), parent = probe.parents[0];
      const base = parent ? lineageOf(parent) : {nodes: new Set(), edges: [], edgeKeys: new Set()};
      base.nodes.add(id);
      if (parent) { base.edges.push({parent, child: id}); base.edgeKeys.add(`${parent}:${id}`); }
      return base;
    }
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
  // The route from the original proof to the best verified candidate (first-parent chain).
  function computeBestPath() {
    bestPath = {nodes: new Set(), edges: new Set()};
    // Every item the best proof came through: real parents, else the focus it was filed under; probes and a
    // scratch experiment promoted into a node on the path count too.
    let current = data.milestones.at(-1)?.candidate_id;
    while (current && itemOf(current) && !bestPath.nodes.has(current)) {
      bestPath.nodes.add(current);
      const promoted = scratchItems.find(x => x.promotedTo === current);
      if (promoted) { bestPath.nodes.add(promoted.id); bestPath.edges.add(`${promoted.id}>${current}`); }
      const parent = placeParents(itemOf(current))[0];
      if (parent && itemOf(parent)) bestPath.edges.add(`${parent}:${current}`);
      current = parent;
    }
    if (bestPath.nodes.size < 2) bestPath = {nodes: new Set(), edges: new Set()};
  }
  function renderGraph() {
    if (!data) return;
    const milestone = new Set(data.milestones.map(m => m.candidate_id)), topBest = data.milestones.at(-1)?.candidate_id;
    const lineage = selected && itemOf(selected) ? lineageOf(selected) : {nodes: new Set(), edgeKeys: new Set()};
    const edges = [], boxes = [], items = allItems();
    for (const it of items) {
      if (!coords.has(it.id)) continue;
      const p = coords.get(it.id), dim = visible(it) ? '' : ' dim', probe = isProbe(it), scratch = isScratch(it);
      const derivations = it.derivations?.length ? it.derivations : [{parents: it.parents}];
      derivations.forEach((d, i) => d.parents.forEach(parent => {
        const a = coords.get(parent); if (!a) return;
        const key = `${parent}:${it.id}`;
        const focus = lineage.edgeKeys.has(key) ? ' lineage' : '', faded = selected && !focus ? ' unrelated' : '';
        const onBest = showBest && bestPath.edges.has(key) ? ' bestpath' : '';
        const ay = a.y + radius(itemOf(parent)), cy = p.y - radius(it), bend = Math.max(18, (cy - ay) * .48);
        edges.push(`<path class="edge${probe ? ' probe-edge' : ''}${scratch ? ' scratch-edge' : ''}${i ? ' alternate' : ''}${onBest}${focus}${faded}${dim}" d="M${a.x},${ay} C${a.x},${ay + bend} ${p.x},${cy - bend} ${p.x},${cy}"/>`);
      }));
      if (it.filed_under && coords.has(it.filed_under)) {
        const a = coords.get(it.filed_under), ay = a.y + radius(itemOf(it.filed_under)), cy = p.y - radius(it), bend = Math.max(18, (cy - ay) * .48);
        const onBest = showBest && bestPath.edges.has(`${it.filed_under}:${it.id}`) ? ' bestpath' : '';
        edges.push(`<path class="edge filed-edge${onBest}${selected && selected !== it.id && !onBest ? ' unrelated' : ''}${dim}" d="M${a.x},${ay} C${a.x},${ay + bend} ${p.x},${cy - bend} ${p.x},${cy}"/>`);
      }
      if (scratch && it.promotedTo && coords.has(it.promotedTo) && (showScratch)) {
        const b = coords.get(it.promotedTo), top = Math.min(p.y, b.y) - 38;
        const onBest = showBest && bestPath.edges.has(`${it.id}>${it.promotedTo}`) ? ' bestpath' : '';
        edges.push(`<path class="edge scratch-edge promotes${onBest}${selected && selected !== it.id && selected !== it.promotedTo && !onBest ? ' unrelated' : ''}${dim}" d="M${p.x},${p.y} Q${(p.x + b.x) / 2},${top} ${b.x},${b.y}"/>`);
      }
      const R = radius(it), st = stat(it);
      const cls = `node k-${probe ? 'probe' : scratch ? 'scratch res-' + scratchResult(it) + (it.promotedTo ? ' promoted' : '') : 'candidate'} st-${st}${it.origin === 'auto_merge' ? ' auto_merge' : ''}${milestone.has(it.id) ? ' best' : ''}${showBest && bestPath.nodes.has(it.id) ? ' onbest' : ''}${lineage.nodes.has(it.id) && selected !== it.id ? ' ancestor' : ''}${selected === it.id ? ' selected' : ''}${selected && !lineage.nodes.has(it.id) ? ' unrelated' : ''}${dim}${hoverGroup && groupKey(hoverGroup.group, it) !== hoverGroup.key ? ' spot-off' : ''}`;
      const data_ = `data-id="${esc(it.id)}" data-route="${esc(it.route || 'none')}" data-status="${st}" data-kind="${kindOf(it)}" data-actor="${esc(actorOf(it))}"`;
      const fill = fillOf(it);
      if (scratch) { const lab = it.index, w = tagWidth(lab, 20) + 6, h = 2 * R;
        boxes.push(`<g class="${cls}" ${data_} transform="translate(${p.x},${p.y})"><rect class="hit" x="${-w / 2 - 3}" y="${-R - 3}" width="${w + 6}" height="${h + 6}"/>${colorBy === 'actor' ? `<path class="actor-ring" fill="none" stroke="${actorColor(actorOf(it))}" d="${hexPath(w + 8, h + 8)}"/>` : ''}<path class="node-body" fill="${fill}" d="${hexPath(w, h)}"/><text class="node-tag" text-anchor="middle" dominant-baseline="central">${esc(lab)}</text></g>`); }
      else if (probe) { const lab = probeLabel(it), w = tagWidth(lab, 14), h = 2 * R;
        boxes.push(`<g class="${cls}" ${data_} transform="translate(${p.x},${p.y})"><rect class="hit" x="${-w / 2 - 3}" y="${-R - 3}" width="${w + 6}" height="${h + 6}"/>${colorBy === 'actor' ? `<rect class="actor-ring" fill="none" stroke="${actorColor(actorOf(it))}" x="${-w / 2 - 4}" y="${-R - 4}" width="${w + 8}" height="${h + 8}" rx="9"/>` : ''}<rect class="node-body" fill="${fill}" x="${-w / 2}" y="${-R}" width="${w}" height="${h}" rx="7"/><text class="node-tag" text-anchor="middle" dominant-baseline="central">${esc(lab)}</text></g>`); }
      else boxes.push(`<g class="${cls}" ${data_} transform="translate(${p.x},${p.y})"><circle class="hit" r="${R + 4}"/>${it.origin === 'auto_merge' ? `<circle class="merge-ring" r="${R + 6}"/><text class="merge-badge" x="${R - 1}" y="${-R + 2}">⊕</text>` : ''}<circle class="node-body" r="${R}" fill="${fill}"/><text class="node-number${shortLabel(it).length > 3 ? ' small' : ''}" text-anchor="middle" dominant-baseline="central">${esc(shortLabel(it))}</text>${it.id === topBest ? `<text class="best-star" x="${-R + 2}" y="${-R + 4}">★</text>` : ''}</g>`);
    }
    graph.innerHTML = edges.join('') + boxes.join(''); applyView();
    renderChips();
  }
  // One delegated handler: click selects, a second click on the selected node clears it.
  graph.addEventListener('click', e => {
    const el = e.target.closest('.node'); if (!el) return;
    el.dataset.id === selected ? clearSelection() : select(el.dataset.id, {focus: false});
  });
  // Hover card.
  const stTag = st => `<span class="tag st-tag st-${st}">${esc(STATUSES.find(x => x[0] === st)?.[1] || st)}</span>`;
  function nodeTip(it) {
    const r = routeById.get(it.route), row = (k, v) => v == null || v === '' ? '' : `<div class="tip-row"><span>${k}</span><b>${v}</b></div>`;
    const route = it.route ? `<i class="sw" data-bg="${routeColor(it.route)}"></i>${esc(it.route)}${it.route_inherited ? ' (parent)' : ''}${r ? ` · ${esc(clip(r.label, 46))}` : ''}` : '<span class="muted">none</span>';
    const routeState = r ? `${r.depth ?? 0} goal states${r.min_holes != null ? `, min ${r.min_holes} holes` : ''}${r.credited ? ' · credited' : r.explored ? ' · explored' : ''}` : '';
    if (isScratch(it)) {
      return `<div class="tip-head">Scratch ${esc(it.index)} · ${esc(String(it.experiment_id ?? it.code_sha256 ?? '?').slice(0, 12))} ${tagHtml(it.outcome || it.phase || 'accepted', scratchResult(it) === 'ok' ? 'good' : scratchResult(it) === 'failed' ? 'bad' : '')}</div>
        ${row('Actor', `<i class="sw" data-bg="${actorColor(actorOf(it))}"></i>${esc(actorLabel(actorOf(it)))}`)}${row('Anchor', esc(it.anchorNote))}${row('Promotion', it.promotion?.state ? esc(`${it.promotion.state}${it.promotion.reason ? `: ${it.promotion.reason}` : ''}`) : null)}
        ${it.promotedTo ? row('Promoted to', esc(numberForId(it.promotedTo))) : ''}${it.headline ? `<div class="tip-note">${esc(clip(it.headline, 160))}</div>` : ''}`;
    }
    if (isProbe(it)) {
      return `<div class="tip-head">Probe ${esc(probeLabel(it))} · ${esc(it.id.slice(0, 8))} ${stTag(stat(it))}</div>${row('Tokens', it.tokens != null ? esc(it.tokens) : null)}${row('Heartbeats', it.heartbeat != null ? esc(it.heartbeat) : null)}
        ${row('Open goals', it.status === 'skeleton' ? `${esc(it.goals)} ${it.goals === 1 ? 'hole' : 'holes'}` : it.status === 'fail' ? `${esc(it.errors ?? '?')} error${it.errors === 1 ? '' : 's'}` : 'none')}
        ${row('Route', route)}${row('Route state', esc(routeState))}${row('Parent', it.parent ? esc(numberForId(it.parent)) : it.filed_under ? `none · filed under ${esc(numberForId(it.filed_under))}` : 'root')}
        ${it.headlines?.[0] ? `<div class="tip-note">${esc(clip(it.headlines[0], 160))}</div>` : it.first_goal ? `<div class="tip-note mono">${esc(clip(it.first_goal, 160))}</div>` : ''}`;
    }
    const proxy = it.local_proxy?.toFixed?.(2);
    return `<div class="tip-head">${esc(nodeLabel(it))} ${stTag(stat(it))}${it.origin === 'auto_merge' ? ' <span class="merge-mark">⊕ merge</span>' : ''}${data.milestones.at(-1)?.candidate_id === it.id ? ' <span class="tag good">best verified</span>' : ''}</div>
      ${row('Tokens', it.tokens != null ? esc(it.tokens) : null)}${row('Heartbeats', it.heartbeat != null ? esc(it.heartbeat) : null)}${row('Proxy', proxy ? esc(proxy) : null)}
      ${row('Actor', `<i class="sw" data-bg="${actorColor(actorOf(it))}"></i>${esc(actorLabel(actorOf(it)))}`)}
      ${row('Route', route)}${row('Route state', esc(routeState))}${row('Parents', it.parents.length ? it.parents.map(x => esc(numberForId(x))).join(', ') : it.filed_under ? `none · filed under ${esc(numberForId(it.filed_under))}` : 'root')}
      ${it.hypothesis ? `<div class="tip-note">${esc(clip(it.hypothesis, 170))}</div>` : ''}`;
  }
  graph.addEventListener('mousemove', e => {
    const el = e.target.closest('.node'), it = el && itemOf(el.dataset.id);
    if (!it) { tip.hidden = true; return; }
    if (tip.dataset.id !== el.dataset.id) { tip.innerHTML = nodeTip(it); paintSwatches(tip); tip.dataset.id = el.dataset.id; }
    tip.hidden = false;
    const box = wrap.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 16, y = e.clientY + 16;
    if (x + w > box.right - 6) x = e.clientX - w - 16;
    if (y + h > window.innerHeight - 6) y = e.clientY - h - 16;
    tip.style.left = `${Math.max(6, x)}px`; tip.style.top = `${Math.max(6, y)}px`;
  });
  graph.addEventListener('mouseleave', () => { tip.hidden = true; tip.dataset.id = ''; });
  wrap.addEventListener('pointerdown', () => { tip.hidden = true; });
  // Highlight a diff row with Lean syntax; old and new sides keep their own block-comment state.
  function hl(row,hlOld,hlNew) {
    const L=window.LeanHL;if(!L)return esc(row.text);
    if(row.kind==='del')return L.line(row.text,hlOld);
    if(row.kind==='same')L.line(row.text,hlOld);
    return L.line(row.text,hlNew);
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
    const out=[],hlOld={block:0},hlNew={block:0},HL=window.LeanHL;
    for(let index=0;index<rows.length;){
      if(!showAll&&!context.has(index)){
        let end=index+1;while(end<rows.length&&!context.has(end))end++;
        out.push(`<div class="diff-fold">⋯ ${end-index} unchanged lines hidden</div>`);index=end;continue;
      }
      const row=rows[index++],sign=row.kind==='add'?'+':row.kind==='del'?'-':' ';
      out.push(`<div class="diff-row ${row.kind}"><span class="diff-gutter">${row.old}</span><span class="diff-gutter">${row.new}</span><span class="diff-sign">${sign}</span><span class="diff-text">${hl(row,hlOld,hlNew)}</span></div>`);
    }
    return out.join('');
  }
  const facts=rows=>`<dl class="facts">${rows.map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const routeName=id=>{const r=(data.routes||[]).find(x=>x.route===id);return r?`${id} (${r.label}) · ${r.depth??0} goal states${r.min_holes!=null?`, min holes ${r.min_holes}`:''}${r.stale_streak?`, stale ${r.stale_streak}`:''}, ${r.explored?'explored':'opened'}${r.credited?', credited':''}`:id;};
  function context(node) {
    const evaluated=best(node)?.result||{},derived=node.derivations||[],ancestry=lineageOf(node.id);
    const reference=[...ancestry.nodes].map(id=>byId.get(id)).find(item=>item.origin==='reference');
    const root=reference||[...ancestry.nodes].map(id=>byId.get(id)).sort((a,b)=>a.index-b.index)[0];
    return {evaluated,derived,ancestry,reference,root};
  }
  const goBtn=p=>`<button data-go="${esc(p)}">${esc(byId.get(p)?nodeLabel(byId.get(p)):pById.has(p)?(pById.get(p).node||`probe ${p.slice(0,6)}`):p.slice(0,8))}</button>`;
  const actorBadge=it=>{const own=actorOf(it),others=[...new Set((it.attempts||[]).map(a=>a.actor_id).filter(a=>a&&a!==own))];return `<span class="route-badge"><i class="sw" data-bg="${actorColor(own)}"></i><b>${esc(actorLabel(own))}</b>${others.length?` <span class="muted">also ${others.map(a=>esc((data?.actors||[]).find(x=>x.actor_id===a)?.job||actorLabel(a))).join(', ')}</span>`:''}</span>`;};
  const routeBadge=id=>{const r=routeById.get(id);return `<span class="route-badge"><i class="sw" data-bg="${routeColor(id)}"></i><b>${esc(id)}</b> ${r?esc(clip(r.label,60)):''}${r?.credited?' <span class="tag good">credited</span>':r?.explored?' <span class="tag">explored</span>':''}</span>`;};
  // Nothing selected: the run at a glance (best path, routes) instead of an empty panel.
  function overview() {
    const top=data.milestones.at(-1),routes=(data.routes||[]);
    $('detail').innerHTML=`<div class="side"><div class="card sumcard"><h2>Run overview</h2><p class="muted small">Click a node to inspect it; click it again, click empty canvas or press Esc to clear. Hover a legend item to spotlight it.</p>
      ${facts([['Candidates',esc(data.nodes.length)],['Probes',esc(probeItems.length)],['Best verified',top?`<button data-go="${esc(top.candidate_id)}" class="primary">${esc(numberForId(top.candidate_id))}</button> proxy ${esc(top.local_proxy?.toFixed?.(2)??'—')}, ${esc(top.tokens??'?')} tok`:'<span class="muted">none yet</span>'],...(data.target?[['Best to beat',`<b>${esc(data.target.proxy.toFixed(2))}</b> proxy <span class="muted">· run best ${esc(top?.local_proxy?.toFixed?.(2)??'—')}</span>${deltaHtml(top?.local_proxy,data.target.proxy)}`]]:[]),['Best path',bestPath.nodes.size?`${bestPath.nodes.size} proofs, original to best`:'<span class="muted">n/a</span>']])}</div>
      <div class="card ancard"><h3>Routes (${routes.length})</h3><div class="evals">${routes.map(r=>`<div class="eval-line route-line" data-route-solo="${esc(r.route)}"><i class="sw" data-bg="${routeColor(r.route)}"></i><b>${esc(r.route)}</b><span class="muted">${esc(clip(r.label,52))}</span><span>${esc(r.attempts??0)} att${r.best_proxy!=null?` · ${esc(r.best_proxy.toFixed(1))}`:''}</span>${r.credited?'<span class="tag good">credited</span>':r.explored?'<span class="tag">explored</span>':''}</div>`).join('')||'<p class="muted">No routes recorded.</p>'}</div></div></div>`;
    paintSwatches($('detail'));
    $('detail').querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>select(el.dataset.go));
    $('detail').querySelectorAll('[data-route-solo]').forEach(el=>el.onclick=e=>{colorBy='route';store.set('arena-colorby','route');toggleGroup('route',el.dataset.routeSolo,true)});
  }
  function probeDetail(p) {
    const tag=(text,kind='')=>`<span class="tag ${kind}">${esc(text)}</span>`,st=stat(p);
    $('detail').innerHTML=`<div class="side"><div class="card sumcard"><h2>Probe ${esc(probeLabel(p))} <span class="muted">${esc(p.id.slice(0,8))}</span> ${stTag(st)}</h2>
      ${facts([['Tokens',esc(p.tokens??'?')],['Heartbeats',esc(p.heartbeat??'—')],['Open goals',p.status==='skeleton'?`${esc(p.goals)} (sorry skeleton)`:p.status==='fail'?`${esc(p.errors??'?')} error(s)`:'none'],
        ['Route',p.route?routeBadge(p.route):'<span class="muted">none</span>'],['Parent',p.parent?goBtn(p.parent):'<span class="muted">none</span>']])}
      <div class="muted small">A probe is a quick compile of a proof sketch; it is not an evaluated candidate and has no score.</div>
      <div class="actions"><button type="button" data-open="calls">Reasoning & calls ↗</button></div></div>
      ${p.headlines?.length?`<div class="card hypcard"><h3>Lean errors</h3>${p.headlines.map(h=>`<p class="hyp">${esc(h)}</p>`).join('')}</div>`:''}
      ${p.first_goal?`<div class="card hypcard"><h3>First open goal</h3><pre class="hyp mono">${esc(p.first_goal)}</pre></div>`:''}</div>`;
    paintSwatches($('detail'));
    $('detail').querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>select(el.dataset.go));
    $('detail').querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>openDetail(el.dataset.open));
  }
  const nodeExperiments=node=>(data.experiments||[]).filter(e=>e.proof_id===node.id||(e.at&&JSON.stringify(e.at).includes(node.id))||(e.at&&[node.node,numberForId(node.id)].some(label=>label&&(e.at===label||e.at.node===label))));
  function scratchDetail(x) {
    $('detail').innerHTML = `<div class="side"><div class="card sumcard"><h2>Scratch experiment ${esc(x.index)} ${tagHtml(x.outcome || x.phase || 'accepted', scratchResult(x) === 'ok' ? 'good' : scratchResult(x) === 'failed' ? 'bad' : '')}</h2>
      ${facts([['Experiment', `<b>${esc(x.index)}</b> <span class="muted">${esc(x.experiment_id ?? x.code_sha256 ?? '?')}</span>`], ['Actor', `<span class="route-badge"><i class="sw" data-bg="${actorColor(actorOf(x))}"></i>${esc(actorLabel(actorOf(x)))}</span>`],
        ['Anchor', `${esc(x.anchorNote)} ${x.parents[0] ? goBtn(x.parents[0]) : ''}`],
        ['Promotion', x.promotion?.state ? `${esc(x.promotion.state)}${x.promotion.reason ? `: ${esc(x.promotion.reason)}` : ''}${x.promotedTo ? ' ' + goBtn(x.promotedTo) : ''}` : '<span class="muted">none</span>']])}
      <div class="muted small">A scratch experiment is a trial run outside the proof graph. Dashed link = anchor; arc = promoted into a proof node.</div></div>
      <div class="card">${experimentRowsHtml([x])}</div></div>`;
    paintSwatches($('detail'));
    bindExperiments($('detail'));
    $('detail').querySelector('[data-experiment]')?.click();
    $('detail').querySelectorAll('[data-go]').forEach(el => el.onclick = () => select(el.dataset.go));
  }
  function detail() {
    if (sById.has(selected)) { scratchDetail(sById.get(selected)); return; }
    if (pById.has(selected)) { probeDetail(pById.get(selected)); return; }
    const node=byId.get(selected);
    if (!node) { overview(); return; }
    const parents=[...new Set((node.derivations?.length?node.derivations:[{parents:node.parents}]).flatMap(d=>d.parents||[]))];
    const tag=(text,kind='')=>`<span class="tag ${kind}">${esc(text)}</span>`;
    const proxy=node.local_proxy?.toFixed?.(2),chain=[...lineageOf(node.id).nodes].map(id=>byId.get(id)).sort((x,y)=>x.index-y.index);
    const evals=node.evaluations.map(e=>`<div class="eval-line"><strong>#${e.number}</strong> <span class="muted">${esc(e.mode)}</span> <span>${esc(e.result.tokens ?? '?')} tok · ${esc(e.result.heartbeat ?? '?')} hb · ${esc(e.result.local_proxy?.toFixed?.(2) ?? '—')}</span>${Object.entries(e.result.compat||{}).map(([v,r])=>`<span class="tag ${r.passed?'good':'bad'}">${esc(v)} ${r.passed?'✓':'✗'}</span>`).join('')}</div>`).join('');
    $('detail').innerHTML=`<div class="side">
      <div class="card sumcard"><h2>${esc(nodeLabel(node))} ${node.origin==='auto_merge'?'<span class="merge-mark">⊕ merge</span>':''}</h2>
        ${facts([['Status',tag(status(node),node.status==='full'?'good':node.status==='fail'?'bad':'')],['Tokens',esc(node.tokens ?? '?')],['Heartbeats',esc(node.heartbeat ?? '?')],['Score',esc(proxy ?? '—')],
                 ['Actor',actorBadge(node)],['Route',node.route?routeBadge(node.route):'<span class="muted">none</span>'],['Parent',parents.length?parents.map(goBtn).join(' '):node.filed_under?`<span class="muted">none · filed under</span> ${goBtn(node.filed_under)}`:'<span class="muted">root</span>'],
                 ['Children',node.children.length?node.children.map(goBtn).join(' '):'<span class="muted">none</span>'],...((probeKids.get(node.id)||[]).length?[['Probes',(probeKids.get(node.id)).map(goBtn).join(' ')]]:[])])}
        <div class="actions"><button type="button" data-open="overview" class="primary">Details ↗</button><button type="button" data-open="diff">Diff ↗</button><button type="button" data-open="proof">Proof ↗</button><button type="button" data-open="lineage">Lineage ↗</button></div></div>
      ${node.hypothesis||node.origin==='auto_merge'?`<div class="card hypcard"><h3>Note</h3><p class="hyp">${esc(node.hypothesis||'Deterministic combination of disjoint edits')}</p></div>`:''}
      <div class="card"><h3>Evaluations (${node.evaluations.length})</h3><div class="evals">${evals||'<p class="muted">None yet.</p>'}</div></div>
      <div class="card"><h3>Verification</h3><div class="tags">${verificationHtml(node)}</div>${attemptsHtml(node.attempts,node.evaluations)}${derivationsHtml(node.alternate_derivations,'Alternate derivations')}${experimentsHtml(nodeExperiments(node),'Scratch experiments on this proof')}</div>
      <div class="card ancard"><h3>Ancestry (${chain.length})</h3><div class="evals">${chain.map(n=>`<div class="eval-line"><button data-go="${esc(n.id)}" class="${n.id===node.id?'primary':''}">${esc(shortLabel(n))}</button><span class="tag ${n.status==='full'?'good':n.status==='fail'?'bad':''}">${esc(status(n))}</span><span>${esc(n.tokens ?? '?')} tok · ${esc(n.heartbeat ?? '?')} hb · ${esc(n.local_proxy?.toFixed?.(2) ?? '—')}</span></div>`).join('')}</div></div></div>`;
    bindExperiments($('detail'));
    $('detail').querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>select(el.dataset.go));
    paintSwatches($('detail'));
    $('detail').querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>openDetail(el.dataset.open));
  }
  const DETAIL_TABS=[['overview','Reasoning and relations'],['diff','Diff and merge provenance'],['proof','Full proof'],['lineage','Lineage diffs'],['evals','Evaluations and Lean feedback'],['calls','Reasoning & calls']];
  function openDetail(tab='overview') {
    const probe=pById.get(selected),node=byId.get(selected)||probe;if(!node)return;
    if(probe)tab='calls'; // a probe has only its creating call; the other tabs need candidate fields
    const dialog=$('code-dialog');
    $('code-dialog-body').innerHTML=`<div class="modal-head"><h2>${probe?`${esc(probe.node || 'Probe')} ${esc(probe.id.slice(0,8))}`:`${esc(nodeLabel(node))} ${node.origin==='auto_merge'?'⊕ automatic merge':''}`}<span class="muted dsub"> · ${esc(probe?stat(probe):status(node))} · ${esc(node.tokens ?? '?')} tokens · ${esc(node.heartbeat ?? '?')} heartbeats</span></h2><button id="close-code" type="button" aria-label="Close details">✕</button></div>
      <nav class="dtabs">${(probe?DETAIL_TABS.filter(([id])=>id==='calls'):DETAIL_TABS).map(([id,label])=>`<button type="button" data-dtab="${id}" aria-selected="${id===tab}">${label}</button>`).join('')}</nav><div id="dtab"></div>`;
    $('close-code').onclick=()=>dialog.close();
    $('code-dialog-body').querySelectorAll('[data-dtab]').forEach(b=>b.onclick=()=>openDetail(b.dataset.dtab));
    renderDetailTab(node,tab);
    if(!dialog.open){if(document.body.classList.contains('embed'))parent.postMessage({type:'arena-focus'},location.origin);dialog.showModal();}
  }
  let callsToken = 0;
  function renderCalls(node) {
    const token = ++callsToken;
    const box = $('dtab');
    box.innerHTML = '<p class="muted">Loading...</p>';
    fetch(`node/${encodeURIComponent(node.id)}.json`).then(response => {
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return response.json();
    }).then(payload => {
      if (token !== callsToken) return;
      box.innerHTML = callsHtml(payload, id => itemOf(id) ? goBtn(id) : '');
      box.querySelectorAll('[data-go]').forEach(el => el.onclick = () => { select(el.dataset.go); openDetail('calls'); });
    }).catch(error => {
      if (token !== callsToken) return;
      box.innerHTML = `<p class="muted">${esc(error && error.message ? error.message : String(error))}</p><button type="button" data-retry>Retry</button>`;
      box.querySelector('[data-retry]').onclick = () => renderCalls(node);
    });
  }
  function renderDetailTab(node,tab) {
    callsToken++; // a late node/<id>.json answer must not overwrite this tab
    if(tab==='calls'){renderCalls(node);return;}
    const {derived,ancestry,reference,root}=context(node),box=$('dtab');
    const bind=()=>box.querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>{select(el.dataset.go);openDetail(tab)});
    if(tab==='overview'){
      const relations=derived.map((d,i)=>`<div>${i?'Alternate derivation':'Recorded parents'}: ${d.parents.length?d.parents.map(goBtn).join(' '):'root'}${d.merge?.base?` · base ${goBtn(d.merge.base)}`:''}</div>`).join('');
      box.innerHTML=`<code>${esc(node.id)}</code><h3>Note</h3><p class="hyp">${esc(node.hypothesis||(node.origin==='auto_merge'?'Deterministic combination of disjoint edits':'No hypothesis recorded'))}</p>
        <h3>Relationships</h3><div class="row">${relations}</div>
        <p class="muted">Children: ${node.children.length?node.children.map(goBtn).join(' '):'none'} · Decision: ${esc(node.decision)}</p><button id="collapse" type="button">${collapsed.has(node.id)?'Expand descendants':'Collapse descendants'}</button>`;
      $('collapse').onclick=()=>{collapsed.has(node.id)?collapsed.delete(node.id):collapsed.add(node.id);view=null;layout();renderGraph();detail();openDetail(tab)};
    } else if(tab==='diff'){
      const options=[...new Set(derived.flatMap(d=>d.parents))].map(p=>`<option value="${esc(p)}">Parent ${esc(byId.get(p)?.index ?? p.slice(0,8))}</option>`).join('')+(node.merge?.base?`<option value="${esc(node.merge.base)}">Common base</option>`:'');
      box.innerHTML=options?`<div class="diff-controls"><select id="diff-parent">${options}</select><label><input type="checkbox" id="diff-all"> Show unchanged lines</label></div><div class="diff" id="diff"></div>`:'<p class="muted">Recorded root: no parent to compare with.</p>';
      box.innerHTML+=node.merge?`<details open><summary>Exact base-relative edit ranges</summary><pre>${esc(JSON.stringify(node.merge.edits,null,2))}</pre></details>`:'';
      const selector=$('diff-parent');if(selector){const update=()=>{$('diff').innerHTML=diff(byId.get(selector.value)?.proof ?? '',node.proof,$('diff-all').checked)};selector.onchange=update;$('diff-all').onchange=update;update();}
    } else if(tab==='proof'){
      box.innerHTML=`<pre class="full-code lean">${window.LeanHL?window.LeanHL.block(node.proof):esc(node.proof)}</pre>`;
    } else if(tab==='lineage'){
      const cumulative=root&&root.id!==node.id?`<h3>${esc(nodeLabel(root))} → ${esc(nodeLabel(node))} · cumulative</h3><div class="diff">${diff(root.proof,node.proof)}</div>`:'<p class="muted">This is the earliest recorded proof.</p>';
      const steps=ancestry.edges.map(({parent,child})=>{const from=byId.get(parent),to=byId.get(child);
        return `<details class="lineage-step" open><summary>${esc(nodeLabel(from))} → ${esc(nodeLabel(to))}${to.origin==='auto_merge'?' · ⊕ merge':''}</summary><div class="diff">${diff(from.proof,to.proof)}</div></details>`;}).join('');
      box.innerHTML=`<p class="muted">${reference?'Pinned original source':'Earliest recorded ancestor'} to current · ${ancestry.edges.length} recorded parent edges, including merge branches</p>${cumulative}<h3>Step-by-step changes</h3>${steps}`;
    } else {
      box.innerHTML=node.evaluations.map(e=>`<div class="feed-row"><strong>#${e.number} ${esc(e.mode)}</strong><span>${esc(e.result.tokens ?? '?')} tokens · ${esc(e.result.heartbeat ?? '?')} heartbeats · ${esc(e.result.local_proxy?.toFixed?.(2) ?? '—')} proxy</span>${Object.entries(e.result.compat || {}).map(([v,r]) => `<span class="tag ${r.passed ? 'good' : 'bad'}">${esc(v)} ${r.passed ? 'pass' : 'fail'}</span>`).join('')}<button type="button" class="feedback-toggle" aria-expanded="false">Complete Lean feedback ▸</button><div class="feedback-body" hidden>${Object.entries(e.result.compat || {}).map(([v,r])=>`<h4>${esc(v)}</h4><pre>${esc(diagnosticText(r))}</pre>`).join('')}${e.result.error ? `<pre>${esc(e.result.error)}</pre>` : ''}${!Object.keys(e.result.compat || {}).length&&!e.result.error?'<p class="muted">No Lean diagnostic was recorded for this evaluation.</p>':''}</div></div>`).join('')||'<p class="muted">No evaluations yet.</p>';
      box.querySelectorAll('.feedback-toggle').forEach(button=>button.onclick=()=>{const body=button.nextElementSibling,open=body.hidden;body.hidden=!open;button.setAttribute('aria-expanded',String(open));button.textContent=`Complete Lean feedback ${open?'▾':'▸'}`;});
    }
    bind();
  }
  $('code-dialog').addEventListener('click',e=>{if(e.target===$('code-dialog'))e.target.close()});
  // focus:false keeps the camera still (clicks on the graph); everything else (charts, buttons) recentres.
  // Right column: node detail or the actors' cards. Selecting a node shows its detail.
  let sideTab = store.get('arena-side') === 'cards' ? 'cards' : 'detail';
  function showSide(tab) {
    sideTab = tab; store.set('arena-side', tab);
    document.querySelectorAll('[data-side]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.side === tab)));
    $('detail').hidden = tab !== 'detail'; $('cards').hidden = tab !== 'cards';
  }
  document.querySelectorAll('[data-side]').forEach(el => el.onclick = () => showSide(el.dataset.side));
  showSide(sideTab);
  function select(id,{focus=true}={}) {
    if(!itemOf(id))return;
    showSide('detail');
    if(isProbe(itemOf(id))&&!showProbes){showProbes=true;store.set('arena-probes','1');layout();}
    if(isScratch(itemOf(id))&&!showScratch){showScratch=true;store.set('arena-scratch','1');layout();}
    selected=id; store.set('arena-selected',id); if(focus&&coords.has(id))focusOn(id); renderGraph(); detail(); renderCharts();
  }
  function clearSelection() {
    if(!selected)return;
    selected=null; store.set('arena-selected',''); renderGraph(); detail(); renderCharts();
  }
  // Esc: close a dialog first (native), then leave a focused control, then clear the selection.
  document.addEventListener('keydown',e=>{
    if(e.key!=='Escape'||document.querySelector('dialog[open]'))return;
    const a=document.activeElement;
    if(a&&(a.tagName==='INPUT'||a.tagName==='SELECT')&&a.id!=='search'){a.blur();return;}
    if(a&&a.id==='search'&&a.value){a.value='';renderGraph();renderChips();return;}
    clearSelection();
  });
  // The run dashboard embeds this page and asks it to select a candidate when a chart point is clicked.
  addEventListener('message', e => { if (e.origin === location.origin && e.data && e.data.type === 'arena-select' && itemOf(e.data.id)) select(e.data.id); });

  // Stacked bottom to top: cheap cache reads first, the usually dominant output last.
  const COST_PARTS=[['cache_read','Cache read','#5fd3a5'],['input','Input','#c792ea'],['cache_write','Cache write','#edc475'],['output','Output','#78baff']];
  function niceTicks(min,max,count) {
    if(!(max>min))return [min];
    // Smallest 1/2/5 step that keeps at most `count` intervals.
    const raw=(max-min)/count,mag=10**Math.floor(Math.log10(raw));
    const step=Math.max(1,[1,2,5,10].map(m=>m*mag).find(s=>s>=raw));
    const ticks=[];
    for(let v=Math.ceil(min/step)*step;v<=max+1e-9;v+=step)ticks.push(Math.round(v));
    return ticks;
  }
  // Shared x/y scales so the card and the enlarged view agree.
  function scales(spec,points,box) {
    const xs=points.map((p,i)=>p.number ?? i+1),xMin=Math.min(...xs),xMax=Math.max(...xs);
    const ys=points.map(p=>p[spec.key]);
    let yMin=spec.zero?0:Math.min(...ys),yMax=Math.max(...ys);
    if(spec.cap)yMax=Math.max(yMax,spec.cap);
    if(spec.target!=null){yMax=Math.max(yMax,spec.target);if(!spec.zero)yMin=Math.min(yMin,spec.target);}
    const xr=xMax-xMin||1,yr=yMax-yMin||1;
    return {xs,xMin,xMax,yMin,yMax,xTicks:niceTicks(xMin,xMax,box.ticks),
      sx:x=>box.x0+(x-xMin)*(box.x1-box.x0)/xr,sy:y=>box.y1-(y-yMin)*(box.y1-box.y0)/yr};
  }
  function linePath(points,xs,sx,sy,value) {
    return points.map((p,i)=>`${i?'L':'M'}${sx(xs[i]).toFixed(1)},${sy(value(p)).toFixed(1)}`).join(' ');
  }
  function stackedAreas(points,xs,sx,sy,cls) {
    let below=points.map(()=>0);
    return COST_PARTS.map(([key,,color])=>{
      const above=points.map((p,i)=>below[i]+(p.parts?.[key]||0));
      const top=points.map((p,i)=>`${i?'L':'M'}${sx(xs[i]).toFixed(1)},${sy(above[i]).toFixed(1)}`).join(' ');
      const bottom=points.map((p,i)=>`L${sx(xs[i]).toFixed(1)},${sy(below[i]).toFixed(1)}`).reverse().join(' ');
      below=above;
      return `<path class="${cls}" fill="${color}" d="${top} ${bottom} Z"/>`;
    }).join('');
  }
  function xAxis(sc,box,labelY,grid) {
    return sc.xTicks.map(t=>{const x=sc.sx(t).toFixed(1);
      return `${grid?`<path class="x-grid" d="M${x} ${box.y0}V${box.y1}"/>`:''}<path class="x-tick" d="M${x} ${box.y1}v4"/><text class="axis-label" x="${x}" y="${labelY}" text-anchor="middle">${esc(t)}</text>`;}).join('');
  }
  function capLine(spec,sc,box,label) {
    if(!spec.cap)return '';
    const y=sc.sy(spec.cap).toFixed(1);
    return `<path class="cap-line" d="M${box.x0} ${y}H${box.x1}"/>${label?`<text class="axis-label cap-label" x="${box.x0+6}" y="${y-5}">limit ${esc(money(spec.cap))}</text>`:''}`;
  }
  // Our latest submission's value for this theorem: the line the run has to cross.
  function targetLine(spec,sc,box,label) {
    if(spec.target==null)return '';
    const y=sc.sy(spec.target).toFixed(1),v=spec.target.toFixed(spec.key==='local_proxy'?2:0);
    return `<path class="target-line" d="M${box.x0} ${y}H${box.x1}"/><text class="axis-label target-label" x="${box.x0+(label?6:4)}" y="${Number(y)+(label?-4:10)}">to beat ${esc(v)}${spec.key==='local_proxy'?' (proxy)':''}</text>`;
  }
  function headValue(spec,value) {
    if(spec.unit==='$')return money(value)+(spec.cap?` / ${money(spec.cap)}`:'');
    return value.toFixed(spec.key==='local_proxy'?2:0);
  }

  // Legend swatches are SVG, so they render the same in every browser and need no CSS.
  const swatch=(color,kind='area')=>kind==='line'
    ?`<svg class="swatch" width="18" height="10" aria-hidden="true"><path d="M1 5H17" stroke="${color}" stroke-width="2.5"/></svg>`
    :kind==='dash'?`<svg class="swatch" width="18" height="10" aria-hidden="true"><path d="M1 5H17" stroke="${color}" stroke-width="1.5" stroke-dasharray="4 3"/></svg>`
    :`<svg class="swatch" width="10" height="10" aria-hidden="true"><rect width="10" height="10" rx="2" fill="${color}"/></svg>`;
  function costLegend(spec,points,withValues) {
    const last=points.at(-1)||{};
    const parts=COST_PARTS.slice().reverse().map(([k,label,color])=>`<span>${swatch(color)}${esc(label)}${withValues?' '+esc(money(last.parts?.[k]||0)):''}</span>`);
    parts.unshift(`<span>${swatch('#78baff','line')}Total${withValues?' '+esc(money(last.spent_usd||0)):''}</span>`);
    if(spec.cap)parts.push(`<span>${swatch('#ff8f8f','dash')}Hard cap ${esc(money(spec.cap))}</span>`);
    return `<span class="cost-legend">${parts.join('')}</span>`;
  }

  // Hover: one tooltip per container (the dialog is in the top layer, so it needs its own).
  const chartGeometry=new Map();
  function delta(value,base) {
    if(value==null||base==null)return '';
    const d=value-base;return ` <span class="${d<0?'good':d>0?'bad':'muted'}">(${d>0?'+':''}${Number.isInteger(d)?d:d.toFixed(2)} vs original)</span>`;
  }
  function tipHtml(spec,points,i,x) {
    const p=points[i],rows=[];
    if(spec.stack){
      const prev=points[i-1]?.parts||{},t=p.tokens||{};
      const head=`API request ${esc(x)}${p.ts?` · ${esc(new Date(p.ts*1000).toLocaleTimeString())}`:''}`;
      const parts=COST_PARTS.slice().reverse().map(([k,label,color])=>`<tr><td>${swatch(color)}${esc(label)}</td><td>${esc(t[k]??0)}</td><td>${esc(money((p.parts?.[k]||0)-(prev[k]||0)))}</td><td>${esc(money(p.parts?.[k]||0))}</td></tr>`).join('');
      const share=spec.cap?` (${Math.round(100*p.spent_usd/spec.cap)}% of cap)`:'';
      return `<div class="tip-head">${head}</div><div class="tip-row"><span>This request</span><b>${esc(money(p.request_usd))}</b></div><div class="tip-row"><span>Cumulative</span><b>${esc(money(p.spent_usd))}${esc(share)}</b></div><div class="tip-row"><span>Cache hit rate</span><b>${p.reuse_pct==null?'—':esc(p.reuse_pct.toFixed(1))+'%'}</b></div><table class="tip-table"><thead><tr><th></th><th>tokens</th><th>request</th><th>total</th></tr></thead><tbody>${parts}</tbody></table>`;
    }
    const node=byId.get(p.candidate_id),base=data.baseline||{};
    const status=p.is_reference?'original proof, every version':p.status==='full'?'passes every version':p.status==='primary'?'primary version only':'failed';
    const title=p.is_reference?'Original proof':`Evaluation ${esc(x)} · #${esc(node?.index??'?')}`;
    rows.push(['Status',esc(status)+(p.mode&&!p.is_reference?` · ${esc(p.mode)} check`:'')]);
    if(p.local_proxy!=null)rows.push(['Score',`${esc(p.local_proxy.toFixed(2))}${p.is_reference?'':delta(p.local_proxy,base.local_proxy)}`]);
    if(p.tokens!=null)rows.push(['Tokens',`${esc(p.tokens)}${p.is_reference?'':delta(p.tokens,base.tokens)}`]);
    if(p.heartbeat!=null)rows.push(['Heartbeats',`${esc(p.heartbeat)}${p.is_reference?'':delta(p.heartbeat,base.heartbeat)}`]);
    if(p.ts)rows.push(['Time',esc(new Date(p.ts*1000).toLocaleTimeString())]);
    const hyp=!p.is_reference&&node?.hypothesis?`<div class="tip-note">${esc(node.hypothesis.slice(0,140))}${node.hypothesis.length>140?'…':''}</div>`:'';
    return `<div class="tip-head">${title}${p.is_best?' <span class="good">★ best so far</span>':''}</div>${rows.map(([k,v])=>`<div class="tip-row"><span>${k}</span><b>${v}</b></div>`).join('')}${hyp}`;
  }
  function attachHover(svg,key,container) {
    const geometry=chartGeometry.get(key);if(!svg||!geometry)return;
    let tip=container.querySelector(':scope > .chart-tip');
    if(!tip){tip=document.createElement('div');tip.className='chart-tip';tip.hidden=true;container.appendChild(tip);}
    const guide=document.createElementNS('http://www.w3.org/2000/svg','line'),dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
    guide.setAttribute('class','hover-guide');dot.setAttribute('class','hover-dot');dot.setAttribute('r',geometry.big?5:4);
    guide.style.display=dot.style.display='none';svg.append(guide,dot);
    svg.addEventListener('mousemove',event=>{
      const {spec,points,sc,box}=geometry,ctm=svg.getScreenCTM();if(!ctm)return;
      const pt=new DOMPoint(event.clientX,event.clientY).matrixTransform(ctm.inverse());
      let best=0;points.forEach((_,i)=>{if(Math.abs(sc.sx(sc.xs[i])-pt.x)<Math.abs(sc.sx(sc.xs[best])-pt.x))best=i});
      const x=sc.sx(sc.xs[best]),y=sc.sy(points[best][spec.key]);
      guide.setAttribute('x1',x);guide.setAttribute('x2',x);guide.setAttribute('y1',box.y0);guide.setAttribute('y2',box.y1);
      dot.setAttribute('cx',x);dot.setAttribute('cy',y);guide.style.display=dot.style.display='';
      tip.innerHTML=tipHtml(spec,points,best,sc.xs[best]);tip.hidden=false;
      const w=tip.offsetWidth,h=tip.offsetHeight;
      // Below-right of the cursor; flip above when it would overflow; always stay inside the window.
      const below=event.clientY+16,above=event.clientY-h-12;
      tip.style.left=`${Math.max(8,Math.min(event.clientX+16,innerWidth-w-8))}px`;
      tip.style.top=`${Math.max(8,Math.min(below+h>innerHeight?above:below,innerHeight-h-8))}px`;
    });
    svg.addEventListener('mouseleave',()=>{tip.hidden=true;guide.style.display=dot.style.display='none';});
  }

  function chart(spec,index) {
    const {title,key}=spec,points=spec.rows.filter(r=>Number.isFinite(r[key]));
    if(!points.length)return `<button type="button" class="chart"><span class="chart-title">${esc(title)}</span><span class="muted">No data yet</span></button>`;
    const box={x0:22,x1:332,y0:8,y1:74,ticks:5},sc=scales(spec,points,box);
    const last=points.at(-1),lx=sc.sx(sc.xs.at(-1)),ly=sc.sy(last[key]);
    // Headline: the best value so far (spend: the running total), matching the submission.
    const values=points.map(p=>p[key]);
    const headline=spec.better==='max'?Math.max(...values):spec.better==='min'?Math.min(...values):last[key];
    const areas=spec.stack?stackedAreas(points,sc.xs,sc.sx,sc.sy,'area'):'';
    chartGeometry.set(`card-${index}`,{spec,points,sc,box});
    return `<button type="button" class="chart" data-chart="${index}" aria-label="Open enlarged ${esc(title)} chart"><span class="chart-head"><span class="chart-title">${esc(title)}</span><strong title="${spec.better?'best so far':'current'}">${esc(headValue(spec,headline))}</strong></span><svg viewBox="0 0 350 96" data-geometry="card-${index}" aria-hidden="true">${areas}${capLine(spec,sc,box,false)}${targetLine(spec,sc,box,false)}<path class="chart-baseline" d="M${box.x0} ${box.y1}H${box.x1}"/>${xAxis(sc,box,90,false)}<path class="series" d="${linePath(points,sc.xs,sc.sx,sc.sy,p=>p[key])}"/><circle class="chart-end" cx="${lx}" cy="${ly}" r="4"/></svg>${spec.stack?`<span class="card-legend">${costLegend(spec,points,false)}</span>`:''}<span class="chart-foot">${points.length} ${esc(spec.xLabel.toLowerCase())}s <span>Click to inspect ↗</span></span></button>`;
  }
  function chartTable(spec,points) {
    if(spec.stack){
      const rows=points.map(p=>{const t=p.tokens||{};return `<tr><td>${esc(p.number)}</td><td>${esc(money(p.request_usd))}</td><td>${esc(money(p.spent_usd))}</td>${COST_PARTS.map(([k])=>`<td>${esc(t[k] ?? '—')}</td>`).join('')}<td>${p.reuse_pct==null?'—':esc(p.reuse_pct.toFixed(1))+'%'}</td><td>${p.ts?esc(new Date(p.ts*1000).toLocaleTimeString()):'—'}</td></tr>`;}).join('');
      return `<thead><tr><th>Request</th><th>Request $</th><th>Cumulative $</th>${COST_PARTS.map(([,label])=>`<th>${esc(label)} tok</th>`).join('')}<th>Cache hit rate</th><th>Time</th></tr></thead><tbody>${rows}</tbody>`;
    }
    const rows=points.map((p,i)=>`<tr ${p.candidate_id?`data-candidate="${esc(p.candidate_id)}"`:''}><td>${p.is_reference?'0 (original)':esc(p.number ?? i+1)}</td><td>${p.candidate_id?`${esc(byId.has(p.candidate_id) ? shortLabel(byId.get(p.candidate_id)) : '?')} ${p.is_reference?'original proof':esc(p.candidate_id.slice(0,8))}`:'—'}</td><td>${esc(p[spec.key].toFixed(spec.key==='local_proxy'?2:0))}</td><td>${esc(p.status ?? p.mode ?? '—')}</td><td>${esc(p.tokens ?? '—')}</td><td>${esc(p.heartbeat ?? '—')}</td><td>${esc(p.local_proxy?.toFixed?.(2) ?? '—')}</td><td>${p.ts?esc(new Date(p.ts*1000).toLocaleString()):'—'}</td></tr>`).join('');
    return `<thead><tr><th>${esc(spec.xLabel)}</th><th>Candidate</th><th>Value</th><th>Status / mode</th><th>Tokens</th><th>Heartbeats</th><th>Proxy</th><th>Time</th></tr></thead><tbody>${rows}</tbody>`;
  }
  function openChart(index) {
    const spec=chartSpecs[index];if(!spec)return;
    const points=spec.rows.filter(r=>Number.isFinite(r[spec.key]));
    if(!points.length)return;
    const box={x0:70,x1:870,y0:30,y1:290,ticks:12},sc=scales(spec,points,box);
    const grid=Array.from({length:5},(_,i)=>{
      const value=sc.yMax-i*(sc.yMax-sc.yMin)/4,y=sc.sy(value);
      return `<path d="M${box.x0} ${y}H${box.x1}"/><text x="${box.x0-8}" y="${y+4}" text-anchor="end">${esc(spec.unit==='$'?money(value):value.toFixed(spec.key==='local_proxy'?2:0))}</text>`;
    }).join('');
    const dots=points.map((p,i)=>`<circle class="modal-dot${p.candidate_id&&p.candidate_id===selected?' selected':''}${p.is_best?' best':''}" cx="${sc.sx(sc.xs[i])}" cy="${sc.sy(p[spec.key])}" r="3.5"/>`).join('');
    const areas=spec.stack?stackedAreas(points,sc.xs,sc.sx,sc.sy,'modal-area'):'';
    const legend=spec.stack?`<div class="modal-legend">${costLegend(spec,points,true)}</div>`:'';
    chartGeometry.set('modal',{spec,points,sc,box,big:true});
    $('chart-dialog-body').innerHTML=`<div class="modal-head"><div><h2>${esc(spec.title)}</h2><p class="muted">${points.length} ${esc(spec.xLabel.toLowerCase())}s · ${esc(spec.caption)}</p></div><button id="close-chart" type="button" aria-label="Close chart">✕</button></div>${legend}<svg class="modal-chart" data-geometry="modal" viewBox="0 0 900 340" role="img" aria-label="${esc(spec.title)} full series"><g class="modal-grid">${grid}${xAxis(sc,box,307,true)}</g>${areas}${capLine(spec,sc,box,true)}${targetLine(spec,sc,box,true)}<path class="modal-series" d="${linePath(points,sc.xs,sc.sx,sc.sy,p=>p[spec.key])}"/>${dots}<text class="axis-label axis-title" x="${(box.x0+box.x1)/2}" y="330" text-anchor="middle">${esc(spec.xLabel)}</text></svg><div class="chart-table-wrap"><table class="chart-table">${chartTable(spec,points)}</table></div>`;
    const dialog=$('chart-dialog');$('close-chart').onclick=()=>dialog.close();
    attachHover($('chart-dialog-body').querySelector('[data-geometry="modal"]'),'modal',$('chart-dialog-body'));
    $('chart-dialog-body').querySelectorAll('[data-candidate]').forEach(row=>row.onclick=()=>{dialog.close();select(row.dataset.candidate)});
    dialog.showModal();
  }
  $('chart-dialog').addEventListener('click',e=>{if(e.target===$('chart-dialog'))e.target.close()});
  function renderCharts() {
    const bestIds=new Set(data.milestones.map(m=>m.candidate_id));
    // The original proof is evaluation 0, so score charts start from where the run started.
    const rows=[...(data.baseline&&!hideInit?[data.baseline]:[]),...data.timeline].map(r=>({...r,is_best:bestIds.has(r.candidate_id)}));
    const pick='Click a candidate row to inspect its proof.',tg=data.target||{};
    $('hide-init').checked=hideInit;
    chartSpecs=[
      {title:'Provisional score · 3/3 only',rows:rows.filter(r=>r.status==='full'),key:'local_proxy',unit:'',xLabel:'Evaluation',caption:pick,better:'max',target:tg.proxy},
      {title:'Proof tokens',rows:rows.filter(r=>r.status!=='fail'),key:'tokens',unit:'',xLabel:'Evaluation',caption:pick,better:'min',target:tg.tokens},
      {title:'Primary heartbeats',rows:rows.filter(r=>r.status!=='fail'),key:'heartbeat',unit:'',xLabel:'Evaluation',caption:pick,better:'min',target:tg.heartbeats},
      {title:'API spend by component',rows:data.cost_timeline||[],key:'spent_usd',unit:'$',xLabel:'API request',
       stack:true,zero:true,cap:data.limit_usd||null,
       caption:'Cumulative ledger spend, stacked by price component; the dashed line is the spend limit.'},
    ];
    $('charts').innerHTML=chartSpecs.map(chart).join('');
    $('charts').querySelectorAll('[data-chart]').forEach(el=>el.onclick=()=>openChart(Number(el.dataset.chart)));
    $('charts').querySelectorAll('[data-geometry]').forEach(svg=>attachHover(svg,svg.dataset.geometry,document.body));
  }
  $('hide-init').onchange=e=>{hideInit=e.target.checked;store.set('arena-hideinit',hideInit?'1':'0');renderCharts();};
  // Run best next to the submission's number, same proxy basis: green when the run beats it, red when it trails.
  function deltaHtml(run,base) {
    if(run==null||base==null)return '';
    const d=Math.round((run-base)*100)/100;
    return ` <span class="${d>0?'good':d<0?'bad':'muted'}">(${d>0?'+':''}${d.toFixed(2)} vs best to beat)</span>`;
  }
  function runBest(top) {
    if(top?.local_proxy==null)return '—';
    return {html:`${esc(top.local_proxy.toFixed(2))}${deltaHtml(top.local_proxy,data.target?.proxy)}`};
  }
  function renderMeta() {
    $('run-label').textContent=`${data.theorem || ''} · ${data.run_id} · ${data.nodes.length} recorded nodes`;
    const full=data.nodes.filter(n=>n.status==='full').length, autos=data.nodes.filter(n=>n.origin==='auto_merge').length;
    const rp=data.route_progress||{},routes=data.routes||[],top=data.milestones.at(-1),probes=probeItems.length;
    const pass=probeItems.filter(p=>p.status==='pass').length,skel=probeItems.filter(p=>p.status==='skeleton').length;
    $('metrics').innerHTML=[['Candidates',data.nodes.length,`${full} verified 3/3 · ${autos} auto merges`],['Probes',probes,`${pass} compiled · ${skel} skeletons · ${probes-pass-skel} failed`],
      ['Routes',routes.length,`${routes.filter(r=>r.attempts).length} with attempts`],['Credited routes',`${rp.credited_routes??0} / ${rp.explored_routes??0}`,'credited / explored'],
      ['Best proxy',runBest(top),top?`${numberForId(top.candidate_id)} · ${top.tokens??'?'} tokens`:'no verified candidate'],
      ...(data.target?[['Best to beat',`${data.target.proxy.toFixed(2)} proxy`,`our latest submission (${data.target.submission}) · ${data.target.source}`]]:[]),
      ['Evaluations',data.evaluations,''],['New goal state',rp.new_state_share==null?'—':`${Math.round(100*rp.new_state_share)}%`,'of model attempts'],['Merge checks',data.merge_checks.length,'']]
      .map(([k,v,t])=>`<span class="metric" title="${esc(t)}">${esc(k)} <b>${typeof v==='object'?v.html:esc(v)}</b></span>`).join('');
        $('frontier').innerHTML=(data.frontier||[]).slice(0,8).map(r=>`<div class="frontier-row"><button data-go="${r.candidate_id}">${esc(numberForId(r.candidate_id))}</button><span>${esc(r.status)} · priority ${esc(r.priority_total)} · ${esc(r.tokens ?? '?')} tokens</span></div>`).join('')||'<p class="muted">No eligible seeds yet.</p>';
    $('frontier').querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>select(el.dataset.go));
    $('worker').innerHTML=`<span class="tag">${esc(data.worker?.state ?? 'not running')}</span> <span class="muted">${data.worker?.updated_at ? esc(new Date(data.worker.updated_at*1000).toLocaleTimeString()) : ''}</span>${data.worker?.detail?.candidate_id ? `<span>${esc(numberForId(data.worker.detail.candidate_id))}</span>` : ''}${data.worker?.detail?.error ? `<pre>${esc(data.worker.detail.error)}</pre>` : ''}`;
    // Ledger and Pi now price requests identically; only a real disagreement is worth showing.
    const ledger=data.cost?.spent_usd||0,pi=data.cost?.pi_embedded_usd||0;
    const drift=pi>0&&Math.abs(ledger-pi)>Math.max(1e-6,0.01*ledger);
    $('cost-note').hidden=!drift;
    if(drift) $('cost-note').innerHTML=`<span class="warning">Pricing drift:</span> ledger <strong>${esc(money(ledger))}</strong> vs Pi's own estimate <strong>${esc(money(pi))}</strong>. The two should agree; check the model prices in Pi's catalog.`;
    $('merge-feed').innerHTML=data.merge_checks.slice(-25).reverse().map(c=>`<div class="feed-row">${c.candidate_id?`<button data-go="${esc(c.candidate_id)}">merge ${esc(numberForId(c.candidate_id))}</button>`:`<span class="muted">skip</span>`}<span>${esc(c.parents?.map(numberForId).join(' + '))}</span><span class="muted">${esc(c.reason || (c.full_passed?'3/3 valid':c.fast_passed?'primary valid':'Lean failed'))}</span></div>`).join('')||'<p class="muted">No pair checks yet.</p>';
    $('merge-feed').querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>select(el.dataset.go));
  }
  // Scratch experiments become canvas nodes. Anchor rule: `at.node` (label, id or #n; a ".step" suffix is dropped);
  // else the node it was promoted into (its first parent); else the current best verified proof; else the root.
  // The ledger rows carry no timestamp, so "best" is the best now, not the best when the experiment ran.
  function nodeByRef(ref) {
    if (typeof ref !== 'string' || !ref) return null;
    for (const key of [ref, ref.split('.')[0]]) {
      const n = data.nodes.find(x => x.node === key || x.id === key || x.proof_id === key || `#${x.index}` === key);
      if (n) return n;
    }
    return null;
  }
  function buildScratch() {
    const best = byId.get(data.milestones.at(-1)?.candidate_id) || data.nodes[0];
    scratchItems = (data.experiments || []).map((e, i) => {
      const at = e.at, promoted = e.promotion?.state === 'promoted' ? nodeByRef(e.promotion.node) || nodeByRef(e.promotion.proof_id) : null;
      let anchor = nodeByRef(typeof at === 'string' ? at : at?.node) || nodeByRef(e.proof_id), note = at ? `at ${typeof at === 'string' ? at : at.node ?? JSON.stringify(at)}` : '';
      if (!anchor && promoted) { anchor = byId.get(promoted.parents[0]); note = 'unanchored; parent of promoted node'; }
      if (!anchor) { anchor = best; note = `${at ? note + ' not found; ' : 'unanchored; '}attached to ${data.milestones.length ? 'current best verified' : 'root'}`; }
      return {...e, id: `x:${e.experiment_id || e.code_sha256 || i}`, kind: 'scratch', index: `e${i + 1}`, order: 2e6 + i, parents: anchor ? [anchor.id] : [],
              anchorNote: note, promotedTo: promoted?.id || null};
    }).filter(x => x.parents.length);
    sById = new Map(scratchItems.map(x => [x.id, x]));
    const ids = new Set(['sol', ...(data.actors || []).map(a => a.actor_id).filter(Boolean)]);
    for (const it of [...data.nodes, ...probeItems, ...scratchItems]) ids.add(actorOf(it));
    actorIds = [...ids].sort((a, b) => (a === 'sol' ? -1 : b === 'sol' ? 1 : a === UNKNOWN_ACTOR ? 1 : b === UNKNOWN_ACTOR ? -1 : a.localeCompare(b)));
  }
  // Derived structures: probe nodes (those that never became candidates), token range, routes, best path.
  function prepare() {
    const known = new Set(data.nodes.map(n => n.id));
    routeById = new Map((data.routes || []).map(r => [r.route, r]));
    const rows = (data.probes || []).filter(p => !known.has(p.proof_id)).sort((a, b) => (a.ts || 0) - (b.ts || 0));
    const ids = new Set(rows.map(p => p.proof_id));
    probeItems = rows.map((p, i) => ({...p, id: p.proof_id, kind: 'probe', index: `p${i + 1}`, order: 1e6 + i,
      parents: p.parent && (known.has(p.parent) || (ids.has(p.parent) && p.parent !== p.proof_id)) ? [p.parent] : []}));
    pById = new Map(probeItems.map(p => [p.id, p]));
    // The harness only fingerprints probes that compile without sorry; the rest take their parent's route (shown as inherited).
    for (const p of probeItems) if (!p.route) { const from = byId.get(p.parents[0]) || pById.get(p.parents[0]); if (from?.route) { p.route = from.route; p.route_inherited = true; } }
    probeKids = new Map();
    for (const p of probeItems) for (const parent of p.parents) probeKids.set(parent, [...(probeKids.get(parent) || []), p.id]);
    for (const n of data.nodes) n.order = n.index;
    buildScratch();
    const tokens = data.nodes.map(n => n.tokens).filter(t => t != null);
    tokenRange = tokens.length ? [Math.min(...tokens), Math.max(...tokens)] : [0, 1];
    computeBestPath();
  }
  // ---- actor cards: each actor's current notes card plus every saved version -------------------
  const CARD_FIELDS = [['focus','Focus'],['best','Best'],['held','Held'],['failed','Failed'],['ideas','Ideas'],['asks','Asks']];
  const cardOpen = new Set(); let cardsKey = null;
  const runClock = m => m == null ? '' : `${Math.floor(m)}:${String(Math.floor((m % 1) * 60)).padStart(2, '0')} into run`;
  const ago = ts => { if (ts == null) return ''; const m = Math.max(0, (Date.now() / 1000 - ts) / 60); return m < 1 ? 'just now' : m < 90 ? `${Math.round(m)} min ago` : `${(m / 60).toFixed(1)} h ago`; };
  // Escaped text with line breaks kept (CSS pre-wrap) and node ids such as n134 turned into buttons when the graph has that node.
  function cardText(text) {
    const names = new Map(); for (const it of [...(data.nodes || []), ...probeItems]) if (it.node) names.set(it.node, it.id);
    return String(text ?? '').split(/(\bn\d+\b)/).map((part, i) => i % 2 && names.has(part) ? `<button type="button" class="node-ref" data-go="${esc(names.get(part))}">${esc(part)}</button>` : esc(part)).join('');
  }
  const fieldBlock = (name, label, text, changed) => `<div class="card-field${changed ? ' changed' : ''}"><div class="card-field-name">${esc(label)}${changed ? ' <span class="tag good">changed</span>' : ''}</div><div class="card-text">${cardText(text)}</div></div>`;
  const roleOf = id => (data?.actors || []).find(a => a.actor_id === id)?.role;
  function renderCards() {
    const box = $('cards'), cards = data.cards?.actors || [];
    $('cards-count').textContent = cards.length ? `(${cards.length})` : '';
    const key = JSON.stringify(cards.map(c => [c.actor_id, c.versions.length, c.latest.ts])) + [...cardOpen].join();
    if (key === cardsKey) { box.querySelectorAll('.card-time').forEach(el => { el.textContent = cardTime(Number(el.dataset.ts), el.dataset.min === '' ? null : Number(el.dataset.min)); }); return; }
    cardsKey = key;
    if (!cards.length) { box.innerHTML = '<p class="muted">No cards yet. Each actor saves one with the card tool.</p>'; return; }
    const known = new Set(CARD_FIELDS.map(f => f[0]));
    box.innerHTML = '<div class="cards-grid">' + cards.map(c => {
      const id = c.actor_id || (c.label === 'orchestrator' ? 'sol' : c.label), latest = c.latest, open = cardOpen.has(id);
      const fields = CARD_FIELDS.concat(Object.keys(latest.fields).filter(k => !known.has(k)).map(k => [k, k]));
      const body = fields.filter(([k]) => latest.fields[k]).map(([k, label]) => fieldBlock(k, label, latest.fields[k], (latest.changed || []).includes(k))).join('') || '<p class="muted">Empty card.</p>';
      const history = c.versions.map((v, i) => {
        const prev = i ? c.versions[i - 1].fields : {};
        const names = (v.changed?.length ? v.changed : Object.keys({...prev, ...v.fields}).filter(k => prev[k] !== v.fields[k]));
        const diffs = names.map(k => `<div class="card-diff"><div class="card-field-name">${esc(k)}</div><div class="card-before"><span class="muted small">before</span><div class="card-text">${prev[k] ? cardText(prev[k]) : '<span class="muted">(empty)</span>'}</div></div><div class="card-after"><span class="muted small">after</span><div class="card-text">${v.fields[k] ? cardText(v.fields[k]) : '<span class="muted">(cleared)</span>'}</div></div></div>`).join('');
        return `<div class="card-version"><div class="card-version-head"><b>v${esc(v.version)}</b> <span class="muted">${esc(runClock(v.minutes))}</span> <span class="muted">· changed ${esc(names.join(', ') || 'nothing')}</span></div>${diffs}</div>`;
      }).reverse().join('');
      return `<article class="actor-card"><div class="card-head"><i class="sw" data-bg="${actorColor(id)}"></i><b>${esc(c.label || id)}</b>${roleOf(c.actor_id) ? `<span class="tag">${esc(roleOf(c.actor_id))}</span>` : ''}<span class="tag">v${esc(latest.version)}</span><span class="muted card-time" data-ts="${latest.ts ?? ''}" data-min="${latest.minutes ?? ''}">${esc(cardTime(latest.ts, latest.minutes))}</span></div>${body}<button type="button" class="linkish card-history-toggle" data-actor="${esc(id)}" aria-expanded="${open}">${open ? '▾' : '▸'} History (${c.versions.length})</button><div class="card-history"${open ? '' : ' hidden'}>${history}</div></article>`;
    }).join('') + '</div>';
    paintSwatches(box);
    box.querySelectorAll('[data-go]').forEach(el => el.onclick = () => select(el.dataset.go));
    box.querySelectorAll('.card-history-toggle').forEach(el => el.onclick = () => { cardOpen.has(el.dataset.actor) ? cardOpen.delete(el.dataset.actor) : cardOpen.add(el.dataset.actor); renderCards(); });
  }
  const cardTime = (ts, min) => `updated ${ago(ts)}${min == null ? '' : ` · ${runClock(min)}`}`;
  async function refresh() {
    try {
      const response=window.GRAPH_SNAPSHOT ? {ok:true,json:async()=>window.GRAPH_SNAPSHOT} : await fetch('graph.json',{cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const next=await response.json(),revision=`${next.ledger_events}:${next.cost_timeline?.length}:${next.worker?.updated_at}:${(next.cards?.actors||[]).map(c=>c.versions.length).join('.')}`;
      $('live').textContent=window.GRAPH_SNAPSHOT?'Saved snapshot':`Live · ${new Date().toLocaleTimeString()}`;$('live').classList.add('ok');
      if(revision===lastRevision)return;
      lastRevision=revision;data=next;byId=new Map(data.nodes.map(n=>[n.id,n]));prepare();
      // First visit only: open on the latest milestone. After that an empty selection stays empty.
      if(!hadStored){hadStored=true;selected=data.milestones.at(-1)?.candidate_id??null;if(selected)store.set('arena-selected',selected);}
      if(selected&&!itemOf(selected)){selected=null;}
      layout();renderGraph();renderLegend();detail();renderCharts();renderMeta();renderCards();
    } catch(error) {$('live').textContent=`Disconnected · ${error.message}`;$('live').classList.remove('ok')}
  }
  refresh(); if(!window.GRAPH_SNAPSHOT)setInterval(refresh,2500);
})();

// v8 evidence: attempts, derivations, scratch experiments, verification, jobs, actors, spend. Every field is escaped.
const tagHtml = (text, kind = '') => `<span class="tag ${kind}">${esc(text)}</span>`;
function verificationHtml(node) {
  const tags = [tagHtml(`checked: ${node.verification || 'unevaluated'}`, node.verification === 'full' ? 'good' : node.verification === 'fail' ? 'bad' : '')];
  const cold = node.cold_outcome;
  tags.push(tagHtml(cold ? `cold: ${cold}${node.cold_cause ? ` (${node.cold_cause})` : ''}` : 'cold: not run', cold === 'passed' ? 'good' : cold === 'proof_error' ? 'bad' : ''));
  if (node.cold_retryable) tags.push(tagHtml('cold retryable'));
  if (cold !== 'passed') tags.push(tagHtml('provisional', 'bad'));
  tags.push(tagHtml(`eligibility: ${node.eligibility || '?'}`, node.eligibility === 'eligible' ? 'good' : ''));
  return tags.join(' ');
}
function attemptsHtml(attempts, evaluations, open = false) {
  const rows = (attempts || []).map(a => {
    const ev = (evaluations || []).find(e => e.evaluation_id && e.evaluation_id === a.evaluation_id);
    const ids = ['tool_call_id', 'job_id', 'request_id', 'operation_id', 'attempt_id'].filter(k => a[k]).map(k => `${k} ${esc(a[k])}`).join(' · ');
    return `<div class="eval-line"><b>${esc(a.actor_id ?? 'unknown actor')}</b> ${tagHtml(a.relation || 'attempt')} <span class="muted">${esc(a.session_id ?? 'no session')}</span>${ev ? ` <span class="tag">eval #${esc(ev.number)} ${esc(ev.mode)}</span>` : ''}${(a.missing || []).length ? ` ${tagHtml(`missing ${a.missing.join(', ')}`, 'bad')}` : ''}<div class="muted small">${ids}</div></div>`;
  }).join('');
  return rows ? `<details${open ? ' open' : ''}><summary>Attempts (${attempts.length})</summary>${rows}</details>` : '';
}
function derivationsHtml(derivations, label = 'Derivations') {
  const rows = (derivations || []).map((d, i) => `<div class="eval-line">${tagHtml(d.type || d.relation || d.kind || 'derivation')} <span class="muted">${esc(d.source || '')}</span> parents ${esc((d.parents || []).map(p => String(p).slice(0, 8)).join(', ') || 'none')}${d.exact === false ? ' ' + tagHtml('inexact') : ''}${(d.missing || []).length ? ` ${tagHtml(`missing ${d.missing.join(', ')}`, 'bad')}` : ''}</div>`).join('');
  return rows ? `<details><summary>${label} (${derivations.length})</summary>${rows}</details>` : '';
}
const experimentTag = e => tagHtml(e.outcome || e.phase || 'accepted', e.outcome === 'success' || e.outcome === 'passed' ? 'good' : e.outcome === 'failure' ? 'bad' : '');
function experimentRowsHtml(list) {
  return (list || []).map(e => `<div class="eval-line"><button type="button" data-experiment="${esc(e.experiment_id)}" title="Load code and diagnostics">${esc(String(e.experiment_id || e.code_sha256 || '?').slice(0, 10))}</button> ${experimentTag(e)} <span class="muted">${esc(e.actor_id ?? '')}${e.at ? ` · at ${esc(typeof e.at === 'string' ? e.at : JSON.stringify(e.at))}` : ''}${e.elapsed_ms != null ? ` · ${esc(e.elapsed_ms)} ms` : ''}</span>${e.promotion?.state ? ' ' + tagHtml(`${e.promotion.state}${e.promotion.reason ? `: ${e.promotion.reason}` : ''}`, e.promotion.state === 'promoted' ? 'good' : '') : ''}${e.headline ? `<div class="muted small">${esc(e.headline)}</div>` : ''}<div class="exp-body"></div></div>`).join('');
}
function experimentsHtml(list, title = 'Scratch experiments') {
  return list?.length ? `<details><summary>${title} (${list.length})</summary>${experimentRowsHtml(list)}</details>` : '';
}
function experimentDetailHtml(x) {
  if (x.missing) return '<p class="muted">Experiment not found.</p>';
  const rendered = Array.isArray(x.rendered) ? x.rendered.join('\n') : x.rendered;
  return `<div class="facts-small">${tagHtml(x.outcome || '?')} ${x.promotion ? tagHtml(`${x.promotion.state}${x.promotion.reason ? `: ${x.promotion.reason}` : ''}`) : ''} ${tagHtml(`validity: ${x.validity ?? '?'}`)} ${tagHtml(`compat: ${x.compatibility ?? '?'}`)} ${tagHtml(`cold: ${x.cold ?? '?'}`)}${x.code_status && x.code_status !== 'retained' ? ' ' + tagHtml(`code ${x.code_status}`, 'bad') : ''}</div>`
    + (x.code != null ? `<h4>Code</h4><pre>${esc(x.code)}</pre>` : '')
    + (rendered ? `<h4>Diagnostics</h4><pre>${esc(rendered)}</pre>` : '') + (x.diagnostic ? `<pre>${esc(x.diagnostic)}</pre>` : '')
    + (x.raw ? `<details><summary>Raw Lean output</summary><pre>${esc(x.raw)}</pre></details>` : '')
    + `<p class="muted small">${['actor_id', 'session_id', 'job_id', 'tool_call_id', 'request_id', 'operation_id'].filter(k => x[k]).map(k => `${k} ${esc(x[k])}`).join(' · ')}</p>`;
}
// Experiment buttons load their code on first click, so the graph payload stays small.
function bindExperiments(root, runPath = '') {
  root.querySelectorAll('[data-experiment]').forEach(button => button.onclick = () => {
    const body = button.parentElement.querySelector('.exp-body');
    if (body.dataset.loaded) { body.hidden = !body.hidden; return; }
    body.dataset.loaded = '1';
    body.textContent = 'Loading...';
    fetch(`${runPath}experiment/${encodeURIComponent(button.dataset.experiment)}.json`)
      .then(r => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); })
      .then(x => { body.innerHTML = experimentDetailHtml(x); })
      .catch(error => { body.textContent = String(error.message || error); delete body.dataset.loaded; });
  });
}
function runEvidenceHtml(data) {
  const spend = data.spend || {}, total = spend.total != null ? Number(spend.total) : null;
  const share = obj => Object.entries(obj || {}).map(([k, v]) => `<div class="eval-line"><b>${esc(k)}</b> <span>${esc(money(Number(v)))}</span></div>`).join('');
  const actors = (data.actors || []).map(a => `<div class="eval-line"><b>${esc(a.actor_id)}</b> ${tagHtml(a.waiting ? 'waiting' : 'active', a.waiting ? 'good' : '')} ${a.session_status !== 'recorded' ? tagHtml(`session ${a.session_status}`, 'bad') : ''}<div class="muted small">${esc((a.sessions || []).join(', ') || 'no session recorded')}</div></div>`).join('');
  const jobs = (data.job_log || []).map(j => `<div class="eval-line">${tagHtml(j.source)} <b>${esc(String(j.job_id ?? j.phase ?? '?').slice(0, 40))}</b> ${tagHtml(j.status ?? '?', j.status === 'failed' || j.status === 'cancelled' ? 'bad' : '')} <span class="muted">${esc([j.actor_id, j.check, j.phase].filter(Boolean).join(' · '))}${j.queue ? ` · queue ${esc(Object.entries(j.queue).map(([k, v]) => `${k} ${v}`).join(', '))}` : ''}</span></div>`).join('');
  return `<div class="card ancard"><h3>Spend${total != null ? ` ${esc(money(total))}` : ''}${spend.accounting && spend.accounting !== 'known' ? ' ' + tagHtml(`accounting ${spend.accounting}`, 'bad') : ''}</h3><div class="muted small">source ${esc(spend.authority ?? '?')}${data.limit_usd ? ` · limit ${esc(money(Number(data.limit_usd)))}` : ''}</div>
      <details><summary>By actor</summary>${share(spend.by_actor) || '<p class="muted">none</p>'}</details>
      <details><summary>By job</summary>${share(spend.by_job) || '<p class="muted">none</p>'}</details></div>
    <div class="card ancard"><h3>Actors (${(data.actors || []).length})</h3>${actors || '<p class="muted">None recorded.</p>'}<p class="muted small">Waiting shows only when a durable wait row exists.</p></div>
    <div class="card ancard"><details><summary>Jobs and checks (${(data.job_log || []).length})</summary>${jobs || '<p class="muted">None.</p>'}</details>${experimentsHtml(data.experiments)}</div>`;
}

// The "Reasoning & calls" tab. `go(id)` is a select button for an id in the graph, or '' when it is not there.
// Graph ids (`n3`) in the filing line and hole fills become buttons through `payload.ids`; everything else is escaped.
function callsHtml(payload, go) {
  const ids = payload.ids || {}, lines = [];
  const named = text => String(text ?? '').split(/\b(n[1-9][0-9]*)\b/).map((part, i) => i % 2 && ids[part] && go(ids[part]) || esc(part)).join('');
  if (payload.reason) lines.push(`<p class="muted">${esc(payload.reason)}</p>`);
  if (payload.origin_line) lines.push(`<p class="origin-line">${named(payload.origin_line)}</p>`);
  if (payload.turn != null) lines.push(`<p>Turn ${esc(payload.turn)}</p>`);
  for (const block of payload.reasoning || []) lines.push(`<h3>${block.type === 'thinking' ? 'Thinking' : 'Reply'}</h3><pre>${esc(block.text)}</pre>`);
  const call = payload.call;
  if (call) {
    lines.push(`<h3>${esc(call.name)}</h3><pre>${esc(typeof call.args === 'string' ? call.args : JSON.stringify(call.args, null, 2))}</pre>`);
    lines.push(`<h3>Delivered</h3><pre>${esc(call.delivered)}</pre>`);
    if (call.trimmed) lines.push(`<details><summary>Untrimmed result</summary><pre>${esc(call.untrimmed)}</pre></details>`);
    if (call.footer) lines.push(`<pre class="calls-footer">${esc(call.footer)}</pre>`);
  }
  if (payload.holes) {
    const rows = payload.holes.map(hole => `<tr><td>${esc(hole.id)}</td><td>${esc(hole.goal)}</td><td>${esc(hole.status)}</td><td>${(hole.fills || []).map(named).join(' ')}</td></tr>`).join('');
    lines.push(`<table class="holes"><thead><tr><th>Hole</th><th>Goal</th><th>Status</th><th>Fills</th></tr></thead><tbody>${rows}</tbody></table>`);
  }
  if (payload.lineage && payload.lineage !== 'recorded') lines.push(`<p>${tagHtml(`lineage ${payload.lineage}`, 'bad')}</p>`);
  lines.push(attemptsHtml(payload.attempts, [], true), derivationsHtml(payload.derivations));
  const refs = (payload.call_refs || []).filter(ref => ref.call);
  if (refs.length) lines.push(`<details><summary>Calls by every attempt (${refs.length})</summary>${refs.map(ref => `<h4>${esc(ref.actor_id ?? '?')} · ${esc(ref.call.name)} · ${esc(ref.tool_call_id)}</h4><pre>${esc(ref.call.delivered)}</pre>${ref.call.trimmed ? `<details><summary>Untrimmed result</summary><pre>${esc(ref.call.untrimmed)}</pre></details>` : ''}`).join('')}</details>`);
  if (payload.records?.length) lines.push(`<details><summary>Original ledger records (${payload.records.length})</summary>${payload.records.map(r => `<div class="muted small">${esc(r.kind)} bytes ${esc(r.start)}-${esc(r.end)} sha256 ${esc(String(r.sha256).slice(0, 12))}</div><pre>${esc(r.line)}</pre>`).join('')}</details>`);
  if (payload.artifact?.bytes != null) lines.push(`<details><summary>Original artifact ${esc(payload.artifact.path ?? '')}</summary><pre>${esc(payload.artifact.bytes)}</pre></details>`);
  const siblings = (payload.siblings || []).map(id => go(id) || esc(String(id).slice(0, 8))).join(' ');
  if (siblings) lines.push(`<p class="row">${siblings}</p>`);
  return lines.join('');
}

function diagnosticText(result) {
  if (typeof result.diagnostics === 'string') return result.diagnostics;
  const lines = (result.diagnostics || []).map(d => `${d.severity} line ${d.file_line} (proof line ${d.proof_line}): ${d.message}\n    ${d.source_line_text}`);
  if (result.full_diagnostics_ref) lines.push(`full output: ${result.full_diagnostics_ref}`);
  return lines.join('\n') || result.error || '';
}
