/* Tiny SVG chart helpers (no libraries, no network). Colours come from CSS classes so charts follow
   light/dark mode; the page CSP forbids inline styles, so everything is attributes and classes. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const W = 960, H = 250, M = {l: 52, r: 14, t: 12, b: 28};

  function niceTicks(lo, hi, count = 5) {
    if (!(hi > lo)) hi = lo + 1;
    const raw = (hi - lo) / count, pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * pow).find(s => s >= raw) || raw;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(10));
    return out;
  }
  const dur = s => s == null ? '' : s >= 3600 ? `${Math.floor(s / 3600)}h${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}` :
    s >= 60 ? `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, '0')}` : `${Math.round(s)}s`;

  /* Scales shared by the chart kinds. xs/ys are arrays of numbers used to size the domain. */
  function scales(xs, ys, o = {}) {
    const w = o.width || W, h = o.height || H;
    let x0 = o.xMin ?? Math.min(0, ...xs), x1 = o.xMax ?? Math.max(1, ...xs);
    let y0 = o.yMin ?? Math.min(0, ...ys), y1 = o.yMax ?? Math.max(...ys, 1e-9);
    if (!isFinite(x0) || !isFinite(x1)) { x0 = 0; x1 = 1; }
    if (!isFinite(y0) || !isFinite(y1)) { y0 = 0; y1 = 1; }
    if (y1 === y0) y1 = y0 + 1;
    y1 += (y1 - y0) * (o.pad ?? 0.06);
    const sx = v => M.l + (v - x0) / ((x1 - x0) || 1) * (w - M.l - M.r);
    const sy = v => h - M.b - (v - y0) / (y1 - y0) * (h - M.t - M.b);
    return {sx, sy, x0, x1, y0, y1, w, h};
  }

  function frame(s, o = {}) {
    const fmtY = o.fmtY || (v => String(+v.toPrecision(4)));
    const fmtX = o.fmtX || dur;
    let out = '';
    for (const v of niceTicks(s.y0, s.y1, 4)) {
      out += `<line class="grid" x1="${M.l}" x2="${s.w - M.r}" y1="${s.sy(v)}" y2="${s.sy(v)}"/>` +
             `<text class="tick" x="${M.l - 6}" y="${s.sy(v) + 3}" text-anchor="end">${esc(fmtY(v))}</text>`;
    }
    for (const v of niceTicks(s.x0, s.x1, 6)) {
      out += `<text class="tick" x="${s.sx(v)}" y="${s.h - 10}" text-anchor="middle">${esc(fmtX(v))}</text>`;
    }
    return out + `<line class="axis" x1="${M.l}" x2="${s.w - M.r}" y1="${s.h - M.b}" y2="${s.h - M.b}"/>` +
      `<line class="axis" x1="${M.l}" x2="${M.l}" y1="${M.t}" y2="${s.h - M.b}"/>`;
  }

  function hline(s, value, cls, label) {
    if (value == null || value < s.y0 || value > s.y1) return '';
    const y = s.sy(value);
    return `<line class="ref ${cls}" x1="${M.l}" x2="${s.w - M.r}" y1="${y}" y2="${y}"/>` +
           `<text class="reflabel ${cls}" x="${s.w - M.r - 2}" y="${y - 3}" text-anchor="end">${esc(label)}</text>`;
  }

  function legend(items) {
    return `<div class="legend">${items.map(([cls, text]) => `<span><i class="sw ${cls}"></i>${esc(text)}</span>`).join('')}</div>`;
  }
  function svg(inner, o = {}) {
    return `<svg class="chart" viewBox="0 0 ${o.width || W} ${o.height || H}" role="img" aria-label="${esc(o.label || 'chart')}">${inner}</svg>`;
  }

  /* series: [{cls, points:[[x,y,title?]], step?, dots?, hollow?, noLine?}], refs: [{y, cls, label}] */
  function line(series, o = {}) {
    const xs = series.flatMap(s => s.points.map(p => p[0])), ys = series.flatMap(s => s.points.map(p => p[1])).concat((o.refs || []).filter(r => o.includeRefs).map(r => r.y));
    if (!xs.length && !(o.refs || []).length) return '<p class="muted">No data yet.</p>';
    const s = scales(xs, ys, o);
    let out = frame(s, o);
    for (const r of o.refs || []) out += hline(s, r.y, r.cls, r.label);
    for (const ser of series) {
      const pts = ser.points.filter(p => p[1] != null);
      if (!pts.length) continue;
      if (!ser.noLine) {
        let d = '';
        pts.forEach((p, i) => {
          const x = s.sx(p[0]), y = s.sy(p[1]);
          d += i === 0 ? `M${x},${y}` : ser.step ? `H${x}V${y}` : `L${x},${y}`;
        });
        if (ser.step && o.extendTo != null) d += `H${s.sx(o.extendTo)}`;
        out += `<path class="line ${ser.cls}" d="${d}"/>`;
      }
      if (ser.dots !== false) {
        for (const p of pts) {
          out += `<circle class="dot ${ser.cls}${ser.hollow ? ' hollow' : ''}" cx="${s.sx(p[0])}" cy="${s.sy(p[1])}" r="${ser.r || 3.5}"><title>${esc(p[2] ?? `${dur(p[0])}: ${p[1]}`)}</title></circle>`;
        }
      }
    }
    return svg(out, o) + (o.legend ? legend(o.legend) : '');
  }

  /* Stacked bars: bars:[{label, parts:[v...], title}], layers:[{cls,label}] */
  function stacked(bars, layers, o = {}) {
    if (!bars.length) return '<p class="muted">No data yet.</p>';
    const totals = bars.map(b => b.parts.reduce((a, v) => a + (v || 0), 0));
    const s = scales([0, bars.length], totals, {...o, xMin: 0, xMax: bars.length, yMin: 0});
    let out = frame(s, {...o, fmtX: v => Number.isInteger(v) && v > 0 ? String(v) : ''});
    for (const r of o.refs || []) out += hline(s, r.y, r.cls, r.label);
    const slot = (s.w - M.l - M.r) / bars.length, bw = Math.max(1.5, slot * 0.72);
    bars.forEach((bar, i) => {
      let acc = 0;
      const x = s.sx(i) + (slot - bw) / 2;
      bar.parts.forEach((v, k) => {
        if (!v) return;
        const y1 = s.sy(acc), y2 = s.sy(acc + v);
        out += `<rect class="bar ${layers[k].cls}" x="${x}" y="${y2}" width="${bw}" height="${Math.max(0.5, y1 - y2)}"><title>${esc(bar.title || '')}</title></rect>`;
        acc += v;
      });
    });
    return svg(out, o) + legend(layers.map(l => [l.cls, l.label]));
  }

  window.Charts = {esc, dur, line, stacked, niceTicks, legend, M, W, H};
})();
