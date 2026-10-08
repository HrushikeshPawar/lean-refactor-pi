/* Tiny SVG chart helpers (no libraries, no network). Colours come from CSS classes so charts follow
   light/dark mode; the page CSP forbids inline styles, so everything is attributes and classes.
   Charts render at the real pixel width of their container (so text is always 12px) and redraw on resize.
   Y axes start at 0 unless a caller says otherwise. Hover any point or bar for exact values. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  /* ---- number and time formatting ---- */
  const dur = s => s == null ? '' : s >= 3600 ? `${Math.floor(s / 3600)}h${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}` :
    s >= 60 ? `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, '0')}` : `${Math.round(s)}s`;
  const tickTime = s => s === 0 ? '0' : s < 60 ? `${s}s` : s < 3600 ? (s % 60 ? `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}` : `${s / 60}m`) :
    (s % 3600 ? `${Math.floor(s / 3600)}h${String(Math.round(s % 3600 / 60)).padStart(2, '0')}` : `${s / 3600}h`);
  const trim = (v, d) => String(+v.toFixed(d));
  const si = v => { const a = Math.abs(v); return a >= 1e6 ? trim(v / 1e6, 2) + 'M' : a >= 1e3 ? trim(v / 1e3, 1) + 'K' : trim(v, 1); };
  const decimals = step => { for (let d = 0; d < 6; d++) if (Math.abs(Math.round(step * 10 ** d) - step * 10 ** d) < 1e-6 * Math.max(1, step * 10 ** d)) return d; return 6; };
  const fmt = {
    num: (v, step) => step >= 1 ? si(v) : trim(v, decimals(step)),
    money: (v, step) => '$' + v.toFixed(Math.max(2, decimals(step || 0.01))),
    pct: v => `${trim(v, 1)}%`,
    sec: (v, step) => `${v.toFixed(step >= 1 ? 0 : decimals(step))} s`,
    score: v => trim(v, 2),
  };

  function niceTicks(lo, hi, count = 5) {
    if (!(hi > lo)) hi = lo + 1;
    const raw = (hi - lo) / count, pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * pow).find(s => s >= raw) || raw;
    const out = [];
    for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(10));
    out.step = step;
    return out;
  }
  function timeTicks(lo, hi, count = 6) {
    const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 28800];
    const step = steps.find(s => (hi - lo) / s <= count) || 86400, out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-6; v += step) out.push(v);
    out.step = step;
    return out;
  }

  /* ---- chart registry: charts draw at the width of their placeholder, after the HTML is in the page ---- */
  const registry = new Map();
  let seq = 0;
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
    for (const entry of entries) {
      const el = entry.target, width = Math.floor(entry.contentRect.width);
      if (el._fn && width && width !== el._w) draw(el);
    }
  });
  function draw(el) {
    el._w = Math.floor(el.clientWidth) || 640;
    try { el.innerHTML = el._fn(Math.max(300, el._w)); }
    catch (error) { console.error('chart failed', error); el.innerHTML = `<p class="warn">Chart failed to draw: ${esc(error.message)}</p>`; }
  }
  function box(fn) {
    const id = 'c' + (++seq);
    registry.set(id, fn);
    return `<div class="chartbox" data-cid="${id}"></div>`;
  }
  const watched = new Set();
  function mount(root) {
    for (const old of watched) if (!old.isConnected) { watched.delete(old); if (observer) observer.unobserve(old); }
    root.querySelectorAll('.chartbox').forEach(el => {
      if (el._fn) return;
      el._fn = registry.get(el.dataset.cid);
      registry.delete(el.dataset.cid);
      if (!el._fn) return;
      draw(el);
      watched.add(el);
      if (observer) observer.observe(el);
    });
  }

  /* ---- hover tooltip, shared by every chart on the page ---- */
  let tip = null;
  const showTip = (event, target) => {
    if (!tip) { tip = document.createElement('div'); tip.className = 'charttip'; document.body.appendChild(tip); }
    tip.textContent = target.getAttribute('data-tip');
    tip.hidden = false;
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = event.clientX + pad, y = event.clientY + pad;
    if (x + w > window.innerWidth - 6) x = event.clientX - w - pad;
    if (y + h > window.innerHeight - 6) y = event.clientY - h - pad;
    tip.style.left = `${Math.max(4, x)}px`; tip.style.top = `${Math.max(4, y)}px`;
  };
  document.addEventListener('mousemove', event => {
    const target = event.target.closest && event.target.closest('[data-tip]');
    if (target) showTip(event, target); else if (tip) tip.hidden = true;
  });
  document.addEventListener('mouseleave', () => { if (tip) tip.hidden = true; });

  /* ---- shared drawing ---- */
  function layout(w, o) {
    const h = o.height || Math.round(Math.max(230, Math.min(330, w * 0.36)));
    const M = {l: o.yLabel ? 74 : 56, r: 18, t: 22, b: o.xLabel ? 52 : 34};
    return {w, h, M};
  }
  function makeScales(L, xs, ys, o) {
    let x0 = o.xMin ?? Math.min(0, ...xs), x1 = o.xMax ?? Math.max(1, ...xs);
    let y0 = o.yMin ?? 0, y1 = o.yMax ?? 0;
    const ymax = Math.max(...ys, ...(o.includeRefs ? (o.refs || []).map(r => r.y) : []));
    if (isFinite(ymax)) y1 = Math.max(y1, ymax * (o.exact ? 1 : 1.1));
    if (!isFinite(x0) || !isFinite(x1)) { x0 = 0; x1 = 1; }
    if (!(y1 > y0)) y1 = y0 + 1;
    const {w, h, M} = L;
    return {x0, x1, y0, y1, sx: v => M.l + (v - x0) / ((x1 - x0) || 1) * (w - M.l - M.r), sy: v => h - M.b - (v - y0) / (y1 - y0) * (h - M.t - M.b)};
  }
  function axes(L, s, o) {
    const {w, h, M} = L, fmtY = o.fmtY || fmt.num;
    const yt = niceTicks(s.y0, s.y1, o.yTicks || (h < 260 ? 4 : 5));
    let out = '';
    for (const v of yt) out += `<line class="grid" x1="${M.l}" x2="${w - M.r}" y1="${s.sy(v)}" y2="${s.sy(v)}"/><text class="tick" x="${M.l - 8}" y="${s.sy(v) + 4}" text-anchor="end">${esc(fmtY(v, yt.step))}</text>`;
    if (o.xTickList) {
      for (const [pos, label] of o.xTickList) out += `<line class="xtick" x1="${s.sx(pos)}" x2="${s.sx(pos)}" y1="${h - M.b}" y2="${h - M.b + 4}"/><text class="tick" x="${s.sx(pos)}" y="${h - M.b + 18}" text-anchor="middle">${esc(label)}</text>`;
    }
    const xt = o.xTickList ? [] : o.xTime === false ? (t => o.intX ? t.filter(Number.isInteger) : t)(niceTicks(s.x0, s.x1, Math.max(3, Math.floor((w - M.l - M.r) / 70)))) : timeTicks(s.x0, s.x1, Math.max(3, Math.floor((w - M.l - M.r) / 80)));
    const fmtX = o.fmtX || (o.xTime === false ? (v => fmt.num(v, 1)) : tickTime);
    for (const v of xt) out += `<line class="xtick" x1="${s.sx(v)}" x2="${s.sx(v)}" y1="${h - M.b}" y2="${h - M.b + 4}"/><text class="tick" x="${s.sx(v)}" y="${h - M.b + 18}" text-anchor="middle">${esc(fmtX(v))}</text>`;
    out += `<line class="axis" x1="${M.l}" x2="${w - M.r}" y1="${h - M.b}" y2="${h - M.b}"/><line class="axis" x1="${M.l}" x2="${M.l}" y1="${M.t}" y2="${h - M.b}"/>`;
    if (o.xLabel) out += `<text class="axtitle" x="${(M.l + w - M.r) / 2}" y="${h - 8}" text-anchor="middle">${esc(o.xLabel)}</text>`;
    if (o.yLabel) out += `<text class="axtitle" transform="translate(16 ${(M.t + h - M.b) / 2}) rotate(-90)" text-anchor="middle">${esc(o.yLabel)}</text>`;
    return out;
  }
  function refLines(L, s, o) {
    const {w, M} = L;
    let out = '';
    for (const r of o.refs || []) {
      if (r.y == null || r.y < s.y0 || r.y > s.y1) continue;
      const y = s.sy(r.y);
      out += `<line class="ref ${r.cls}" x1="${M.l}" x2="${w - M.r}" y1="${y}" y2="${y}"/>` +
             `<text class="reflabel ${r.cls}" x="${M.l + 6}" y="${Math.max(M.t + 10, y - 6)}" text-anchor="start">${esc(r.label)}</text>`;
    }
    for (const [i, note] of (o.notes || []).entries()) out += `<text class="reflabel ${note.cls || 'hard'}" x="${w - M.r - 4}" y="${M.t - 6 + i * 14}" text-anchor="end">${esc(note.text)}</text>`;
    return out;
  }
  const svg = (L, inner, label) => `<svg class="chart" width="${L.w}" height="${L.h}" role="img" aria-label="${esc(label || 'chart')}">${inner}</svg>`;
  const legend = items => `<div class="legend">${items.map(([cls, text]) => `<span><i class="sw ${cls}"></i>${esc(text)}</span>`).join('')}</div>`;

  /* series: [{cls, points:[[x,y,tip?]], step?, dots?, hollow?, noLine?, r?}]
     opts: refs:[{y,cls,label}], notes:[{text,cls}], best:{x,y,text}, legend:[[cls,text]], yMin/yMax, exact, includeRefs,
           fmtY(v, step), fmtX, xTime=false for non-time x, xLabel, yLabel, xMin/xMax, extendTo (step lines run on to this x) */
  /* Monotone cubic (Fritsch–Carlson) path through screen points: smooth, passes through every
     point, and never overshoots between two of them, so it invents no highs or lows. */
  function smoothPath(xy, move = true) {
    const n = xy.length;
    if (!n) return '';
    let d = move ? `M${xy[0][0]},${xy[0][1]}` : `L${xy[0][0]},${xy[0][1]}`;
    if (n === 1) return d;
    const dx = [], m = [], t = [];
    for (let i = 0; i < n - 1; i++) { dx.push(xy[i + 1][0] - xy[i][0]); m.push(dx[i] ? (xy[i + 1][1] - xy[i][1]) / dx[i] : 0); }
    t[0] = m[0]; t[n - 1] = m[n - 2];
    for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
    for (let i = 0; i < n - 1; i++) {
      if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
      const a = t[i] / m[i], b = t[i + 1] / m[i], h = a * a + b * b;
      if (h > 9) { const k = 3 / Math.sqrt(h); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
    }
    for (let i = 0; i < n - 1; i++) {
      const [x0, y0] = xy[i], [x1, y1] = xy[i + 1], h = dx[i] / 3;
      d += `C${x0 + h},${y0 + t[i] * h} ${x1 - h},${y1 - t[i + 1] * h} ${x1},${y1}`;
    }
    return d;
  }

  function line(series, o = {}) {
    const xs = series.flatMap(s => s.points.map(p => p[0])), ys = series.flatMap(s => s.points.filter(p => p[1] != null).map(p => p[1]));
    if (!xs.length && !(o.refs || []).length) return '<p class="muted">No data yet.</p>';
    return box(w => {
      const L = layout(w, o), s = makeScales(L, xs, ys, o);
      let out = axes(L, s, o) + refLines(L, s, o);
      for (const ser of series) {
        const pts = ser.points.filter(p => p[1] != null);
        if (!pts.length) continue;
        if (!ser.noLine) {
          let d = smoothPath(pts.map(p => [s.sx(p[0]), s.sy(p[1])]));
          if (ser.step && o.extendTo != null) d += `H${s.sx(o.extendTo)}`;
          out += `<path class="line ${ser.cls}${ser.thin ? ' thin' : ''}" d="${d}"/>`;
        }
      }
      for (const ser of series) {
        if (ser.dots === false) continue;
        for (const p of ser.points.filter(q => q[1] != null)) {
          const tipText = p[2] ?? `${dur(p[0])}: ${p[1]}`;
          out += `<circle class="dot ${ser.cls}${ser.hollow ? ' hollow' : ''}" cx="${s.sx(p[0])}" cy="${s.sy(p[1])}" r="${ser.r || 4}"/>` +
                 `<circle class="hit${p[3] ? ' pick' : ''}" cx="${s.sx(p[0])}" cy="${s.sy(p[1])}" r="10" data-tip="${esc(tipText)}"${p[3] ? ` data-cand="${esc(p[3])}"` : ''}/>`;
        }
      }
      for (const lab of o.pointLabels || []) {
        if (lab.y == null) continue;
        out += `<text class="besttxt" x="${s.sx(lab.x) + (lab.dx ?? 10)}" y="${s.sy(lab.y) + (lab.dy ?? -10)}" text-anchor="${lab.anchor || 'start'}">${esc(lab.text)}</text>`;
      }
      if (o.best && o.best.y != null) {
        const bx = s.sx(o.best.x), by = s.sy(o.best.y), anchor = bx > w - 120 ? 'end' : bx < L.M.l + 60 ? 'start' : 'middle';
        out += `<circle class="bestring" cx="${bx}" cy="${by}" r="8"/><text class="besttxt" x="${bx}" y="${o.best.below ? by + 26 : Math.max(12, by - 14)}" text-anchor="${anchor}">${esc(o.best.text)}</text>`;
      }
      return svg(L, out, o.label) + (o.legend ? legend(o.legend) : '');
    });
  }

  /* Stacked bars: bars:[{parts:[v...], title}], layers:[{cls,label}]; x is the 1-based bar number. */
  function stacked(bars, layers, o = {}) {
    if (!bars.length) return '<p class="muted">No data yet.</p>';
    const totals = bars.map(b => b.parts.reduce((a, v) => a + (v || 0), 0));
    o = {...o, xLabel: o.xLabel || 'request #'};
    return box(w => {
      const L = layout(w, o), {M} = L;
      const s = makeScales(L, [0, bars.length], totals, {...o, xMin: 0, xMax: bars.length, yMin: 0});
      const slot = (w - M.l - M.r) / bars.length, bw = Math.max(1.5, slot * 0.74);
      const per = Math.max(1, Math.ceil(40 / slot)), tl = [];
      for (let k = 1; k <= bars.length; k++) if (k === 1 || k % per === 0) tl.push([k - 0.5, String(k)]);
      let out = axes(L, s, {...o, xTickList: tl, xLabel: o.xLabel || 'request #'});
      out += refLines(L, s, o);
      bars.forEach((bar, i) => {
        let acc = 0;
        const x = s.sx(i) + (slot - bw) / 2;
        bar.parts.forEach((v, k) => {
          if (!v) return;
          const y1 = s.sy(acc), y2 = s.sy(acc + v);
          out += `<rect class="bar ${layers[k].cls}" x="${x}" y="${y2}" width="${bw}" height="${Math.max(0.8, y1 - y2)}"/>`;
          acc += v;
        });
        out += `<rect class="hit" x="${s.sx(i)}" y="${M.t}" width="${slot}" height="${L.h - M.t - M.b}" data-tip="${esc(bar.title || '')}"/>`;
      });
      return svg(L, out, o.label) + legend(layers.map(l => [l.cls, l.label]));
    });
  }


  /* Stacked area: pts:[{x, parts:[v...], tip}], layers:[{cls,label}] (first layer at the bottom). The top edge is the running total. */
  function area(pts, layers, o = {}) {
    if (!pts.length) return '<p class="muted">No data yet.</p>';
    const totals = pts.map(p => p.parts.reduce((a, v) => a + (v || 0), 0)), xs = pts.map(p => p.x);
    o = {...o, xTime: false, intX: true};
    return box(w => {
      const L = layout(w, o), {M} = L, s = makeScales(L, xs, totals, o);
      let out = axes(L, s, o) + refLines(L, s, o);
      let below = pts.map(() => 0);
      layers.forEach((layer, k) => {
        const above = pts.map((p, i) => below[i] + (p.parts[k] || 0));
        const top = smoothPath(pts.map((p, i) => [s.sx(p.x), s.sy(above[i])]));
        const bottom = smoothPath(pts.map((p, i) => [s.sx(p.x), s.sy(below[i])]).reverse(), false);
        out += `<path class="area ${layer.cls}" d="${top}${bottom}Z"/>`;
        below = above;
      });
      out += `<path class="line toptotal" d="${smoothPath(pts.map((p, i) => [s.sx(p.x), s.sy(totals[i])]))}"/>`;
      const right = w - M.r;
      pts.forEach((p, i) => {
        if (p.tip == null || i === 0) return;
        const a = Math.max(M.l, (s.sx(xs[i - 1]) + s.sx(p.x)) / 2), b = Math.min(right, i + 1 < pts.length ? (s.sx(p.x) + s.sx(xs[i + 1])) / 2 : right);
        out += `<rect class="hit" x="${a}" y="${M.t}" width="${Math.max(2, b - a)}" height="${L.h - M.t - M.b}" data-tip="${esc(p.tip)}"/>`;
      });
      return svg(L, out, o.label) + (o.legend ? legend(o.legend) : '');
    });
  }

  window.Charts = {esc, dur, tickTime, fmt, line, stacked, area, niceTicks, timeTicks, legend, mount, box};
})();
