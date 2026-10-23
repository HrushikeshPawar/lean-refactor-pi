"""Mine improving step-level diffs; classify by syntax features; save only aggregate stats."""
import difflib, json, os, re, statistics as st
from arena.submit.select import RUNS
from arena.graph import Graph
from arena.run_control import committed_operation_ids
from arena.package import _jsonl
from arena.steps import split_steps
from arena.prices import snippet_tokens

def has(p, s): return re.search(p, s) is not None
def cnt(p, s): return len(re.findall(p, s))
RULES = [  # (name, features, predicate(old,new))
 ("obtain_to_projection", "obtain/rcases -> .1/.2", lambda o,n: has(r"\b(obtain|rcases|cases)\b",o) and not has(r"\b(obtain|rcases|cases)\b",n) and has(r"\.\d|\.(mp|mpr|left|right|1|2)\b",n)),
 ("rcases_to_rintro", "intro+rcases -> rintro", lambda o,n: has(r"\bintro\b",o) and has(r"\b(rcases|obtain)\b",o) and has(r"\brintro\b",n)),
 ("inline_have_into_term", "have := by; exact -> exact (by ..)", lambda o,n: cnt(r"\bhave\b",o)>cnt(r"\bhave\b",n) and has(r"\(by ",n)),
 ("inline_have_show", "have -> rw [show .. by ..]", lambda o,n: cnt(r"\bhave\b",o)>cnt(r"\bhave\b",n) and has(r"\bshow\b",n)),
 ("drop_have_chain", "fewer have", lambda o,n: cnt(r"\bhave\b",o)>cnt(r"\bhave\b",n)),
 ("drop_set_let", "set/let/generalize removed", lambda o,n: cnt(r"\b(set|let|letI|haveI|generalize)\b",o)>cnt(r"\b(set|let|letI|haveI|generalize)\b",n)),
 ("simp_to_simp_only", "simp -> simp only", lambda o,n: cnt(r"\bsimp\b(?! only)",o)>cnt(r"\bsimp\b(?! only)",n) and has(r"simp only",n)),
 ("simp_only_to_simp", "simp only -> simp", lambda o,n: has(r"simp only",o) and cnt(r"simp only",o)>cnt(r"simp only",n)),
 ("grind_replaces", "manual tactics -> grind", lambda o,n: has(r"\bgrind\b",n) and not has(r"\bgrind\b",o)),
 ("grind_removed", "grind -> other", lambda o,n: has(r"\bgrind\b",o) and not has(r"\bgrind\b",n)),
 ("omega_replaces", "chain -> omega/lia", lambda o,n: has(r"\b(omega|lia)\b",n) and not has(r"\b(omega|lia)\b",o)),
 ("linarith_to_omega", "linarith/nlinarith -> omega/positivity", lambda o,n: has(r"\b(linarith|nlinarith)\b",o) and has(r"\b(omega|positivity|lia)\b",n)),
 ("aesop_replaced", "aesop -> explicit", lambda o,n: has(r"\baesop\b",o) and not has(r"\baesop\b",n)),
 ("rw_chain_merge", "consecutive rw merged", lambda o,n: cnt(r"\brw\b",o)>cnt(r"\brw\b",n) and has(r"\brw\b",n)),
 ("rw_to_simp_only", "rw -> simp only", lambda o,n: has(r"\brw\b",o) and has(r"simp only",n) and not has(r"\brw\b",n)),
 ("rw_to_term", "rw+exact -> term/▸", lambda o,n: has(r"\brw\b",o) and (has("▸",n) or (not has(r"\brw\b",n) and not has(r"\bsimp",n)))),
 ("rwa_simpa", "rw;exact -> rwa/simpa", lambda o,n: has(r"\b(rwa|simpa)\b",n) and not has(r"\b(rwa|simpa)\b",o)),
 ("intro_exact_to_fun", "intro+exact -> fun", lambda o,n: has(r"\bintro\b",o) and has(r"\bfun\b|λ",n) and not has(r"\bintro\b",n)),
 ("constructor_to_anon", "constructor+exacts -> ⟨,⟩", lambda o,n: has(r"\bconstructor\b|refine ⟨",o) and has("⟨",n) and cnt(r"\bconstructor\b",o)>cnt(r"\bconstructor\b",n)),
 ("bullets_to_comb", "bullets -> <;> / all_goals / exacts", lambda o,n: cnt(r"^\s*[·.] ",o)>cnt(r"^\s*[·.] ",n) and has(r"<;>|all_goals|any_goals|exacts|iterate|repeat",n)),
 ("bullets_removed", "fewer bullets", lambda o,n: cnt(r"^\s*[·.] ",o)>cnt(r"^\s*[·.] ",n)),
 ("explicit_args_to_underscore", "explicit args -> _", lambda o,n: cnt(r"\b_\b",n)>cnt(r"\b_\b",o) and len(n)<len(o)),
 ("drop_type_ascription", "(x : T) removed", lambda o,n: cnt(r"\(\w+ : [^()]+\)",o)>cnt(r"\(\w+ : [^()]+\)",n)),
 ("drop_show_change", "show/change removed", lambda o,n: cnt(r"\b(show|change)\b",o)>cnt(r"\b(show|change)\b",n)),
 ("exact_by_unwrap", "exact (by tac) -> tac", lambda o,n: has(r"exact \(?by ",o) and not has(r"exact \(?by ",n)),
 ("refine_qmark", "exact f h -> refine f ?_", lambda o,n: cnt(r"\?_",n)>cnt(r"\?_",o)),
 ("apply_exact_merge", "apply f; exact h -> exact f h", lambda o,n: has(r"\bapply\b",o) and cnt(r"\bapply\b",o)>cnt(r"\bapply\b",n)),
 ("induction_to_match_or_rec", "induction/cases restructure", lambda o,n: has(r"\b(induction|cases|rcases|match)\b",o) and has(r"\b(induction|cases|rcases|match|rec)\b",n) and len(n)<len(o)),
 ("drop_induction", "induction/cases removed", lambda o,n: has(r"\b(induction|cases)\b",o) and not has(r"\b(induction|cases)\b",n)),
 ("by_contra_push_neg", "by_contra+push_neg -> by_contra!", lambda o,n: has(r"push_neg",o) and has(r"by_contra!|contrapose!|push_neg",n) and cnt(r"\n",n)<cnt(r"\n",o)),
 ("calc_to_chain", "calc removed", lambda o,n: has(r"\bcalc\b",o) and not has(r"\bcalc\b",n)),
 ("calc_shortened", "calc fewer steps", lambda o,n: has(r"\bcalc\b",o) and has(r"\bcalc\b",n) and cnt(r"\n\s*_ ",o)>cnt(r"\n\s*_ ",n)),
 ("norm_num_replaces", "norm_num/simp arith merge", lambda o,n: has(r"norm_num|decide|simp_arith",n) and not has(r"norm_num|decide|simp_arith",o)),
 ("cast_tactics", "push_cast/exact_mod_cast", lambda o,n: has(r"exact_mod_cast|push_cast|norm_cast",n) and not has(r"exact_mod_cast|push_cast|norm_cast",o)),
 ("convert_congr", "convert/congr/gcongr", lambda o,n: has(r"convert|congr|gcongr",n) and not has(r"convert|congr|gcongr",o)),
 ("use_witness", "refine ⟨_,_⟩ -> use", lambda o,n: has(r"\buse\b",n) and not has(r"\buse\b",o)),
 ("ext_funext_removed", "ext/funext removed or merged", lambda o,n: cnt(r"\b(ext|funext)\b",o)>cnt(r"\b(ext|funext)\b",n)),
 ("simp_arg_trim", "fewer simp lemmas", lambda o,n: has(r"simp",o) and has(r"simp",n) and cnt(r",",o)>cnt(r",",n) and len(n)<len(o)),
 ("simp_star", "simp [*] / simp_all", lambda o,n: has(r"simp_all|simp \[\*|simp at \*",n) and not has(r"simp_all|simp \[\*|simp at \*",o)),
 ("exact_term_direct", "tactic block -> single exact", lambda o,n: cnt(r"\n",o)>0 and not has(r"\n",n.strip()) and has(r"^\s*exact",n)),
 ("positivity_gcongr", "inequality tactic", lambda o,n: has(r"positivity|gcongr|bound",n) and not has(r"positivity|gcongr|bound",o)),
 ("term_mode_lambda", "fun x => f x -> f / (· ..)", lambda o,n: has(r"fun \w+ (=>|↦)",o) and cnt(r"fun \w+ (=>|↦)",o)>cnt(r"fun \w+ (=>|↦)",n)),
 ("pipe_paren_removal", "parens -> <| / |>", lambda o,n: cnt(r"\(",o)>cnt(r"\(",n) and has(r"<\||\|>",n)),
 ("lemma_swap", "different lemma names, same shape", lambda o,n: set(re.findall(r"[A-Za-z_.]+\.[a-z_]+",o))!=set(re.findall(r"[A-Za-z_.]+\.[a-z_]+",n)) and len(n)<len(o)),
 ("other_shrink", "uncategorised shrink", lambda o,n: len(n)<len(o)),
]
def classify(o,n):
    return [name for name,_,p in RULES if p(o,n)]

