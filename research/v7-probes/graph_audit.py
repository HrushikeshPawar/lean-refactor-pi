"""Read-only audit of v6 candidate graphs (BACKLOG 5c-1-lite). Usage: python3 -I graph_audit.py [--json out]"""
import json, glob, os, re, sys, difflib, collections
ROOT = "/mnt/SharedDrive/ActiveProjects/lean-refactor-pi/runs/pi-budget"
PREF = ("v6cov", "v6ark2", "v6ark", "v6pilot")
PAT = {
 "go_back": r"(restore|revert to|go(ing)? back to|return(ing)? to|back to|fall back to|roll back to) (the )?(draft |candidate |node )?(#|p)\d+",
 "combine": r"(combin|merg|mix|splic|hybrid|together)\w*[^.\n]{0,80}(#\d+|\bp\d+)[^.\n]{0,50}(#\d+|\bp\d+)|(#\d+|\bp\d+) ?(\+|and|with) ?(#\d+|\bp\d+)[^.\n]{0,40}(combin|merg|togeth)|(#\d+|\bp\d+) \+ (#\d+|\bp\d+)",
 "other_approach": r"other approach|different (route|approach|strategy)|alternative (route|approach)|another (route|approach)|completely new",
 "fork_from": r"(based on|build(ing)? (on|from)|start(ing)? from|branch(ing)? (off |out )?(from|of)|fork(ing)? from|variants? of|modify(ing)?) (the )?(draft |candidate |node )?(#|p)\d+",
}
def lines_of(t):
    out=[]
    for l in t.splitlines():
        s=l.strip()
        if len(s)>=6 and s not in ("by",): out.append(s)
    return out
