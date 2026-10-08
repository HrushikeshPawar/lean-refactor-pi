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
    if (data.finished) return {text: `done · ${s.stop_reason || 'stopped'}`, kind: s.stop_reason === 'finished' ? 'good' : 'mid'};
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
      ['Cache hit rate', cache.reuse_pct != null ? cache.reuse_pct + '%' : '—', `recent 10: ${cache.reuse_pct_recent_10 ?? '—'}% · cost savings ${cache.savings_pct ?? '—'}%`],
      ['Tool results', num((s.tools || {}).results), `${(s.tools || {}).error_total ?? 0} errors`],
      ['Submission', sub ? `${sub.candidate} · ${sub.proxy}` : 'none', sub ? (sub.verified_by === 'cold compile' ? 'cold-verified' : `verified by ${sub.verified_by || '?'}`) : (data.finished ? 'not submitted' : 'running')]];
    $('kpis').innerHTML = items.map(([l, v, n, good]) => `<div class="kpi" title="${esc(n)}"><div class="l">${esc(l)}</div><div class="v${good ? ' good' : ''}">${esc(v)}</div><div class="n">${esc(n)}</div></div>`).join('');
  }

  /* ---- overview widgets: x is the evaluation number (0 = the original proof) or the API request number ---- */
  const evalEnd = () => Math.max(1, ...data.scores.map(r => r.n || 0));
  const signed = (v, d = 2) => `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(+v.toFixed(d))}`;
  /* A "vs original" delta for a tooltip row; lowerBetter flips which direction is green. */
  const vs = (v, base, lowerBetter, d = 2) => {
    if (v == null || base == null) return {};
    const diff = v - base, better = lowerBetter ? diff < 0 : diff > 0;
    return {delta: `${signed(diff, d)} vs original`, good: diff !== 0 && better, bad: diff !== 0 && !better};
  };
  const evalTip = (r, key, sw) => {
    const ref = data.reference || {}, score = r.proxy ?? r.estimated_proxy, mark = k => k === key ? {sw, bold: true} : {};
    return C.tipCard({title: `Evaluation ${r.n} · candidate ${r.candidate}`, sub: `${r.mode} check${r.compiled === false ? ' · did not compile' : ''} · at ${dur(r.t)}`,
      rows: [{label: r.proxy == null ? 'Fast estimate' : 'Score', value: score == null ? '—' : String(score), ...mark('proxy'), ...vs(score, data.baseline_proxy, false)},
             {label: 'Tokens', value: num(r.tokens), ...mark('tokens'), ...vs(r.tokens, ref.tokens, true, 0)},
             {label: 'Heartbeats', value: num(r.heartbeats), ...mark('heartbeats'), ...vs(r.heartbeats, ref.heartbeats, true, 0)}],
      foot: 'click to select this candidate in the graph'});
  };
  const origTip = (label, value) => C.tipCard({title: 'Original proof · evaluation 0', rows: [{sw: 'korig', label, value: String(value), bold: true}], foot: 'the proof the run started from'});

  function scoreHtml(spark) {
    const rows = data.scores, full = rows.filter(r => r.mode === 'full' && r.proxy != null), fast = rows.filter(r => r.mode !== 'full' && r.estimated_proxy != null), end = evalEnd();
    const bestFull = full.reduce((m, r) => !m || r.proxy > m.proxy ? r : m, null);
    const ptF = r => [r.n, r.proxy, evalTip(r, 'proxy', 'k0'), r.candidate_id];
    const ptE = r => [r.n, r.estimated_proxy, evalTip(r, 'proxy', 'k2'), r.candidate_id];
    return C.line([
      {cls: 'k1', step: true, dots: false, points: [[0, data.baseline_proxy], ...rows.filter(r => r.best_verified != null).map(r => [r.n, r.best_verified])]},
      {cls: 'korig', noLine: true, r: 6, points: [[0, data.baseline_proxy, origTip('Score', data.baseline_proxy)]]},
      {cls: 'k0', noLine: true, r: 5, points: full.map(ptF)},
      {cls: 'k2', noLine: true, hollow: true, r: 4, points: fast.map(ptE)}],
      {refs: [{y: data.baseline_proxy, cls: 'base', label: ''}], pointLabels: [{x: 0, y: data.baseline_proxy, text: `original ${data.baseline_proxy}`, dy: -12}],
       extendTo: end, xMin: 0, xMax: end, xTime: false, intX: true, better: 'max', yMax: 100, yMin: 0, height: spark ? 64 : 360, spark,
       fmtY: C.fmt.score, yLabel: 'proxy score (0 to 100)', xLabel: 'evaluation number (0 = original proof)',
       best: bestFull && {x: bestFull.n, y: bestFull.proxy, text: `best ${bestFull.proxy} (${bestFull.candidate})`},
       legend: [['korig', 'original proof (evaluation 0)'], ['k0', 'full evaluation, all versions checked'], ['k2', 'fast estimate (hollow)'], ['k1', 'best verified so far']], label: 'score by evaluation'});
  }

  const PARTS = [['cache_read', 'Cache read', 'cp0'], ['input', 'Input', 'cp1'], ['cache_write', 'Cache write', 'cp2'], ['output', 'Output', 'cp3']];
  const sumParts = obj => PARTS.reduce((a, [k]) => a + (obj[k] || 0), 0);

  function spendHtml(spark) {
    const sp = data.spend, pts = sp.points;
    const sums = Object.fromEntries(PARTS.map(([k]) => [k, 0])), area = [{x: 0, parts: PARTS.map(() => 0)}];
    for (const p of pts) {
      for (const [k] of PARTS) sums[k] += p.parts[k] || 0;
      const tools = (p.tools || []).map(n => n.replace(/^arena_/, ''));
      area.push({x: p.n, parts: PARTS.map(([k]) => sums[k]), tip: C.tipCard({
        title: `Request #${p.n}${p.kind ? ` · ${p.kind} turn` : ''}`, sub: `at ${dur(p.t)} · ${num(p.tokens?.output)} output tokens`,
        table: {head: ['', 'this request', 'running total'], rows: [...PARTS.slice().reverse().map(([k, label, cls]) => ({sw: cls, label, cells: [money(p.parts[k] || 0), money(sums[k])]})),
                {sw: 'toptot', label: 'Total', bold: true, cells: [money(p.request_usd), money(sumParts(sums))]}]},
        foot: `cache hit rate ${p.reuse_pct ?? '—'}%${tools.length ? ` · ${tools.slice(0, 3).join(', ')}${tools.length > 3 ? ` +${tools.length - 3}` : ''}` : ''}`})});
    }
    const grand = sumParts(sums), top = Math.max(grand, sp.soft_cap_usd || 0, 1e-9);
    const hardVisible = !!sp.hard_cap_usd && sp.hard_cap_usd <= 2.5 * top;
    const refs = [], notes = [];
    if (sp.soft_cap_usd) refs.push({y: sp.soft_cap_usd, cls: 'soft', label: 'soft cap ' + money(sp.soft_cap_usd)});
    if (hardVisible) refs.push({y: sp.hard_cap_usd, cls: 'hard', label: 'hard cap ' + money(sp.hard_cap_usd)});
    else if (sp.hard_cap_usd && !spark) notes.push({cls: 'hard', text: `hard cap ${money(sp.hard_cap_usd)} is off scale`});
    const legend = [['toptot', `Total ${money(grand)}`], ...PARTS.slice().reverse().map(([k, label, cls]) => [cls, `${label} ${money(sums[k])}${grand ? ` (${(100 * sums[k] / grand).toFixed(0)}%)` : ''}`])];
    return C.area(area, PARTS.map(([, label, cls]) => ({cls, label})),
      {refs, notes, xMin: 0, xMax: Math.max(1, pts.length), yMin: 0, yMax: hardVisible && !spark ? sp.hard_cap_usd * 1.08 : top * 1.15, exact: true, height: spark ? 64 : 360, spark,
       fmtY: C.fmt.money, yLabel: 'cumulative spend (USD)', xLabel: 'API request number', legend, label: 'API spend by component'});
  }

  function metricHtml(key, ref, unit, cls, spark) {
    const ok = data.scores.filter(r => r.compiled && r[key] != null), end = evalEnd();
    // The original proof is evaluation 0, so the best-so-far line starts from it.
    let low = ref ?? Infinity; const steps = ref != null ? [[0, ref]] : [];
    for (const r of ok) { low = Math.min(low, r[key]); steps.push([r.n, low]); }
    const lowest = ok.reduce((m, r) => !m || r[key] < m[key] ? r : m, null);
    const pt = r => [r.n, r[key], evalTip(r, key, cls), r.candidate_id];
    return C.line([
      {cls, step: true, dots: false, points: steps},
      {cls: 'korig', noLine: true, r: 6, points: ref != null ? [[0, ref, origTip(unit[0].toUpperCase() + unit.slice(1), num(ref))]] : []},
      {cls, noLine: true, r: 4, points: ok.filter(r => r.mode === 'full').map(pt)},
      {cls, noLine: true, r: 4, hollow: true, points: ok.filter(r => r.mode !== 'full').map(pt)}],
      {refs: ref != null ? [{y: ref, cls: 'base', label: ''}] : [], pointLabels: ref != null ? [{x: 0, y: ref, text: `original ${num(ref)}`, dy: 24}] : [],
       includeRefs: true, extendTo: end, xMin: 0, xMax: end, xTime: false, intX: true, better: 'min', yMin: 0, height: spark ? 64 : 360, spark, fmtY: C.fmt.num,
       yLabel: unit, xLabel: 'evaluation number (0 = original proof)', best: lowest && {below: true, x: lowest.n, y: lowest[key], text: `${num(lowest[key])} (${lowest.candidate})`},
       legend: [['korig', 'original proof'], [cls, 'full evaluation (hollow = fast)']], label: unit});
  }

  /* Each widget: headline for the card, the sparkline, the full chart and a data table for the modal. */
  function widgetInfo(k) {
    const ref = data.reference || {}, rows = data.scores, sp = data.spend;
    const pctOf = (v, base) => base ? `${v <= base ? '−' : '+'}${Math.abs(100 * (v - base) / base).toFixed(0)}%` : '';
    if (k === 'score') {
      const full = rows.filter(r => r.mode === 'full' && r.proxy != null), best = Math.max(data.baseline_proxy ?? 0, ...full.map(r => r.proxy));
      return {title: 'Score', value: String(best), sub: `${signed(best - data.baseline_proxy)} vs original ${data.baseline_proxy} · ${rows.length} evaluations`, good: best > data.baseline_proxy, spark: scoreHtml(true), full: scoreHtml(false),
              sup: 'best so far', modalSub: 'proxy 0 to 100, higher is better; evaluation 0 is the original proof. Click a point or row to select that candidate in the graph.', table: evalTable('proxy')};
    }
    if (k === 'tokens' || k === 'hb') {
      const key = k === 'tokens' ? 'tokens' : 'heartbeats', base = ref[key], ok = rows.filter(r => r.compiled && r[key] != null), low = Math.min(base ?? Infinity, ...ok.map(r => r[key]));
      return {title: k === 'tokens' ? 'Tokens' : 'Heartbeats', value: isFinite(low) ? num(low) : '—', sub: `${base != null && isFinite(low) ? `${pctOf(low, base)} vs original ${num(base)}` : 'no original'} · lower is better`, good: base != null && low < base,
              spark: metricHtml(key, base, key, k === 'tokens' ? 'k3' : 'k5', true), full: metricHtml(key, base, key, k === 'tokens' ? 'k3' : 'k5', false), sup: 'lowest so far',
              modalSub: `${key} per evaluation that compiled; lower is better. Click a point or row to select that candidate in the graph.`, table: evalTable(key)};
    }
    const soft = sp.soft_cap_usd;
    return {title: 'API spend', value: money(sp.spent_usd), sub: `${soft ? `${(100 * sp.spent_usd / soft).toFixed(0)}% of soft cap ${money(soft)}` : 'no soft cap'} · ${sp.points.length} requests`, good: false, sup: 'total',
            spark: spendHtml(true), full: spendHtml(false), modalSub: `${money(sp.spent_usd)} settled · ${money(sp.unresolved_usd)} reserved · cumulative, stacked by billed component`, table: spendTable()};
  }
  const WIDGETS = ['score', 'tokens', 'hb', 'spend'];
  function widgets() {
    $('widgets').innerHTML = WIDGETS.map(k => { const w = widgetInfo(k);
      return `<button type="button" class="widget" data-w="${k}" aria-label="Open the ${esc(w.title)} chart"><div class="w-head"><span class="w-title">${esc(w.title)}</span><span class="w-open" aria-hidden="true">&#10530;</span></div>
        <div class="w-val${w.good ? ' good' : ''}">${esc(w.value)} <span class="w-sup">${esc(w.sup)}</span></div><div class="w-sub">${esc(w.sub)}</div><div class="w-chart">${w.spark}</div></button>`; }).join('');
    C.mount($('widgets'));
    $('widgets').querySelectorAll('[data-w]').forEach(el => el.onclick = () => openModal(el.dataset.w));
  }

  /* ---- modal with the full chart and its data table ---- */
  let modalKey = null;
  function evalTable(key) {
    const ref = data.reference || {}, rows = data.scores.filter(r => key === 'proxy' ? true : r.compiled && r[key] != null);
    const cell = (v, base, lower, d) => v == null ? '—' : `${num(v, d)}${base != null ? ` <span class="${(lower ? v < base : v > base) ? 'good' : v === base ? 'muted' : 'bad'}">${signed(v - base, d)}</span>` : ''}`;
    return `<table><thead><tr><th class="num">#</th><th>candidate</th><th>mode</th><th class="num">score</th><th class="num">tokens</th><th class="num">heartbeats</th><th>compiled</th><th class="num">at</th></tr></thead><tbody>
      <tr><td class="num">0</td><td>original proof</td><td>reference</td><td class="num">${num(data.baseline_proxy, 2)}</td><td class="num">${num(ref.tokens)}</td><td class="num">${num(ref.heartbeats)}</td><td></td><td></td></tr>
      ${rows.map(r => { const v = r.proxy ?? r.estimated_proxy; return `<tr class="click" data-cand="${esc(r.candidate_id)}"><td class="num">${r.n}</td><td>${esc(r.candidate)}</td><td>${esc(r.mode)}</td><td class="num">${v == null ? '—' : cell(v, data.baseline_proxy, false, 2)}${r.proxy == null && v != null ? ' <span class="muted">est.</span>' : ''}</td>
        <td class="num">${cell(r.tokens, ref.tokens, true, 0)}</td><td class="num">${cell(r.heartbeats, ref.heartbeats, true, 0)}</td><td>${r.compiled ? 'yes' : badge('no', 'bad')}</td><td class="num">${dur(r.t)}</td></tr>`; }).join('')}</tbody></table>`;
  }
  function spendTable() {
    const pts = data.spend.points;
    return `<table><thead><tr><th class="num">#</th><th>kind</th><th class="num">at</th><th class="num">this request</th><th class="num">running total</th>${PARTS.slice().reverse().map(([, l, c]) => `<th class="num"><i class="sw box ${c}"></i>${l}</th>`).join('')}<th class="num">cache hit rate</th><th>tools</th></tr></thead><tbody>
      ${pts.map(p => `<tr><td class="num">${p.n}</td><td>${esc(p.kind || '')}</td><td class="num">${dur(p.t)}</td><td class="num"><b>${money(p.request_usd)}</b></td><td class="num">${money(p.spent_usd)}</td>${PARTS.slice().reverse().map(([k]) => `<td class="num">${money(p.parts[k] || 0)}</td>`).join('')}<td class="num">${p.reuse_pct ?? '—'}%</td><td class="small muted">${esc((p.tools || []).map(n => n.replace(/^arena_/, '')).join(', '))}</td></tr>`).join('')}</tbody></table>`;
  }
  function renderModal() {
    if (!modalKey || !data) return;
    const w = widgetInfo(modalKey), body = $('modal-body');
    $('modal-title').textContent = w.title === 'API spend' ? 'API spend by component' : `${w.title} by evaluation`;
    $('modal-sub').textContent = w.modalSub;
    const scroll = body.querySelector('.scroll'), top = scroll ? scroll.scrollTop : 0;
    body.innerHTML = `${w.full}<div class="scroll modal-table">${w.table}</div>`;
    C.mount(body);
    const fresh = body.querySelector('.scroll'); if (fresh) fresh.scrollTop = top;
  }
  function openModal(key) { modalKey = key; $('modal').hidden = false; renderModal(); $('modal-close').focus(); }
  function closeModal() { modalKey = null; $('modal').hidden = true; $('modal-body').innerHTML = ''; }
  $('modal-close').onclick = closeModal;
  $('modal').addEventListener('mousedown', e => { if (e.target === $('modal')) closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && modalKey) closeModal(); });

  /* ---- tool activity: tall rows filling the card, rich tooltips ---- */
  const argSummary = t => {
    let text = String(t.args ?? '');
    try { const o = JSON.parse(text); if (o && typeof o === 'object') text = Object.entries(o).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', '); } catch {}
    return text.length > 150 ? text.slice(0, 149) + '…' : text;
  };
  function toolsTimeline() {
    const all = data.tools;
    if (!all.length) return place('c-tools', '<p class="muted">No tool calls yet.</p>');
    const short = n => String(n).replace(/^mcp__arena_/, '').replace(/^arena_/, '');
    const counts = new Map(), errs = new Map(); all.forEach(t => { counts.set(t.name, (counts.get(t.name) || 0) + 1); if (t.is_error) errs.set(t.name, (errs.get(t.name) || 0) + 1); });
    const names = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
    const shown = names.slice(0, 13), rowOf = t => { const i = shown.indexOf(t.name); return i < 0 ? shown.length : i; };
    const rows = shown.map(n => [short(n), counts.get(n), errs.get(n) || 0]);
    if (names.length > shown.length) rows.push(['other', names.slice(shown.length).reduce((a, n) => a + counts.get(n), 0), 0]);
    const end = Math.max(1, ...data.tools.map(t => t.t_end || 0));
    const mount = C.box((w, hh) => {
      const left = 190, foot = 40, avail = Math.max(260, hh || 440) - foot, rowH = Math.max(24, Math.min(84, avail / rows.length)), plotH = rows.length * rowH, h = plotH + foot, sx = v => left + v / end * (w - left - 14);
      const barH = Math.min(28, rowH - 8);
      let g = '';
      rows.forEach(([name, n, e], i) => g += `<rect class="rowband${i % 2 ? ' odd' : ''}" x="0" y="${i * rowH}" width="${w}" height="${rowH}"/><text class="gname" x="6" y="${i * rowH + rowH / 2 + 4}">${esc(name.length > 24 ? name.slice(0, 23) + '…' : name)} <tspan class="tick">×${n}</tspan>${e ? ` <tspan class="errn">${e} err</tspan>` : ''}</text>`);
      for (const v of C.timeTicks(0, end, Math.max(4, Math.floor((w - left) / 90)))) g += `<line class="vgrid" x1="${sx(v)}" x2="${sx(v)}" y1="0" y2="${plotH}"/><text class="tick" x="${sx(v)}" y="${plotH + 16}" text-anchor="middle">${C.tickTime(Math.round(v))}</text>`;
      g += `<text class="axtitle" x="${(left + w) / 2}" y="${h - 4}" text-anchor="middle">time since run start</text>`;
      all.forEach((t, k) => {
        const x = sx(t.t || 0), bw = Math.max(4, sx(t.t_end || 0) - x);
        const tip = C.tipCard({title: short(t.name), sub: t.is_error ? 'ended in an error' : t.running ? 'still running' : 'completed ok',
          rows: [{sw: toolClass(t.name) + (t.is_error ? ' errsw' : ''), label: 'Start', value: `${dur(t.t)} into the run`}, {label: 'Duration', value: t.running ? 'running' : `${t.duration_s}s`, bold: true},
                 {label: 'Status', value: t.is_error ? 'error' : t.running ? 'running' : 'ok', ...(t.is_error ? {bad: true} : {good: !t.running})},
                 ...(argSummary(t) ? [{label: 'Args', value: argSummary(t), wrap: true}] : []),
                 ...(t.is_error && t.result ? [{label: 'Result', value: String(t.result).slice(0, 160), wrap: true, bad: true}] : [])], foot: 'click for arguments and result'});
        g += `<rect class="gbar ${toolClass(t.name)}${t.is_error ? ' err' : ''}${selectedTool === k ? ' sel' : ''}" data-tool="${k}" x="${x}" y="${rowOf(t) * rowH + (rowH - barH) / 2}" width="${bw}" height="${barH}" rx="3" data-tip="${esc(tip)}"/>`;
      });
      return `<svg class="gantt" width="${w}" height="${h}" role="img" aria-label="tool activity timeline">${g}</svg>`;
    }, 'fill');
    place('c-tools', mount);
  }
  $('c-tools').addEventListener('click', e => { const bar = e.target.closest('[data-tool]'); if (bar) openTool(+bar.dataset.tool); });

  function ideasCard() {
    const ideas = data.ideas, kind = s => s === 'succeeded' ? 'good' : s === 'failed' || s === 'abandoned' ? 'bad' : 'mid';
    $('h-ideas').textContent = `${ideas.length} idea${ideas.length === 1 ? '' : 's'}`;
    const routes = (data.routes || []).filter(r => r.attempts || r.original);
    const routeHtml = routes.length ? `<div class="idea"><div class="t">Routes (harness fingerprints)</div>${routes.map(r => `<div class="small muted">${esc(r.route)} ${esc(r.label)}${r.original ? ' · original proof' : ''} · ${r.attempts} attempt${r.attempts === 1 ? '' : 's'} · ${r.depth ?? 0} goal state${r.depth === 1 ? '' : 's'}${r.min_holes != null ? ` · min holes ${r.min_holes}` : ''}${r.stale_streak ? ` · stale streak ${r.stale_streak}` : ''} · ${r.explored ? 'explored' : 'opened'}${r.credited ? ` · credited${r.skeleton ? ' (skeleton)' : ''}` : ''} · best proxy ${r.best_proxy ?? '—'}</div>`).join('')}</div>` : '';
    place('c-ideas', routeHtml + (ideas.length ? ideas.map(i => `<div class="idea"><div class="t">${esc(i.title || i.id)} ${badge(i.status || '?', kind(i.status))}</div>
      <div class="small muted">${i.attempts.length} attempt${i.attempts.length === 1 ? '' : 's'} · ${i.probes} probe${i.probes === 1 ? '' : 's'} · best proxy ${i.best_proxy ?? '—'}${i.attempts.length ? ' · ' + esc(i.attempts.map(a => a.candidate).join(', ')) : ''}</div></div>`).join('') : '<p class="muted">No ideas recorded.</p>'));
  }

  function leanCard() {
    const mix = data.lean, paths = Object.entries(mix.paths), total = paths.reduce((a, [, v]) => a + v.runs, 0), cold = mix.cold_verification;
    const compile = total ? `<div class="line1"><span class="lbl">Compiles</span><div class="stack">${paths.map(([k, v], i) => `<span class="k${i}" data-width="${(100 * v.runs / total).toFixed(1)}" title="${esc(k)} ${v.runs}"></span>`).join('')}</div>
      <span class="small">${paths.map(([k, v]) => `${esc(k)} ${v.runs} · ${v.seconds}s`).join(' · ')}</span></div>` : '<div class="line1 muted">No Lean runs recorded.</div>';
    const versions = cold ? `<div class="line1"><span class="lbl">Cold</span>${cold.confirmed ? badge('confirmed', 'good') : badge('not confirmed', 'bad')}${Object.entries(cold.passed || {}).map(([k, v]) => badge(`${k} ${v ? '✓' : '✗'}`, v ? 'good' : 'bad')).join('')}</div>
      <div class="line1"><span class="lbl">Heartbeats</span><span>recorded ${num(cold.recorded_heartbeats)} · cold ${num(cold.cold_heartbeats)}</span>${cold.recorded_heartbeats === cold.cold_heartbeats ? badge('match', 'good') : badge('differ', 'mid')}</div>` : '<div class="line1"><span class="lbl">Cold</span><span class="muted">not run yet</span></div>';
    place('c-lean', `${compile}${versions}${data.submission ? `<div class="line1 small muted">Submission ${esc(data.submission.candidate)}: proxy ${esc(data.submission.proxy)}, ${esc(data.submission.tokens)} tok / ${esc(data.submission.heartbeats)} hb, ${esc(data.submission.verified_by)}</div>` : ''}`);
  }

  function lfCard() {
    if (!lf) return place('c-lf', '<p class="muted">Loading Langfuse…</p>');
    if (!lf.available) return place('c-lf', `<div class="warn">Langfuse unavailable: ${esc(lf.error || 'unknown error')}. <button id="lf-retry">Retry</button></div>`), ($('lf-retry').onclick = () => loadLangfuse(true));
    const t = lf.totals, ledger = data.spend.spent_usd, diff = t.cost_usd - ledger, ok = Math.abs(diff) <= Math.max(0.0005, 0.02 * ledger);
    $('h-lf').innerHTML = lf.session_url ? `<a href="${esc(lf.session_url)}" target="_blank" rel="noopener">session &#8599;</a>` : 'no project link';
    const gens = lf.observations.filter(o => o.type === 'GENERATION').map((o, i) => [i + 1, o.latency_s, C.tipCard({title: `Generation #${i + 1}`, sub: o.name, rows: [{sw: 'k5', label: 'Latency', value: `${o.latency_s} s`, bold: true}, ...(o.cost_usd != null ? [{label: 'Cost', value: money(o.cost_usd)}] : [])]})]).filter(g => g[1] != null);
    const slowest = gens.reduce((m, g) => !m || g[1] > m[1] ? g : m, null);
    place('c-lf', `${lf.stale ? `<div class="warn">Cached data; refresh failed: ${esc(lf.error)}</div>` : ''}
      <div class="mini"><div><div class="l">Traces</div><div class="v">${lf.traces.length}</div></div><div><div class="l">Generations</div><div class="v">${t.generations}</div></div>
      <div><div class="l">Mean latency</div><div class="v">${t.mean_generation_latency_s ?? '—'}s</div></div><div><div class="l">Errors</div><div class="v">${t.errors}</div></div></div>
      <div class="line1"><span class="lbl">Cost</span><span>${money(t.cost_usd)}</span>${ok ? badge('matches ledger', 'good') : badge(`ledger ${money(ledger)}, differs ${money(Math.abs(diff))}`, 'mid')}</div>
      ${C.line([{cls: 'k5', points: gens}], {xMin: 0, xTime: false, fmtY: C.fmt.sec, yLabel: '', xLabel: 'generation #', height: 118, yTicks: 3, better: 'min',
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
    $('panel').innerHTML = `<div class="grid2"><div class="card"><div class="head"><h2>Cache tokens per request</h2><span class="hint">overall hit rate ${cache.reuse_pct ?? '—'}% · read ${num(cache.read_tokens)} / write ${num(cache.write_tokens)} · alarms ${cache.alarms ?? 0}</span></div>
      ${C.stacked(pts.map(p => ({parts: [p.tokens.cache_read || 0, p.tokens.cache_write || 0], title: `#${p.n}: read ${num(p.tokens.cache_read)}, write ${num(p.tokens.cache_write)}, reuse ${p.reuse_pct ?? '—'}%`})),
        [{cls: 'k2', label: 'cache read'}, {cls: 'k3', label: 'cache write'}], {fmtY: C.fmt.num, yLabel: 'tokens per request', height: 260, label: 'cache tokens'})}</div>
      <div class="card"><div class="head"><h2>Cache hit rate per request</h2><span class="hint">cache read over all prompt tokens; low after the first requests means the prompt prefix is not reused</span></div>
      ${C.line([{cls: 'k1', points: pts.filter(p => p.reuse_pct != null).map(p => [p.n, p.reuse_pct, `request #${p.n}: ${p.reuse_pct}% of prompt tokens were cache reads`])}], {yMin: 0, yMax: 100, exact: true, xTime: false, xMin: 0, xMax: Math.max(1, pts.length), fmtY: C.fmt.pct, yLabel: 'cache hit rate (%)', xLabel: 'request #', height: 260, label: 'cache hit rate'})}</div></div>
      <div class="card"><div class="head"><h2>Cost per request</h2><span class="hint">each request's own cost by billed component; the overview chart shows the running total</span></div>
      ${C.stacked(pts.map(p => ({parts: PARTS.map(([k]) => p.parts[k] || 0), title: `#${p.n} ${p.kind || ''}: ${money(p.request_usd)}\ncache hit rate ${p.reuse_pct ?? '—'}%\n${(p.tools || []).join(', ')}`})),
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
    if (modalKey) closeModal();
    frame.contentWindow.postMessage({type: 'arena-select', id: el.dataset.cand}, location.origin);
    frame.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  });

  // The graph (an iframe) asks to be brought fully into view before it opens a detail modal.
  addEventListener('message', e => { if (e.origin === location.origin && e.data && e.data.type === 'arena-focus') $('graph-frame').scrollIntoView({behavior: 'instant', block: 'center'}); });

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
    for (const fn of [header, kpis, widgets, toolsTimeline, ideasCard, leanCard, lfCard, folds, renderPanel, renderModal]) safely(fn);
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
