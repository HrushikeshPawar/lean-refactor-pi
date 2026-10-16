"""Read-only big-edit analysis of v6 runs. python3 -I bigedit.py [--dump out.json]"""
import json, glob, os, re, sys, difflib, collections, statistics as st
ROOT="/mnt/SharedDrive/ActiveProjects/lean-refactor-pi/runs/pi-budget"
PREF=("v6cov","v6ark2","v6ark","v6pilot")
FOCUS=("fiberwise","fold_advances","interleaved","FieldSpec","Electromagnetism","putnam_1964_a4","putnam_1964_b2")
def body(t):
    L=t.splitlines()
    for k,l in enumerate(L):
        if l.rstrip().endswith(":= by"): return L[k+1:]
    return L
def passed(r):
    c=(r or {}).get("compat") or {}
    return bool(c) and all(v.get("passed") for v in c.values())
def nerr(r):
    c=(r or {}).get("compat") or {}
    for v in c.values():
        return (v.get("diagnostic_counts") or {}).get("errors", len([x for x in v.get("diagnostics",[]) if x.get("severity")=="error"]))
    return None
def first_err(r):
    c=(r or {}).get("compat") or {}
    for v in c.values():
        for x in v.get("diagnostics",[]):
            if x.get("severity")=="error":
                m=re.sub(r"[\d]+|\?m\.\d+","N",x.get("message","").split("\n")[0])[:60]
                return (x.get("proof_line"),m)
    return None
def bucket(n):
    return "0" if n==0 else "1-3" if n<=3 else "4-10" if n<=10 else "11-30" if n<=30 else ">30"
def run(d):
    led=[json.loads(l) for l in open(d+"/ledger.jsonl") if l.strip()]
    cands=[];probes=[];cres={};pres={};ref=None
    for e in led:
        if e["kind"]=="candidate" and e["candidate_id"] not in cands:
            cands.append(e["candidate_id"])
            if ref is None: ref=e["candidate_id"]
        elif e["kind"]=="probe" and e["proof_id"] not in probes:
            probes.append(e["proof_id"]); pres[e["proof_id"]]=e["result"]
        elif e["kind"]=="evaluation" and e["candidate_id"] not in cres: cres[e["candidate_id"]]=e["result"]
    def txt(i):
        p=f"{d}/proofs/{i}.lean"
        return body(open(p).read()) if os.path.exists(p) else None
    drafts=[]; seq=0
    compiled=[(0,ref,txt(ref))] if ref and txt(ref) else []
    # candidates from non-draft sources (hybrids etc.) are joined as compiled when pass and appear; ordered by ledger idx later
    for turn,e in enumerate(x for x in map(json.loads,open(d+"/events.jsonl")) if x["type"]=="turn_end"):
        m=e["message"]; u=m.get("usage") or {}
        calls=[c for c in m["content"] if c["type"]=="toolCall"]
        res={r["toolCallId"]:r for r in e.get("toolResults",[])}
        pd=[c for c in calls if c["name"]=="arena_probe"]
        nd=0; recs=[]
        for c in pd:
            try: out=json.loads(res[c["id"]]["content"][0]["text"])
            except Exception: continue
            args=c["arguments"]
            if isinstance(args,str): args=json.loads(args)
            for k,dr in enumerate(out.get("drafts",[])):
                if dr.get("cached"): continue
                nd+=1
                dtxt=args["drafts"][k] if k<len(args["drafts"]) else ""
                pid=None;r=None
                if dr.get("probe"):
                    n=int(dr["probe"][1:])-1
                    if n<len(probes): pid=probes[n]; r=pres[pid]
                elif dr.get("candidate"):
                    n=int(dr["candidate"][1:])-1
                    if n<len(cands): pid=cands[n]; r=cres.get(pid)
                recs.append(dict(pid=pid,r=r,ok=dr.get("ok",False),dtxt=dtxt,sorry=bool(dr.get("contains_sorry")),idea=dr.get("idea_id"),
                                 compat=dr.get("compat")))
        if not recs: continue
        cost=(u.get("cost") or {}).get("total",0); outk=u.get("output",0)
        for rc in recs:
            rc["turn"]=turn; rc["cost"]=cost/len(recs); rc["out"]=outk/len(recs); rc["turn_ndr"]=len(recs); rc["reason"]=u.get("reasoning",0)/len(recs)
            drafts.append(rc)
    # size analysis
    out=[]; prev_nodes=list(compiled); seen=set()
    for rc in drafts:
        pid=rc["pid"]
        if pid is None or pid in seen: continue
        seen.add(pid)
        t=txt(pid)
        if t is None: continue
        r=rc["r"]
        if r is None and rc["compat"]:
            r={"compat":rc["compat"]}
        ok=passed(r) and not rc["sorry"]
        best=None
        for (_,nid,nt) in prev_nodes:
            if nid==pid: continue
            sm=difflib.SequenceMatcher(None,nt,t,autojunk=False)
            ch=sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!="equal")
            add=sum(j2-j1 for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!="equal")
            if best is None or ch<best[0]: best=(ch,add,nid); best_t=nt
        if best is None: continue
        ch,add,nid=best; best_t=txt(nid)
        dl=max(1,len(t)); dch=len("\n".join(rc["dtxt"].splitlines()))
        unch_chars=0
        # chars of draft not new: approx by line share
        dlines=len(rc["dtxt"].splitlines()) or dl
        newl=min(add,dlines)
        out.append(dict(pid=pid,turn=rc["turn"],ok=ok,sorry=rc["sorry"],errs=nerr(r) if not ok else 0,changed=ch,frac=ch/max(dl,len(best_t)),lines=dl,
                        dlines=dlines,dchars=len(rc["dtxt"]),new=newl,cost=rc["cost"],out=rc["out"],reason=rc["reason"],ndr=rc["turn_ndr"],
                        fe=first_err(r) if not ok else None,idea=rc["idea"],nearest=nid,parent_pass=None,
                        text=t))
        out[-1]["prev_nodes_text"]=None
        if ok: prev_nodes.append((len(prev_nodes),pid,t))
    return out
