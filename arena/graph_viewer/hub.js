/* Arena run hub: a filterable, sortable table of every run plus one tab per run with its dashboard. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = v => v == null ? '—' : '$' + (v >= 0.1 ? v.toFixed(3) : v.toFixed(4));
  const shortTheorem = name => String(name || '—').split('.').slice(-1)[0];
  const frames = new Map();
  let runs = [], active = null, openTabs = [];
  try { openTabs = JSON.parse(localStorage.getItem('arena-hub-open') || '[]').filter(t => typeof t === 'string'); } catch {}
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
  const capShare = run => run.limit_usd ? run.spent_usd / run.limit_usd : null;

  const shortModel = r => String(r.model || '—').replace(/^.*\//, '');
  const pctChange = (v, base) => v == null || !base ? '' : `${v <= base ? '−' : '+'}${Math.abs(100 * (v - base) / base).toFixed(0)}%`;
  // Signed delta of v against base as a coloured span: green when better (lowerBetter flips it), red when worse.
  const beat = (v, base, lowerBetter, d = 0) => {
    if (v == null || base == null) return '';
    const diff = +(v - base).toFixed(d), better = lowerBetter ? diff < 0 : diff > 0;
    return `<span class="${diff === 0 ? '' : better ? 'up' : 'down'}">${diff > 0 ? '+' : diff < 0 ? '−' : '±'}${Math.abs(diff)}</span>`;
  };
  const stat = r => r.status === 'finished' ? (r.stop_reason || 'stopped').replace(/_/g, ' ') : r.status;
  // Column definitions: label, width, sort value, cell html. Eight columns so the table never needs a horizontal scroll.
  const COLS = [
    {k: 'run', label: 'Run', w: 21, v: r => r.run_id, h: r => `<div class="l1"><span class="dot ${r.status}"></span>${esc(title(r))}${r.langfuse_url ? ` <a href="${esc(r.langfuse_url)}" target="_blank" rel="noopener" title="Langfuse session">&#8599;</a>` : ''}</div><div class="l2">${esc(shortTheorem(r.theorem))} · ${esc(r.campaign || '—')}</div>`},
    {k: 'status', label: 'Status', w: 14, v: r => statusText(r), h: r => {
      const kind = r.status === 'live' ? 'good' : r.status === 'stalled' ? 'bad' : r.stop_reason === 'finished' ? 'good' : r.stop_reason ? 'mid' : '';
      return `<span class="badge ${kind}" title="${esc(statusText(r))}">${esc(stat(r))}</span>`; }},
    {k: 'phase', label: 'Phase / checks', w: 13, v: r => r.phase || '', h: r => {
      const job = r.active_job ? `${r.active_job.job} ${dur(r.active_job_elapsed_s)}` : 'idle';
      const checks = `fast ${dur(r.fast_check_age_s)} · full ${dur(r.full_check_age_s)}`;
      return `<div class="l1"><span class="badge ${r.full_check_stale ? 'bad' : 'mid'}" title="${esc(checks)}">${esc(r.phase || 'idle')}</span> ${esc(job)}</div><div class="l2 ${r.full_check_stale ? 'down' : ''}">${r.active_checker ? `checker: ${esc(r.active_checker.phase)} · ` : ''}${esc(checks)}${r.full_check_stale ? ' · full stale' : ''}</div>`; }},
    {k: 'proxy', label: 'Best proxy', w: 10, v: r => r.best?.proxy ?? -1, h: (r, top) => r.best?.proxy == null ? '—' :
      `<div class="l1"><span class="${top ? 'best' : ''}">${r.best.proxy.toFixed(2)}</span> <span class="${r.delta_proxy >= 0 ? 'up' : 'down'}">${r.delta_proxy >= 0 ? '+' : ''}${r.delta_proxy}</span></div><div class="l2">${esc(r.best.candidate || '')}${r.target ? ` · beat ${r.target.proxy.toFixed(2)} ${beat(r.best.proxy, r.target.proxy, false, 2)}` : ''}</div>`},
    {k: 'tokens', label: 'Tokens / heartbeats', w: 12, v: r => r.best?.tokens ?? 1e9, h: r => r.best?.tokens == null ? '—' :
      `<div class="l1">${esc(r.best.tokens)} / ${esc(r.best.heartbeats)}</div><div class="l2">${pctChange(r.best.tokens, r.reference?.tokens)} / ${pctChange(r.best.heartbeats, r.reference?.heartbeats)}</div>${r.target && (r.target.tokens != null || r.target.heartbeats != null) ? `<div class="l2">beat ${esc(r.target.tokens ?? '—')} / ${esc(r.target.heartbeats ?? '—')}: ${beat(r.best.tokens, r.target.tokens, true) || '—'} / ${beat(r.best.heartbeats, r.target.heartbeats, true) || '—'}</div>` : ''}`},
    {k: 'spend', label: 'Spend / limit', w: 14, v: r => r.spent_usd, h: r => {
      const share = capShare(r), kind = share > 1 ? ' over' : share > 0.8 ? ' warn' : '';
      return `<div class="l1"><span class="bar${kind}"><span data-width="${Math.min(100, 100 * (share || 0)).toFixed(1)}"></span></span>${money(r.spent_usd)}</div><div class="l2">of ${money(r.limit_usd)}</div>`; }},
    {k: 'requests', label: 'Requests · tools · errors', w: 13, v: r => r.requests, h: r => `<div class="l1">${esc(r.requests ?? '—')} req · ${esc(r.tool_results ?? '—')} tools</div><div class="l2">${r.tool_errors ? `<span class="down">${r.tool_errors} errors</span>` : '0 errors'}</div>`},
    {k: 'submission', label: 'Submission', w: 7, v: r => r.submission_info?.cold_verified ? 2 : r.submission ? 1 : 0, h: r =>
      r.submission_info?.cold_verified ? `<span class="badge good" title="cold-verified">✓ ${esc(r.submission)}</span>` : r.submission ? `<span class="badge mid">${esc(r.submission)}</span>` : '<span class="muted">—</span>'},
    {k: 'started', label: 'Started', w: 9, v: r => r.started ?? 0, h: r => `<div class="l1">${when(r.started)}</div><div class="l2">${dur(r.duration_s)}</div>`},
  ];
  // Secondary metrics live in the row's hover card instead of more columns.
  const detail = r => [['Run', r.run_id], ['Thinking', r.thinking || '—'], ['Original proof', r.reference ? `${r.reference.tokens} tokens / ${r.reference.heartbeats} heartbeats` : '—'],
    ['Cache hit rate', pct(r.cache_reuse_pct)], ['Bookkeeping + rejected', pct(r.bookkeeping_pct)],
    ['Spend after best', r.spent_after_best_usd == null ? '—' : `${money(r.spent_after_best_usd)} (${r.requests_after_best ?? '?'} req)`]];

  function showTip(row) {
    const run = runs.find(r => r.run_id === row.dataset.run); if (!run) return;
    const tip = $('rowtip');
    tip.innerHTML = detail(run).map(([k, v], i) => i === 0 ? `<div class="id">${esc(v)}</div>` : `<span class="k">${esc(k)}</span><span>${esc(v)}</span>`).join('');
    tip.hidden = false;
  }
  function moveTip(event) {
    const tip = $('rowtip');
    tip.style.left = `${Math.min(event.clientX + 16, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${Math.min(event.clientY + 16, window.innerHeight - tip.offsetHeight - 8)}px`;
  }

  function renderTabs() {
    const tabs = [`<button class="tab" role="tab" data-tab="overview" aria-selected="${active === 'overview'}"><span class="lbl"><span class="tab-title">Runs</span><span class="tab-meta">${runs.length} run${runs.length === 1 ? '' : 's'}</span></span></button>`];
    for (const id of openTabs) {
      const run = runs.find(r => r.run_id === id); if (!run) continue;
      tabs.push(`<button class="tab" role="tab" data-tab="${esc(id)}" aria-selected="${active === id}" title="${esc(id)}"><span class="lbl">
        <span class="tab-title"><span class="dot ${run.status}"></span>${esc(title(run))}</span>
        <span class="tab-meta">${esc(shortTheorem(run.theorem))} · ${run.best?.proxy != null ? run.best.proxy.toFixed(2) : '—'} · ${esc(money(run.spent_usd))}</span></span>
        <span class="x" data-close="${esc(id)}" role="button" aria-label="Close tab" title="Close">&times;</span></button>`);
    }
    $('tabs').innerHTML = tabs.join('');
    $('tabs').querySelectorAll('[data-tab]').forEach(button => {
      button.onclick = event => { const close = event.target.closest('[data-close]'); close ? closeTab(close.dataset.close) : open(button.dataset.tab); };
      button.onauxclick = event => { if (event.button === 1 && button.dataset.tab !== 'overview') { event.preventDefault(); closeTab(button.dataset.tab); } };
    });
  }
  function closeTab(id) {
    const at = openTabs.indexOf(id);
    openTabs = openTabs.filter(t => t !== id);
    frames.get(id)?.remove(); frames.delete(id);
    saveTabs();
    if (active === id) open(openTabs[Math.min(at, openTabs.length - 1)] || 'overview'); else renderTabs();
  }
  const saveTabs = () => { try { localStorage.setItem('arena-hub-open', JSON.stringify(openTabs)); } catch {} };

  // A native <select> must never be rebuilt while its menu is open: replacing its options on a poll closes
  // the menu and snaps the choice back to the first entry. Rebuild only when the option list really
  // changed, and not at all while the control has focus (the blur handler below catches up).
  function fillSelect(id, label, values) {
    const select = $(id), current = view[id.slice(2)];
    const list = [...new Set(values.filter(Boolean))].sort(), signature = JSON.stringify([label, list]);
    if (select.dataset.sig !== signature && document.activeElement !== select) {
      select.innerHTML = `<option value="">${label}</option>` + list.map(v => `<option value="${esc(v)}">${esc(id === 'f-theorem' ? shortTheorem(v) : v)}</option>`).join('');
      select.dataset.sig = signature;
    }
    if (select.dataset.sig === signature && select.value !== current && document.activeElement !== select) select.value = current;
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
    const livePhases = list.filter(r => r.phase).map(r => `${shortTheorem(r.theorem)}: ${r.phase}`);
    const stale = list.filter(r => r.full_check_stale).length;
    const runningJobs = list.filter(r => r.active_job).map(r => `${shortTheorem(r.theorem)} ${r.active_job.job} ${dur(r.active_job_elapsed_s)}`);
    const parts = [`<span><b>${list.filter(r => r.status === 'live').length}</b> live</span>`, `<span><b>${esc(money(spend))}</b> spent</span>`, ...(stale ? [`<span class="down"><b>${stale}</b> full check stale (&gt;10m)</span>`] : []), ...livePhases.map(p => `<span>${esc(p)}</span>`), ...runningJobs.map(p => `<span>${esc(p)}</span>`)];
    for (const [theorem, r] of best) parts.push(`<span class="best" title="${esc(r.run_id)}">best ${esc(shortTheorem(theorem))} <b>${r.best.proxy.toFixed(2)}</b></span>`);
    $('strip').innerHTML = parts.join('');
  }

  function renderOverview() {
    const topByTheorem = new Map();
    for (const run of runs) if (run.best?.proxy != null && run.best.proxy > (topByTheorem.get(run.theorem) ?? -Infinity)) topByTheorem.set(run.theorem, run.best.proxy);
    fillSelect('f-theorem', 'any theorem', runs.map(r => r.theorem));
    fillSelect('f-model', 'any model', runs.map(r => r.model));
    fillSelect('f-campaign', 'any campaign', runs.map(r => r.campaign));
    if (document.activeElement !== $('f-status')) $('f-status').value = view.status;
    $('f-group').checked = view.group;
    if (document.activeElement !== $('f-text')) $('f-text').value = view.text;
    const list = runs.filter(matches);
    $('f-count').textContent = `${list.length} shown`;
    strip(list);
    const col = COLS.find(c => c.k === view.sort) || COLS.find(c => c.k === 'started');
    const sign = view.dir === 'asc' ? 1 : -1;
    const cmp = (a, b) => { const x = col.v(a), y = col.v(b); return sign * (typeof x === 'string' ? x.localeCompare(y) : x - y); };
    $('thead').innerHTML = '<tr>' + COLS.map(c => `<th data-sort="${c.k}" data-w="${c.w}"${c.k === col.k ? ` aria-sort="${view.dir === 'asc' ? 'ascending' : 'descending'}"` : ''}>${c.label}</th>`).join('') + '</tr>';
    $('thead').querySelectorAll('[data-w]').forEach(th => th.style.width = `${th.dataset.w}%`);
    $('thead').querySelectorAll('[data-sort]').forEach(th => th.onclick = () => {
      view.dir = view.sort === th.dataset.sort && view.dir === 'desc' ? 'asc' : 'desc'; view.sort = th.dataset.sort; save(); renderOverview(); });
    const rowHtml = run => {
      const top = run.best?.proxy != null && run.best.proxy === topByTheorem.get(run.theorem);
      return `<tr class="run${top ? ' top' : ''}" data-run="${esc(run.run_id)}" title="${esc(run.run_id)}${top ? ' — best for this theorem' : ''}">` +
        COLS.map(c => `<td>${c.h(run, top)}</td>`).join('') + '</tr>';
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
    $('overview-rows').querySelectorAll('[data-run]').forEach(row => { row.onmouseenter = () => showTip(row); row.onmousemove = moveTip; row.onmouseleave = () => $('rowtip').hidden = true; });
    $('overview-rows').querySelectorAll('[data-run]').forEach(row => row.onclick = event => { if (!event.target.closest('a')) open(row.dataset.run); });
    $('overview-rows').querySelectorAll('[data-group]').forEach(row => row.onclick = () => {
      const name = row.dataset.group; view.collapsed = view.collapsed.includes(name) ? view.collapsed.filter(n => n !== name) : [...view.collapsed, name]; save(); renderOverview(); });
  }

  function open(tab) {
    if (tab !== 'overview' && !runs.some(run => run.run_id === tab)) tab = 'overview';
    if (tab !== 'overview' && !openTabs.includes(tab)) { openTabs.push(tab); saveTabs(); }
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

  let assetsVersion = null;
  async function refresh() {
    try {
      const response = await fetch('runs.json', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      // A tab opened before the viewer code changed keeps running the old code; reload it once the server has newer assets.
      const version = response.headers.get('X-Assets-Version');
      if (version && assetsVersion && version !== assetsVersion && !document.querySelector('select:focus')) { location.reload(); return; }
      if (version) assetsVersion = assetsVersion || version;
      runs = await response.json();
      const live = runs.filter(run => run.status === 'live').length;
      $('hub-sub').textContent = `${runs.length} run${runs.length === 1 ? '' : 's'}`;
      $('hub-live').textContent = `Live · ${new Date().toLocaleTimeString()}`;
      $('hub-live').classList.add('ok');
      if (active === null) {
        let wanted = decodeURIComponent(location.hash.slice(1));
        try { wanted = wanted || localStorage.getItem('arena-hub-tab') || ''; } catch {}
        open(wanted || 'overview');
      } else renderTabs();
      if (runs.length && openTabs.some(t => !runs.some(r => r.run_id === t))) { openTabs = openTabs.filter(t => runs.some(r => r.run_id === t)); saveTabs(); }
      renderOverview();
    } catch (error) {
      $('hub-live').textContent = `Disconnected: ${error.message}`;
      $('hub-live').classList.remove('ok');
    }
  }
  for (const [id, key] of [['f-theorem', 'theorem'], ['f-model', 'model'], ['f-campaign', 'campaign'], ['f-status', 'status']]) {
    $(id).onchange = () => { view[key] = $(id).value; save(); renderOverview(); };
    $(id).onblur = () => renderOverview();
  }
  $('f-text').oninput = () => { view.text = $('f-text').value; save(); renderOverview(); };
  $('f-group').onchange = () => { view.group = $('f-group').checked; save(); renderOverview(); };
  $('f-reset').onclick = () => { Object.assign(view, {text: '', theorem: '', model: '', campaign: '', status: ''}); save(); renderOverview(); };
  window.addEventListener('hashchange', () => open(decodeURIComponent(location.hash.slice(1)) || 'overview'));
  refresh();
  setInterval(refresh, 5000);
})();