def pairs():
    for r in sorted(os.listdir(RUNS)):
        d=RUNS/r
        try:
            h=_jsonl(d/'ledger.jsonl')
            def rd(p,d=d):
                f=d/'proofs'/f'{p}.lean'
                return f.read_text(encoding='utf-8') if f.exists() else None
            g=Graph.from_history(h,rd,committed_operations=committed_operation_ids(d))
        except Exception: continue
        by={n.proof_id:n for n in g.nodes}
        for n in g.nodes:
            fr=(n.edge or {}).get("from") or []
            if not fr or fr[0] not in by or n.origin=="reference": continue
            p=by[fr[0]]
            if not(n.verified and p.verified and n.tokens and p.tokens): continue
            a,b=rd(p.proof_id),rd(n.proof_id)
            if a and b and a!=b: yield n,p,a,b

def main():
    agg={}; npairs=0; improving=0; tokcache={}
    def tk(t):
        if t not in tokcache: tokcache[t]=snippet_tokens(t) if t.strip() else 0
        return tokcache[t]
    for n,p,a,b in pairs():
        npairs+=1
        if not(n.tokens<p.tokens or (n.heartbeats and p.heartbeats and n.heartbeats<p.heartbeats)): continue
        improving+=1
        sa=[s.text for s in split_steps(a)]; sb=[s.text for s in split_steps(b)]
        ops=[op for op in difflib.SequenceMatcher(None,sa,sb,autojunk=False).get_opcodes() if op[0]!="equal"]
        single=len(ops)==1
        L=max(len(sa),1)
        for tag,i1,i2,j1,j2 in ops:
            rel=(i1+i2)/2/L
            pos="opening" if (i1==0 or rel<0.2) else "closing" if (i2>=len(sa) or rel>=0.8) else "middle"
            o="\n".join(sa[i1:i2]); nw="\n".join(sb[j1:j2])
            if tag=="insert" or not o.strip(): cls=["step_added"]
            elif tag=="delete" or not nw.strip(): cls=["step_deleted"]
            else: cls=classify(o,nw) or ["unclassified"]
            try: dt=tk(nw)-tk(o)
            except Exception: continue
            for c in cls[:3]:   # first three matching tags
                e=agg.setdefault(c,{"count":0,"dtok":[],"dhb_single":[],"runs":set(),"pos":{}})
                pe=e["pos"].setdefault(pos,{"tok":[],"hb":[]}); pe["tok"].append(dt)
                e["count"]+=1; e["dtok"].append(dt); e["runs"].add(n.id[:0]+str(id(p))[:0])
                if single and n.heartbeats and p.heartbeats: (e["dhb_single"].append(n.heartbeats-p.heartbeats), pe["hb"].append(n.heartbeats-p.heartbeats))
    feats={name:f for name,f,_ in RULES}
    out={"pairs_seen":npairs,"improving_pairs":improving,"moves":{}}
    for c,e in sorted(agg.items(),key=lambda kv:-kv[1]["count"]):
        out["moves"][c]={"count":e["count"],"features":feats.get(c,""),
          "mean_step_token_delta":round(st.mean(e["dtok"]),2),
          "median_step_token_delta":st.median(e["dtok"]),
          "share_token_reducing":round(sum(x<0 for x in e["dtok"])/len(e["dtok"]),2),
          "n_hb_single":len(e["dhb_single"]),
          "mean_hb_delta_single_step_pairs":round(st.mean(e["dhb_single"])) if e["dhb_single"] else None,
          "share_hb_reducing":round(sum(x<0 for x in e["dhb_single"])/len(e["dhb_single"]),2) if e["dhb_single"] else None}
    def sg(xs):
        return {"n":len(xs),"down":sum(x<0 for x in xs),"up":sum(x>0 for x in xs),"mean":round(st.mean(xs)) if xs else None}
    for c,e in agg.items():
        out["moves"][c]["positions"]={b:{"tokens":sg(v["tok"]),"heartbeats":sg(v["hb"])} for b,v in sorted(e["pos"].items())}
    json.dump(out,open("research/strategy-bank/move-stats.json","w"),indent=1)
    print(npairs,improving)
    for c,v in out["moves"].items(): print(c,v["count"],v["mean_step_token_delta"],v["share_token_reducing"],v["n_hb_single"],v["mean_hb_delta_single_step_pairs"])
main()
