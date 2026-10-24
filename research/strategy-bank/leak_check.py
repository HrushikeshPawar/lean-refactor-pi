"""Fail if cards.yaml contains benchmark-specific identifiers or 25+ char substrings of benchmark proofs.

Run: uv run --no-sync python research/strategy-bank/leak_check.py
"""
import json, re, sys
from pathlib import Path
from arena import engine
from arena.package import RUNS

HERE = Path(__file__).parent
CARDS = (HERE / "cards.yaml").read_text(encoding="utf-8")
SUB = RUNS / "v8d-submission"
NAMES = list(json.load(open(SUB / "scores.json")))
rows = [engine.problem(n) for n in NAMES]

# --- texts that count as "benchmark proof material"
texts = []
for r in rows:
    texts += [r["src"], r["statement"]]
for line in (SUB / "submission.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        j = json.loads(line)
        texts += [v for v in j.values() if isinstance(v, str) and len(v) > 25]
theorems = set(NAMES)
for d in RUNS.iterdir():
    try:
        cfg = json.load(open(d / "run-config.json"))
    except Exception:
        continue
    if cfg.get("theorem") in theorems:
        for f in (d / "proofs").glob("*.lean"):
            texts.append(f.read_text(encoding="utf-8"))
# names of the problems themselves and project paths
extra_names = set()
for r in rows:
    for key in ("name", "file_path"):
        extra_names |= set(re.findall(r"[A-Za-z][A-Za-z0-9_']{2,}", r.get(key, "")))

# --- identifier extraction
ID = re.compile(r"[A-Za-z_Ͱ-Ͽᴀ-ᶿ][\w'!?₀-₟ᵢ-ᵪ]*(?:\.[A-Za-z_][\w'!?]*)*")
LEAN_WORDS = set("""theorem lemma def example by exact apply intro intros rintro rcases obtain cases induction match with fun have show from at using
 simp simpa simp_all rw rwa nth_rewrite omega linarith nlinarith positivity gcongr norm_num norm_cast push_cast exact_mod_cast decide rfl trivial aesop grind
 constructor refine use exists ext funext congr convert calc split_ifs by_cases by_contra push_neg contrapose subst clear set let generalize specialize
 all_goals any_goals first try repeat choose rotate_left swap letI haveI iterate fin_cases interval_cases tauto ring ring_nf field_simp unfold change dsimp rename_i exacts assumption left right
 open namespace section variable universe import end in only if then else do return where instance structure class inductive abbrev private protected noncomputable
 sorry True False And Or Not Iff Eq Ne Exists Prop Type Sort Nat Int Real Rat Fin List Array Finset Set Multiset Option Bool String Unit Prod Sum Sigma Subtype
 Function id fst snd inl inr intro elim mp mpr symm trans refl left right some none cons nil succ zero length map filter sum prod card range max min abs
 mod div pow add mul sub neg inv lt le ge gt ne mem insert erase union inter subset sq sqrt exp log sin cos
 rec induction Decidable Inhabited Nonempty Monotone Continuous Differentiable Even Odd Prime Dvd gcd lcm""".split())
GENERIC_PREFIX = re.compile(r"^(Nat|Int|List|Array|Finset|Set|Multiset|Option|Bool|String|Fin|Prod|Sum|Function|Real|Rat|Or|And|Iff|Eq|Exists|Not|Subtype|Classical|Decidable|"
    r"le_|lt_|ge_|gt_|ne_|eq_|add_|sub_|mul_|div_|neg_|pow_|sq_|abs_|max_|min_|mem_|not_|and_|or_|iff_|exists_|forall_|congr|sum_|prod_|card_|zero_|one_|two_|succ_|pos_|nonneg_|"
    r"Finsupp|Polynomial|Matrix|Monotone|Antitone|Continuous|StrictMono|Std|Lean|Mathlib|Id|Prop|Type|Sort|Dvd|Nonempty|Inhabited|Zero|One|Add|Mul|Neg|Sub|Div|Inv|Ring|Field|Group|Monoid|"
    r"Order|Lattice|Preorder|PartialOrder|LinearOrder|Unit|ENat|NNReal|ENNReal|Complex|Pi|Sigma|PUnit|True|False|Even|Odd|Prime|Fintype|DecidableEq|Finite|Infinite)\b")
LEAN_NS_LEMMA = re.compile(r"^[a-z]+(_[a-z0-9']+)+$")  # snake_case generic lemma shape

EXTRA_GENERIC = set("""by_contra! fun_prop exact? grind? rw? apply? simp? with_reducible continuity measurability generalizing conv if_pos if_neg continuous_const
 le_trans lt_of_lt_of_le split_ifs push_neg arith split this exact_mod_cast simp_arith decide cast const defs""".split())

def generic(i: str) -> bool:
    if i in EXTRA_GENERIC or ('.' in i and generic(i.split('.')[0])):
        return True
    if i in LEAN_WORDS or len(i) <= 3 or GENERIC_PREFIX.match(i):
        return True
    if re.fullmatch(r"h[A-Za-z0-9_']*|[a-z]\d*|[a-z][a-z0-9]?'*", i):  # hypotheses / variables
        return True
    return False

def code_only(t):
    t = re.sub(r"/-.*?-/", " ", t, flags=re.S)
    return re.sub(r"--[^\n]*", " ", t)

bench_ids = set()
for t in texts:
    for i in ID.findall(code_only(t)):
        if not generic(i):
            bench_ids.add(i)
bench_ids |= {n for n in extra_names if not generic(n)}

# generic allowlist: snake_case Mathlib-shaped names whose first component is generic vocabulary
allow_tail = {i for i in bench_ids if LEAN_NS_LEMMA.match(i) and i.split("_")[0] in {"le","lt","ge","gt","ne","eq","add","sub","mul","div","neg","pow","sq","abs","max","min","mem","not","and","or","iff","exists","forall","sum","prod","card","zero","one","two","succ","pos","nonneg","nat","int","list","finset","set","of","is","exp","log","sin","cos","sqrt"}}
# these are Mathlib-shaped; still flagged if they appear in cards AND are not part of the generic lemma allowlist below.
GENERIC_LEMMAS = set(re.findall(r"[A-Za-z_][\w'.]*", ""))

code_lines = [l for l in CARDS.splitlines() if not re.match(r"\s+(when|how|title|version_notes|id|move_class|opening|middle|closing):", l)]
prose_lines = [l for l in CARDS.splitlines() if re.match(r"\s+(when|how|title|version_notes|id|move_class|opening|middle|closing):", l)]
cards_ids = set(ID.findall("\n".join(code_lines)))
cards_ids |= {i for l in prose_lines for i in ID.findall(l) if re.search(r"[_.'!?]|[a-z][A-Z]", i) or i[0].isupper()}
flagged_ids = sorted(i for i in cards_ids if i in bench_ids and i not in allow_tail and not generic(i))
flagged_soft = sorted(i for i in cards_ids if i in allow_tail)  # reported for manual review

# --- 25-char shingles
def norm(s): return re.sub(r"\s+", "", s)
K = 25
shingles = set()
for t in texts:
    n = norm(t)
    for k in range(0, max(0, len(n) - K + 1)):
        shingles.add(n[k:k + K])
cn = norm(CARDS)
hits = sorted({cn[k:k + K] for k in range(0, len(cn) - K + 1) if cn[k:k + K] in shingles})

print("benchmark rows:", len(rows), "| identifier pool:", len(bench_ids), "| texts:", len(texts))
print("FLAGGED identifiers:", flagged_ids)
print("Soft (generic-shaped snake_case, review):", flagged_soft)
print("FLAGGED 25-char substrings:", len(hits), hits[:10] if "--all" not in sys.argv else hits)
if "--allowlist" in sys.argv:
    print("allowlist prefixes:", GENERIC_PREFIX.pattern); print("allowlist words:", sorted(LEAN_WORDS))
sys.exit(1 if (flagged_ids or hits) else 0)
