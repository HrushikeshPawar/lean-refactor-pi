/* Arena run hub: an overview of every run plus one tab per run with that run's live viewer. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = v => v == null ? '—' : '$' + (v >= 0.1 ? v.toFixed(3) : v.toFixed(4));
  const frames = new Map();
  let runs = [], active = null;

  // Short tab title: what differs between runs (the model and the replicate/run suffix).
  function title(run) {
    const model = run.model || run.run_id;
    const suffix = run.run_id.replace(/-model-.*$/, '').split('-').pop();
    return suffix && suffix !== model && suffix !== run.run_id ? `${model} · ${suffix}` : model;
  }
  function status(run) {
    return run.finished ? `done · ${run.stop_reason || 'stopped'}` : 'live';
  }
  function bestText(run) {
    return run.best?.proxy != null ? run.best.proxy.toFixed(2) : '—';
  }

  function renderTabs() {
    const tabs = [`<button class="tab" role="tab" data-tab="overview" aria-selected="${active === 'overview'}">
      <span class="tab-title">Overview</span><span class="tab-meta">${runs.length} run${runs.length === 1 ? '' : 's'}</span></button>`];
    for (const run of runs) {
      tabs.push(`<button class="tab" role="tab" data-tab="${esc(run.run_id)}" aria-selected="${active === run.run_id}" title="${esc(run.run_id)}">
        <span class="tab-title"><span class="dot ${run.finished ? 'done' : 'live'}"></span>${esc(title(run))}</span>
        <span class="tab-meta">${esc(shortTheorem(run.theorem))} · ${esc(bestText(run))} · ${esc(money(run.spent_usd))}</span></button>`);
    }
    $('tabs').innerHTML = tabs.join('');
    $('tabs').querySelectorAll('[data-tab]').forEach(button => button.onclick = () => open(button.dataset.tab));
  }

  const shortTheorem = name => String(name || '—').split('.').slice(-1)[0];
  // A value with its change against the original proof; `lower` says whether smaller is better.
  function delta(value, base, lower) {
    if (value == null) return '—';
    if (base == null) return esc(value);
    const change = value - base, better = lower ? change < 0 : change > 0;
    if (!change) return `${esc(value)} <span class="muted">= original</span>`;
    const pct = base ? Math.round(100 * Math.abs(change) / base) : null;
    const amount = Number.isInteger(change) ? Math.abs(change) : Math.abs(change).toFixed(2);
    return `${esc(lower ? value : value.toFixed(2))} <span class="${better ? 'up' : 'down'}">${change < 0 ? '↓' : '↑'}${esc(amount)}${pct != null && lower ? ` (${pct}%)` : ''}</span>`;
  }
  function leading(run) {
    const lead = run.leading_unverified;
    if (lead) return `${esc(lead.candidate)} est. ${esc(lead.estimated_proxy)} · ${run.checking?.includes(lead.candidate) ? 'checking' : 'not checked'}`;
    return `<span class="muted">${run.best ? 'none · best is verified' : 'none yet'}</span>`;
  }

  function renderOverview() {
    // Best score per theorem, so runs on different theorems are not compared with each other.
    const bestByTheorem = new Map();
    for (const run of runs) {
      const score = run.best?.proxy;
      if (score != null && score > (bestByTheorem.get(run.theorem) ?? -Infinity)) bestByTheorem.set(run.theorem, score);
    }
    const ordered = [...runs].sort((a, b) => String(a.theorem).localeCompare(String(b.theorem)));
    $('overview-rows').innerHTML = ordered.length ? ordered.map(run => {
      const share = run.cap_usd ? Math.min(100, 100 * run.spent_usd / run.cap_usd) : 0;
      const over = run.cap_usd && run.spent_usd > run.cap_usd;
      const ref = run.reference || {};
      const top = run.best?.proxy != null && run.best.proxy === bestByTheorem.get(run.theorem);
      return `<tr data-run="${esc(run.run_id)}">
        <td title="${esc(run.run_id)}"><span class="dot ${run.finished ? 'done' : 'live'}"></span>${esc(title(run))}</td>
        <td title="${esc(run.theorem)}">${esc(shortTheorem(run.theorem))}</td>
        <td>${esc(run.model || '—')}</td><td>${esc(run.thinking || '—')}</td>
        <td class="num ${top ? 'best' : ''}">${run.best?.proxy != null ? delta(run.best.proxy, ref.proxy, false) : '—'}${run.best?.candidate ? ` <span class="muted">${esc(run.best.candidate)}</span>` : ''}</td>
        <td class="num">${delta(run.best?.tokens, ref.tokens, true)}</td>
        <td class="num">${delta(run.best?.heartbeats, ref.heartbeats, true)}</td>
        <td>${leading(run)}</td>
        <td class="num"><span class="bar${over ? ' over' : ''}"><span data-width="${share.toFixed(1)}"></span></span>${esc(money(run.spent_usd))} / ${esc(money(run.cap_usd))}</td>
        <td class="num">${esc(run.requests)}</td><td>${esc(status(run))}</td><td>${esc(run.submission || '—')}</td></tr>`;
    }).join('') : '<tr><td colspan="12" class="muted">No runs yet.</td></tr>';
    // Widths are set through the CSSOM because the page's CSP forbids inline style attributes.
    $('overview-rows').querySelectorAll('[data-width]').forEach(bar => bar.style.width = `${bar.dataset.width}%`);
    $('overview-rows').querySelectorAll('[data-run]').forEach(row => row.onclick = () => open(row.dataset.run));
  }

  function open(tab) {
    if (tab !== 'overview' && !runs.some(run => run.run_id === tab)) tab = 'overview';
    active = tab;
    try { localStorage.setItem('arena-hub-tab', tab); } catch {}
    if (location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
    $('panel-overview').hidden = tab !== 'overview';
    if (tab !== 'overview' && !frames.has(tab)) {
      // Each viewer loads once, on first open, and keeps polling its run afterwards.
      const frame = document.createElement('iframe');
      frame.className = 'run-frame';
      frame.title = `Viewer for ${tab}`;
      frame.src = `run/${encodeURIComponent(tab)}/`;
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
      const live = runs.filter(run => !run.finished).length;
      $('hub-sub').textContent = `${runs.length} run${runs.length === 1 ? '' : 's'} · ${live} live`;
      $('hub-live').textContent = `Live · ${new Date().toLocaleTimeString()}`;
      $('hub-live').classList.add('ok');
      if (active === null) {
        let wanted = decodeURIComponent(location.hash.slice(1));
        try { wanted = wanted || localStorage.getItem('arena-hub-tab') || ''; } catch {}
        open(wanted || 'overview');
      } else {
        renderTabs();
      }
      renderOverview();
    } catch (error) {
      $('hub-live').textContent = `Disconnected: ${error.message}`;
      $('hub-live').classList.remove('ok');
    }
  }
  window.addEventListener('hashchange', () => open(decodeURIComponent(location.hash.slice(1)) || 'overview'));
  refresh();
  setInterval(refresh, 4000);
})();
