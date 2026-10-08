/* Per-run dashboard: score, spend, cache, tools, ideas, events, Lean mix, packet, Langfuse. */
(() => {
  const C = window.Charts || {};
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = v => v == null ? '—' : '$' + (Math.abs(v) >= 0.1 ? v.toFixed(3) : v.toFixed(4));
  const num = (v, d = 0) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
  const dur = s => s == null ? '—' : (C.dur ? C.dur(s) : s + 's');
  const TABS = [['score', 'Score'], ['spend', 'Spend'], ['cache', 'Cache'], ['tools', 'Tools'], ['ideas', 'Ideas'],
                ['events', 'Events'], ['lean', 'Lean'], ['packet', 'Packet'], ['langfuse', 'Langfuse']];
  let data = null, lf = null, tab = 'score', selectedTool = null, zoom = 1, toolFilter = '', obsType = 'GENERATION', obsOpen = null;
  try { tab = localStorage.getItem('arena-dash-tab') || tab; } catch {}
  if (TABS.some(([id]) => id === location.hash.slice(1))) tab = location.hash.slice(1);

  const toolIndex = new Map();
  const toolClass = name => {
    if (!toolIndex.has(name)) toolIndex.set(name, toolIndex.size % 8);
    return 'k' + toolIndex.get(name);
  };
  const badge = (text, kind = '') => `<span class="badge ${kind}">${esc(text)}</span>`;

  function applyWidths(root) {
    // The CSP forbids inline style attributes, so widths are set through the CSSOM.
    root.querySelectorAll('[data-width]').forEach(el => el.style.width = `${el.dataset.width}%`);
  }

  function kpis() {
    const s = data.summary || {}, cost = s.cost || {}, cache = s.cache || {}, best = (s.progress || {}).best_verified_candidate;
    const sub = data.submission;
    const items = [
      ['Best verified', best ? `${best.proxy}` : '—', best ? `${best.candidate} · Δ ${(best.proxy - data.baseline_proxy).toFixed(2)} vs ${data.baseline_proxy}` : 'none yet'],
      ['Tokens / heartbeats', best ? `${best.tokens} / ${best.heartbeats}` : '—', data.reference ? `original ${data.reference.tokens} / ${data.reference.heartbeats}` : ''],
      ['Spend', money(data.spend.spent_usd), `soft cap ${money(data.spend.soft_cap_usd)} · hard ${money(data.spend.hard_cap_usd)}`],
      ['Requests', num(cost.requests ?? data.spend.points.length), `${cost.retries ?? 0} retries · ${cost.requests_after_best ?? '—'} after best`],
      ['Post-best spend', money(cost.spent_after_best_usd), `bookkeeping+rejected ${cost.bookkeeping_and_rejected_pct ?? '—'}%`],
      ['Cache reuse', cache.reuse_pct != null ? cache.reuse_pct + '%' : '—', `recent 10: ${cache.reuse_pct_recent_10 ?? '—'}%`],
      ['Tool results', num((s.tools || {}).results), `${(s.tools || {}).error_total ?? 0} errors`],
      ['Stop', s.stop_reason || 'running', sub ? `submission ${sub.candidate} (${sub.verified_by || '?'})` : 'no submission']];
    $('kpis').innerHTML = items.map(([l, v, n]) => `<div class="kpi"><div class="l">${esc(l)}</div><div class="v">${esc(v)}</div><div class="n">${esc(n)}</div></div>`).join('');
  }

  function scorePanel() {
    const rows = data.scores, full = rows.filter(r => r.mode === 'full' && r.proxy != null), fast = rows.filter(r => r.mode !== 'full' && r.estimated_proxy != null);
    const end = Math.max(1, ...rows.map(r => r.t || 0), ...data.spend.points.map(p => p.t || 0));
    const pt = (r, v, extra = '') => [r.t, v, `${r.candidate} ${r.mode} · ${extra}${v} (${r.tokens} tok, ${r.heartbeats} HB)`];
    const score = C.line([
      {cls: 'k1', step: true, dots: false, points: [[0, data.baseline_proxy], ...rows.filter(r => r.best_verified != null).map(r => [r.t, r.best_verified])]},
      {cls: 'k0', noLine: true, points: full.map(r => pt(r, r.proxy))},
      {cls: 'k2', noLine: true, hollow: true, r: 3, points: fast.map(r => pt(r, r.estimated_proxy, 'est. '))}],
      {refs: [{y: data.baseline_proxy, cls: 'base', label: 'original ' + data.baseline_proxy}], extendTo: end, xMax: end,
       legend: [['k1', 'best verified (step)'], ['k0', 'full evaluation proxy'], ['k2', 'fast estimate']], label: 'score timeline'});
    const metric = (key, ref, title) => C.line([{cls: 'k3', points: full.map(r => [r.t, r[key], `${r.candidate}: ${r[key]}`])}],
      {refs: ref != null ? [{y: ref, cls: 'base', label: 'original ' + ref}] : [], includeRefs: true, xMax: end, label: title});
    $('panel').innerHTML = `<div class="card"><h2>Score over time</h2><p class="hint">Proxy score of each evaluation; the green step line is the best verified so far. Time is since the run started.</p>${score}</div>
      <div class="grid2">
        <div class="card"><h2>Tokens (full evaluations)</h2>${metric('tokens', data.reference?.tokens, 'tokens')}</div>
        <div class="card"><h2>Heartbeats (full evaluations)</h2>${metric('heartbeats', data.reference?.heartbeats, 'heartbeats')}</div></div>
      <div class="card"><h2>Evaluations</h2><div class="scroll"><table><thead><tr><th>t</th><th>candidate</th><th>mode</th><th class="num">proxy</th><th class="num">est.</th><th class="num">tokens</th><th class="num">heartbeats</th><th>compiled</th></tr></thead><tbody>
      ${rows.map(r => `<tr><td>${dur(r.t)}</td><td>${esc(r.candidate)}</td><td>${esc(r.mode)}</td><td class="num">${r.proxy ?? '—'}</td><td class="num">${r.estimated_proxy ?? '—'}</td><td class="num">${num(r.tokens)}</td><td class="num">${num(r.heartbeats)}</td><td>${r.compiled ? 'yes' : badge('no', 'bad')}</td></tr>`).join('')}</tbody></table></div></div>`;
  }

  function spendPanel() {
    const sp = data.spend, pts = sp.points;
    const top = Math.max(sp.spent_usd, 1e-9);
    const hardVisible = sp.hard_cap_usd && sp.hard_cap_usd <= Math.max(top * 3, (sp.soft_cap_usd || 0) * 3);
    const refs = [];
    if (sp.soft_cap_usd) refs.push({y: sp.soft_cap_usd, cls: 'soft', label: 'soft cap ' + money(sp.soft_cap_usd)});
    if (hardVisible) refs.push({y: sp.hard_cap_usd, cls: 'hard', label: 'hard cap ' + money(sp.hard_cap_usd)});
    const yMax = Math.max(top, sp.soft_cap_usd || 0, hardVisible ? sp.hard_cap_usd : 0);
    const cum = C.line([{cls: 'k0', step: true, points: [[0, 0], ...pts.map(p => [p.t, p.spent_usd, `#${p.n} ${p.kind || ''}: ${money(p.request_usd)}, total ${money(p.spent_usd)}`])]}],
      {refs, yMax, fmtY: money, label: 'cumulative spend'});
    const layers = [{cls: 'k0', label: 'input'}, {cls: 'k1', label: 'output'}, {cls: 'k2', label: 'cache read'}, {cls: 'k3', label: 'cache write'}];
    const bars = C.stacked(pts.map(p => ({parts: ['input', 'output', 'cache_read', 'cache_write'].map(k => p.parts[k] || 0),
      title: `#${p.n} ${p.kind || ''} ${(p.tools || []).join(', ')}: ${money(p.request_usd)}`})), layers, {fmtY: money, label: 'cost per request'});
    const byType = Object.entries((data.summary.cost || {}).by_turn_type || {});
    $('panel').innerHTML = `<div class="card"><h2>Cumulative spend</h2><p class="hint">Settled spend only.${hardVisible ? '' : ` The ${money(sp.hard_cap_usd)} hard cap is off scale.`} Unresolved reservations: ${money(sp.unresolved_usd)}.</p>${cum}</div>
      <div class="card"><h2>Cost per request</h2><p class="hint">Split by billed component. Hover a bar for the request and its tools.</p>${bars}</div>
      <div class="card"><h2>By turn type</h2><table><thead><tr><th>type</th><th class="num">requests</th><th class="num">cost</th><th class="num">share</th></tr></thead><tbody>
      ${byType.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v.requests}</td><td class="num">${money(v.usd)}</td><td class="num">${sp.spent_usd ? (100 * v.usd / sp.spent_usd).toFixed(1) : 0}%</td></tr>`).join('')}</tbody></table></div>`;
  }

  function cachePanel() {
    const pts = data.spend.points;
    const layers = [{cls: 'k2', label: 'cache read tokens'}, {cls: 'k3', label: 'cache write tokens'}];
    const chart = C.stacked(pts.map(p => ({parts: [p.tokens.cache_read || 0, p.tokens.cache_write || 0], title: `#${p.n}: read ${num(p.tokens.cache_read)}, write ${num(p.tokens.cache_write)}, reuse ${p.reuse_pct ?? '—'}%`})), layers, {fmtY: v => v >= 1000 ? (v / 1000) + 'k' : v, label: 'cache tokens'});
    const reuse = C.line([{cls: 'k1', points: pts.filter(p => p.reuse_pct != null).map(p => [p.n, p.reuse_pct, `#${p.n}: ${p.reuse_pct}%`])}], {yMin: 0, yMax: 100, pad: 0, fmtX: v => String(v), xMin: 0, label: 'cache reuse'});
    const cache = data.summary.cache || {};
    $('panel').innerHTML = `<div class="card"><h2>Cache tokens per request</h2><p class="hint">Overall reuse ${cache.reuse_pct ?? '—'}% (read ${num(cache.read_tokens)} / write ${num(cache.write_tokens)}), alarms: ${cache.alarms ?? 0}. A low read share after the first requests means the prompt prefix is not being reused.</p>${chart}</div>
      <div class="card"><h2>Reuse % per request</h2>${reuse}</div>`;
  }

  function toolsPanel() {
    const all = data.tools, tools = toolFilter ? all.filter(t => t.name === toolFilter) : all;
    const names = [...new Set(all.map(t => t.name))];
    const counts = n => all.filter(t => t.name === n).length;
    names.sort((a, b) => counts(b) - counts(a));
    const end = Math.max(1, ...all.map(t => t.t_end || 0));
    const left = 150, rowH = 20, width = Math.max(720, 1100 * zoom), h = names.length * rowH + 30;
    const sx = v => left + (v / end) * (width - left - 12);
    let g = '';
    names.forEach((n, i) => {
      g += `<line class="row" x1="0" x2="${width}" y1="${i * rowH + rowH}" y2="${i * rowH + rowH}"/><text class="gname" x="6" y="${i * rowH + 14}">${esc(n)} (${counts(n)})</text>`;
    });
    for (const v of C.niceTicks(0, end, 8)) g += `<text class="tick" x="${sx(v)}" y="${h - 8}" text-anchor="middle">${dur(v)}</text>`;
    all.forEach((t, k) => {
      const i = names.indexOf(t.name), x = sx(t.t || 0), w = Math.max(3, sx(t.t_end || 0) - x);
      g += `<rect class="gbar ${toolClass(t.name)}${t.is_error ? ' err' : ''}${selectedTool === k ? ' sel' : ''}" data-tool="${k}" x="${x}" y="${i * rowH + 4}" width="${w}" height="${rowH - 8}" rx="2"><title>${esc(t.name)} ${dur(t.t)} +${t.duration_s}s${t.is_error ? ' ERROR' : ''}</title></rect>`;
    });
    const chosen = selectedTool != null ? all[selectedTool] : null;
    $('panel').innerHTML = `<div class="card"><h2>Tool timeline</h2><p class="hint">One row per tool, one bar per call (width = duration; red = the tool reported an error). Click a bar for its arguments and result. <button id="z-in">Zoom +</button> <button id="z-out">Zoom −</button></p>
      <div class="gantt-scroll"><svg class="gantt" width="${width}" height="${h}" role="img" aria-label="tool timeline">${g}</svg></div></div>
      <div class="card"><h2>${chosen ? `${esc(chosen.name)} at ${dur(chosen.t)} (${chosen.duration_s}s)${chosen.is_error ? ' ' + badge('error', 'bad') : ''}` : 'Selected call'}</h2>
      ${chosen ? `<h3>Arguments</h3><pre>${esc(chosen.args)}</pre><h3>Result</h3><pre>${esc(chosen.result ?? (chosen.running ? '(still running)' : ''))}</pre>` : '<p class="muted">Select a bar above.</p>'}</div>
      <div class="card"><h2>All calls</h2><div class="scroll"><table><thead><tr><th>t</th><th>tool</th><th class="num">duration</th><th>result</th></tr></thead><tbody>
      ${all.map((t, k) => `<tr class="click" data-tool="${k}"><td>${dur(t.t)}</td><td>${esc(t.name)}</td><td class="num">${t.duration_s}s</td><td>${t.is_error ? badge('error', 'bad') : t.running ? badge('running', 'mid') : ''} <span class="muted small">${esc((t.result || '').slice(0, 90))}</span></td></tr>`).join('')}</tbody></table></div></div>`;
    $('panel').querySelectorAll('[data-tool]').forEach(el => el.onclick = () => { selectedTool = +el.dataset.tool; render(); });
    const zi = $('z-in'), zo = $('z-out');
    if (zi) { zi.onclick = () => { zoom = Math.min(16, zoom * 1.6); render(); }; zo.onclick = () => { zoom = Math.max(1, zoom / 1.6); render(); }; }
  }

  function ideasPanel() {
    const ideas = data.ideas;
    $('panel').innerHTML = ideas.length ? ideas.map(i => `<details open><summary>${esc(i.title || i.id)} ${badge(i.status || '?', i.status === 'succeeded' ? 'good' : i.status === 'failed' || i.status === 'abandoned' ? 'bad' : 'mid')}
      <span class="muted small">${i.attempts.length} attempt${i.attempts.length === 1 ? '' : 's'} · ${i.probes} probe${i.probes === 1 ? '' : 's'} · best ${i.best_proxy ?? '—'}</span></summary>
      <p class="small muted">${esc(i.id)}${i.region ? ' · lines ' + esc(i.region.join('–')) : ''}</p>
      <p>${esc(i.hypothesis)}</p>${i.reason ? `<p><b>Outcome:</b> ${esc(i.reason)}</p>` : ''}
      ${i.expected_effect ? `<p class="small muted">Expected: ${esc(Object.entries(i.expected_effect).map(([k, v]) => `${k}: ${v}`).join(' · '))}</p>` : ''}
      <p class="small">Lineage: ${i.attempts.length ? i.attempts.map(a => `${esc(a.candidate)}${a.parents.length ? ` <span class="muted">← ${esc(a.parents.join(', '))}</span>` : ''}`).join(' · ') : '<span class="muted">no candidate attached to this idea</span>'}</p></details>`).join('')
      : '<p class="muted">No ideas recorded.</p>';
    const without = (data.summary.ideas_without_attempts || []);
    if (without.length) $('panel').insertAdjacentHTML('afterbegin', `<div class="warn">Ideas without attempts: ${esc(without.join(', '))}</div><br>`);
  }

  function eventsPanel() {
    const rows = data.controls;
    $('panel').innerHTML = `<div class="card"><h2>Finish, control and gate events</h2><p class="hint">Finish review/confirm, soft-cap crossing, refused requests, no-work fallbacks and the final stop decision.</p>
      ${rows.length ? `<table><thead><tr><th>t</th><th>event</th><th>details</th></tr></thead><tbody>${rows.map(r => `<tr><td>${dur(r.t)}</td><td>${badge(r.kind, r.kind === 'gate' || r.kind === 'cache_alarm' ? 'bad' : r.kind === 'soft_cap' ? 'mid' : '')} ${esc(r.label)}</td><td class="small"><code>${esc(JSON.stringify(r.detail))}</code></td></tr>`).join('')}</tbody></table>` : '<p class="muted">No events yet.</p>'}</div>`;
  }

  function leanPanel() {
    const mix = data.lean, paths = Object.entries(mix.paths), total = paths.reduce((a, [, v]) => a + v.runs, 0);
    const cold = mix.cold_verification;
    $('panel').innerHTML = `<div class="grid2"><div class="card"><h2>Lean path mix</h2><p class="hint">Per-version compiles, warm session worker versus cold compile.</p>
      ${total ? `<div class="stack">${paths.map(([k, v], i) => `<span class="k${i}" data-width="${(100 * v.runs / total).toFixed(1)}" title="${esc(k)} ${v.runs}"></span>`).join('')}</div>
      <table><thead><tr><th>path</th><th class="num">compiles</th><th class="num">seconds</th><th>by check</th></tr></thead><tbody>${paths.map(([k, v], i) => `<tr><td><i class="sw k${i}">&nbsp;&nbsp;</i> ${esc(k)}</td><td class="num">${v.runs}</td><td class="num">${v.seconds}</td><td class="small">${esc(Object.entries(v.by_check).map(([c, n]) => `${c} ×${n}`).join(', '))}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">No Lean runs recorded.</p>'}</div>
      <div class="card"><h2>Cold verification</h2>${cold ? `<p>${cold.confirmed ? badge('confirmed', 'good') : badge('not confirmed', 'bad')} ${esc(cold.candidate_id.slice(0, 10))}…</p>
        <table><tbody>${Object.entries(cold.passed || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v ? badge('pass', 'good') : badge('fail', 'bad')}</td></tr>`).join('')}
        <tr><td>heartbeats recorded / cold</td><td>${num(cold.recorded_heartbeats)} / ${num(cold.cold_heartbeats)}</td></tr></tbody></table>`
        : '<p class="muted">No cold verification yet.</p>'}
      ${data.submission ? `<h3>Submission</h3><p>${esc(data.submission.candidate)} · proxy ${esc(data.submission.proxy)} · ${esc(data.submission.tokens)} tokens / ${esc(data.submission.heartbeats)} heartbeats · ${esc(data.submission.verified_by)}</p>` : ''}</div></div>`;
    applyWidths($('panel'));
  }

  function packetPanel() {
    $('panel').innerHTML = data.packet ? `<details><summary>Kickoff packet (${num(data.packet.length)} characters)</summary><pre>${esc(data.packet)}</pre></details>` : '<p class="muted">No packet.txt in this run.</p>';
  }

  function lfPanel() {
    if (!lf) { $('panel').innerHTML = '<p class="muted">Loading Langfuse…</p>'; return; }
    if (!lf.available) {
      $('panel').innerHTML = `<div class="warn">Langfuse unavailable: ${esc(lf.error || 'unknown error')}. The rest of this dashboard is unaffected. <button id="lf-retry">Retry</button></div>`;
      $('lf-retry').onclick = () => loadLangfuse(true);
      return;
    }
    const t = lf.totals, ledger = data.spend.spent_usd;
    const obs = lf.observations.filter(o => !obsType || o.type === obsType);
    const maxLat = Math.max(0.001, ...obs.map(o => o.latency_s || 0));
    const types = [...new Set(lf.observations.map(o => o.type))];
    const latChart = C.line([{cls: 'k5', points: lf.observations.filter(o => o.type === 'GENERATION').map((o, i) => [i + 1, o.latency_s, `${o.name}: ${o.latency_s}s`])}],
      {xMin: 0, fmtX: v => String(v), fmtY: v => v + 's', label: 'generation latency'});
    $('panel').innerHTML = `${lf.stale ? `<div class="warn">Showing cached data; refresh failed: ${esc(lf.error)}</div><br>` : ''}
      <div class="kpis"><div class="kpi"><div class="l">Observations</div><div class="v">${t.observations}</div><div class="n">${t.generations} generations · ${t.tools} tools · ${t.errors} errors</div></div>
      <div class="kpi"><div class="l">Langfuse cost</div><div class="v">${money(t.cost_usd)}</div><div class="n">ledger ${money(ledger)}</div></div>
      <div class="kpi"><div class="l">Generation latency</div><div class="v">${t.mean_generation_latency_s ?? '—'}s</div><div class="n">max ${t.max_generation_latency_s ?? '—'}s</div></div>
      <div class="kpi"><div class="l">Traces</div><div class="v">${lf.traces.length}</div><div class="n">${lf.session_url ? `<a href="${esc(lf.session_url)}" target="_blank" rel="noopener">session in Langfuse</a>` : 'no project link'}</div></div></div>
      <div class="card"><h2>Generation latency</h2>${latChart}</div>
      <div class="card"><h2>Traces</h2><div class="scroll"><table><thead><tr><th>start</th><th>name</th><th class="num">latency</th><th class="num">cost</th><th class="num">gens</th><th class="num">tools</th><th class="num">errors</th><th>models</th><th></th></tr></thead><tbody>
      ${lf.traces.map(x => `<tr><td>${x.start ? new Date(x.start * 1000).toLocaleTimeString() : ''}</td><td>${esc(x.name || x.trace_id.slice(0, 8))}</td><td class="num">${x.latency_s != null ? dur(x.latency_s) : '—'}</td><td class="num">${money(x.cost_usd)}</td><td class="num">${x.generations}</td><td class="num">${x.tools}</td><td class="num">${x.errors || ''}</td><td class="small">${esc(x.models.join(', '))}</td><td>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">open</a>` : ''}</td></tr>`).join('')}</tbody></table></div></div>
      <div class="card"><h2>Observations</h2><p class="hint">Type: <select id="obs-type"><option value="">all</option>${types.map(x => `<option ${x === obsType ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select> ${obs.length} shown</p>
      <div class="scroll"><table><thead><tr><th>start</th><th>type</th><th>name</th><th>model</th><th>latency</th><th class="num">cost</th><th class="num">in / out</th><th class="num">cache r / w</th><th></th></tr></thead><tbody>
      ${obs.map(o => `<tr><td>${o.start ? new Date(o.start * 1000).toLocaleTimeString() : ''}</td><td>${esc(o.type)}${o.level === 'ERROR' ? ' ' + badge('error', 'bad') : ''}</td><td>${esc(o.name)}</td><td class="small">${esc(o.model || '')}</td>
      <td><span class="bars"><span data-width="${(100 * (o.latency_s || 0) / maxLat).toFixed(1)}"></span></span>${o.latency_s ?? '—'}s</td><td class="num">${o.cost_usd != null ? money(o.cost_usd) : ''}</td>
      <td class="num">${o.input_tokens || o.output_tokens ? num(o.input_tokens) + ' / ' + num(o.output_tokens) : ''}</td><td class="num">${o.cache_read_tokens || o.cache_write_tokens ? num(o.cache_read_tokens) + ' / ' + num(o.cache_write_tokens) : ''}</td>
      <td>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">open</a>` : ''}</td></tr>`).join('')}</tbody></table></div></div>`;
    $('obs-type').onchange = e => { obsType = e.target.value; lfPanel(); };
    applyWidths($('panel'));
  }

  const renderers = {score: scorePanel, spend: spendPanel, cache: cachePanel, tools: toolsPanel, ideas: ideasPanel,
                     events: eventsPanel, lean: leanPanel, packet: packetPanel, langfuse: lfPanel};
  function render() {
    if (!data) return;
    $('tabs').innerHTML = TABS.map(([id, label]) => `<button role="tab" data-tab="${id}" aria-selected="${id === tab}">${label}</button>`).join('');
    $('tabs').querySelectorAll('[data-tab]').forEach(b => b.onclick = () => {
      tab = b.dataset.tab; history.replaceState(null, '', '#' + tab); try { localStorage.setItem('arena-dash-tab', tab); } catch {}
      if (tab === 'langfuse' && !lf) loadLangfuse(); render();
    });
    kpis();
    const scrollY = window.scrollY;
    renderers[tab]();
    window.scrollTo(0, scrollY);
  }

  async function loadLangfuse(refresh = false) {
    try {
      const r = await fetch(`langfuse.json${refresh ? '?refresh=1' : ''}`, {cache: 'no-store'});
      lf = await r.json();
    } catch (e) { lf = {available: false, error: 'viewer server did not answer'}; }
    if (lf.session_url) { $('lf-link').href = lf.session_url; $('lf-link').hidden = false; }
    if (tab === 'langfuse') render();
  }

  let busy = false;
  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const r = await fetch('dashboard.json', {cache: 'no-store'});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const next = await r.json();
      const changed = JSON.stringify(next) !== JSON.stringify(data);
      data = next;
      $('title').textContent = data.run_id;
      const s = data.summary || {};
      $('sub').textContent = `${s.model || data.config.model || ''} · ${s.theorem || data.config.theorem || ''} · thinking ${s.thinking || data.config.thinking || '—'}${s.stop_reason ? ' · stopped: ' + s.stop_reason : ' · running'}`;
      $('live').textContent = `Live · ${new Date().toLocaleTimeString()}`;
      $('live').classList.add('ok');
      document.title = `Dashboard ${data.run_id}`;
      if (changed) render();
    } catch (e) {
      $('live').textContent = `Disconnected: ${e.message}`;
      $('live').classList.remove('ok');
    }
    busy = false;
  }
  refresh();
  loadLangfuse();
  setInterval(refresh, 6000);
  setInterval(() => { if (tab === 'langfuse') loadLangfuse(); }, 45000);
})();
