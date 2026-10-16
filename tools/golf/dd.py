"""greedy deletion golfing: python dd.py key infile outfile"""
import sys,re,json,time
sys.path.insert(0,"/mnt/SharedDrive/ActiveProjects/lean-refactor-pi")
from pathlib import Path
src=Path("/mnt/SharedDrive/ActiveProjects/lean-refactor-pi/runs/analysis/hybrid-push/score.py").read_text()
NAMES=eval(re.search(r"NAMES = (\{.*?\})\nkey",src,re.S).group(1))
from arena.engine import evaluate, force_cold
key,inf,outf=sys.argv[1:4]
name=NAMES[key]
cache={}
def score(p):
    if p in cache: return cache[p]
    try:
        with force_cold():
            r=evaluate(name,p,"fast")
    except Exception as e:
        cache[p]=None; return None
    ok=all(i.get("passed") for i in r.get("compat",{}).values())
    v=(r.get("local_proxy") or (r.get("metrics") or {}).get("estimated_proxy") or 0) if ok else None
    cache[p]=v; return v
def split_top(s):
    """split bracket content on top-level commas -> list of (start,end)"""
    out=[];d=0;st=0
    for i,c in enumerate(s):
        if c in "([{⟨": d+=1
        elif c in ")]}⟩": d-=1
        elif c=="," and d==0: out.append((st,i)); st=i+1
    out.append((st,len(s)))
    return out
def cands(p):
    # skip header up to ':= by'
    hi=p.index(":= by")+5 if ":= by" in p else 0
    res=[]
    # whole lines
    lines=p[hi:].split("\n")
    off=hi
    pos=hi
    for ln in lines:
        if ln.strip() and pos>hi:
            res.append(p[:pos-1]+p[pos+len(ln)-0:] if False else p[:pos]+p[pos+len(ln)+1:])
        pos+=len(ln)+1
    # list elements inside [ ... ] after hi
    for m in re.finditer(r"\[",p[hi:]):
        a=hi+m.start()
        d=0
        for j in range(a,len(p)):
            if p[j] in "([{⟨": d+=1
            elif p[j] in ")]}⟩":
                d-=1
                if d==0: b=j; break
        else: continue
        inner=p[a+1:b]
        parts=split_top(inner)
        if len(parts)>1:
            for k,(s,e) in enumerate(parts):
                keep=[inner[x:y] for i2,(x,y) in enumerate(parts) if i2!=k]
                new=",".join(keep)
                if k==0 and new.startswith(" "): new=new[1:]
                res.append(p[:a+1]+new+p[b:])
    # <;> segments / `; ` segments
    for m in re.finditer(r" <;> |; ",p[hi:]):
        a=hi+m.start(); b=hi+m.end()
        # delete rest of line after separator
        eol=p.find("\n",b); eol=len(p) if eol<0 else eol
        res.append(p[:a]+p[eol:])
        # delete part before separator on the line
        bol=p.rfind("\n",0,a)+1
        indent=re.match(r" *",p[bol:]).group()
        res.append(p[:bol]+indent+p[b:])
    return [r for r in dict.fromkeys(res) if r!=p]
best=Path(inf).read_text()
bs=score(best); print("start",bs,flush=True)
improved=True
while improved:
    improved=False
    for c in cands(best):
        v=score(c)
        if v is not None and v>bs+0.005:
            print("accept",v,flush=True); best,bs=c,v; Path(outf).write_text(best); improved=True; break
print("final",bs); Path(outf).write_text(best)
