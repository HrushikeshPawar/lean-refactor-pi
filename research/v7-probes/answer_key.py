import json,re,sys
sys.path.insert(0,'.')
from arena.engine import problem
tok=re.compile(r"[A-Za-z_][A-Za-z0-9_'!?]*(?:\.[A-Za-z_][A-Za-z0-9_'!?]*)*")
binder=re.compile(r"(?:\b(?:intro|intros|rintro|obtain|rcases|have|let|set|fun|λ|case|next|rename_i|ext|by_cases|by_contra|generalizing|induction|cases|specialize|show|calc|refine|use|exists|exact|suffices|choose|lift|with)\b)")
def idents(text):
    # drop comments
    text=re.sub(r"--[^\n]*","",text); text=re.sub(r"/-.*?-/","",text,flags=re.S)
    return text
def locals_of(proof):
    L=set()
    t=idents(proof)
    # binders: (a b : T) {a b : T} [inst : T]; fun a b =>; intro a b; rintro/obtain/rcases patterns; have h :; case x =>; with x y; ⟨a, b⟩ patterns
    for m in re.finditer(r"[({\[]\s*([A-Za-z_][\w'₀-₉ ]*?)\s*:",t):
        L|=set(m.group(1).split())
    for m in re.finditer(r"\b(?:intro|intros|rintro|rename_i|fun|λ|next|case|ext|generalizing|induction|cases|obtain|rcases|choose|lift|set|let|have|suffices|by_cases|by_contra)\b([^\n:=]*)",t):
        L|=set(re.findall(r"[A-Za-z_][\w'₀-₉]*",m.group(1)))
    for m in re.finditer(r"\bwith\b([^\n]*)",t):
        L|=set(re.findall(r"[A-Za-z_][\w'₀-₉]*",m.group(1)))
    for m in re.finditer(r"⟨([^⟩\n]*)⟩",t):
        L|=set(re.findall(r"[A-Za-z_][\w'₀-₉]*",m.group(1)))
    return L
def cands(proof):
    t=idents(proof); L=locals_of(proof)
    out=set()
    for m in tok.finditer(t):
        s=m.group(0)
        if s in L: continue
        parts=s.split('.')
        if '.' not in s and '_' not in s: continue
        if s.startswith('_') or s in('this',): continue
        if parts[0] in L: continue
        out.add(s.strip('.'))
    return out
if __name__=='__main__':
    sub={json.loads(l)['name']:json.loads(l)['proof'] for l in open('runs/analysis/submission-v3/submission.jsonl')}
    key={}
    for n,p in sub.items():
        ref=problem(n)['src']
        rc=cands(ref); bc=cands(p)
        rlast={c.split('.')[-1] for c in rc}
        k=sorted(c for c in bc if c not in rc and c.split('.')[-1] not in rlast)
        key[n]=k
        print(n,len(rc),len(bc),len(k),k[:40])
    json.dump(key,open('runs/analysis/experiments/answer_key_candidates.json','w'),indent=1)
