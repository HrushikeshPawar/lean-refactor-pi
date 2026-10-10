import json,glob,hashlib,re,sys,os
sys.path.insert(0,'.')
from arena import engine, context
from arena.scoring import exchange_rates, reference
from arena.engine import problem, measure_version, versions, _proof_length
A='runs/analysis/'
sub=[json.loads(l) for l in open(A+'submission-v3/submission.jsonl')]
# results by name, newest version wins; match on tokens
res={}
for f in ['submission-v1','submission-v2','submission-v3']:
    for l in open(f'{A}{f}/results.jsonl'):
        d=json.loads(l); res.setdefault(d['name'],[]).append(d)
# profile events by proof_id
prof={}
for f in glob.glob('runs/**/ledger.jsonl',recursive=True):
    for l in open(f):
        if '"kind":"profile"' not in l: continue
        try:d=json.loads(l)
        except: continue
        if d['result'].get('ok'): prof[d['proof_id']]=d['result']
def step_table(p, rates):
    ents=p['entries']; lt={int(k):v for k,v in (p.get('line_tokens') or {}).items()}
    tot=p['measured_total'] or p['profiled_total'] or 1
    # innermost attribution of tokens
    own={i:0 for i in range(len(ents))}; other=0
    for ln,t in lt.items():
        best=None
        for i,e in enumerate(ents):
            if e['proof_line']<=ln<=e['end_proof_line'] and (best is None or e['depth']>=ents[best]['depth'] and (e['proof_line'],-e['end_proof_line'])>=(ents[best]['proof_line'],-ents[best]['end_proof_line'])): best=i
        if best is None: other+=t
        else: own[best]+=t
    rows=[]
    for i,e in enumerate(ents):
        tk=own[i]; 
        pts=tk*rates['points_per_token']+e['self_hb']*rates['points_per_100_heartbeats']/100
        rows.append(dict(id=i+1,lines=e['lines'],depth=e['depth'],tok=tk,hb=e['hb'],self_hb=e['self_hb'],share=round(100*e['self_hb']/tot,1),pts_tok=round(tk*rates['points_per_token'],2),pts_hb=round(e['self_hb']*rates['points_per_100_heartbeats']/100,2),pts=round(pts,2),text=' '.join(e['text'].split())[:48]))
    return rows,other
