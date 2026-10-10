"""Where did the lemma names in each row's submitted best proof come from? (offline, no Lean)"""
import json, re, glob, os, subprocess
R = {json.loads(l)['name']: json.loads(l) for l in open('benchmark/original/warmup.jsonl')}
best = {}
for l in open('runs/analysis/submission-v3/submission.jsonl'):
    d = json.loads(l); best[d.get('name') or d.get('problem')] = d.get('proof') or d.get('formal_proof')
TACTICS = set("""intro intros exact apply refine rw rwa simp simp_all simpa omega decide grind aesop cases rcases obtain
induction constructor use exists ring linarith nlinarith norm_num field_simp positivity gcongr calc show have let
by fun match with at only all_goals any_goals first try repeat rotate_left rotate_right exfalso contradiction
subst unfold dsimp ext funext congr specialize generalize classical tauto trivial rfl assumption split_ifs
by_cases by_contra push_neg change convert left right infer_instance""".split())
ident = re.compile(r"(?<![\w.'])([A-Za-z_][\w']*(?:\.[\w'.]+)+|[a-z][a-z0-9]*(?:_[\w']+)+)")
def names(t): return {m for m in ident.findall(t) if m.split('.')[0] not in TACTICS and m not in TACTICS}
def ctx(row):
    fs = sorted(glob.glob(f"runs/cache/context/{re.sub(r'[^A-Za-z0-9_.-]','_',row)}-*.json"), key=os.path.getmtime)
    if not fs: return None
    return json.load(open(fs[-1]))
out = []; tot = dict(ref=0, top60=0, packet_other=0, searched=0, none=0)
for row, pf in best.items():
    if row not in R or not pf: continue
    ref = names(R[row]['src']); bn = names(pf[len(R[row]['statement']):] if pf.startswith(R[row]['statement']) else pf)
    c = ctx(row) or {}
    lib = [x['name'] for x in c.get('library', [])]; top60 = set(lib[:60]); alllib = set(lib)
    pk = {x.get('name') for k in ('used', 'source', 'dependency', 'constant') for x in c.get(k, []) if isinstance(x, dict)}
    short = row.split('.')[-1][:25]
    journals = [j for j in glob.glob('runs/pi-budget/*/trace-journal.jsonl') if short.replace("'", "_") in j or short in j]
    res = {}
    for n in sorted(bn):
        if n in ref: k = 'ref'
        elif n in top60 or n.split('.')[-1] in {x.split('.')[-1] for x in top60}: k = 'top60'
        elif n in pk or n in alllib: k = 'packet_other'
        elif journals and subprocess.run(['rg', '-q', '-F', n] + journals).returncode == 0: k = 'searched'
        else: k = 'none'
        res[n] = k; tot[k] += 1
    new = {n: k for n, k in res.items() if k != 'ref'}
    out.append((row, len(bn), sum(1 for k in res.values() if k == 'ref'), new))
for row, n, r, new in out:
    print(f"{row[:42]:42} names={n:3} in_ref={r:3} new={new}")
print("TOTAL", tot)
json.dump({'rows': out, 'total': tot}, open('runs/analysis/experiments/library-hitrate.json', 'w'), indent=1, default=str)