def audit(d):
    led=[json.loads(l) for l in open(d+"/ledger.jsonl") if l.strip()]
    nodes={}; order=[]; ev=[]
    for e in led:
        k=e.get("kind")
        if k=="candidate":
            i=e["candidate_id"]
            if i not in nodes: nodes[i]={"id":i,"parents":e.get("parents",[]),"idea":e.get("idea_id"),"kind":"cand","origin":e.get("origin")}; order.append(i)
        elif k=="probe":
            i=e["proof_id"]
            if i not in nodes: nodes[i]={"id":i,"parents":[e["parent"]] if e.get("parent") else [],"idea":e.get("idea_id"),"kind":"probe","origin":"model"}; order.append(i)
        elif k=="evaluation": ev.append(e)
    text={}
    for i in order:
        p=f"{d}/proofs/{i}.lean"
        text[i]=open(p).read() if os.path.exists(p) else ""
    ref=order[0] if order else None
    reflines=set(lines_of(text[ref])) if ref else set()
    L={i:lines_of(text[i]) for i in order}
    anc={}
    def ancestors(i):
        if i in anc: return anc[i]
        s=set(); 
        for p in nodes[i]["parents"]:
            if p in nodes: s|={p}|ancestors(p)
        anc[i]=s; return s
    def ratio(a,b):
        return difflib.SequenceMatcher(None,L[a],L[b],autojunk=False).ratio()
    loose=0; merges=[]; agree=0; agree_n=0; tparent={}; chain=0; nonchain=0
    for n,i in enumerate(order):
        if i==ref: continue
        earlier=order[:n]
        if not earlier: continue
        # chain test: parent is immediately preceding node
        if nodes[i]["parents"] and nodes[i]["parents"][0]==order[n-1]: chain+=1
        else: nonchain+=1
        mine=L[i]
        sc=[(ratio(i,x),x) for x in earlier if L[x]]
        if sc:
            m=max(s for s,_ in sc)
            tops=[x for s,x in sc if s>=m-0.02]
            tparent[i]=tops[-1] if nodes[i]["parents"] and nodes[i]["parents"][0] not in tops else nodes[i]["parents"][0] if nodes[i]["parents"] else tops[-1]
            if nodes[i]["parents"]:
                agree_n+=1; agree+= nodes[i]["parents"][0] in tops
        # merge: novel lines (not in reference) covered by two non-ancestor-related nodes
        novel=[l for l in mine if l not in reflines]
        if len(novel)<4: continue
        cover={x:set(l for l in novel if l in set(L[x])) for x in earlier}
        # pick X: best coverage, then Y: best extra coverage
        X=max(earlier,key=lambda x:len(cover[x]),default=None)
        if X is None or len(cover[X])<0.3*len(novel): continue
        rest=set(novel)-cover[X]
        Y=max((y for y in earlier if y!=X and y not in ancestors(X) and X not in ancestors(y)),key=lambda y:len(cover[y]&rest),default=None)
        if Y is None: continue
        extra=cover[Y]&rest
        # extra lines must not be explained by ancestors shared with X's lineage
        if len(extra)>=2 and len(extra)>=0.15*len(novel): loose+=1
        if len(extra)>=3 and len(extra)>=0.25*len(novel):
            merges.append({"node":i,"X":X,"Y":Y,"fx":round(len(cover[X])/len(novel),2),"fy":round(len(extra)/len(novel),2),
                           "declared": len(nodes[i]["parents"])>1})
    # best node
    best=None;bp=-1;bfull=None
    for e in ev:
        r=e.get("result",{}); p=r.get("local_proxy")
        c=r.get("compat",{}) 
        ok=next(iter(c.values()),{}).get("passed") if c else False
        if ok and p is not None and p>bp: bp=p;best=e["candidate_id"]
    def depth(i,par):
        n=0
        while i in par and par[i] and n<500:
            i=par[i]; n+=1
        return n
    rec_par={i:(nodes[i]["parents"][0] if nodes[i]["parents"] else None) for i in order}
    rd=depth(best,rec_par) if best else None
    td=depth(best,tparent) if best else None
    # call-level stats from events.jsonl
    c=collections.Counter(); mentions=collections.Counter(); ex=collections.defaultdict(list); ign=0
    for l in open(d+"/events.jsonl"):
        if l.startswith('{"type":"tool_execution_start"'):
            j=json.loads(l); t=j["toolName"]; a=j.get("args") or {}
            if t=="arena_probe":
                c["probe_calls"]+=1; c["probe_drafts"]+=len(a.get("drafts") or [])+(1 if a.get("proof") or a.get("draft") else 0)
                c["probe_parent"]+=bool(a.get("parent")); c["probe_idea_id"]+=bool(a.get("idea_id")); c["probe_idea_title"]+=bool(a.get("idea"))
            elif t=="arena_evaluate":
                c["eval_calls"]+=1; c["eval_parents"]+=bool(a.get("parents")); c["eval_idea_id"]+=bool(a.get("idea_id")); c["eval_cand_ref"]+=bool(a.get("candidate"))
                c["eval_from_probe"]+=bool(a.get("from_probe"))
                c["eval_cand_plus_proof"]+=bool(a.get("candidate") and a.get("proof"))
            elif t=="arena_candidate": c["restore"]+=1
        elif l.startswith('{"type":"tool_execution_end"') and "ignored" in l and "parent" in l: ign+=l.count("ignored: ")
        elif l.startswith('{"type":"turn_end"'):
            j=json.loads(l)
            for part in j["message"].get("content",[]):
                if isinstance(part,dict) and part.get("type") in("thinking","text"):
                    s=part.get("thinking") or part.get("text") or ""
                    for k,p in PAT.items():
                        for m in re.finditer(p,s,re.I):
                            mentions[k]+=1
                            if len(ex[k])<3: ex[k].append(s[max(0,m.start()-80):m.end()+100].replace("\n"," "))
    ideas=sum(1 for i in order if nodes[i]["idea"])
    ncur=[e for e in led if e.get("kind")=="current"]
    return dict(run=os.path.basename(d).replace("-deepseek-v4.1-flash-r1","-DS").replace("-gpt-6-luna-r1","-Luna").replace("-qwen3.8-flash-r1","-Qwen"),
        nodes=len(order),cands=sum(nodes[i]["kind"]=="cand" for i in order),
        non_chain=nonchain,chain=chain,agree=f"{agree}/{agree_n}",agree_frac=round(agree/agree_n,2) if agree_n else None,
        merges=len(merges),merges_loose=loose,declared_merges=sum(m["declared"] for m in merges),two_parent=sum(len(nodes[i]["parents"])>1 for i in order),
        nodes_with_idea=ideas,best=best and order.index(best),best_proxy=bp,best_depth_rec=rd,best_depth_text=td,
        ignored_parent_notes=ign,**dict(c),mentions=dict(mentions),examples=dict(ex),merge_list=merges[:5])
if __name__=="__main__":
    res=[]
    for d in sorted(glob.glob(ROOT+"/v6*-r1")):
        b=os.path.basename(d)
        if not b.startswith(PREF) or not os.path.exists(d+"/ledger.jsonl") or not os.path.exists(d+"/events.jsonl"): continue
        try: res.append(audit(d))
        except Exception as e: print("ERR",b,e,file=sys.stderr)
    out=sys.argv[2] if len(sys.argv)>2 else None
    if out: json.dump(res,open(out,"w"),indent=1)
    for r in res: print({k:v for k,v in r.items() if k not in("examples","merge_list")})