def main():
    allrows={}
    for d in sorted(glob.glob(ROOT+"/*-r1")):
        b=os.path.basename(d)
        if not b.startswith(PREF): continue
        if not os.path.exists(d+"/ledger.jsonl"): continue
        rows=run(d)
        allrows[b]=rows
    return allrows
def report(allrows,focus_only=True):
    sel={b:r for b,r in allrows.items() if (not focus_only or any(f in b for f in FOCUS))}
    rows=[x for r in sel.values() for x in r]
    print("runs:",len(sel),"drafts w/ size:",len(rows))
    tot=sum(x["cost"] for x in rows)
    for name,flt in (("ALL",lambda x:True),("excl sorry-probes",lambda x:not x["sorry"])):
        print("==",name)
        for b in ["0","1-3","4-10","11-30",">30"]:
            g=[x for x in rows if bucket(x["changed"])==b and flt(x)]
            if not g: continue
            f=[x for x in g if not x["ok"]]
            e=[x["errs"] for x in f if x["errs"] is not None]
            print(f"{b:6} n={len(g):4} succ={100*sum(x['ok'] for x in g)/len(g):5.1f}% avgerr(fail)={st.mean(e) if e else 0:5.2f} spend={sum(x['cost'] for x in g):7.3f} share={100*sum(x['cost'] for x in g)/tot:5.1f}% failspend={100*sum(x['cost'] for x in f)/tot:5.1f}% avgdraftlines={st.mean(x['dlines'] for x in g):6.1f} avgfrac={st.mean(x['frac'] for x in g):.2f}")
    return sel,rows

