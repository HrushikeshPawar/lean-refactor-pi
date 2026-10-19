#!/usr/bin/env python3
"""Build the self-contained, offline V7/V8 run timing report."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUMMARY = ROOT / "tools/audits/run-timing-2026-10-18/summary.json"
DEFAULT_CSV = ROOT / "tools/audits/run-timing-2026-10-18/runs.csv"
DEFAULT_OUTPUT = ROOT / "docs/reports/V7_V8_TIMING_2026-10-18.html"

CSS = r"""
:root {
  color-scheme: light;
  --paper: #f4f1e9;
  --panel: #fffdf8;
  --ink: #172820;
  --muted: #637168;
  --line: #d9ded5;
  --deep: #173c35;
  --deep-2: #244c42;
  --llm: #247765;
  --tools: #d66d44;
  --setup: #7a91b1;
  --tail: #e3b94f;
  --gaps: #9aaa79;
  --shadow: 0 16px 44px rgba(26, 50, 41, .08);
  --radius: 18px;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--paper); color: var(--ink); line-height: 1.5; }
a { color: #1d6657; text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: #a84e30; }
button, input, select { font: inherit; }
button, select, input { color: var(--ink); }
button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible, th button:focus-visible {
  outline: 3px solid #e5a249; outline-offset: 3px;
}
.skip { position: absolute; left: 1rem; top: -4rem; background: white; padding: .7rem 1rem; z-index: 10; }
.skip:focus { top: 1rem; }
.hero { background: var(--deep); color: #f7f4eb; padding: 2.1rem max(1.25rem, calc((100vw - 1240px)/2)) 2rem; }
.hero-top, .hero-links { display: flex; justify-content: space-between; gap: 1rem; align-items: center; }
.eyebrow { text-transform: uppercase; letter-spacing: .14em; font-size: .72rem; font-weight: 760; color: #c2d1c5; }
.hero-links a { color: #e0e9df; font-size: .88rem; }
h1 { font-family: Georgia, "Times New Roman", serif; font-weight: 500; letter-spacing: -.045em; font-size: clamp(2.5rem, 6vw, 5.3rem); line-height: .98; max-width: 900px; margin: 2.2rem 0 1.1rem; }
.deck { color: #dce7dc; max-width: 770px; font-size: clamp(1rem, 1.5vw, 1.2rem); margin: 0; }
.hero-meta { display: flex; flex-wrap: wrap; gap: .55rem; margin-top: 1.55rem; }
.pill { display: inline-flex; align-items: center; border: 1px solid rgba(239,245,234,.28); border-radius: 999px; padding: .3rem .7rem; font-size: .78rem; color: #e4ece3; }
main { width: min(1240px, calc(100% - 2rem)); margin: 1.5rem auto 4rem; }
.toolbar { position: sticky; top: 0; z-index: 5; margin: 0 0 1.1rem; background: rgba(244,241,233,.94); backdrop-filter: blur(12px); border: 1px solid var(--line); border-radius: 14px; padding: .7rem .85rem; display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; box-shadow: 0 6px 20px rgba(23,56,46,.06); }
.toolbar label { font-weight: 700; font-size: .86rem; }
.toolbar select, .toolbar input { min-height: 40px; border: 1px solid #cbd3c9; border-radius: 9px; background: var(--panel); padding: .45rem .7rem; }
.toolbar input { flex: 1; min-width: 210px; }
.toolbar .result-count { margin-left: auto; font-size: .82rem; color: var(--muted); }
.section { margin: 1.2rem 0 1.5rem; }
.section-heading { display: flex; justify-content: space-between; align-items: end; gap: 1.25rem; margin: 0 0 .85rem; }
.section-heading h2 { font: 500 clamp(1.55rem,3vw,2.2rem)/1.1 Georgia, "Times New Roman", serif; letter-spacing: -.025em; margin: 0; }
.section-heading p { max-width: 650px; color: var(--muted); margin: 0; font-size: .94rem; }
.grid { display: grid; gap: 1rem; }
.kpis { grid-template-columns: repeat(4, minmax(0,1fr)); }
.two { grid-template-columns: repeat(2, minmax(0,1fr)); }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: clamp(1rem,2vw,1.4rem); min-width: 0; }
.kpi { min-height: 132px; position: relative; overflow: hidden; }
.kpi::after { content: ""; position: absolute; width: 75px; height: 75px; border-radius: 50%; right: -20px; bottom: -28px; background: #e8efe4; }
.kpi-label { color: var(--muted); text-transform: uppercase; letter-spacing: .08em; font-size: .7rem; font-weight: 800; }
.kpi-value { display: block; font: 500 clamp(1.55rem,2.6vw,2.25rem)/1.15 Georgia, "Times New Roman", serif; margin-top: .45rem; font-variant-numeric: tabular-nums; }
.kpi-note { display: block; color: var(--muted); font-size: .79rem; margin-top: .3rem; }
.chart-wrap { min-width: 0; overflow-x: auto; }
svg.chart { display: block; width: 100%; height: auto; overflow: visible; }
.legend { display: flex; flex-wrap: wrap; gap: .55rem 1rem; color: var(--muted); font-size: .8rem; margin: .65rem 0 0; }
.legend-item { display: inline-flex; align-items: center; gap: .4rem; }
.swatch { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
.chart-note { color: var(--muted); font-size: .81rem; margin: .65rem 0 0; }
.axis-label { fill: #6b786f; font-size: 11px; }
.chart-label { fill: #26392f; font-size: 12px; }
.bar-value { fill: #fff; font-size: 11px; font-weight: 750; }
.bar-value.dark { fill: #25372e; }
.plot-title { font-size: .8rem; color: var(--muted); margin: 0 0 .5rem; }
.subpanel { background: #f8f7f0; border-radius: 12px; padding: .85rem; margin-top: .85rem; }
.subpanel h3 { margin: 0 0 .45rem; font-size: .95rem; }
.table-scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; }
table { width: 100%; border-collapse: collapse; font-size: .83rem; }
th, td { text-align: left; vertical-align: top; padding: .68rem .72rem; border-bottom: 1px solid #e7e9e2; }
thead th { position: sticky; top: 0; background: #edf1e9; color: #30453a; white-space: nowrap; font-size: .72rem; text-transform: uppercase; letter-spacing: .055em; }
tbody tr:hover { background: #f7f8f1; }
tbody tr:last-child td { border-bottom: 0; }
th button { background: none; border: 0; cursor: pointer; padding: 0; text-align: inherit; text-transform: inherit; letter-spacing: inherit; font: inherit; color: inherit; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .76rem; overflow-wrap: anywhere; }
.small { font-size: .76rem; color: var(--muted); }
.status { display: inline-block; border-radius: 999px; padding: .13rem .48rem; background: #e9eee6; color: #40574a; font-size: .72rem; white-space: nowrap; }
.status.none { background: #f8e7d9; color: #7b482b; }
.inspect { border: 1px solid #9bb7a8; background: #f4f8f1; color: #234e40; border-radius: 7px; padding: .32rem .5rem; cursor: pointer; font-size: .76rem; font-weight: 680; white-space: nowrap; }
.inspect:hover { background: #e4efe3; }
.empty { padding: 1rem; color: var(--muted); }
.callout { border-left: 4px solid var(--tools); background: #fff6eb; padding: .85rem 1rem; border-radius: 0 10px 10px 0; margin: .85rem 0; }
.callout strong { color: #733e28; }
.opportunities { counter-reset: opp; display: grid; gap: .7rem; }
.opportunity { display: grid; grid-template-columns: 2.25rem 1fr; gap: .8rem; align-items: start; padding: .85rem; border: 1px solid var(--line); background: #fbfaf5; border-radius: 12px; }
.opportunity::before { counter-increment: opp; content: counter(opp, decimal-leading-zero); color: #9a5c3d; font-weight: 800; font-variant-numeric: tabular-nums; }
.opportunity h3 { margin: 0 0 .2rem; font-size: .96rem; }
.opportunity p { margin: 0; font-size: .86rem; color: var(--muted); }
.timeline-head { display: flex; justify-content: space-between; gap: .8rem; align-items: start; flex-wrap: wrap; }
.timeline-head h3 { margin: 0; font: 500 1.4rem Georgia, "Times New Roman", serif; }
.timeline-meta { color: var(--muted); font-size: .82rem; margin: .45rem 0 .8rem; }
.timeline-lane { fill: #617168; font-size: 12px; }
.interval { stroke: rgba(23,40,32,.28); stroke-width: .7; }
.axis-line { stroke: #aeb8af; stroke-width: 1; }
.footer { border-top: 1px solid var(--line); margin-top: 2rem; padding-top: 1rem; color: var(--muted); font-size: .82rem; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2,minmax(0,1fr)); } .two { grid-template-columns: 1fr; } }
@media (max-width: 560px) {
  main { width: min(100% - 1rem, 1240px); margin-top: .5rem; }
  .hero { padding: 1.25rem 1rem 1.55rem; }
  .hero-top { align-items: start; flex-direction: column; }
  .hero-links { justify-content: start; flex-wrap: wrap; }
  .kpis { gap: .55rem; }
  .kpi { padding: .85rem; min-height: 112px; }
  .kpi-value { font-size: 1.55rem; }
  .section-heading { align-items: start; flex-direction: column; }
  .toolbar { position: static; }
  .toolbar .result-count { margin-left: 0; width: 100%; }
  svg.chart { min-width: 960px; }
  th, td { padding: .55rem; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
@media print {
  :root { --paper: #fff; --panel: #fff; --shadow: none; }
  body { background: #fff; font-size: 10pt; }
  .hero { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  .toolbar, .inspect, .skip { display: none !important; }
  main { width: 100%; margin: .5rem 0; }
  .panel { box-shadow: none; break-inside: avoid; }
  .grid { break-inside: avoid; }
  table { font-size: 7pt; }
  thead th { position: static; }
  a { color: inherit; }
}
"""

JS = r"""
(() => {
  const DATA = JSON.parse(document.getElementById('report-data').textContent);
  const families = DATA.families;
  const models = DATA.models;
  const familySelect = document.getElementById('family-filter');
  const searchInput = document.getElementById('run-search');
  const sortSelect = document.getElementById('run-sort');
  const tableBody = document.getElementById('run-rows');
  const COLORS = { llm:'#247765', tools:'#d66d44', setup:'#7a91b1', tail:'#e3b94f', gaps:'#9aaa79' };
  const CAT_KEYS = ['llm','tools','setup','tail','gaps'];
  const CAT_LABELS = { llm:'LLM activity', tools:'Tool activity · exclusive', setup:'Setup / no provider', tail:'After final trace', gaps:'Interactive gaps' };
  const MODEL_COLORS = ['#226f61','#ce6741','#748cab','#8d7d57'];
  const TOOL_COLORS = ['#ce6741','#bc795d','#a98975','#8a987d','#688e83','#70849e','#8f80a4'];
  let chosenFamily = 'all';
  let chosenRun = null;
  let sortKey = 'observed_wall_s';
  let sortDirection = -1;

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const hours = seconds => (Number(seconds || 0) / 3600);
  const fmtH = seconds => `${hours(seconds).toFixed(2)} h`;
  const fmtCompactH = seconds => `${hours(seconds).toFixed(1)} h`;
  const fmtPct = (part, total) => total ? `${(100*part/total).toFixed(1)}%` : '0.0%';
  const fmtSec = (value, places=1) => value == null ? '—' : `${Number(value).toFixed(places)} s`;
  const fmtNum = value => Number(value || 0).toLocaleString('en-US');
  const fmtSpan = seconds => {
    const s=Math.max(0,Math.round(Number(seconds||0))), h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60;
    return h ? `${h}h ${String(m).padStart(2,'0')}m` : m ? `${m}m ${String(sec).padStart(2,'0')}s` : `${sec}s`;
  };
  const quantile = (values, q) => {
    if (!values.length) return null;
    const a=values.slice().sort((x,y)=>x-y), position=(a.length-1)*q, lo=Math.floor(position), hi=Math.ceil(position);
    return a[lo] + (a[hi]-a[lo])*(position-lo);
  };
  const sum = (items, fn) => items.reduce((a,x)=>a+(Number(fn(x))||0),0);
  const mergeIntervals = intervals => {
    const a=intervals.filter(x=>x&&x.length>=2&&x[1]>x[0]).map(x=>[Number(x[0]),Number(x[1])]).sort((x,y)=>x[0]-y[0]);
    const out=[];
    for (const item of a) { const last=out[out.length-1]; if (last&&item[0]<=last[1]) last[1]=Math.max(last[1],item[1]); else out.push(item); }
    return out;
  };
  const globalUnion = runs => mergeIntervals(runs.map(r=>[r.start,r.end])).reduce((a,x)=>a+x[1]-x[0],0);
  const currentRuns = () => DATA.runs.filter(r=>chosenFamily==='all'||r.family===chosenFamily);
  const selectedIndices = runs => new Set(runs.map(r=>r.i));
  const selectedRequests = runs => { const ids=selectedIndices(runs); return DATA.requests.filter(r=>ids.has(r[0])); };
  const selectedTools = runs => { const ids=selectedIndices(runs); return DATA.tools.filter(t=>ids.has(t[0])); };
  const totals = runs => ({
    observed_wall_s:sum(runs,r=>r.observed_wall_s), llm:sum(runs,r=>r.llm_union_s),
    tools:sum(runs,r=>r.tool_exclusive_s), setup:sum(runs,r=>r.before_first_request_s),
    tail:sum(runs,r=>r.after_last_trace_s), gaps:sum(runs,r=>r.interactive_unattributed_s),
    union:globalUnion(runs)
  });
  const scaleSvg = (width,height,body,label) => `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title>${body}</svg>`;
  const legendHtml = items => `<div class="legend">${items.map(x=>`<span class="legend-item"><i class="swatch" style="background:${x.color}" aria-hidden="true"></i>${esc(x.label)}</span>`).join('')}</div>`;
  const categoryItems = CAT_KEYS.map(k=>({label:CAT_LABELS[k],color:COLORS[k]}));
  const noData = message => `<p class="empty">${esc(message)}</p>`;

  function fillFilters() {
    familySelect.innerHTML = `<option value="all">All families · ${DATA.runs.length} runs</option>` + families.map(f=>`<option value="${esc(f)}">${esc(f)} · ${DATA.runs.filter(r=>r.family===f).length} runs</option>`).join('');
  }

  function renderKpis(runs, t, requests) {
    const reqTimes=requests.map(x=>x[2]);
    const p95=quantile(reqTimes,.95);
    const requestsWithProvider=runs.filter(r=>r.request_count>0).length;
    const share=fmtPct(t.llm,t.observed_wall_s);
    $('kpi-runs').textContent=fmtNum(runs.length);
    $('kpi-runs-note').textContent=`${requestsWithProvider} with completed provider calls · ${runs.length-requestsWithProvider} without`;
    $('kpi-run-hours').textContent=fmtH(t.observed_wall_s);
    $('kpi-run-hours-note').textContent='summed observed spans across runs';
    $('kpi-wall-union').textContent=fmtH(t.union);
    $('kpi-wall-union-note').textContent='global union; concurrent runs overlap';
    $('kpi-requests').textContent=fmtNum(requests.length);
    $('kpi-requests-note').textContent=`actual completed calls · p95 ${fmtSec(p95)}`;
    $('summary-scope').textContent=chosenFamily==='all'?'All 66 audited runs':`${chosenFamily} · ${runs.length} runs`;
    $('headline-share').textContent=share;
  }

  function renderOverallStack(t) {
    const width=1050, x0=16, y=36, barH=44, barW=width-32, total=t.observed_wall_s||1;
    let x=x0, body=`<text x="${x0}" y="19" class="chart-label" font-weight="700">${esc(chosenFamily==='all'?'All audited runs':chosenFamily)} · ${fmtH(total)} summed observed activity</text>`;
    CAT_KEYS.forEach((k,i)=>{
      const value=t[k], w=barW*value/total;
      if(w>0){body+=`<rect x="${x}" y="${y}" width="${Math.max(w,.4)}" height="${barH}" fill="${COLORS[k]}" rx="${i===0?7:0}" ry="7"><title>${esc(CAT_LABELS[k])}: ${fmtH(value)} (${fmtPct(value,total)})</title></rect>`;
        if(w>82)body+=`<text x="${x+w/2}" y="${y+27}" text-anchor="middle" class="bar-value">${fmtCompactH(value)}</text>`;
        x+=w;
      }
    });
    body+=`<text x="${x0}" y="97" class="axis-label">0 h</text><text x="${width-16}" y="97" text-anchor="end" class="axis-label">${fmtH(total)}</text>`;
    $('overall-stack').innerHTML=scaleSvg(width,106,body,'Stacked observed activity duration: LLM activity, exclusive tool activity, setup or no-provider runs, after-final-trace tail, and interactive gaps.')+legendHtml(categoryItems);
    $('overall-stack-note').textContent=`LLM share of summed observed span: ${fmtPct(t.llm,total)}. Tool calls may overlap; the stacked tool segment is the exclusive union portion.`;
  }

  function renderFamilyChart(runs) {
    const visibleFamilies=chosenFamily==='all'?families:[chosenFamily];
    const rows=visibleFamilies.map(f=>{
      const rs=runs.filter(r=>r.family===f), t=totals(rs);
      return {family:f,runs:rs.length,total:t.observed_wall_s,...Object.fromEntries(CAT_KEYS.map(k=>[k,t[k]]))};
    });
    const width=1050,left=115,right=100,top=22,rowH=42,barW=width-left-right,height=top+rows.length*rowH+23;
    const max=Math.max(...rows.map(r=>r.total),1); let body='';
    rows.forEach((r,i)=>{
      const y=top+i*rowH+5; body+=`<text x="${left-12}" y="${y+18}" text-anchor="end" class="chart-label" font-weight="700">${esc(r.family)}</text>`;
      let x=left;
      CAT_KEYS.forEach(k=>{const w=barW*r[k]/max;if(w>0){body+=`<rect x="${x}" y="${y}" width="${Math.max(w,.5)}" height="24" fill="${COLORS[k]}" rx="3"><title>${esc(r.family)} — ${esc(CAT_LABELS[k])}: ${fmtH(r[k])} (${fmtPct(r[k],r.total)})</title></rect>`;x+=w;}});
      body+=`<text x="${left+barW+10}" y="${y+17}" class="chart-label">${fmtH(r.total)}</text>`;
    });
    body+=`<line x1="${left}" y1="${height-18}" x2="${left+barW}" y2="${height-18}" class="axis-line"/>`;
    [0,.25,.5,.75,1].forEach(p=>{const x=left+barW*p;body+=`<line x1="${x}" y1="${height-21}" x2="${x}" y2="${height-14}" class="axis-line"/><text x="${x}" y="${height-3}" text-anchor="middle" class="axis-label">${(max*p/3600).toFixed(1)} h</text>`;});
    $('family-chart').innerHTML=scaleSvg(width,height,body,'Stacked observed activity hours by family. Each family shares a common horizontal scale.')+legendHtml(categoryItems);
    $('family-chart-note').textContent=`Common scale across ${rows.length} ${rows.length===1?'selected family':'families'}; each bar is the sum of its run spans, not elapsed calendar time.`;
    $('family-table').innerHTML=`<div class="table-scroll"><table><thead><tr><th>Family</th><th class="num">Runs</th>${CAT_KEYS.map(k=>`<th class="num">${esc(CAT_LABELS[k])}</th>`).join('')}<th class="num">Total</th></tr></thead><tbody>${rows.map(r=>`<tr><th scope="row">${esc(r.family)}</th><td class="num">${r.runs}</td>${CAT_KEYS.map(k=>`<td class="num">${fmtH(r[k])}<br><span class="small">${fmtPct(r[k],r.total)}</span></td>`).join('')}<td class="num"><strong>${fmtH(r.total)}</strong></td></tr>`).join('')}</tbody></table></div>`;
  }

  const HIST_BINS=[0,5,10,20,40,60,90,180,300,Infinity];
  const HIST_LABELS=['0–5','5–10','10–20','20–40','40–60','60–90','90–180','180–300','300+'];
  function modelStats(requests) {
    return models.map((name,mi)=>{
      const rows=requests.filter(r=>r[1]===mi), vals=rows.map(r=>r[2]);
      return {name,mi,n:rows.length,failed:rows.filter(r=>r[3]).length,retry:rows.filter(r=>r[4]).length,
        mean:vals.length?sum(vals,x=>x)/vals.length:null,p50:quantile(vals,.5),p90:quantile(vals,.9),p95:quantile(vals,.95),max:vals.length?Math.max(...vals):null,values:vals};
    }).filter(x=>x.n>0);
  }
  function renderRequestHistogram(requests) {
    if(!requests.length){$('request-hist').innerHTML=noData('No completed provider requests in this selection. The three provider-free runs remain visible in the run table.');$('model-stats').innerHTML='';return;}
    const stats=modelStats(requests), width=1050,height=335,left=55,right=20,top=25,bottom=57,plotW=width-left-right,plotH=height-top-bottom;
    const perModel=stats.map(s=>{const bins=HIST_BINS.slice(0,-1).map((lo,i)=>requests.filter(r=>r[1]===s.mi&&r[2]>=lo&&r[2]<(HIST_BINS[i+1]??Infinity)).length);return {...s,bins};});
    const maxPct=Math.max(...perModel.flatMap(m=>m.bins.map(n=>100*n/m.n)),1), scaleMax=Math.ceil(maxPct/10)*10;
    let body='';
    for(let i=0;i<=4;i++){const p=scaleMax*i/4,y=top+plotH*(1-p/scaleMax);body+=`<line x1="${left}" y1="${y}" x2="${left+plotW}" y2="${y}" stroke="#e3e7df"/><text x="${left-8}" y="${y+4}" text-anchor="end" class="axis-label">${p.toFixed(0)}%</text>`;}
    const groupW=plotW/HIST_LABELS.length, gap=3, barW=Math.min(15,(groupW-8)/Math.max(stats.length,1));
    HIST_LABELS.forEach((label,bi)=>{
      const gx=left+bi*groupW; perModel.forEach((m,mi)=>{
        const pct=100*m.bins[bi]/m.n,h=plotH*pct/scaleMax,x=gx+(groupW-(stats.length*barW+(stats.length-1)*gap))/2+mi*(barW+gap),y=top+plotH-h;
        if(h>0)body+=`<rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="2" fill="${MODEL_COLORS[m.mi%MODEL_COLORS.length]}"><title>${esc(m.name)} · ${label} seconds: ${m.bins[bi]} requests (${pct.toFixed(1)}% of model)</title></rect>`;
      });
      body+=`<text x="${gx+groupW/2}" y="${height-27}" text-anchor="middle" class="axis-label">${label}</text>`;
    });
    body+=`<text transform="translate(15 ${top+plotH/2}) rotate(-90)" text-anchor="middle" class="axis-label">Share of each model’s requests</text>`;
    $('request-hist').innerHTML=scaleSvg(width,height,body,`Histogram of ${fmtNum(requests.length)} completed provider request durations, grouped by duration bin and model.`)+legendHtml(stats.map(s=>({label:`${s.name} · n=${fmtNum(s.n)}`,color:MODEL_COLORS[s.mi%MODEL_COLORS.length]})));
    $('model-stats').innerHTML=`<div class="table-scroll"><table><thead><tr><th>Model</th><th class="num">n</th><th class="num">Mean</th><th class="num">p50</th><th class="num">p90</th><th class="num">p95</th><th class="num">Max</th><th class="num">Retries</th><th class="num">Failures</th></tr></thead><tbody>${stats.map(s=>`<tr><th scope="row">${esc(s.name)}</th><td class="num">${fmtNum(s.n)}</td><td class="num">${fmtSec(s.mean)}</td><td class="num">${fmtSec(s.p50)}</td><td class="num">${fmtSec(s.p90)}</td><td class="num"><strong>${fmtSec(s.p95)}</strong></td><td class="num">${fmtSec(s.max)}</td><td class="num">${fmtNum(s.retry)}</td><td class="num">${fmtNum(s.failed)}</td></tr>`).join('')}</tbody></table></div>`;
    $('request-hist-note').textContent=`Each bar shows the percentage of that model’s completed requests in the bin; counts and interpolated percentiles are listed below. Durations are end minus request start from matched request/response trace records.`;
  }

  function renderToolChart(tools) {
    if(!tools.length){$('tool-chart').innerHTML=noData('No completed tool calls in this selection.');$('tool-stats').innerHTML='';return;}
    const names=DATA.toolNames;
    const rows=names.map((name,i)=>{const a=tools.filter(t=>t[1]===i),vals=a.map(t=>t[2]);return {name,i,n:a.length,failed:a.filter(t=>t[3]).length,sum:sum(vals,x=>x),p50:quantile(vals,.5),p95:quantile(vals,.95),max:vals.length?Math.max(...vals):0};}).filter(x=>x.n).sort((a,b)=>b.sum-a.sum);
    const width=1050,left=108,right=100,top=16,rowH=39,barW=width-left-right,height=top+rows.length*rowH+22,max=Math.max(...rows.map(r=>r.sum),1);let body='';
    rows.forEach((r,i)=>{const y=top+i*rowH+3,w=barW*r.sum/max;body+=`<text x="${left-10}" y="${y+16}" text-anchor="end" class="chart-label" font-weight="700">${esc(r.name)}</text><rect x="${left}" y="${y}" width="${w}" height="22" rx="4" fill="${TOOL_COLORS[r.i%TOOL_COLORS.length]}"><title>${esc(r.name)}: ${fmtH(r.sum)} across ${fmtNum(r.n)} calls; p95 ${fmtSec(r.p95)}</title></rect><text x="${left+w+9}" y="${y+16}" class="chart-label">${fmtH(r.sum)}</text>`;});
    $('tool-chart').innerHTML=scaleSvg(width,height,body,'Recorded elapsed duration by tool name. Tool calls may overlap with one another and with other activity.')+`<p class="chart-note">${fmtNum(tools.length)} completed tool calls · ${fmtH(sum(tools,t=>t[2]))} sum of individual call durations. The top-level stacked report uses exclusive tool activity to avoid overlap double-counting.</p>`;
    $('tool-stats').innerHTML=`<div class="table-scroll"><table><thead><tr><th>Tool</th><th class="num">Calls</th><th class="num">Total call time</th><th class="num">p50</th><th class="num">p95</th><th class="num">Max</th><th class="num">Failed</th></tr></thead><tbody>${rows.map(r=>`<tr><th scope="row">${esc(r.name)}</th><td class="num">${fmtNum(r.n)}</td><td class="num">${fmtH(r.sum)}</td><td class="num">${fmtSec(r.p50)}</td><td class="num">${fmtSec(r.p95)}</td><td class="num">${fmtSec(r.max)}</td><td class="num">${fmtNum(r.failed)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function renderV8c(runs) {
    const panel=$('v8c-panel');
    if(chosenFamily!=='all'&&chosenFamily!=='v8c'){panel.hidden=true;return;}
    panel.hidden=false;
    const cases=runs.filter(r=>r.family==='v8c').sort((a,b)=>a.start-b.start);
    if(!cases.length){$('v8c-chart').innerHTML=noData('No v8c runs in this selection.');return;}
    const width=1100,left=285,right=115,top=16,rowH=46,barW=width-left-right,height=top+cases.length*rowH+25,max=Math.max(...cases.map(r=>r.observed_wall_s),1);let body='';
    cases.forEach((r,i)=>{
      const y=top+i*rowH+4,label=(r.theorem||r.run).replace(/^Binius\.BinaryBasefold\./,'').replace(/^Cslib\.CCS\./,'');
      body+=`<text x="${left-11}" y="${y+16}" text-anchor="end" class="chart-label" font-weight="700">${esc(label.slice(0,38))}${label.length>38?'…':''}<title>${esc(r.theorem)}</title></text>`;
      let x=left;
      const runKey={llm:'llm_union_s',tools:'tool_exclusive_s',setup:'before_first_request_s',tail:'after_last_trace_s',gaps:'interactive_unattributed_s'};
      CAT_KEYS.forEach(k=>{const value=r[runKey[k]],w=barW*value/max;if(w>0){body+=`<rect x="${x}" y="${y}" width="${w}" height="23" fill="${COLORS[k]}" rx="3"><title>${esc(r.run)} — ${esc(CAT_LABELS[k])}: ${fmtH(value)}</title></rect>`;x+=w;}});
      body+=`<text x="${left+barW+9}" y="${y+16}" class="chart-label">${fmtH(r.observed_wall_s)}</text><text x="${left+barW+9}" y="${y+31}" class="axis-label">${r.request_count} calls</text>`;
    });
    $('v8c-chart').innerHTML=scaleSvg(width,height,body,'Five v8c runs shown as stacked observed activity spans on a common scale.')+legendHtml(categoryItems);
    $('v8c-table').innerHTML=`<div class="table-scroll"><table><thead><tr><th>Run / theorem</th><th class="num">Observed</th><th class="num">LLM</th><th class="num">Tools</th><th class="num">Setup</th><th class="num">Tail</th><th class="num">Gaps</th><th class="num">Best full proxy</th><th class="num">LLM after best</th></tr></thead><tbody>${cases.map(r=>`<tr><th scope="row">${esc(r.theorem)}<br><span class="small mono">${esc(r.run)}</span></th><td class="num">${fmtH(r.observed_wall_s)}</td><td class="num">${fmtH(r.llm_union_s)}<br><span class="small">${fmtPct(r.llm_union_s,r.observed_wall_s)}</span></td><td class="num">${fmtH(r.tool_exclusive_s)}<br><span class="small">${fmtPct(r.tool_exclusive_s,r.observed_wall_s)}</span></td><td class="num">${fmtH(r.before_first_request_s)}</td><td class="num">${fmtH(r.after_last_trace_s)}<br><span class="small">${fmtPct(r.after_last_trace_s,r.observed_wall_s)}</span></td><td class="num">${fmtH(r.interactive_unattributed_s)}</td><td class="num">${r.best_full_proxy==null?'—':Number(r.best_full_proxy).toFixed(2)}</td><td class="num">${fmtH(r.llm_after_last_best_s)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function renderRunTable(runs) {
    const query=searchInput.value.trim().toLowerCase();
    const rows=runs.filter(r=>!query||[r.run,r.family,r.model,r.theorem,r.stop_reason].join(' ').toLowerCase().includes(query));
    rows.sort((a,b)=>{const av=a[sortKey],bv=b[sortKey];if(typeof av==='string'||typeof bv==='string')return String(av??'').localeCompare(String(bv??''))*sortDirection;return ((Number(av)||0)-(Number(bv)||0))*sortDirection;});
    $('table-count').textContent=`${rows.length} of ${runs.length} selected runs`;
    $('run-rows').innerHTML=rows.map(r=>`<tr><th scope="row"><button class="inspect" data-run="${r.i}" aria-label="Inspect timeline for ${esc(r.run)}">Inspect</button><div class="mono">${esc(r.run)}</div></th><td><span class="status">${esc(r.family)}</span></td><td>${esc(r.theorem||'—')}</td><td>${esc(r.model||'—')}</td><td class="num">${fmtNum(r.request_count)}<br><span class="small">${r.request_count?'completed':'no completed calls'}</span></td><td class="num">${fmtH(r.observed_wall_s)}</td><td class="num">${fmtH(r.llm_union_s)}</td><td class="num">${fmtH(r.tool_exclusive_s)}</td><td class="num">${fmtH(r.after_last_trace_s)}</td><td><span class="status ${r.stop_reason==='finished'?'':'none'}">${esc(r.stop_reason||'not recorded')}</span></td></tr>`).join('');
    if(!rows.length)tableBody.innerHTML=`<tr><td colspan="10">${noData('No runs match this search.')}</td></tr>`;
  }

  function renderTimeline(runId) {
    const r=DATA.runs.find(x=>x.i===Number(runId)); if(!r)return;
    chosenRun=r.i;
    const card=$('timeline-panel');card.hidden=false;
    $('timeline-title').textContent=r.theorem||r.run;
    $('timeline-run').textContent=`${r.run} · ${r.family} · ${r.model||'No provider journal'} · ${r.request_count} completed calls`;
    $('timeline-facts').innerHTML=[
      ['Observed activity span',fmtH(r.observed_wall_s)],['LLM interval union',fmtH(r.llm_union_s)],['Tool-exclusive union',fmtH(r.tool_exclusive_s)],
      ['Setup / no-provider',fmtH(r.before_first_request_s)],['After final trace',fmtH(r.after_last_trace_s)],['Interactive gaps',fmtH(r.interactive_unattributed_s)],
      ['Unmatched requests',fmtNum(r.missing_response_count)],['Orphan responses excluded',fmtNum(r.orphan_response_count)],['Inherited ledger events excluded',fmtNum(r.inherited_ledger_events_excluded)]
    ].map(x=>`<div class="kpi"><span class="kpi-label">${esc(x[0])}</span><strong class="kpi-value" style="font-size:1.1rem">${esc(x[1])}</strong></div>`).join('');
    const start=r.start,end=r.end,duration=Math.max(end-start,.001),width=1100,left=125,right=24,top=36,plotW=width-left-right,height=184;
    let body=`<line x1="${left}" y1="${top+62}" x2="${left+plotW}" y2="${top+62}" class="axis-line"/><line x1="${left}" y1="${top+116}" x2="${left+plotW}" y2="${top+116}" class="axis-line"/>`;
    body+=`<text x="${left-12}" y="${top+51}" text-anchor="end" class="timeline-lane">LLM</text><text x="${left-12}" y="${top+105}" text-anchor="end" class="timeline-lane">Tools</text>`;
    const draw=(intervals,y,color,label)=>intervals.forEach(([a,b],i)=>{const x=left+Math.max(0,(a-start)/duration)*plotW,w=Math.max(1,(b-a)/duration*plotW);body+=`<rect class="interval" x="${x}" y="${y}" width="${Math.min(w,left+plotW-x)}" height="27" rx="3" fill="${color}"><title>${label} ${i+1}: ${new Date(a*1000).toISOString()} – ${new Date(b*1000).toISOString()} · ${fmtSec(b-a,2)}</title></rect>`;});
    draw(r.llm_intervals,top+37,COLORS.llm,'LLM union interval');draw(r.tool_intervals,top+91,COLORS.tools,'Tool union interval');
    for(let i=0;i<=4;i++){const p=i/4,x=left+plotW*p,epoch=start+duration*p;body+=`<line x1="${x}" y1="${top+129}" x2="${x}" y2="${top+136}" class="axis-line"/><text x="${x}" y="${top+155}" text-anchor="${i===0?'start':i===4?'end':'middle'}" class="axis-label">${new Date(epoch*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</text>`;}
    $('timeline-chart').innerHTML=scaleSvg(width,height,body,'Run timeline using Unix epoch-second interval data; horizontal labels show local clock time and tooltips contain exact ISO timestamps.');
    $('timeline-epoch').textContent=`Epoch start ${r.start.toFixed(3)} · end ${r.end.toFixed(3)} · ${new Date(r.start*1000).toISOString()} to ${new Date(r.end*1000).toISOString()}`;
    $('timeline-empty').hidden=Boolean(r.llm_intervals.length||r.tool_intervals.length);
    card.scrollIntoView({behavior:'smooth',block:'start'});
  }

  function renderOpportunities() {
    const overall=DATA.aggregate;
    const deep=overall.models['deepseek-v4.1-flash'].duration;
    const deepHdr=overall.models['deepseek-v4.1-flash'].response_headers;
    const stream=overall.models['deepseek-v4.1-flash'].stream_after_headers;
    const comp=overall.tools.compile;
    $('opportunities').innerHTML=`
      <article class="opportunity"><div><h3>Reduce the longest provider wait, beginning with streaming latency</h3><p>DeepSeek accounts for ${fmtNum(deep.n)} of the ${fmtNum(overall.request_latency.n)} completed requests. Its p95 duration is ${fmtSec(deep.p95_s)} (max ${fmtSec(deep.max_s)}); response headers p95 at ${fmtSec(deepHdr.p95_s)}, while stream-after-header p95 is ${fmtSec(stream.p95_s)}. This points investigation toward long response streams before broad tool changes.</p></div></article>
      <article class="opportunity"><div><h3>Inspect post-trace work in v8c runs with long tails</h3><p>Across five v8c runs, after-final-trace time is ${fmtPct(3481.2009,14442.1541)} of summed observed activity. Historical golf entries sum to 1,633.91 s, concentrated in Fiberwise, Wick time-order, and interleaved tensor-gap runs; current automatic golf is disabled, so treat this as historical workload to compare against current behavior.</p></div></article>
      <article class="opportunity"><div><h3>Prioritize compile-tool paths for tool-side profiling</h3><p>Compile is the largest individual tool category: ${fmtNum(comp.n)} calls and ${fmtH(comp.sum_s)} summed call time, with p95 ${fmtSec(comp.p95_s)}. Individual tool-call durations can overlap; the overall stacked chart instead uses exclusive tool-union time.</p></div></article>`;
  }

  function render() {
    const runs=currentRuns(), t=totals(runs), requests=selectedRequests(runs), tools=selectedTools(runs);
    renderKpis(runs,t,requests); renderOverallStack(t); renderFamilyChart(runs);
    renderRequestHistogram(requests); renderToolChart(tools); renderV8c(runs); renderRunTable(runs);
  }

  $('excluded-containers').textContent=DATA.excludedContainers.join(', ');
  $('scope-text').textContent=DATA.scope;
  fillFilters(); renderOpportunities(); render();
  familySelect.addEventListener('change',()=>{chosenFamily=familySelect.value;render();});
  searchInput.addEventListener('input',()=>renderRunTable(currentRuns()));
  sortSelect.addEventListener('change',()=>{const [key,dir]=sortSelect.value.split(':');sortKey=key;sortDirection=Number(dir);renderRunTable(currentRuns());});
  tableBody.addEventListener('click',event=>{const button=event.target.closest('[data-run]');if(button)renderTimeline(button.dataset.run);});
  document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{const key=button.dataset.sort;sortDirection=sortKey===key?-sortDirection:-1;sortKey=key;sortSelect.value=`${sortKey}:${sortDirection}`;renderRunTable(currentRuns());}));
})();
"""


def compact_data(summary: dict) -> dict:
    raw_runs = summary["runs"]
    run_index = {row["run"]: i for i, row in enumerate(raw_runs)}
    family_order = ["v7", "v7solo", "v8", "v8a", "v8b", "v8c"]
    model_names = sorted({row.get("model") for row in summary["requests"] if row.get("model")})
    tool_names = sorted({row.get("name") for row in summary["tools"] if row.get("name")})
    model_index = {name: i for i, name in enumerate(model_names)}
    tool_index = {name: i for i, name in enumerate(tool_names)}
    request_counts: dict[str, int] = {}
    for row in summary["requests"]:
        request_counts[row["run"]] = request_counts.get(row["run"], 0) + 1

    runs = []
    for i, row in enumerate(raw_runs):
        runs.append({
            "i": i,
            "run": row["run"],
            "family": row["family"],
            "model": row.get("model"),
            "theorem": row.get("theorem"),
            "stop_reason": row.get("stop_reason"),
            "start": row.get("start"),
            "end": row.get("end"),
            "observed_wall_s": row.get("observed_wall_s", 0),
            "request_count": request_counts.get(row["run"], 0),
            "missing_response_count": len(row.get("missing_response_ids") or []),
            "orphan_response_count": row.get("orphan_response_count", 0),
            "inherited_ledger_events_excluded": row.get("inherited_ledger_events_excluded", 0),
            "llm_union_s": row.get("llm_union_s", 0),
            "tool_exclusive_s": row.get("tool_exclusive_s", 0),
            "before_first_request_s": row.get("before_first_request_s", 0),
            "after_last_trace_s": row.get("after_last_trace_s", 0),
            "interactive_unattributed_s": row.get("interactive_unattributed_s", 0),
            "best_full_proxy": row.get("best_full_proxy"),
            "llm_after_last_best_s": row.get("llm_after_last_best_s"),
            # Keep the exact Unix epoch-second pairs from scan.py for timeline drilldown.
            "llm_intervals": row.get("llm_intervals", []),
            "tool_intervals": row.get("tool_intervals", []),
        })
    requests = [[run_index[row["run"]], model_index[row["model"]], row["seconds"],
                 bool(row.get("failed")), bool(row.get("retry"))]
                for row in summary["requests"] if row.get("model") in model_index]
    tools = [[run_index[row["run"]], tool_index[row["name"]], row["seconds"],
              bool(row.get("failed"))]
             for row in summary["tools"] if row.get("name") in tool_index]
    return {
        "families": family_order,
        "models": model_names,
        "toolNames": tool_names,
        "runs": runs,
        "requests": requests,
        "tools": tools,
        "aggregate": summary["aggregate"],
        "excludedContainers": summary.get("excluded_containers", []),
        "scope": summary.get("scope", ""),
    }


def build(summary_path: Path, csv_path: Path, output_path: Path) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    # Read the companion CSV as an input integrity check; charts and table share summary.json's richer data.
    with csv_path.open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != len(summary["runs"]):
        raise ValueError(f"runs.csv has {len(csv_rows)} rows, summary has {len(summary['runs'])} runs")
    data = compact_data(summary)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    generated = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="description" content="An offline interval-based timing report for 66 V7/V8 Lean Refactor Arena runs, with interactive charts and timelines.">
  <title>V7 / V8 timing audit · 18 October 2026</title>
  <style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to report</a>
<header class="hero">
  <div class="hero-top"><span class="eyebrow">Lean Refactor Arena · timing audit · 18 October 2026</span><div class="hero-links"><a href="V7_V8_TIMING_2026-10-18.md">Agent-facing Markdown</a><a href="../../tools/audits/run-timing-2026-10-18/runs.csv">Run-level CSV</a></div></div>
  <h1>Where the run hours went</h1>
  <p class="deck">An interval-based view of V7 and V8 campaigns: provider waits, tool activity, setup, and the work that continued after the last trace. Every number below is an <strong>observed activity span</strong>, not process wall time or CPU time.</p>
  <div class="hero-meta"><span class="pill">66 runs · 6 families</span><span class="pill">6,111 completed provider requests</span><span class="pill">offline · no external assets</span><span class="pill" id="summary-scope">All 66 audited runs</span></div>
</header>
<main id="main">
  <nav class="toolbar" aria-label="Report filters">
    <label for="family-filter">Family</label><select id="family-filter"></select>
    <label for="run-search">Find a run</label><input id="run-search" type="search" placeholder="theorem, model, or run id" autocomplete="off">
    <label for="run-sort">Sort table</label><select id="run-sort"><option value="observed_wall_s:-1">Longest observed span</option><option value="llm_union_s:-1">Most LLM activity</option><option value="tool_exclusive_s:-1">Most tool activity</option><option value="after_last_trace_s:-1">Longest tail</option><option value="start:1">Start time · oldest</option><option value="family:1">Family A–Z</option></select>
    <span class="result-count" id="table-count" aria-live="polite"></span>
  </nav>

  <section class="section" aria-labelledby="overview-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Current selection</span><h2 id="overview-title">The time ledger</h2></div><p>Run spans are summed for work attribution. The union across concurrent runs is shown separately so the total does not read like one sequential wall-clock campaign.</p></div>
    <div class="grid kpis">
      <article class="panel kpi"><span class="kpi-label">Runs in view</span><strong class="kpi-value" id="kpi-runs">—</strong><span class="kpi-note" id="kpi-runs-note">—</span></article>
      <article class="panel kpi"><span class="kpi-label">Summed observed span</span><strong class="kpi-value" id="kpi-run-hours">—</strong><span class="kpi-note" id="kpi-run-hours-note">—</span></article>
      <article class="panel kpi"><span class="kpi-label">Global wall union</span><strong class="kpi-value" id="kpi-wall-union">—</strong><span class="kpi-note" id="kpi-wall-union-note">—</span></article>
      <article class="panel kpi"><span class="kpi-label">Completed LLM requests</span><strong class="kpi-value" id="kpi-requests">—</strong><span class="kpi-note" id="kpi-requests-note">—</span></article>
    </div>
    <article class="panel" style="margin-top:1rem"><div class="section-heading"><h3 style="margin:0;font-size:1rem">Observed activity composition</h3><span class="small">LLM share · <strong id="headline-share">—</strong></span></div><div class="chart-wrap" id="overall-stack"></div><p class="chart-note" id="overall-stack-note"></p></article>
  </section>

  <section class="section" aria-labelledby="family-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Comparison</span><h2 id="family-title">Families on one scale</h2></div><p>Each family’s stacked bar uses the same hour scale. Pick a family above to isolate its composition; choose “All families” to compare the full set.</p></div>
    <article class="panel"><div class="chart-wrap" id="family-chart"></div><p class="chart-note" id="family-chart-note"></p><div id="family-table" class="subpanel"></div></article>
  </section>

  <section class="section" aria-labelledby="models-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Provider calls</span><h2 id="models-title">How long did each response take?</h2></div><p>Histogram bars show the share of each model’s completed calls in each duration bin. Failed responses with a matched end timestamp remain in the distribution.</p></div>
    <article class="panel"><p class="plot-title">Request duration · bins in seconds · filtered by selected family</p><div class="chart-wrap" id="request-hist"></div><p class="chart-note" id="request-hist-note"></p><div id="model-stats" class="subpanel"></div></article>
  </section>

  <section class="section" aria-labelledby="tools-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Tool calls</span><h2 id="tools-title">The tool-side mix</h2></div><p>Individual call duration by tool. These sums can overlap; the composition chart above uses exclusive tool activity.</p></div>
    <article class="panel"><div class="chart-wrap" id="tool-chart"></div><div id="tool-stats" class="subpanel"></div></article>
  </section>

  <section class="section" id="v8c-panel" aria-labelledby="v8c-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Focused comparison</span><h2 id="v8c-title">Five V8c runs, side by side</h2></div><p>These runs have a smaller LLM share and a larger post-trace tail than the aggregate. Hover or focus a segment for the exact category value.</p></div>
    <article class="panel"><div class="chart-wrap" id="v8c-chart"></div><p class="chart-note">Across the five V8c runs, LLM time is 38.5%, exclusive tools 26.7%, and after-final-trace tail 24.1% of summed observed activity.</p><div id="v8c-table" class="subpanel"></div><div class="callout"><strong>Historical work detail.</strong> The V8c ledgers record 1,633.91 s of golf activity, alongside other post-trace/background work. Current automatic golf is disabled; use these figures as historical comparison data, not a current expected cost.</div></article>
  </section>

  <section class="section" aria-labelledby="opportunity-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Evidence-led next questions</span><h2 id="opportunity-title">Where an investigation may pay off</h2></div><p>Ranked by observed time and request volume. These are prioritization cues, not projected savings.</p></div>
    <div class="opportunities" id="opportunities"></div>
  </section>

  <section class="section" aria-labelledby="runs-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Run explorer</span><h2 id="runs-title">Every observed run</h2></div><p>All 66 runs are included, including three with no provider journal and two more with unmatched request starts. Search, sort, and select a row to inspect its Unix-epoch interval timeline.</p></div>
    <article class="panel"><div class="table-scroll"><table id="runs-table"><thead><tr><th><button data-sort="run">Run</button></th><th><button data-sort="family">Family</button></th><th>Theorem</th><th>Model</th><th class="num">Calls</th><th class="num"><button data-sort="observed_wall_s">Observed</button></th><th class="num"><button data-sort="llm_union_s">LLM</button></th><th class="num"><button data-sort="tool_exclusive_s">Tools</button></th><th class="num"><button data-sort="after_last_trace_s">Tail</button></th><th>Stop</th></tr></thead><tbody id="run-rows"></tbody></table></div></article>
  </section>

  <section class="section" id="timeline-panel" aria-labelledby="timeline-title" hidden>
    <article class="panel"><div class="timeline-head"><div><span class="eyebrow" style="color:#637168">Run drilldown</span><h3 id="timeline-title"></h3><div class="timeline-meta" id="timeline-run"></div></div><a href="#runs-title">Back to run table</a></div><div class="grid kpis" id="timeline-facts" style="margin:1rem 0"></div><div class="chart-wrap" id="timeline-chart"></div><p class="small" id="timeline-epoch"></p><p class="empty" id="timeline-empty" hidden>This run has no matched LLM or tool intervals; the observed span is still present in the table.</p></article>
  </section>

  <section class="section" aria-labelledby="method-title">
    <div class="section-heading"><div><span class="eyebrow" style="color:#637168">Read this carefully</span><h2 id="method-title">Method and boundaries</h2></div><p>Interval accounting turns trace records into activity attribution. It does not turn the campaign into a process profile.</p></div>
    <article class="panel">
      <div class="grid two">
        <div><h3>What the report counts</h3><ul>
          <li>All 66 run directories under the audited V7/V8 scope; 63 have completed provider calls, three have no provider journal, and two more have unmatched request starts.</li>
          <li>6,111 matched request/response intervals in model latency percentiles and histograms.</li>
          <li>14 requests with no matched response have unknown completion time and are excluded from duration statistics.</li>
          <li>10 synthetic orphan responses are excluded; 887 inherited seeded-ledger events are excluded from run timing.</li>
          <li>13 campaign containers are excluded: <span id="excluded-containers"></span>.</li>
        </ul></div>
        <div><h3>What the hours mean</h3><ul>
          <li><strong>Observed activity span</strong> is the timestamp span from available run lifecycle, ledger, trace, cost, and health evidence. It is not exact process wall time or CPU time.</li>
          <li>45.03 summed run-hours describe total across-run activity spans; 25.15 h is the union on the global clock after concurrent runs overlap.</li>
          <li>35.14 h LLM (78.05%), 6.785 h exclusive tools (15.07%), 1.17 h setup/provider-free, 1.68 h after-final-trace, and 0.25 h interactive gaps partition the summed observed span.</li>
          <li>Individual tool-call totals may overlap. The stacked composition uses tool-exclusive time; tool-by-tool totals use each call’s own start/end.</li>
          <li>Run timeline intervals retain the source JSON’s Unix epoch seconds; hover/focus each interval to see exact ISO timestamps.</li>
        </ul></div>
      </div>
      <p class="footer">Source scope: <code id="scope-text"></code>. The chart data is embedded in this file. No CDN, network request, external font, or runtime dependency is used.</p>
    </article>
  </section>
  <footer class="footer">Built from the saved timing summary and run CSV. <a href="V7_V8_TIMING_2026-10-18.md">Open the detailed Markdown companion</a> · <a href="../../tools/audits/run-timing-2026-10-18/runs.csv">Download the run table</a>.</footer>
</main>
<script id="report-data" type="application/json">{payload}</script>
<script>{JS}</script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generated, encoding="utf-8")
    print(f"wrote {output_path.relative_to(ROOT)} ({len(generated.encode('utf-8')):,} bytes; {len(data['runs'])} runs, {len(data['requests']):,} request samples, {len(data['tools']):,} tool samples)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.summary, args.csv, args.output)


if __name__ == "__main__":
    main()