out=['# Hotspots for all 15 rows (cached data, no Lean)\n',
'Step table: `tok` = tokens attributed to the innermost tactic span covering each proof line (harness per-line counts, `line_tokens`); `hb` inclusive, `self` exclusive of nested tactics (units = raw/1000); `share` = self/measured total; points = what removing that step entirely would be worth (tok*pts/token + self*pts/hb), not predicted savings. Indent = depth.\n']
summ=[]; need=0
for r in sub:
    n=r['name']; row=problem(n); ver,commit=measure_version(row); nv=len(versions(row))
    rates=exchange_rates(n,nv); rt,rh=rates['reference_tokens'],rates['reference_heartbeats']
    salt=((context.Path(context.__file__).with_name('lean')/'profile.lean').read_text()+row['src']+str(context.MAX_DEPTH if hasattr(context,'MAX_DEPTH') else 4)+'profile-schema-v3-innermost-span-token-hotspots')
    from arena.profile import MAX_DEPTH
    salt=((context.Path(context.__file__).with_name('lean')/'profile.lean').read_text()+row['src']+str(MAX_DEPTH)+'profile-schema-v3-innermost-span-token-hotspots')
    cur=context._cache('profile',n,commit,salt)
    cands=sorted(glob.glob(f"runs/cache/profile/{re.sub(r'[^A-Za-z0-9_.-]','_',n)}-*.json"),key=os.path.getmtime)
    pf=cur if cur.exists() else (cands[-1] if cands else None)
    tag='current' if cur.exists() else 'newest (not current packet hash)'
    P=json.load(open(pf)); rows,other=step_table(P,rates)
    tok=_proof_length(r['proof'],row.get('statement'))
    m=[d for d in res.get(n,[]) if d['tokens']==tok]
    m=m[-1] if m else None
    pid=hashlib.sha256((n+"\0"+r["proof"]).encode()).hexdigest()
    bp=prof.get(pid)
    if m:
        hb=m['heartbeat']; tp=round((rt-tok)/rt*100,2); hp=round((rh-hb)/rh*100,2)
        comp=m['compat']; cov=round(100*sum(1 for c in comp.values() if c['passed'])/nv,1)
        proxy=m['proxy']
    else: hb=tp=hp=cov=proxy=None
    # headroom in points per axis
    if m:
        head={'tokens':(100-tp)/3,'heartbeats':(100-hp)/3,'coverage':(100-cov)/3}
        ax=max(head,key=head.get); hr=f"{ax} ({head[ax]:.1f})"
    else: hr='?'
    byhb=sorted(rows,key=lambda x:-x['self_hb'])[:3]; bytok=sorted(rows,key=lambda x:-x['tok'])[:3]
    out.append(f"\n## {n}\n")
    out.append(f"Reference: {rt} tokens, {rh} hb (official denominators); measured on {ver}; profile {os.path.basename(pf)} ({tag}), measured total {P['measured_total']}, profiled {P['profiled_total']}, floor {P.get('statement_floor_hb')}. Rates: {rates['points_per_token']} pts/token, {rates['points_per_100_heartbeats']} pts/100 hb, {rates['points_per_lost_version']} pts/lost version ({nv} versions).\n")
    out.append("| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |\n|---|---|---|---|---|---|---|---|---|")
    for x in rows: out.append(f"| {x['id']} | {x['lines']} | {x['tok']} | {x['hb']} | {x['self_hb']} | {x['share']} | {x['pts_tok']} | {x['pts_hb']} | {'. '*x['depth']}{x['text'].replace('|','/')} |")
    out.append(f"\n(tokens on lines outside any tactic span: {other}; total {P.get('line_tokens_total')} vs ref {rt})\n")
    out.append(f"Top-3 hb: "+'; '.join(f"#{x['id']} L{x['lines']} {x['self_hb']} ({x['share']}%)" for x in byhb)+"\n\nTop-3 tokens: "+'; '.join(f"#{x['id']} L{x['lines']} {x['tok']}" for x in bytok)+"\n")
    out.append(f"Best submitted (v3): {tok} tokens; "+(f"hb {hb} on {m['measured_on']}, tok% {tp}, hb% {hp}, cov% {cov}, proxy {proxy} (cand {m['cand']})" if m else "no matching results record")+"; "+("profile cached in a ledger event." if bp else "needs one profile compile."))
    if bp:
        brs,_=step_table(bp,rates)
        out.append("\nBest-proof hotspots (self hb): "+'; '.join(f"L{x['lines']} {x['self_hb']} ({x['share']}%) tok {x['tok']} `{x['text'][:30]}`" for x in sorted(brs,key=lambda x:-x['self_hb'])[:3]))
    else: need+=1
    top=byhb[0]
    summ.append((n,rt,tok,rh,hb,tp,hp,cov,proxy,hr,f"L{top['lines']} {top['self_hb']}hb ({top['share']}%)", 'Y' if bp else 'N'))
hdr="| row | ref tok | best tok | ref hb | best hb | tok% | hb% | cov% | proxy | headroom axis (pts) | top ref hotspot | best profiled |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n"
S="\n## Cross-row summary\n\n"+hdr+"\n".join('| '+' | '.join(str(x if len(str(x))<45 else str(x)[:30]+'..'+str(x)[-12:]) for x in s)+' |' for s in summ)+f"\n\nRows needing one profile compile of the best proof: {need} of 15.\n"
out.insert(2,S)
open(A+'experiments/hotspots-15.md','w').write('\n'.join(out))
print(S)
