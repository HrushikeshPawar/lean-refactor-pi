/* Per-run dashboard: one screen of key charts, then a few drill-down views. Desktop only. */
(() => {
  const C = window.Charts;
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = v => v == null ? '—' : '$' + (Math.abs(v) >= 0.1 ? v.toFixed(3) : v.toFixed(4));
  const num = (v, d = 0) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
  const dur = s => s == null ? '—' : C.dur(s);
  const TABS = [['tools', 'Tool calls'], ['ideas', 'Ideas and evaluations'], ['spend', 'Spend and cache'], ['langfuse', 'Langfuse']];
  let data = null, lf = null, tab = 'tools', selectedTool = null, obsType = 'GENERATION';
  try { tab = localStorage.getItem('arena-dash-tab') || tab; } catch {}
  if (!TABS.some(([id]) => id === tab)) tab = 'tools';

  const toolIndex = new Map();
  const toolClass = name => { if (!toolIndex.has(name)) toolIndex.set(name, toolIndex.size % 8); return 'k' + toolIndex.get(name); };
  const badge = (text, kind = '') => `<span class="badge ${kind}">${esc(text)}</span>`;
  const applyWidths = root => root.querySelectorAll('[data-width]').forEach(el => el.style.width = `${el.dataset.width}%`);  // the CSP forbids style attributes
  const place = (id, html) => { const el = $(id); el.innerHTML = html; C.mount(el); applyWidths(el); };

  /* ---- header and KPIs ---- */
  function statusInfo() {
    const s = data.summary || {};
    if (s.stop_reason) return {text: `done · ${s.stop_reason}`, kind: s.stop_reason === 'finished' ? 'good' : 'mid'};
    if (data.last_activity && Date.now() / 1000 - data.last_activity > 900) return {text: 'stalled', kind: 'bad'};
    return {text: 'live', kind: 'good'};
  }
  function header() {
    const s = data.summary || {}, c = data.config || {}, st = statusInfo();
    $('title').textContent = data.run_id;
    $('status').textContent = st.text; $('status').className = `badge ${st.kind}`;
    $('sub').textContent = `${s.model || c.model || ''} · ${s.theorem || c.theorem || ''} · thinking ${s.thinking || c.thinking || '—'}`;
    document.title = `Dashboard ${data.run_id}`;
  }
  function kpis() {
    const s = data.summary || {}, cost = s.cost || {}, cache = s.cache || {}, best = (s.progress || {}).best_verified_candidate, sub = data.submission;
    const ref = data.reference, pctOf = (v, base) => base ? `${v <= base ? '−' : '+'}${Math.abs(100 * (v - base) / base).toFixed(0)}%` : '';
    const items = [
      ['Best verified', best ? best.proxy : '—', best ? `${best.candidate} · ${best.proxy - data.baseline_proxy >= 0 ? '+' : ''}${(best.proxy - data.baseline_proxy).toFixed(2)} vs ${data.baseline_proxy}` : 'none yet', best && best.proxy > data.baseline_proxy],
      ['Tokens / heartbeats', best ? `${num(best.tokens)} / ${num(best.heartbeats)}` : '—', ref ? `orig ${num(ref.tokens)} / ${num(ref.heartbeats)}` + (best ? ` (${pctOf(best.tokens, ref.tokens)} / ${pctOf(best.heartbeats, ref.heartbeats)})` : '') : ''],
      ['Spend', money(data.spend.spent_usd), `soft cap $${+(data.spend.soft_cap_usd ?? 0).toFixed(2)} · hard $${data.spend.hard_cap_usd}`],
      ['Requests', num(cost.requests ?? data.spend.points.length), `${cost.retries ?? 0} retries · ${cost.requests_after_best ?? '—'} after best`],
      ['Post-best spend', money(cost.spent_after_best_usd), `bookkeeping+rejected ${cost.bookkeeping_and_rejected_pct ?? '—'}%`],
      ['Cache reuse', cache.reuse_pct != null ? cache.reuse_pct + '%' : '—', `recent 10: ${cache.reuse_pct_recent_10 ?? '—'}%`],
      ['Tool results', num((s.tools || {}).results), `${(s.tools || {}).error_total ?? 0} errors`],
      ['Submission', sub ? `${sub.candidate} · ${sub.proxy}` : 'none', sub ? (sub.verified_by === 'cold compile' ? 'cold-verified' : `verified by ${sub.verified_by || '?'}`) : (s.stop_reason ? 'not submitted' : 'running')]];
    $('kpis').innerHTML = items.map(([l, v, n, good]) => `<div class="kpi" title="${esc(n)}"><div class="l">${esc(l)}</div><div class="v${good ? ' good' : ''}">${esc(v)}</div><div class="n">${esc(n)}</div></div>`).join('');
  }

  /* ---- overview charts: x is the evaluation number (0 = the original proof) or the API request number ---- */
  const evalEnd = () => Math.max(1, ...data.scores.map(r => r.n || 0));
  const original = () => ({proxy: data.baseline_proxy, tokens: data.reference?.tokens, heartbeats: data.reference?.heartbeats});

  function scoreChart() {
    const rows = data.scores, full = rows.filter(r => r.mode === 'full' && r.proxy != null), fast = rows.filter(r => r.mode !== 'full' && r.estimated_proxy != null), end = evalEnd();
    const pt = (r, v, extra = '') => [r.n, v, `evaluation ${r.n}: candidate ${r.candidate} (${r.mode})\n${extra}proxy ${v}\n${num(r.tokens)} tokens, ${num(r.heartbeats)} heartbeats\nclick to select in the graph`, r.candidate_id];
    const bestFull = full.reduce((m, r) => !m || r.proxy > m.proxy ? r : m, null);
    place('c-score', C.line([
      {cls: 'k1', step: true, dots: false, points: [[0, data.baseline_proxy], ...rows.filter(r => r.best_verified != null).map(r => [r.n, r.best_verified])]},
      {cls: 'korig', noLine: true, r: 6, points: [[0, data.baseline_proxy, `evaluation 0: the original proof\nproxy ${data.baseline_proxy}`]]},
      {cls: 'k0', noLine: true, r: 5, points: full.map(r => pt(r, r.proxy))},
      {cls: 'k2', noLine: true, hollow: true, r: 4, points: fast.map(r => pt(r, r.estimated_proxy, 'fast estimate '))}],
      {refs: [{y: data.baseline_proxy, cls: 'base', label: ''}], pointLabels: [{x: 0, y: data.baseline_proxy, text: `original ${data.baseline_proxy}`, dy: -12}],
       extendTo: end, xMin: 0, xMax: end, xTime: false, intX: true, yMin: 0, yMax: 100, exact: true, height: 300,
       fmtY: C.fmt.score, yLabel: 'proxy score (0 to 100)', xLabel: 'evaluation number (0 = original proof)',
       best: bestFull && {x: bestFull.n, y: bestFull.proxy, text: `best ${bestFull.proxy} (${bestFull.candidate})`},
       legend: [['korig', 'original proof (evaluation 0)'], ['k0', 'full evaluation, all versions checked'], ['k2', 'fast estimate'], ['k1', 'best verified so far']], label: 'score by evaluation'}));
  }

  const PARTS = [['cache_read', 'Cache read', 'cp0'], ['input', 'Input', 'cp1'], ['cache_write', 'Cache write', 'cp2'], ['output', 'Output', 'cp3']];

  function spendCharts() {
    const sp = data.spend, pts = sp.points;
    const sums = Object.fromEntries(PARTS.map(([k]) => [k, 0])), area = [{x: 0, parts: PARTS.map(() => 0)}];
    for (const p of pts) {
      for (const [k] of PARTS) sums[k] += p.parts[k] || 0;
      const row = PARTS.slice().reverse().map(([k, label]) => `${label}: ${money(p.parts[k] || 0)} (total ${money(sums[k])})`);
      area.push({x: p.n, parts: PARTS.map(([k]) => sums[k]),
                 tip: `request #${p.n}${p.kind ? ' ' + p.kind : ''}: ${money(p.request_usd)}\nrunning total ${money(Object.values(sums).reduce((a, v) => a + v, 0))}\n${row.join('\n')}`});
    }
    const grand = Object.values(sums).reduce((a, v) => a + v, 0), top = Math.max(grand, sp.soft_cap_usd || 0, 1e-9);
    const hardVisible = !!sp.hard_cap_usd && sp.hard_cap_usd <= 2.5 * top;
    const refs = [], notes = [];
    if (sp.soft_cap_usd) refs.push({y: sp.soft_cap_usd, cls: 'soft', label: 'soft cap ' + money(sp.soft_cap_usd)});
    if (hardVisible) refs.push({y: sp.hard_cap_usd, cls: 'hard', label: 'hard cap ' + money(sp.hard_cap_usd)});
    else if (sp.hard_cap_usd) notes.push({cls: 'hard', text: `hard cap ${money(sp.hard_cap_usd)} is off scale`});
    $('h-spend').textContent = `${money(sp.spent_usd)} settled · ${money(sp.unresolved_usd)} reserved`;
    const legend = [['toptot', `Total ${money(grand)}`], ...PARTS.slice().reverse().map(([k, label, cls]) => [cls, `${label} ${money(sums[k])}${grand ? ` (${(100 * sums[k] / grand).toFixed(0)}%)` : ''}`])];
    place('c-spend', C.area(area, PARTS.map(([, label, cls]) => ({cls, label})),
      {refs, notes, xMin: 0, xMax: Math.max(1, pts.length), yMin: 0, yMax: hardVisible ? sp.hard_cap_usd * 1.08 : top * 1.15, exact: true, height: 300,
       fmtY: C.fmt.money, yLabel: 'cumulative spend (USD)', xLabel: 'API request number', legend, label: 'API spend by component'}));
  }

  function metricChart(id, key, ref, unit, cls) {
    const ok = data.scores.filter(r => r.compiled && r[key] != null), end = evalEnd();
    // The original proof is evaluation 0, so the best-so-far line starts from it.
    let low = ref ?? Infinity; const steps = ref != null ? [[0, ref]] : [];
    for (const r of ok) { low = Math.min(low, r[key]); steps.push([r.n, low]); }
    const lowest = ok.reduce((m, r) => !m || r[key] < m[key] ? r : m, null);
    const pt = r => [r.n, r[key], `evaluation ${r.n}: candidate ${r.candidate} (${r.mode})\n${num(r[key])} ${unit}\nclick to select in the graph`, r.candidate_id];
    place(id, C.line([
      {cls, step: true, dots: false, points: steps},
      {cls: 'korig', noLine: true, r: 6, points: ref != null ? [[0, ref, `evaluation 0: the original proof\n${num(ref)} ${unit}`]] : []},
      {cls, noLine: true, r: 4, points: ok.filter(r => r.mode === 'full').map(pt)},
      {cls, noLine: true, r: 4, hollow: true, points: ok.filter(r => r.mode !== 'full').map(pt)}],
      {refs: ref != null ? [{y: ref, cls: 'base', label: ''}] : [], pointLabels: ref != null ? [{x: 0, y: ref, text: `original ${num(ref)}`, dy: 24}] : [],
       includeRefs: true, extendTo: end, xMin: 0, xMax: end, xTime: false, intX: true, yMin: 0, height: 260, fmtY: C.fmt.num,
       yLabel: unit, xLabel: 'evaluation number (0 = original proof)', best: lowest && {below: true, x: lowest.n, y: lowest[key], text: `${num(lowest[key])} (${lowest.candidate})`},
       legend: [['korig', 'original proof'], [cls, 'full evaluation (hollow = fast)']], label: unit}));
  }

  function toolsTimeline() {
    const all = data.tools;
    if (!all.length) return place('c-tools', '<p class="muted">No tool calls yet.</p>');
    const short = n => String(n).replace(/^mcp__arena_/, '').replace(/^arena_/, '');
    const counts = new Map(); all.forEach(t => counts.set(t.name, (counts.get(t.name) || 0) + 1));
    const names = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
    const shown = names.slice(0, 11), rowOf = t => { const i = shown.indexOf(t.name); return i < 0 ? shown.length : i; };
    const rows = shown.map(n => [short(n), counts.get(n)]);
    if (names.length > shown.length) rows.push(['other', names.slice(shown.length).reduce((a, n) => a + counts.get(n), 0)]);
    const end = Math.max(1, ...data.tools.map(t => t.t_end || 0));
    place('c-tools', C.box(w => {
      const left = 200, rowH = 22, h = rows.length * rowH + 46, sx = v => left + v / end * (w - left - 14);
      let g = '';
      rows.forEach(([name, n], i) => g += `<line class="row" x1="0" x2="${w}" y1="${(i + 1) * rowH}" y2="${(i + 1) * rowH}"/><text class="gname" x="4" y="${i * rowH + 15}">${esc(name.length > 26 ? name.slice(0, 25) + '…' : name)} <tspan class="tick">×${n}</tspan></text>`);
      for (const v of C.timeTicks(0, end, Math.max(4, Math.floor((w - left) / 90)))) g += `<line class="vgrid" x1="${sx(v)}" x2="${sx(v)}" y1="0" y2="${rows.length * rowH}"/><text class="tick" x="${sx(v)}" y="${rows.length * rowH + 16}" text-anchor="middle">${C.tickTime(Math.round(v))}</text>`;
      g += `<text class="axtitle" x="${(left + w) / 2}" y="${h - 6}" text-anchor="middle">time since run start</text>`;
      all.forEach((t, k) => {
        const x = sx(t.t || 0), bw = Math.max(3, sx(t.t_end || 0) - x);
        g += `<rect class="gbar ${toolClass(t.name)}${t.is_error ? ' err' : ''}${selectedTool === k ? ' sel' : ''}" data-tool="${k}" x="${x}" y="${rowOf(t) * rowH + 3}" width="${bw}" height="${rowH - 7}" rx="2" data-tip="${esc(`${t.name} at ${dur(t.t)}, ${t.duration_s}s${t.is_error ? ' (error)' : ''}`)}"/>`;
      });
      return `<svg class="gantt" width="${w}" height="${h}" role="img" aria-label="tool activity timeline">${g}</svg>`;
    }));
    $('c-tools').querySelectorAll('[data-tool]').forEach(el => el.onclick = () => openTool(+el.dataset.tool));
  }

  function ideasCard() {
    const ideas = data.ideas, kind = s => s === 'succeeded' ? 'good' : s === 'failed' || s === 'abandoned' ? 'bad' : 'mid';
    $('h-ideas').textContent = `${ideas.length} idea${ideas.length === 1 ? '' : 's'}`;
    place('c-ideas', ideas.length ? ideas.map(i => `<div class="idea"><div class="t">${esc(i.title || i.id)} ${badge(i.status || '?', kind(i.status))}</div>
      <div class="small muted">${i.attempts.length} attempt${i.attempts.length === 1 ? '' : 's'} · ${i.probes} probe${i.probes === 1 ? '' : 's'} · best proxy ${i.best_proxy ?? '—'}${i.attempts.length ? ' · ' + esc(i.attempts.map(a => a.candidate).join(', ')) : ''}</div></div>`).join('') : '<p class="muted">No ideas recorded.</p>');
  }

  function leanCard() {
    const mix = data.lean, paths = Object.entries(mix.paths), total = paths.reduce((a, [, v]) => a + v.runs, 0), cold = mix.cold_verification;
    place('c-lean', `${total ? `<div class="small muted">Per-version compiles by path</div><div class="stack">${paths.map(([k, v], i) => `<span class="k${i}" data-width="${(100 * v.runs / total).toFixed(1)}" title="${esc(k)} ${v.runs}"></span>`).join('')}</div>
      <div class="kv">${paths.map(([k, v], i) => `<span><i class="sw box k${i}"></i> ${esc(k)}</span><span>${v.runs} compiles · ${v.seconds}s</span>`).join('')}</div>` : '<p class="muted">No Lean runs recorded.</p>'}
      <h3>Cold verification</h3>${cold ? `<p>${cold.confirmed ? badge('confirmed', 'good') : badge('not confirmed', 'bad')} <span class="small muted">${esc(String(cold.candidate_id).slice(0, 10))}</span></p>
        <div class="kv">${Object.entries(cold.passed || {}).map(([k, v]) => `<span>${esc(k)}</span><span>${v ? badge('pass', 'good') : badge('fail', 'bad')}</span>`).join('')}<span>heartbeats recorded / cold</span><span>${num(cold.recorded_heartbeats)} / ${num(cold.cold_heartbeats)}</span></div>` : '<p class="muted">Not run yet.</p>'}
      ${data.submission ? `<div class="small muted">Submission ${esc(data.submission.candidate)}: proxy ${esc(data.submission.proxy)}, ${esc(data.submission.tokens)} tokens / ${esc(data.submission.heartbeats)} heartbeats, ${esc(data.submission.verified_by)}</div>` : ''}`);
  }

  function lfCard() {
    if (!lf) return place('c-lf', '<p class="muted">Loading Langfuse…</p>');
    if (!lf.available) return place('c-lf', `<div class="warn">Langfuse unavailable: ${esc(lf.error || 'unknown error')}. <button id="lf-retry">Retry</button></div>`), ($('lf-retry').onclick = () => loadLangfuse(true));
    const t = lf.totals, ledger = data.spend.spent_usd, diff = t.cost_usd - ledger, ok = Math.abs(diff) <= Math.max(0.0005, 0.02 * ledger);
    $('h-lf').innerHTML = lf.session_url ? `<a href="${esc(lf.session_url)}" target="_blank" rel="noopener">session &#8599;</a>` : 'no project link';
    const gens = lf.observations.filter(o => o.type === 'GENERATION').map((o, i) => [i + 1, o.latency_s, `generation #${i + 1} ${o.name}: ${o.latency_s} s`]).filter(g => g[1] != null);
    const slowest = gens.reduce((m, g) => !m || g[1] > m[1] ? g : m, null);
    place('c-lf', `${lf.stale ? `<div class="warn">Cached data; refresh failed: ${esc(lf.error)}</div>` : ''}
      <div class="mini"><div><div class="l">Traces</div><div class="v">${lf.traces.length}</div></div><div><div class="l">Generations</div><div class="v">${t.generations}</div></div>
      <div><div class="l">Mean latency</div><div class="v">${t.mean_generation_latency_s ?? '—'}s</div></div><div><div class="l">Errors</div><div class="v">${t.errors}</div></div></div>
      <div class="kv"><span>Langfuse cost</span><span>${money(t.cost_usd)} ${ok ? badge('matches ledger', 'good') : badge(`ledger ${money(ledger)}, differs ${money(Math.abs(diff))}`, 'mid')}</span></div>
      ${C.line([{cls: 'k5', points: gens}], {xMin: 0, xTime: false, fmtY: C.fmt.sec, yLabel: 'latency', xLabel: 'generation #', height: 190,
        best: slowest && {x: slowest[0], y: slowest[1], text: `slowest ${slowest[1]} s`}, label: 'generation latency'})}`);
  }

  /* ---- drill-down panels ---- */
  function toolsPanel() {
    const all = data.tools, chosen = selectedTool != null ? all[selectedTool] : null;
    $('panel').innerHTML = `<div class="card"><div class="head"><h2>${chosen ? `${esc(chosen.name)} at ${dur(chosen.t)} (${chosen.duration_s}s)${chosen.is_error ? ' ' + badge('error', 'bad') : ''}` : 'Selected call'}</h2></div>
      ${chosen ? `<h3>Arguments</h3><pre>${esc(chosen.args)}</pre><h3>Result</h3><pre>${esc(chosen.result ?? (chosen.running ? '(still running)' : ''))}</pre>` : '<p class="muted">Select a bar above or a row below.</p>'}</div>
      <div class="card"><div class="head"><h2>All calls (${all.length})</h2></div><div class="scroll"><table><thead><tr><th>t</th><th>tool</th><th class="num">duration</th><th>result</th></tr></thead><tbody>
      ${all.map((t, k) => `<tr class="click${selectedTool === k ? ' sel' : ''}" data-tool="${k}"><td>${dur(t.t)}</td><td>${esc(t.name)}</td><td class="num">${t.duration_s}s</td><td>${t.is_error ? badge('error', 'bad') : t.running ? badge('running', 'mid') : ''} <span class="muted small">${esc((t.result || '').slice(0, 140))}</span></td></tr>`).join('')}</tbody></table></div></div>`;
    $('panel').querySelectorAll('tr[data-tool]').forEach(el => el.onclick = () => { selectedTool = +el.dataset.tool; renderPanel(); toolsTimeline(); });
  }

  function ideasPanel() {
    const rows = data.scores, ideas = data.ideas, without = data.summary.ideas_without_attempts || [];
    $('panel').innerHTML = `${without.length ? `<div class="warn">Ideas without attempts: ${esc(without.join(', '))}</div><br>` : ''}
      <div class="grid2"><div>${ideas.length ? ideas.map(i => `<details open><summary>${esc(i.title || i.id)} ${badge(i.status || '?', i.status === 'succeeded' ? 'good' : i.status === 'failed' || i.status === 'abandoned' ? 'bad' : 'mid')}
      <span class="muted small">${i.attempts.length} attempt${i.attempts.length === 1 ? '' : 's'} · ${i.probes} probe${i.probes === 1 ? '' : 's'} · best ${i.best_proxy ?? '—'}</span></summary>
      <p class="small muted">${esc(i.id)}${i.region ? ' · lines ' + esc(i.region.join('–')) : ''}</p><p>${esc(i.hypothesis)}</p>${i.reason ? `<p><b>Outcome:</b> ${esc(i.reason)}</p>` : ''}
      ${i.expected_effect ? `<p class="small muted">Expected: ${esc(Object.entries(i.expected_effect).map(([k, v]) => `${k}: ${v}`).join(' · '))}</p>` : ''}
      <p class="small">Lineage: ${i.attempts.length ? i.attempts.map(a => `${esc(a.candidate)}${a.parents.length ? ` <span class="muted">← ${esc(a.parents.join(', '))}</span>` : ''}`).join(' · ') : '<span class="muted">no candidate attached to this idea</span>'}</p></details>`).join('') : '<p class="muted">No ideas recorded.</p>'}</div>
      <div class="card"><div class="head"><h2>Evaluations (${rows.length})</h2></div><div class="scroll"><table><thead><tr><th>t</th><th>candidate</th><th>mode</th><th class="num">proxy</th><th class="num">est.</th><th class="num">tokens</th><th class="num">heartbeats</th><th>compiled</th></tr></thead><tbody>
      ${rows.map(r => `<tr><td>${dur(r.t)}</td><td>${esc(r.candidate)}</td><td>${esc(r.mode)}</td><td class="num">${r.proxy ?? '—'}</td><td class="num">${r.estimated_proxy ?? '—'}</td><td class="num">${num(r.tokens)}</td><td class="num">${num(r.heartbeats)}</td><td>${r.compiled ? 'yes' : badge('no', 'bad')}</td></tr>`).join('')}</tbody></table></div></div></div>`;
  }

  function spendPanel() {
    const pts = data.spend.points, cache = data.summary.cache || {}, byType = Object.entries((data.summary.cost || {}).by_turn_type || {}), spent = data.spend.spent_usd;
    $('panel').innerHTML = `<div class="grid2"><div class="card"><div class="head"><h2>Cache tokens per request</h2><span class="hint">overall reuse ${cache.reuse_pct ?? '—'}% · read ${num(cache.read_tokens)} / write ${num(cache.write_tokens)} · alarms ${cache.alarms ?? 0}</span></div>
      ${C.stacked(pts.map(p => ({parts: [p.tokens.cache_read || 0, p.tokens.cache_write || 0], title: `#${p.n}: read ${num(p.tokens.cache_read)}, write ${num(p.tokens.cache_write)}, reuse ${p.reuse_pct ?? '—'}%`})),
        [{cls: 'k2', label: 'cache read'}, {cls: 'k3', label: 'cache write'}], {fmtY: C.fmt.num, yLabel: 'tokens per request', height: 260, label: 'cache tokens'})}</div>
      <div class="card"><div class="head"><h2>Cache reuse per request</h2><span class="hint">a low read share after the first requests means the prompt prefix is not reused</span></div>
      ${C.line([{cls: 'k1', points: pts.filter(p => p.reuse_pct != null).map(p => [p.n, p.reuse_pct, `request #${p.n}: ${p.reuse_pct}% of cached tokens were reads`])}], {yMin: 0, yMax: 100, exact: true, xTime: false, xMin: 0, xMax: Math.max(1, pts.length), fmtY: C.fmt.pct, yLabel: 'cache reuse (%)', xLabel: 'request #', height: 260, label: 'cache reuse'})}</div></div>
      <div class="card"><div class="head"><h2>Cost per request</h2><span class="hint">each request's own cost by billed component; the overview chart shows the running total</span></div>
      ${C.stacked(pts.map(p => ({parts: PARTS.map(([k]) => p.parts[k] || 0), title: `#${p.n} ${p.kind || ''}: ${money(p.request_usd)}\ncache reuse ${p.reuse_pct ?? '—'}%\n${(p.tools || []).join(', ')}`})),
        PARTS.map(([, label, cls]) => ({cls, label})), {fmtY: C.fmt.money, yLabel: 'cost per request (USD)', xLabel: 'API request number', height: 240, label: 'cost per request'})}</div>
      <div class="card"><div class="head"><h2>By turn type</h2></div><table><thead><tr><th>type</th><th class="num">requests</th><th class="num">cost</th><th class="num">share</th></tr></thead><tbody>
      ${byType.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v.requests}</td><td class="num">${money(v.usd)}</td><td class="num">${spent ? (100 * v.usd / spent).toFixed(1) : 0}%</td></tr>`).join('')}</tbody></table></div>`;
  }

  function lfPanel() {
    if (!lf) { $('panel').innerHTML = '<p class="muted">Loading Langfuse…</p>'; return; }
    if (!lf.available) { $('panel').innerHTML = `<div class="warn">Langfuse unavailable: ${esc(lf.error || 'unknown error')}. <button id="lf-retry2">Retry</button></div>`; $('lf-retry2').onclick = () => loadLangfuse(true); return; }
    const obs = lf.observations.filter(o => !obsType || o.type === obsType), maxLat = Math.max(0.001, ...obs.map(o => o.latency_s || 0)), types = [...new Set(lf.observations.map(o => o.type))];
    $('panel').innerHTML = `<div class="card"><div class="head"><h2>Traces (${lf.traces.length})</h2></div><div class="scroll"><table><thead><tr><th>start</th><th>name</th><th class="num">latency</th><th class="num">cost</th><th class="num">gens</th><th class="num">tools</th><th class="num">errors</th><th>models</th><th></th></tr></thead><tbody>
      ${lf.traces.map(x => `<tr><td>${x.start ? new Date(x.start * 1000).toLocaleTimeString() : ''}</td><td>${esc(x.name || x.trace_id.slice(0, 8))}</td><td class="num">${x.latency_s != null ? dur(x.latency_s) : '—'}</td><td class="num">${money(x.cost_usd)}</td><td class="num">${x.generations}</td><td class="num">${x.tools}</td><td class="num">${x.errors || ''}</td><td class="small">${esc(x.models.join(', '))}</td><td>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">open</a>` : ''}</td></tr>`).join('')}</tbody></table></div></div>
      <div class="card"><div class="head"><h2>Observations</h2><span class="hint">type <select id="obs-type"><option value="">all</option>${types.map(x => `<option ${x === obsType ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select> ${obs.length} shown</span></div>
      <div class="scroll"><table><thead><tr><th>start</th><th>type</th><th>name</th><th>model</th><th>latency</th><th class="num">cost</th><th class="num">in / out</th><th class="num">cache r / w</th><th></th></tr></thead><tbody>
      ${obs.map(o => `<tr><td>${o.start ? new Date(o.start * 1000).toLocaleTimeString() : ''}</td><td>${esc(o.type)}${o.level === 'ERROR' ? ' ' + badge('error', 'bad') : ''}</td><td>${esc(o.name)}</td><td class="small">${esc(o.model || '')}</td>
      <td><span class="bars"><span data-width="${(100 * (o.latency_s || 0) / maxLat).toFixed(1)}"></span></span>${o.latency_s ?? '—'}s</td><td class="num">${o.cost_usd != null ? money(o.cost_usd) : ''}</td>
      <td class="num">${o.input_tokens || o.output_tokens ? num(o.input_tokens) + ' / ' + num(o.output_tokens) : ''}</td><td class="num">${o.cache_read_tokens || o.cache_write_tokens ? num(o.cache_read_tokens) + ' / ' + num(o.cache_write_tokens) : ''}</td>
      <td>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">open</a>` : ''}</td></tr>`).join('')}</tbody></table></div></div>`;
    $('obs-type').onchange = e => { obsType = e.target.value; renderPanel(); };
  }

  function folds() {
    const rows = data.controls;
    $('d-events').innerHTML = rows.length ? `<table><thead><tr><th>t</th><th>event</th><th>details</th></tr></thead><tbody>${rows.map(r => `<tr><td>${dur(r.t)}</td><td>${badge(r.kind, r.kind === 'gate' || r.kind === 'cache_alarm' ? 'bad' : r.kind === 'soft_cap' ? 'mid' : '')} ${esc(r.label)}</td><td class="small"><code>${esc(JSON.stringify(r.detail))}</code></td></tr>`).join('')}</tbody></table>` : '<p class="muted">No finish, control or gate events yet.</p>';
    $('d-packet').innerHTML = data.packet ? `<p class="muted small">${num(data.packet.length)} characters</p><pre>${esc(data.packet)}</pre>` : '<p class="muted">No packet.txt in this run.</p>';
  }

  document.addEventListener('click', event => {
    const el = event.target.closest && event.target.closest('[data-cand]');
    const frame = $('graph-frame');
    if (!el || !frame || !frame.contentWindow) return;
    frame.contentWindow.postMessage({type: 'arena-select', id: el.dataset.cand}, location.origin);
    frame.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  });

  const panels = {tools: toolsPanel, ideas: ideasPanel, spend: spendPanel, langfuse: lfPanel};
  function renderPanel() {
    if (!data) return;
    $('tabs').innerHTML = TABS.map(([id, label]) => `<button role="tab" data-tab="${id}" aria-selected="${id === tab}">${label}</button>`).join('');
    $('tabs').querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { selectTab(b.dataset.tab); });
    safely(() => panels[tab]());
    C.mount($('panel')); applyWidths($('panel'));
  }
  function selectTab(id) { tab = id; try { localStorage.setItem('arena-dash-tab', tab); } catch {} renderPanel(); }
  function openTool(k) { selectedTool = k; selectTab('tools'); toolsTimeline(); $('drill').scrollIntoView({behavior: 'smooth', block: 'start'}); }
  function safely(fn) { try { fn(); } catch (error) { console.error(error); } }  // one broken card must never blank the others

  function render() {
    if (!data) return;
    for (const fn of [header, kpis, scoreChart, spendCharts, () => metricChart('c-tokens', 'tokens', data.reference?.tokens, 'tokens', 'k3'),
                      () => metricChart('c-hb', 'heartbeats', data.reference?.heartbeats, 'heartbeats', 'k5'), toolsTimeline, ideasCard, leanCard, lfCard, folds, renderPanel]) safely(fn);
  }

  async function loadLangfuse(refresh = false) {
    try { lf = await (await fetch(`langfuse.json${refresh ? '?refresh=1' : ''}`, {cache: 'no-store'})).json(); }
    catch (e) { lf = {available: false, error: 'viewer server did not answer'}; }
    if (lf.session_url) { $('lf-link').href = lf.session_url; $('lf-link').hidden = false; }
    if (data) { safely(lfCard); if (tab === 'langfuse') renderPanel(); }
  }

  let busy = false, last = '';
  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const r = await fetch('dashboard.json', {cache: 'no-store'});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const text = await r.text();
      data = JSON.parse(text);
      $('live').textContent = `Live · ${new Date().toLocaleTimeString()}`;
      $('live').classList.add('ok');
      if (text !== last) { last = text; render(); }
    } catch (e) {
      $('live').textContent = `Disconnected: ${e.message}`;
      $('live').classList.remove('ok');
    }
    busy = false;
  }
  refresh();
  loadLangfuse();
  setInterval(refresh, 6000);
  setInterval(() => loadLangfuse(), 45000);
})();
