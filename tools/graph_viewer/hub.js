/* Arena run hub: a filterable, sortable table of every run plus one tab per run with its dashboard. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = v => v == null ? '—' : '$' + (v >= 0.1 ? v.toFixed(3) : v.toFixed(4));
  const shortTheorem = name => String(name || '—').split('.').slice(-1)[0];
  const frames = new Map();
  let runs = [], active = null;
  const saved = (() => { try { return JSON.parse(localStorage.getItem('arena-hub-view') || '{}'); } catch { return {}; } })();
  const view = {text: '', theorem: '', model: '', campaign: '', status: '', group: false, sort: 'started', dir: 'desc', collapsed: [], ...saved};
  const save = () => { try { localStorage.setItem('arena-hub-view', JSON.stringify(view)); } catch {} };

  const dur = s => s == null ? '—' : s >= 3600 ? `${Math.floor(s / 3600)}h ${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}m` : s >= 60 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, '0')}s` : `${Math.round(s)}s`;
  const when = ts => ts ? new Date(ts * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';
  const pct = v => v == null ? '—' : v.toFixed(1) + '%';

  function delta(value, base, lower) {
    if (value == null) return '—';
    if (base == null) return esc(value);
    const change = value - base, better = lower ? change < 0 : change > 0;
    if (!change) return `${esc(value)} <span class="muted">=</span>`;
    const amount = Number.isInteger(change) ? Math.abs(change) : Math.abs(change).toFixed(2);
    const shown = Number.isInteger(value) ? value : value.toFixed(2);
    return `${esc(shown)} <span class="${better ? 'up' : 'down'}">${change < 0 ? '↓' : '↑'}${esc(amount)}</span>`;
  }
  function title(run) {
    const model = run.model || run.run_id;
    const suffix = (run.run_id.match(/-(r\d+)$/) || [])[1];
    return suffix ? `${model} · ${suffix}` : model;
  }
  const statusText = run => run.status === 'finished' ? `done · ${run.stop_reason || 'stopped'}` : run.status;
  const capShare = run => run.soft_cap_usd ? run.spent_usd / run.soft_cap_usd : null;

  // Column definitions: label, numeric?, sort value, cell html.
  const COLS = [
    {k: 'run', label: 'Run', v: r => r.run_id, h: r => `<span class="dot ${r.status}"></span>${esc(title(r))}`},
    {k: 'campaign', label: 'Campaign', v: r => r.campaign || '', h: r => esc(r.campaign || '—')},
    {k: 'theorem', label: 'Theorem', v: r => shortTheorem(r.theorem), h: r => `<span title="${esc(r.theorem)}">${esc(shortTheorem(r.theorem))}</span>`},
    {k: 'model', label: 'Model', v: r => r.model || '', h: r => esc(r.model || '—')},
    {k: 'thinking', label: 'Thinking', v: r => r.thinking || '', h: r => esc(r.thinking || '—')},
    {k: 'status', label: 'Status', v: r => statusText(r), h: r => {
      const kind = r.status === 'live' ? 'good' : r.status === 'stalled' ? 'bad' : r.stop_reason === 'finished' ? 'good' : r.stop_reason ? 'mid' : '';
      return `<span class="badge ${kind}">${esc(statusText(r))}</span>`; }},
    {k: 'proxy', num: true, label: 'Best proxy (Δ)', v: r => r.best?.proxy ?? -1, h: (r, top) => r.best?.proxy == null ? '—' :
      `<span class="${top ? 'best' : ''}">${r.best.proxy.toFixed(2)}</span> <span class="${r.delta_proxy >= 0 ? 'up' : 'down'}">${r.delta_proxy >= 0 ? '+' : ''}${r.delta_proxy}</span> <span class="muted">${esc(r.best.candidate || '')}</span>`},
    {k: 'tokens', num: true, label: 'Tokens', v: r => r.best?.tokens ?? 1e9, h: r => delta(r.best?.tokens, r.reference?.tokens, true)},
    {k: 'heartbeats', num: true, label: 'Heartbeats', v: r => r.best?.heartbeats ?? 1e9, h: r => delta(r.best?.heartbeats, r.reference?.heartbeats, true)},
    {k: 'submission', label: 'Submission', v: r => r.submission_info?.cold_verified ? 2 : r.submission ? 1 : 0, h: r =>
      r.submission_info?.cold_verified ? `<span class="badge good" title="cold-verified">✓ ${esc(r.submission)}</span>` : r.submission ? `<span class="badge mid">${esc(r.submission)} unverified</span>` : '<span class="muted">—</span>'},
    {k: 'spend', num: true, label: 'Spend / soft cap', v: r => r.spent_usd, h: r => {
      const share = capShare(r), kind = share > 1 ? ' over' : share > 0.8 ? ' warn' : '';
      return `<span class="bar${kind}" title="soft cap ${money(r.soft_cap_usd)}; hard cap ${money(r.hard_cap_usd)}"><span data-width="${Math.min(100, 100 * (share || 0)).toFixed(1)}"></span></span>${money(r.spent_usd)} / ${money(r.soft_cap_usd)}`; }},
    {k: 'requests', num: true, label: 'Requests', v: r => r.requests, h: r => esc(r.requests ?? '—')},
    {k: 'tools', num: true, label: 'Tool results', v: r => r.tool_results ?? -1, h: r => esc(r.tool_results ?? '—')},
    {k: 'errors', num: true, label: 'Tool errors', v: r => r.tool_errors ?? -1, h: r => r.tool_errors ? `<span class="down">${r.tool_errors}</span>` : esc(r.tool_errors ?? '—')},
    {k: 'cache', num: true, label: 'Cache reuse', v: r => r.cache_reuse_pct ?? -1, h: r => pct(r.cache_reuse_pct)},
    {k: 'book', num: true, label: 'Bookkeep+rejected', v: r => r.bookkeeping_pct ?? -1, h: r => pct(r.bookkeeping_pct)},
    {k: 'postbest', num: true, label: 'Post-best spend', v: r => r.spent_after_best_usd ?? -1, h: r => r.spent_after_best_usd == null ? '—' : `${money(r.spent_after_best_usd)} <span class="muted">${r.requests_after_best ?? ''}req</span>`},
    {k: 'started', label: 'Started', v: r => r.started ?? 0, h: r => when(r.started)},
    {k: 'duration', num: true, label: 'Duration', v: r => r.duration_s ?? -1, h: r => dur(r.duration_s)},
    {k: 'langfuse', label: 'Langfuse', v: r => r.langfuse_url ? 1 : 0, h: r => r.langfuse_url ? `<a class="lf" href="${esc(r.langfuse_url)}" target="_blank" rel="noopener">session ↗</a>` : '<span class="muted">—</span>'},
  ];

  function renderTabs() {
    const tabs = [`<button class="tab" role="tab" data-tab="overview" aria-selected="${active === 'overview'}">
      <span class="tab-title">Runs</span><span class="tab-meta">${runs.length} run${runs.length === 1 ? '' : 's'}</span></button>`];
    for (const run of runs) {
      tabs.push(`<button class="tab" role="tab" data-tab="${esc(run.run_id)}" aria-selected="${active === run.run_id}" title="${esc(run.run_id)}">
        <span class="tab-title"><span class="dot ${run.status}"></span>${esc(title(run))}</span>
        <span class="tab-meta">${esc(shortTheorem(run.theorem))} · ${run.best?.proxy != null ? run.best.proxy.toFixed(2) : '—'} · ${esc(money(run.spent_usd))}</span></button>`);
    }
    $('tabs').innerHTML = tabs.join('');
    $('tabs').querySelectorAll('[data-tab]').forEach(button => button.onclick = () => open(button.dataset.tab));
  }

  function fillSelect(id, label, values) {
    const select = $(id), current = view[id.slice(2)];
    select.innerHTML = `<option value="">${label}</option>` + [...new Set(values.filter(Boolean))].sort().map(v => `<option ${v === current ? 'selected' : ''} value="${esc(v)}">${esc(id === 'f-theorem' ? shortTheorem(v) : v)}</option>`).join('');
  }
  function matches(run) {
    const hay = [run.run_id, run.theorem, run.model, run.campaign, run.thinking].join(' ').toLowerCase();
    return (!view.text || view.text.toLowerCase().split(/\s+/).every(w => hay.includes(w))) &&
      (!view.theorem || run.theorem === view.theorem) && (!view.model || run.model === view.model) &&
      (!view.campaign || run.campaign === view.campaign) && (!view.status || run.status === view.status);
  }

  function strip(list) {
    const best = new Map();
    for (const r of runs) if (r.best?.proxy != null && r.best.proxy > (best.get(r.theorem)?.best.proxy ?? -1)) best.set(r.theorem, r);
    const spend = list.reduce((a, r) => a + (r.spent_usd || 0), 0);
    const chips = [['Runs', `${list.length}${list.length !== runs.length ? ` of ${runs.length}` : ''}`], ['Live', list.filter(r => r.status === 'live').length],
      ['Finished', list.filter(r => r.status === 'finished').length], ['Total spend', money(spend)],
      ['Tool errors', list.reduce((a, r) => a + (r.tool_errors || 0), 0)]]
      .map(([l, v]) => `<div class="chip"><div class="l">${l}</div><div class="v">${esc(v)}</div></div>`);
    for (const [theorem, r] of best) chips.push(`<div class="chip best" title="${esc(r.run_id)}"><div class="l">Best · ${esc(shortTheorem(theorem))}</div><div class="v">${r.best.proxy.toFixed(2)} <span class="muted">${esc(r.model)}</span></div></div>`);
    $('strip').innerHTML = chips.join('');
  }

  function renderOverview() {
    const topByTheorem = new Map();
    for (const run of runs) if (run.best?.proxy != null && run.best.proxy > (topByTheorem.get(run.theorem) ?? -Infinity)) topByTheorem.set(run.theorem, run.best.proxy);
    fillSelect('f-theorem', 'any theorem', runs.map(r => r.theorem));
    fillSelect('f-model', 'any model', runs.map(r => r.model));
    fillSelect('f-campaign', 'any campaign', runs.map(r => r.campaign));
    $('f-status').value = view.status; $('f-group').checked = view.group;
    if (document.activeElement !== $('f-text')) $('f-text').value = view.text;
    const list = runs.filter(matches);
    $('f-count').textContent = `${list.length} shown`;
    strip(list);
    const col = COLS.find(c => c.k === view.sort) || COLS.find(c => c.k === 'started');
    const sign = view.dir === 'asc' ? 1 : -1;
    const cmp = (a, b) => { const x = col.v(a), y = col.v(b); return sign * (typeof x === 'string' ? x.localeCompare(y) : x - y); };
    $('thead').innerHTML = '<tr>' + COLS.map(c => `<th data-sort="${c.k}" class="${c.num ? 'num' : ''}"${c.k === col.k ? ` aria-sort="${view.dir === 'asc' ? 'ascending' : 'descending'}"` : ''}>${c.label}</th>`).join('') + '</tr>';
    $('thead').querySelectorAll('[data-sort]').forEach(th => th.onclick = () => {
      view.dir = view.sort === th.dataset.sort && view.dir === 'desc' ? 'asc' : 'desc'; view.sort = th.dataset.sort; save(); renderOverview(); });
    const rowHtml = run => {
      const top = run.best?.proxy != null && run.best.proxy === topByTheorem.get(run.theorem);
      return `<tr class="run${top ? ' top' : ''}" data-run="${esc(run.run_id)}" title="${esc(run.run_id)}${top ? ' — best for this theorem' : ''}">` +
        COLS.map(c => `<td class="${c.num ? 'num' : ''}">${c.h(run, top)}</td>`).join('') + '</tr>';
    };
    let body = '';
    if (view.group) {
      const groups = new Map();
      for (const run of list) { const k = run.campaign || '(none)'; groups.set(k, [...(groups.get(k) || []), run]); }
      for (const [name, members] of [...groups].sort((a, b) => Math.max(...b[1].map(r => r.started || 0)) - Math.max(...a[1].map(r => r.started || 0)))) {
        const closed = view.collapsed.includes(name);
        const spend = members.reduce((a, r) => a + (r.spent_usd || 0), 0);
        body += `<tr class="group" data-group="${esc(name)}"><td colspan="${COLS.length}">${closed ? '▸' : '▾'} ${esc(name)} <span class="muted">· ${members.length} run${members.length === 1 ? '' : 's'} · ${members.filter(r => r.status === 'live').length} live · ${esc(money(spend))}</span></td></tr>`;
        if (!closed) body += members.sort(cmp).map(rowHtml).join('');
      }
    } else body = list.sort(cmp).map(rowHtml).join('');
    $('overview-rows').innerHTML = body || `<tr><td colspan="${COLS.length}" class="muted">No runs match.</td></tr>`;
    // Widths are set through the CSSOM because the page's CSP forbids inline style attributes.
    $('overview-rows').querySelectorAll('[data-width]').forEach(bar => bar.style.width = `${bar.dataset.width}%`);
    $('overview-rows').querySelectorAll('[data-run]').forEach(row => row.onclick = event => { if (!event.target.closest('a')) open(row.dataset.run); });
    $('overview-rows').querySelectorAll('[data-group]').forEach(row => row.onclick = () => {
      const name = row.dataset.group; view.collapsed = view.collapsed.includes(name) ? view.collapsed.filter(n => n !== name) : [...view.collapsed, name]; save(); renderOverview(); });
  }

  function open(tab) {
    if (tab !== 'overview' && !runs.some(run => run.run_id === tab)) tab = 'overview';
    active = tab;
    try { localStorage.setItem('arena-hub-tab', tab); } catch {}
    if (location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
    $('panel-overview').hidden = tab !== 'overview';
    if (tab !== 'overview' && !frames.has(tab)) {
      // Each dashboard loads once, on first open, and keeps polling its run afterwards.
      const frame = document.createElement('iframe');
      frame.className = 'run-frame';
      frame.title = `Dashboard for ${tab}`;
      frame.src = `run/${encodeURIComponent(tab)}/dashboard.html`;
      $('panels').appendChild(frame);
      frames.set(tab, frame);
    }
    for (const [id, frame] of frames) frame.hidden = id !== tab;
    renderTabs();
  }

  async function refresh() {
    try {
      const response = await fetch('runs.json', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      runs = await response.json();
      const live = runs.filter(run => run.status === 'live').length;
      $('hub-sub').textContent = `${runs.length} run${runs.length === 1 ? '' : 's'} · ${live} live`;
      $('hub-live').textContent = `Live · ${new Date().toLocaleTimeString()}`;
      $('hub-live').classList.add('ok');
      if (active === null) {
        let wanted = decodeURIComponent(location.hash.slice(1));
        try { wanted = wanted || localStorage.getItem('arena-hub-tab') || ''; } catch {}
        open(wanted || 'overview');
      } else renderTabs();
      renderOverview();
    } catch (error) {
      $('hub-live').textContent = `Disconnected: ${error.message}`;
      $('hub-live').classList.remove('ok');
    }
  }
  for (const [id, key] of [['f-theorem', 'theorem'], ['f-model', 'model'], ['f-campaign', 'campaign'], ['f-status', 'status']]) {
    $(id).onchange = () => { view[key] = $(id).value; save(); renderOverview(); };
  }
  $('f-text').oninput = () => { view.text = $('f-text').value; save(); renderOverview(); };
  $('f-group').onchange = () => { view.group = $('f-group').checked; save(); renderOverview(); };
  $('f-reset').onclick = () => { Object.assign(view, {text: '', theorem: '', model: '', campaign: '', status: ''}); save(); renderOverview(); };
  window.addEventListener('hashchange', () => open(decodeURIComponent(location.hash.slice(1)) || 'overview'));
  refresh();
  setInterval(refresh, 5000);
})();