def analyse(a):
    sel={b:r for b,r in a.items() if any(f in b for f in FOCUS)}
    rows=[x for r in sel.values() for x in r if not x["sorry"]]
    tot=sum(x["cost"] for x in [y for r in sel.values() for y in r])
    print("non-sorry drafts",len(rows),"sorry-probe drafts",sum(x["sorry"] for r in sel.values() for x in r),"total attributed spend",round(tot,3))
    print("== table (focus, non-sorry); frac=changed/max(len)")
    for b in ["0","1-3","4-10","11-30",">30"]:
        g=[x for x in rows if bucket(x["changed"])==b]
        if not g: continue
        f=[x for x in g if not x["ok"]]; e=[x["errs"] for x in f if x["errs"] is not None]
        tu=sum(1/x["ndr"] for x in g)
        print(f"{b:6} n={len(g):4} succ={100*sum(x['ok'] for x in g)/len(g):5.1f}% avgerr(fail)={st.mean(e):.2f} spend=${sum(x['cost'] for x in g):.3f} share={100*sum(x['cost'] for x in g)/tot:4.1f}% failshare={100*sum(x['cost'] for x in f)/tot:4.1f}% turns={tu:.0f} avgdraftlines={st.mean(x['dlines'] for x in g):.0f} medfrac={st.median(x['frac'] for x in g):.2f}")
    sp=[x for r in sel.values() for x in r if x["sorry"]]
    print("sorry probes: n",len(sp),"spend",round(sum(x['cost'] for x in sp),3),"share",round(100*sum(x['cost'] for x in sp)/tot,1))
    # per-run
    print("== per run")
    for b,r in sel.items():
        r2=[x for x in r if not x["sorry"]]
        if not r2: continue
        big=[x for x in r2 if x["changed"]>10]
        print(f"{b[:40]:40} n={len(r2)} sorry={len(r)-len(r2)} succ={100*sum(x['ok'] for x in r2)/len(r2):.0f}% big(>10) n={len(big)} succ={100*sum(x['ok'] for x in big)/max(1,len(big)):.0f}% medlines={st.median(x['dlines'] for x in r2):.0f}")
    # streaks
    print("== streaks (consecutive non-sorry failures, per run, reset on success)")
    L=[];same=0;pairs=0;near=0;dch=[];sizes=[]
    for b,r in sel.items():
        cur=[]
        for x in [y for y in r if not y["sorry"]]+[None]:
            if x is not None and not x["ok"]:
                if cur:
                    p=cur[-1]; pairs+=1
                    if p["fe"] and x["fe"]:
                        if p["fe"][1]==x["fe"][1]: same+=1
                        if p["fe"][0] is not None and x["fe"][0] is not None and abs(p["fe"][0]-x["fe"][0])<=3: near+=1
                    sm=difflib.SequenceMatcher(None,p["text"],x["text"],autojunk=False)
                    dch.append(sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!="equal"))
                cur.append(x)
            else:
                if cur: L.append((b,cur))
                cur=[]
                if x is not None and not x["ok"]: pass
    ls=[len(c) for _,c in L]
    print("streaks",len(L),"mean len",round(st.mean(ls),2),"median",st.median(ls),"max",max(ls),"len>=3:",sum(l>=3 for l in ls),"drafts in len>=3 streaks",sum(l for l in ls if l>=3),"of",sum(ls))
    print("consecutive-failure pairs",pairs,"same first-error headline",round(100*same/pairs),"% ; first error within 3 proof lines",round(100*near/pairs),"%; median lines changed between consecutive failing drafts",st.median(dch),"mean",round(st.mean(dch),1), "share of retries changing <=10 lines",round(100*sum(d<=10 for d in dch)/len(dch)))
    top=sorted(L,key=lambda t:-len(t[1]))[:5]
    for b,c in top: print(" longest",b[:40],len(c),[ (x["changed"],x["fe"][0] if x["fe"] else None) for x in c][:12])
    # big streak cost
    bigfail_runs=[]
    # failing big edits (>10, non-sorry): turns and spend vs small
    for lab,flt in (("big>10",lambda x:x["changed"]>10),("small<=10",lambda x:x["changed"]<=10)):
        g=[x for x in rows if flt(x)]; f=[x for x in g if not x["ok"]]
        print(lab,"n",len(g),"fail",len(f),"fail spend $%.3f (%.1f%% of all)"%(sum(x['cost'] for x in f),100*sum(x['cost'] for x in f)/tot),"fail turns %.0f"%sum(1/x['ndr'] for x in f),"spend per success $%.4f"%(sum(x['cost'] for x in g)/max(1,sum(x['ok'] for x in g))),"draft turns per success %.1f"%(sum(1/x['ndr'] for x in g)/max(1,sum(x['ok'] for x in g))))
    # item 4
    print("== successful big edits (>10 lines)")
    res=[]
    for b,r in sel.items():
        r2=[y for y in r if not y["sorry"]]; since=[]
        for x in r2:
            if x["ok"]:
                if x["changed"]>10: res.append((b,x,list(since)))
                since=[]
            else: since.append(x)
    n=len(res); print("n",n)
    z=sum(1 for _,x,s in res if len(s)==0); print("succeeded with 0 prior failures since last success",z)
    prior_small=sum(1 for _,x,s in res if len(s)>0 and sum(y["changed"]<=10 for y in s)>=max(1,len(s)/2))
    print("with >=1 prior failure(s) mostly small (<=10)",prior_small,"; prior failures mostly big",sum(1 for _,x,s in res if len(s)>0 and sum(y["changed"]>10 for y in s)>len(s)/2))
    print("mean prior failures",round(st.mean(len(s) for _,x,s in res),2))
    # was a successful big edit preceded (in time order, per run, within 5 drafts) by successful small edits?
    pre_small_succ=0
    for b,r in sel.items():
        r2=[y for y in r if not y["sorry"]]
        for k,x in enumerate(r2):
            if x["ok"] and x["changed"]>10 and k>0 and r2[k-1]["ok"] and r2[k-1]["changed"]<=10: pre_small_succ+=1
    print("big success immediately after a small success",pre_small_succ)
    for b,x,s in res[:0]: pass
    # re-emission
    print("== re-emission")
    D=[x for r in sel.values() for x in r]
    ch=sum(x["dchars"] for x in D); un=sum(x["dchars"]*(1-min(1,x["new"]/max(1,x["dlines"]))) for x in D)
    print("all drafts incl sorry: chars",ch,"unchanged share",round(100*un/ch,1))
    nd=[x for x in D if not x["sorry"]]
    ch2=sum(x["dchars"] for x in nd); un2=sum(x["dchars"]*(1-min(1,x["new"]/max(1,x["dlines"]))) for x in nd)
    print("non-sorry drafts: unchanged share",round(100*un2/ch2,1))
    f=[x for x in nd if not x["ok"]]
    print("failing non-sorry drafts: unchanged share",round(100*sum(x["dchars"]*(1-min(1,x["new"]/max(1,x["dlines"]))) for x in f)/sum(x["dchars"] for x in f),1))
    seen=set(); O=0;R=0;vis=0;unv=0
    for x in D:
        O+=x["out"];R+=x["reason"];vis+=x["out"]-x["reason"]
    print("output tokens attributed",round(O),"reasoning share",round(100*R/O,1),"non-reasoning (tool-call+text) share",round(100*vis/O,1))
    unv=sum((x["out"]-x["reason"])*(1-min(1,x["new"]/max(1,x["dlines"]))) for x in D)
    print("upper-bound re-emission as share of ALL output tokens",round(100*unv/O,1),"; as share of non-reasoning output",round(100*unv/vis,1))
    print("for big failing edits >10: unchanged share by chars", round(100*sum(x["dchars"]*(1-min(1,x["new"]/max(1,x["dlines"]))) for x in f if x["changed"]>10)/sum(x["dchars"] for x in f if x["changed"]>10),1))
if __name__=="__main__":
    a=main(); analyse(a)
