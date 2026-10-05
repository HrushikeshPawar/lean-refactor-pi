"""Build a self-contained browser explorer for one Arena candidate ledger."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_graph(run_id: str) -> dict:
    directory = ROOT / "runs" / "pi-budget" / run_id
    events = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
    nodes: dict[str, dict] = {}
    order: list[str] = []
    evaluation_number = 0
    milestones: list[dict] = []
    best_proxy = float("-inf")
    for event in events:
        if event["kind"] == "candidate":
            candidate_id = event["candidate_id"]
            nodes[candidate_id] = {
                "id": candidate_id,
                "index": len(order) + 1,
                "parents": event.get("parents", []),
                "hypothesis": event.get("hypothesis", ""),
                "proof": (directory / "proofs" / f"{candidate_id}.lean").read_text(),
                "evaluations": [],
            }
            order.append(candidate_id)
        elif event["kind"] == "evaluation":
            evaluation_number += 1
            nodes[event["candidate_id"]]["evaluations"].append({
                "number": evaluation_number,
                "mode": event["mode"],
                "result": event["result"],
            })
            result = event["result"]
            compat = result.get("compat", {})
            proxy = result.get("local_proxy")
            if (event["mode"] == "full" and len(compat) == 3
                    and all(version.get("passed") for version in compat.values())
                    and proxy is not None and proxy > best_proxy):
                best_proxy = proxy
                milestones.append({"candidate_id": event["candidate_id"],
                                   "evaluation": evaluation_number,
                                   "tokens": result["tokens"], "heartbeat": result["heartbeat"],
                                   "local_proxy": proxy})
    for candidate_id in order:
        node = nodes[candidate_id]
        node["children"] = [other for other in order if candidate_id in nodes[other]["parents"]]
        node["depth"] = 0 if not node["parents"] else 1 + max(nodes[parent]["depth"] for parent in node["parents"])
        node["best"] = max(node["evaluations"], key=lambda row: (
            row["mode"] == "full" and all(v.get("passed") for v in row["result"].get("compat", {}).values())
            and len(row["result"].get("compat", {})) == 3,
            sum(bool(v.get("passed")) for v in row["result"].get("compat", {}).values()),
            row["result"].get("local_proxy") or -1,
            -(row["result"].get("tokens") or 9999)), default=None)
    return {"run_id": run_id, "nodes": [nodes[candidate_id] for candidate_id in order],
            "evaluations": evaluation_number, "milestones": milestones}


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · Candidate graph</title>
<style>
:root{color-scheme:dark;--bg:#0d1117;--surface:#161b22;--surface2:#202833;--border:#354150;--text:#e9edf3;--muted:#a8b5c5;--blue:#71b7ff;--green:#73dcad;--amber:#f2c77b;--red:#ff8f91}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}button,input,select{font:inherit}button,select,input{background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:7px;padding:7px 10px}button{cursor:pointer}button:hover{border-color:var(--blue)}button.active{background:#244661;border-color:var(--blue)}header{padding:19px 24px;border-bottom:1px solid var(--border);display:flex;align-items:flex-end;gap:25px;flex-wrap:wrap}h1{font-size:22px;margin:0}h2{font-size:17px;margin:0 0 10px}h3{font-size:14px;margin:15px 0 7px}.sub{color:var(--muted)}.metrics{display:flex;gap:10px;flex-wrap:wrap}.metric{background:var(--surface);padding:8px 13px;border:1px solid var(--border);border-radius:8px}.metric b{font-size:16px}.shell{display:grid;grid-template-columns:minmax(460px,1fr) minmax(390px,600px);height:calc(100vh - 112px)}.left{min-width:0;border-right:1px solid var(--border);display:flex;flex-direction:column}.toolbar{padding:12px 16px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--border)}.toolbar input{min-width:170px;flex:1}.graphbox{flex:1;overflow:auto;background:radial-gradient(circle at 20% 10%,#17212e,var(--bg) 60%)}svg{display:block}.node{cursor:pointer}.node rect{fill:#26313f;stroke:#556a7e;stroke-width:1.5}.node.root rect{fill:#303343}.node.full rect{fill:#173c34;stroke:#4eab83}.node.fail rect{fill:#3a2b31;stroke:#9a6a73}.node.selected rect{stroke:#fff;stroke-width:3}.node text{fill:var(--text);font-size:12px;pointer-events:none}.node .small{fill:#b7c5d5;font-size:10px}.edge{fill:none;stroke:#667b91;stroke-width:1.5;opacity:.55}.edge.focus{stroke:var(--blue);stroke-width:3;opacity:1}.edge.multi{stroke-dasharray:5 4}.legend{padding:8px 16px;color:var(--muted);border-top:1px solid var(--border);font-size:12px}.right{overflow:auto;padding:18px 20px}.card{border:1px solid var(--border);background:var(--surface);border-radius:9px;padding:12px;margin-bottom:12px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}.tag{border-radius:5px;background:#293747;padding:2px 7px;color:#d9e4ee;font-size:12px}.good{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}.muted{color:var(--muted)}code,pre{font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}code{overflow-wrap:anywhere}pre{white-space:pre-wrap;word-break:break-word;margin:0;padding:12px;background:#0b1016;border:1px solid var(--border);border-radius:7px;max-height:400px;overflow:auto}.diff .add{background:#183d2e;color:#c3f4dc}.diff .del{background:#4a252d;color:#ffd0d0}.diff .same{color:#95a6b8}.diff div{white-space:pre-wrap;word-break:break-word;font:12px/1.4 ui-monospace,monospace;padding:1px 7px}.list{max-height:160px;overflow:auto}.list button{margin:2px}.eval{padding:7px 0;border-top:1px solid var(--border)}.eval:first-child{border-top:0}details summary{cursor:pointer;color:var(--blue)}@media(max-width:980px){.shell{display:block;height:auto}.left{height:55vh;border-right:0;border-bottom:1px solid var(--border)}.right{height:auto;overflow:visible}}
.node.milestone rect{stroke:var(--amber);stroke-width:2.5}.milestones{display:flex;gap:6px;overflow:auto;padding:7px 12px;border-bottom:1px solid var(--border);white-space:nowrap}.milestones button{font-size:12px;padding:4px 8px}
</style></head><body>
<header><div><h1>Core.InitsUpdatesComm · Luna candidate graph</h1><div class="sub">Run <code id="runName"></code> · recorded ancestry only</div></div><div class="metrics" id="metrics"></div></header>
<div class="shell"><section class="left"><div class="toolbar"><input id="search" placeholder="Search ID, hypothesis, proof…"><select id="filter"><option value="all">All candidates</option><option value="full">3/3 validated</option><option value="primary">Primary Lean passed</option><option value="fail">No primary pass</option></select><button id="fit">Fit</button><button id="zoomIn">+</button><button id="zoomOut">−</button></div><div class="milestones" id="milestones"></div><div class="graphbox" id="graphbox"><svg id="graph"></svg></div><div class="legend">Gold outline: new verified best · green: 3/3 full result · red: no primary pass · dashed edge: candidate with two recorded parents. Select a node for its proof, results, reasoning, and exact parent diff.</div></section><section class="right" id="detail"></section></div>
<script id="graphData" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('graphData').textContent),nodes=data.nodes,byId=new Map(nodes.map(n=>[n.id,n])),milestoneIds=new Set(data.milestones.map(m=>m.candidate_id));let chosen=null,zoom=1;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function status(n){let evals=n.evaluations.map(e=>e.result);if(evals.some(r=>Object.keys(r.compat||{}).length===3&&Object.values(r.compat).every(v=>v.passed)))return 'full';if(evals.some(r=>r.compat?.['v4.29.1']?.passed))return 'primary';return 'fail'}
function best(n){let full=n.evaluations.filter(e=>e.mode==='full'&&Object.keys(e.result.compat||{}).length===3&&Object.values(e.result.compat).every(v=>v.passed));return full.sort((a,b)=>(b.result.local_proxy??-1)-(a.result.local_proxy??-1))[0]||n.evaluations.at(-1)}
document.getElementById('runName').textContent=data.run_id;
document.getElementById('metrics').innerHTML=[['Candidates',nodes.length],['Evaluations',data.evaluations],['3/3 candidates',nodes.filter(n=>status(n)==='full').length],['Roots',nodes.filter(n=>!n.parents.length).length],['Two-parent joins',nodes.filter(n=>n.parents.length>1).length]].map(([k,v])=>`<div class="metric">${esc(k)} <b>${v}</b></div>`).join('');
document.getElementById('milestones').innerHTML='<span class="muted">Verified best:</span>'+data.milestones.map(m=>`<button data-milestone="${m.candidate_id}">#${m.evaluation} · ${m.tokens} tokens · ${m.local_proxy.toFixed(2)} proxy</button>`).join('');
const layers=new Map();for(const n of nodes){if(!layers.has(n.depth))layers.set(n.depth,[]);layers.get(n.depth).push(n)}
for(const layer of layers.values())layer.sort((a,b)=>a.index-b.index);
const coords=new Map();let maxY=0;for(const [depth,layer] of layers){layer.forEach((n,i)=>{const y=40+i*68;coords.set(n.id,{x:40+depth*230,y});maxY=Math.max(maxY,y)})}
const W=100+(Math.max(...layers.keys())+1)*230,H=maxY+100,svg=document.getElementById('graph');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
function graph(){const q=document.getElementById('search').value.toLowerCase(),f=document.getElementById('filter').value;const vis=n=>(f==='all'||status(n)===f||(f==='primary'&&status(n)==='full'))&&(!q||n.id.includes(q)||n.hypothesis.toLowerCase().includes(q)||n.proof.toLowerCase().includes(q));let edges='',boxes='';for(const n of nodes){const p=coords.get(n.id),dim=vis(n)?1:.15;for(const parent of n.parents){const a=coords.get(parent),focus=chosen&&(chosen===n.id||chosen===parent);edges+=`<path class="edge ${focus?'focus':''} ${n.parents.length>1?'multi':''}" opacity="${dim}" d="M${a.x+174},${a.y+22} C${a.x+199},${a.y+22} ${p.x-24},${p.y+22} ${p.x},${p.y+22}"/>`}
 const b=best(n),r=b?.result||{};boxes+=`<g class="node ${status(n)} ${milestoneIds.has(n.id)?'milestone':''} ${chosen===n.id?'selected':''}" data-id="${n.id}" opacity="${dim}" transform="translate(${p.x},${p.y})"><rect width="174" height="45" rx="7"/><text x="9" y="18">#${n.index} · ${n.id.slice(0,9)}</text><text class="small" x="9" y="35">${r.tokens??'?'} tok · ${status(n)==='full'?'3/3':status(n)==='primary'?'primary':'failed'} · ${n.parents.length} parent${n.parents.length===1?'':'s'}</text></g>`}
svg.innerHTML=edges+boxes;svg.querySelectorAll('.node').forEach(el=>el.addEventListener('click',()=>select(el.dataset.id)));svg.style.width=(W*zoom)+'px';svg.style.height=(H*zoom)+'px'}
function diff(a,b){const aa=a.split('\n'),bb=b.split('\n'),m=aa.length,n=bb.length;const dp=Array.from({length:m+1},()=>new Uint16Array(n+1));for(let i=m-1;i>=0;i--)for(let j=n-1;j>=0;j--)dp[i][j]=aa[i]===bb[j]?dp[i+1][j+1]+1:Math.max(dp[i+1][j],dp[i][j+1]);let i=0,j=0,out=[];while(i<m||j<n){if(i<m&&j<n&&aa[i]===bb[j]){out.push(['same','  '+aa[i]]);i++;j++}else if(j<n&&(i===m||dp[i][j+1]>=dp[i+1][j])){out.push(['add','+ '+bb[j++]]);}else{out.push(['del','- '+aa[i++]]);}}return out.map(([cls,s])=>`<div class="${cls}">${esc(s)}</div>`).join('')}
function renderDetail(){const el=document.getElementById('detail');if(!chosen){el.innerHTML='<div class="card"><h2>Select a candidate</h2><p>The arrows are exactly the parent IDs supplied to <code>arena_evaluate</code>. Roots have no recorded parent. Choose a node to inspect its full proof and changes.</p></div>';return}const n=byId.get(chosen),e=best(n),r=e?.result||{},parents=n.parents.map(id=>byId.get(id)),kids=n.children.map(id=>byId.get(id));const options=parents.map((p,i)=>`<option value="${p.id}">Parent #${p.index} · ${p.id.slice(0,12)}</option>`).join('');el.innerHTML=`<div class="card"><h2>Candidate #${n.index} <span class="tag">${status(n)}</span></h2><code>${n.id}</code><p><strong>Recorded hypothesis</strong><br>${esc(n.hypothesis||'(none supplied)')}</p><div class="row"><span class="tag">${r.tokens??'?'} proof tokens</span><span class="tag">${r.heartbeat??'?'} heartbeat</span><span class="tag">${r.local_proxy??'—'} local proxy</span><span class="tag">${n.evaluations.length} evaluations</span></div></div>
<div class="card"><h3>Recorded relations</h3><div>Parents: ${parents.length?parents.map(p=>`<button data-go="${p.id}">#${p.index} ${p.id.slice(0,9)}</button>`).join(' '):'<span class="muted">none; recorded root</span>'}</div><div>Children: ${kids.length?kids.map(k=>`<button data-go="${k.id}">#${k.index} ${k.id.slice(0,9)}</button>`).join(' '):'<span class="muted">none</span>'}</div></div>
<div class="card"><h3>Exact proof</h3><pre>${esc(n.proof)}</pre></div>
<div class="card"><h3>Diff from recorded parent</h3>${parents.length?`<div class="row"><select id="parentSelect">${options}</select><span class="muted">line-by-line; unchanged lines included</span></div><div class="diff" id="diff"></div>`:'<p class="muted">This candidate has no parent in the ledger.</p>'}</div>
<div class="card"><h3>All evaluations</h3>${n.evaluations.map(v=>{const x=v.result,c=Object.entries(x.compat||{});return `<div class="eval"><div><b>#${v.number} ${esc(v.mode)}</b> · ${x.tokens??'?'} tokens · ${x.heartbeat??'?'} heartbeat · proxy ${x.local_proxy??'—'}</div><div>${c.map(([ver,z])=>`<span class="tag ${z.passed?'good':'bad'}">${esc(ver)} ${z.passed?'pass':'fail'}</span>`).join(' ')}</div>${c.filter(([_,z])=>!z.passed).map(([ver,z])=>`<details><summary>${esc(ver)} diagnostics</summary><pre>${esc(z.diagnostics||z.error_headlines?.join('\n')||'')}</pre></details>`).join('')}</div>`}).join('')}</div>`;
el.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>select(b.dataset.go)));const sel=el.querySelector('#parentSelect');if(sel){const update=()=>el.querySelector('#diff').innerHTML=diff(byId.get(sel.value).proof,n.proof);sel.addEventListener('change',update);update()}}
function select(id){chosen=id;graph();renderDetail();const p=coords.get(id),box=document.getElementById('graphbox');box.scrollTo({left:Math.max(0,p.x*zoom-box.clientWidth/2),top:Math.max(0,p.y*zoom-box.clientHeight/2),behavior:'smooth'})}
document.getElementById('search').addEventListener('input',graph);document.getElementById('filter').addEventListener('change',graph);document.querySelectorAll('[data-milestone]').forEach(b=>b.onclick=()=>select(b.dataset.milestone));document.getElementById('fit').onclick=()=>{const b=document.getElementById('graphbox');zoom=Math.min(1,b.clientWidth/W,b.clientHeight/H);graph()};document.getElementById('zoomIn').onclick=()=>{zoom=Math.min(2,zoom*1.3);graph()};document.getElementById('zoomOut').onclick=()=>{zoom=Math.max(.2,zoom/1.3);graph()};graph();renderDetail();
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    graph = load_graph(args.run_id)
    output = args.output or ROOT / "runs" / "analysis" / f"{args.run_id}-graph.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = HTML.replace("__TITLE__", html.escape(args.run_id)).replace("__DATA__", payload)
    output.write_text(page)
    print(f"{output}: {len(graph['nodes'])} candidates, {graph['evaluations']} evaluations, {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
