"""Builds cards.yaml: hand-written generic cards + measured effect pulled from move-stats.json."""
import json
from pathlib import Path
D = Path(__file__).parent
stats = json.load(open(D / "move-stats.json"))["moves"]

C = []
def card(id, title, when, how, before, after, move=None, source="mined", notes="", tags=(), pub="", goal_tags=(), at=None):
    C.append(dict(id=id, title=title, when=when, how=how, before=before.strip("\n"), after=after.strip("\n"),
                  move=move, source=source, notes=notes, tags=list(tags), pub=pub, goal_tags=list(goal_tags), at=at or {}))

# ---- mined + public: term/tactic shrinking ----
card("obtain-to-projection","Replace destructuring with projections",
 "A hypothesis of type A ∧ B, A ↔ B or ∃ is destructured, and each component is used once.",
 "Use h.1 / h.2 / h.mp / h.mpr / h.left directly where the component is needed. For ∃, keep one obtain only if the witness is used several times.",
 "example (p q : Prop) (h : p ∧ q) : q ∧ p := by\n  obtain ⟨hp, hq⟩ := h\n  exact ⟨hq, hp⟩",
 "example (p q : Prop) (h : p ∧ q) : q ∧ p := ⟨h.2, h.1⟩","obtain_to_projection",tags=["obtain","rcases","cases","anonymous-constructor"],source="both")
card("rintro-merge","Merge intro with pattern matching",
 "Goal starts with intro followed by rcases/obtain on the introduced hypothesis.",
 "Use rintro with the pattern. rintro ⟨a, rfl⟩ also substitutes equalities on the spot.",
 "example (p q r : Prop) : p ∧ q → r ∨ p := by\n  intro h\n  obtain ⟨hp, _⟩ := h\n  exact Or.inr hp",
 "example (p q r : Prop) : p ∧ q → r ∨ p := by\n  rintro ⟨hp, -⟩\n  exact .inr hp","rcases_to_rintro",tags=["intro","rintro","rcases"],source="both")
card("inline-single-use-have","Inline a single-use have into the term that uses it",
 "have h : T := by tac, then exactly one later use as an argument.",
 "Pass (by tac) in the argument position; the expected type is then known, so T is not written.",
 "example (a b : ℕ) (f : a < b → a ≤ b) (h0 : a + 1 ≤ b) : a ≤ b := by\n  have h : a < b := by omega\n  exact f h",
 "example (a b : ℕ) (f : a < b → a ≤ b) (h0 : a + 1 ≤ b) : a ≤ b :=\n  f (by omega)","inline_have_into_term",tags=["have","exact","by"],source="both",
 notes="Do not inline a have used 3 or more times; the term is then copied each time.")
card("inline-have-as-show-rw","Turn a have used only by rw into an inline show",
 "have h : a = b := by tac; rw [h] with no other use of h.",
 "rw [show a = b by tac] (or from term). The statement can often be partly elided: show _ = b.",
 "example (x y : ℕ) (hy : y = 2 * x) : x + y = 3 * x := by\n  have h : x + y = x + 2 * x := by rw [hy]\n  rw [h]; ring",
 "example (x y : ℕ) (hy : y = 2 * x) : x + y = 3 * x := by\n  rw [hy]; ring","inline_have_show",tags=["have","rw","show"],source="both",
 notes="Often the whole have dissolves once the hypothesis is rewritten directly; check whether the closing tactic works without it.")
card("merge-have-chain","Collapse a chain of small haves",
 "Several consecutive have lines each feed only the next one or the final close.",
 "Fold them into the final call: pass them as terms, give them to simp/omega/linarith as arguments, or let a closer find them from context.",
 "example (a b c : ℤ) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c + 1 := by\n  have h3 : a ≤ c := le_trans h1 h2\n  have h4 : c ≤ c + 1 := by omega\n  exact le_trans h3 h4",
 "example (a b c : ℤ) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c + 1 := by omega","drop_have_chain",tags=["have","omega"],source="both")
card("drop-set-let","Delete set / let / generalize abbreviations",
 "A local abbreviation is introduced to shorten text, but is used fewer than about three times.",
 "Substitute the definition back, or delete the abbreviation if the closing tactic does not need it. Names count as one token, so an abbreviation only pays when it replaces a long expression used often.",
 "example (a b : ℕ) (h : a < b) : a + 1 ≤ b := by\n  set d := b - a with hd\n  omega",
 "example (a b : ℕ) (h : a < b) : a + 1 ≤ b := by omega","drop_set_let",tags=["set","let","generalize"],source="both")
card("simp-to-simp-only","Squeeze a bare simp for heartbeats",
 "A non-terminal simp or simp [..] is expensive (the profiler shows it) and runs on a big context.",
 "Run simp? once, paste the simp only list. The list adds tokens but removes simp's search. Use when heartbeat weight dominates.",
 "example (xs ys : List ℕ) : (xs ++ ys).length = ys.length + xs.length := by\n  simp [Nat.add_comm]",
 "example (xs ys : List ℕ) : (xs ++ ys).length = ys.length + xs.length := by\n  simp only [List.length_append, Nat.add_comm]","simp_to_simp_only",tags=["simp","heartbeats"],source="both",
 notes="Lemma lists break on renames across Lean 4.25-4.33; keep a bare simp as fallback if versions matter more than heartbeats. 4.33 transparency change can stop listed lemmas from firing.")
card("simp-only-to-simp","Drop a simp only list when bare simp is as fast",
 "simp only [long list] where bare simp closes the goal; the list costs many tokens.",
 "Try plain simp (or simp with one or two lemmas). Keep it only if heartbeats do not rise by more than the token gain is worth.",
 "example (xs : List ℕ) : (xs.map (· + 1)).length = xs.length := by\n  simp only [List.length_map]",
 "example (xs : List ℕ) : (xs.map (· + 1)).length = xs.length := by simp","simp_only_to_simp",tags=["simp"],source="both",
 notes="Bare simp is the most version-stable form.")
card("grind-closer","Replace a multi-step arithmetic or case chain by grind",
 "Goal after intros is first-order with equalities, linear arithmetic, or constructor injectivity; the manual proof is several lines.",
 "Try grind, then grind only [lemmas] from grind? to bound cost. Tokens fall, but grind can cost much more search than the steps it replaces; check the profile before and after.",
 "example (a b : ℕ) (h : a = b + 1) (h2 : b > 3) : a > 4 ∧ a ≠ 0 := by\n  constructor <;> omega",
 "example (a b : ℕ) (h : a = b + 1) (h2 : b > 3) : a > 4 ∧ a ≠ 0 := by grind","grind_replaces",tags=["grind"],source="both",
 notes="grind behaviour changed in 4.26 (cutsat to lia), 4.30 (canonicalizer), 4.32, 4.33; a bare grind can flip between versions. Fallback: first | omega | grind.")
card("grind-to-explicit","Replace grind that is too slow or unstable",
 "grind closes a goal but costs many heartbeats or fails on another toolchain.",
 "Read grind? output; use grind only [..] or replace with omega/simp_all/exact of the lemma it used.",
 "example (xs : List ℕ) (h : xs = []) : xs.length = 0 := by grind",
 "example (xs : List ℕ) (h : xs = []) : xs.length = 0 := by simp [h]","grind_removed",tags=["grind","heartbeats"],source="both",
 notes="Library names can change between versions; keep grind as the fallback if the explicit term breaks.")
card("omega-for-arith","Close linear Nat/Int goals with omega",
 "A chain of le_trans / add_lt_add / Nat.* lemma steps or calc over linear arithmetic with +, -, *const, /const, %const, min, max.",
 "One omega. If context is large, clear unrelated hypotheses first, since omega reads all of them.",
 "example (n m : ℕ) (h : n < m) : n + 2 ≤ m + 1 := by\n  have := Nat.succ_le_of_lt h\n  exact Nat.succ_le_succ this",
 "example (n m : ℕ) (h : n < m) : n + 2 ≤ m + 1 := by omega","omega_replaces",tags=["omega","arith"],source="both",
 notes="From 4.33, lia is a stronger sibling; omega stays stable across 4.25-4.33.")
card("nonlinear-to-omega-or-positivity","Swap linarith/nlinarith for a cheaper decision tactic",
 "linarith or nlinarith on a goal that is linear over ℕ/ℤ, or a positivity/monotonicity claim.",
 "Use omega for linear integer goals; positivity for 0 < / 0 ≤ of products, sums, powers; gcongr for monotone shapes.",
 "example (x y : ℤ) (h : 0 ≤ x) (h' : 0 ≤ y) : 0 ≤ x + 2 * y := by linarith",
 "example (x y : ℤ) (h : 0 ≤ x) (h' : 0 ≤ y) : 0 ≤ x + 2 * y := by omega","linarith_to_omega",tags=["linarith","nlinarith","positivity"],source="both")
card("aesop-to-script","Replace aesop by its explicit script",
 "aesop closes a goal but is slow or its search is opaque.",
 "Use aesop? and paste the Try this script, then shorten with simp_all or exact.",
 "example (p q : Prop) (hp : p) (hq : q) : p ∧ q := by aesop",
 "example (p q : Prop) (hp : p) (hq : q) : p ∧ q := ⟨hp, hq⟩","aesop_replaced",tags=["aesop","heartbeats"],source="both")
card("rw-merge","Merge consecutive rewrites",
 "Several rw lines in a row on the same goal or hypothesis.",
 "One rw [a, b, c]. Add at h ⊢ to hit several locations at once.",
 "example (a b : ℕ) (h1 : a = b) (h2 : b = 3) : a + 0 = 3 := by\n  rw [Nat.add_zero]\n  rw [h1]\n  rw [h2]",
 "example (a b : ℕ) (h1 : a = b) (h2 : b = 3) : a + 0 = 3 := by\n  rw [Nat.add_zero, h1, h2]","rw_chain_merge",tags=["rw"],source="both")
card("rw-to-simp-only","Use simp only when rw hits motive trouble or repeated patterns",
 "A rw chain repeats one rewrite across many occurrences, or needs conv / nth_rewrite.",
 "simp only [lemma] rewrites all instances and goes under binders.",
 "example (f : ℕ → ℕ) (h : ∀ x, f x = x) : f 1 + f 2 = 3 := by\n  rw [h 1, h 2]",
 "example (f : ℕ → ℕ) (h : ∀ x, f x = x) : f 1 + f 2 = 3 := by\n  simp only [h]","rw_to_simp_only",tags=["rw","simp only","binders"],source="both",
 notes="rw is cheaper than simp when it works; use this only when rw fails or needs several lines.")
card("rw-to-transport","Replace rw+exact by a term (▸ or Eq.mp)",
 "rw [h]; exact t where the rewrite only changes the goal's type.",
 "h ▸ t, or (h ▸ t : T). Test the motive; if it fails, use rwa [h].",
 "example (a b : ℕ) (h : a = b) (p : ℕ → Prop) (ha : p a) : p b := by\n  rw [← h]\n  exact ha",
 "example (a b : ℕ) (h : a = b) (p : ℕ → Prop) (ha : p a) : p b := h ▸ ha","rw_to_term",tags=["rw","transport"],source="both")
card("rwa-simpa","Fuse rewrite/simp with the closing assumption",
 "rw/simp at h followed by exact h, or rw then assumption.",
 "rwa [..] at h, or simpa [..] using h.",
 "example (a b : ℕ) (h : a + 0 = b) : a = b := by\n  rw [Nat.add_zero] at h\n  exact h",
 "example (a b : ℕ) (h : a + 0 = b) : a = b := by\n  simpa using h","rwa_simpa",tags=["rwa","simpa"],source="both",
 notes="simpa is brittle if a linter-fired simp set changes; rwa is stable.")
card("intro-to-fun","Turn intro + exact into a lambda",
 "Goal is ∀ / → and the proof is intro x y followed by one exact.",
 "Write fun x y => term, or fun ⟨a, b⟩ => .. for patterns.",
 "example (p q : Prop) : p → q → p := by\n  intro hp _\n  exact hp",
 "example (p q : Prop) : p → q → p := fun hp _ => hp","intro_exact_to_fun",tags=["intro","fun"],source="both")
card("constructor-to-anonymous","constructor/refine ⟨?_, ?_⟩ + exacts -> anonymous constructor",
 "Goal is a structure, ∧, ↔ or ∃ and every field has a one-line proof.",
 "⟨a, b⟩ in term mode; (by tac) per field if needed. For ↔ use ⟨fun h => .., fun h => ..⟩.",
 "example (p q : Prop) (hp : p) (hq : q) : p ∧ q := by\n  constructor\n  · exact hp\n  · exact hq",
 "example (p q : Prop) (hp : p) (hq : q) : p ∧ q := ⟨hp, hq⟩","constructor_to_anon",tags=["constructor","anonymous-constructor"],source="both")
card("bullets-to-combinators","Replace parallel bullets with <;>, all_goals or exacts",
 "Several sibling goals are closed by the same tactic or by one-line exacts.",
 "t <;> s runs s on every goal from t; exacts [a, b]; all_goals s for leftover goals.",
 "example (p q : Prop) (hp : p) (hq : q) : (p ∧ q) ∧ (q ∧ p) := by\n  refine ⟨⟨?_, ?_⟩, ⟨?_, ?_⟩⟩\n  · exact hp\n  · exact hq\n  · exact hq\n  · exact hp",
 "example (p q : Prop) (hp : p) (hq : q) : (p ∧ q) ∧ (q ∧ p) := by\n  refine ⟨⟨?_, ?_⟩, ⟨?_, ?_⟩⟩ <;> assumption","bullets_to_comb",tags=["bullets","<;>","all_goals","exacts"],source="both",
 notes="<;> reruns elaboration per goal; fine for cheap closers, wasteful for simp_all on big contexts.")
card("drop-bullets","Remove bullets when goals are closed in order by single tactics",
 "Bullet blocks with a single short tactic each.",
 "exacts [..], or a flat sequence of exact with focusing handled by the tactic (case _ or no focus) when only one goal remains each time.",
 "example (p q : Prop) (hp : p) (hq : q) : p ∧ q := by\n  refine ⟨?_, ?_⟩\n  · exact hp\n  · exact hq",
 "example (p q : Prop) (hp : p) (hq : q) : p ∧ q := by\n  refine ⟨?_, ?_⟩\n  exacts [hp, hq]","bullets_removed",tags=["bullets","exacts"],source="both")
card("explicit-to-underscore","Replace derivable explicit arguments by _",
 "A lemma application spells arguments the unifier can infer from hypotheses or the goal.",
 "Use _ for them, or drop (x := ..) named args. Keep the ones the unifier cannot solve (compile to check).",
 "example (a b c : ℕ) (h : a ≤ b) : a + c ≤ b + c :=\n  Nat.add_le_add_right h c",
 "example (a b c : ℕ) (h : a ≤ b) : a + c ≤ b + c :=\n  Nat.add_le_add_right h _","explicit_args_to_underscore",tags=["args","underscore","unification"],source="both",
 notes="Underscores can make elaboration slower if unification postpones; check heartbeats.")
card("drop-type-ascription","Drop type ascriptions the elaborator infers",
 "(x : T) casts, (f : A → B) annotations, binder types in fun/∀ that follow from the expected type.",
 "Delete, recompile. Keep numerals ascribed only when elaboration becomes ambiguous (ℕ vs ℤ vs ℝ).",
 "example : ∀ n : ℕ, n + 0 = n := fun (n : ℕ) => rfl",
 "example : ∀ n : ℕ, n + 0 = n := fun _ => rfl","drop_type_ascription",tags=["ascription","binder"],source="both")
card("drop-show-change","Remove show/change before a tactic that does not need it",
 "show T or change T followed by tactics that work on the original goal form.",
 "Delete. Keep when the later tactic depends on the unfolded form; then prefer a term ascription (h : T).",
 "example (n : ℕ) : n * 1 = n := by\n  show n * 1 = n\n  simp",
 "example (n : ℕ) : n * 1 = n := by simp","drop_show_change",tags=["show","change"],source="both",
 notes="The change ... with syntax was removed in Lean 4.30; avoid it.")
card("unwrap-exact-by","Unwrap redundant by / exact wrappers",
 "exact (by tac), by exact t, by rfl, `by simpa using h` where h already has the type.",
 "Write tac directly, or the bare term t / rfl / h.",
 "example (n : ℕ) : n + 0 = n := by exact (by simp)",
 "example (n : ℕ) : n + 0 = n := rfl","exact_by_unwrap",tags=["exact","by","rfl"],source="both")
card("refine-holes","Use refine with ?_ to delay only the unknown sub-proofs",
 "exact f a b (by tac1) (by tac2) or apply f followed by a goal-by-goal rewrite.",
 "refine f a b ?_ ?_ <;> tac, or refine f (?_ : T) when the type of a middle step needs naming once.",
 "example (p q r : Prop) (h : p → q) (g : q → r) (hp : p) : r := by\n  apply g\n  apply h\n  exact hp",
 "example (p q r : Prop) (h : p → q) (g : q → r) (hp : p) : r := by\n  refine g (h ?_)\n  exact hp","refine_qmark",tags=["refine","apply"],source="both")
card("apply-exact-merge","Merge apply f; exact h into exact f h",
 "apply followed by one exact (or assumption).",
 "exact f h (or exact f ‹_›).",
 "example (p q : Prop) (f : p → q) (hp : p) : q := by\n  apply f\n  exact hp",
 "example (p q : Prop) (f : p → q) (hp : p) : q := f hp","apply_exact_merge",tags=["apply","exact"],source="both")
card("restructure-induction-as-match","Restructure case analysis into a flat match or rcases",
 "Nested cases / induction / bullets, each case short.",
 "match n with | 0 => .. | k + 1 => .. ; rcases n with _ | _ | n ; or induction n <;> simp_all for uniform cases.",
 "example (n : ℕ) : n = 0 ∨ 0 < n := by\n  cases n with\n  | zero => exact Or.inl rfl\n  | succ k => exact Or.inr (Nat.succ_pos k)",
 "example (n : ℕ) : n = 0 ∨ 0 < n := by omega","induction_to_match_or_rec",tags=["induction","cases","match","rcases"],source="both",
 notes="Goal order after cases/induction on match-defined functions changed in 4.26; avoid relying on case tags and rename_i.")
card("drop-induction","Eliminate an induction that a closer or library lemma already covers",
 "induction/cases whose branches are all closed by the same decision procedure.",
 "Delete induction, call the closer on the whole goal; or use a library recursion principle.",
 "example (n : ℕ) : n < n + 1 := by\n  induction n with\n  | zero => decide\n  | succ k ih => omega",
 "example (n : ℕ) : n < n + 1 := by omega","drop_induction",tags=["induction"],source="both",
 notes="Heartbeats can rise on this move when the closer must do real search; verify.")
card("by-contra-bang","Merge by_contra with push_neg",
 "by_contra h; push_neg at h, or by_contra then simp at h.",
 "by_contra! h (and contrapose! for contrapositive).",
 "example (a b : ℕ) (h : ¬ b < a) : a ≤ b := by\n  by_contra h2\n  push_neg at h2\n  omega",
 "example (a b : ℕ) (h : ¬ b < a) : a ≤ b := by\n  by_contra! h2\n  omega","by_contra_push_neg",tags=["by_contra","push_neg","contrapose"],source="both")
card("calc-to-trans","Shorten calc chains",
 "calc with two or three steps, or steps that are each closed by a one-line lemma.",
 "Use .trans / le_trans / lt_of_lt_of_le chains, or one omega/nlinarith/positivity for the whole inequality. Heartbeats can fall because calc rechecks every _ line.",
 "example (a b c : ℕ) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c := by\n  calc a ≤ b := h1\n    _ ≤ c := h2",
 "example (a b c : ℕ) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c := h1.trans h2","calc_to_chain",tags=["calc","trans"],source="both")
card("calc-fewer-steps","Remove an intermediate calc line",
 "Two adjacent calc steps use the same relation and the first is by rfl/simp/ring.",
 "Merge them into one step whose proof is one tactic (ring, omega, simp).",
 "example (a b : ℕ) : a * 2 + b = b + a + a := by\n  calc a * 2 + b = a + a + b := by ring\n    _ = b + a + a := by ring",
 "example (a b : ℕ) : a * 2 + b = b + a + a := by\n  calc a * 2 + b = b + a + a := by ring","calc_shortened",tags=["calc","ring"],source="both")
card("numeric-closers","Close concrete numeric facts with norm_num / decide / simp arith",
 "Goals about literals, small bounded Finset/Fin/Nat facts, divisibility of numerals.",
 "norm_num [defs] in one call; decide for tiny decidable props; omega for linear.",
 "example : (12 : ℕ) % 5 = 2 ∧ 2 ^ 5 = 32 := by\n  constructor\n  · rfl\n  · rfl",
 "example : (12 : ℕ) % 5 = 2 ∧ 2 ^ 5 = 32 := by norm_num","norm_num_replaces",tags=["norm_num","decide"],source="both",
 notes="decide cost explodes on big Nat/Finset terms; bound the range first.")
card("cast-tactics","Use norm_cast / push_cast / exact_mod_cast over manual cast lemmas",
 "Goal mixes ↑n casts and chains of Nat.cast_add / Int.natCast_* rewrites.",
 "exact_mod_cast h; push_cast; norm_cast at h ⊢.",
 "example (a b : ℕ) (h : a ≤ b) : (a : ℤ) ≤ b := by\n  rw [Int.ofNat_le]\n  exact h",
 "example (a b : ℕ) (h : a ≤ b) : (a : ℤ) ≤ b := by exact_mod_cast h","cast_tactics",tags=["cast","norm_cast"],source="both",
 notes="Library cast lemma names (Int.ofNat_*, Int.natCast_*) were renamed repeatedly; cast tactics are stable.")
card("convert-congr","Use convert / congr / gcongr instead of rewrite scaffolding",
 "Goal differs from a known fact only in a subterm.",
 "convert h using 2 leaves just the differing subgoals; congr! and gcongr for function applications and monotone shapes.",
 "example (f : ℕ → ℕ) (a b : ℕ) (h : a = b) : f (a + 0) = f b := by\n  rw [Nat.add_zero, h]",
 "example (f : ℕ → ℕ) (a b : ℕ) (h : a = b) : f (a + 0) = f b := by\n  simp [h]","convert_congr",tags=["convert","congr","gcongr"],source="both")
card("use-witness","Use use for existential goals",
 "refine ⟨w, ?_⟩ then a closing tactic, or exists w.",
 "use w closes trivial residual goals automatically (rfl, trivial).",
 "example : ∃ n : ℕ, n + 2 = 5 := by\n  refine ⟨3, ?_⟩\n  rfl",
 "example : ∃ n : ℕ, n + 2 = 5 := ⟨3, rfl⟩","use_witness",tags=["exists","use"],source="both")
card("drop-ext","Remove ext / funext that simp or the lemma already handles",
 "ext x followed by rfl/simp, or Subtype.ext/Fin.ext before simp.",
 "Delete the ext and call simp/rfl on the equation, or use funext _ <;> exact.",
 "example (f : ℕ → ℕ) : (fun x => f x) = f := by\n  funext x\n  rfl",
 "example (f : ℕ → ℕ) : (fun x => f x) = f := rfl","ext_funext_removed",tags=["ext","funext"],source="both")
card("trim-simp-args","Trim simp lemma lists",
 "simp [a, b, c, d] where some lemmas are already simp lemmas or unused.",
 "Remove one lemma at a time and recompile (a linter flags unused simp args). Fewer tokens, usually fewer heartbeats.",
 "example (xs : List ℕ) : (xs ++ []).length = xs.length := by\n  simp [List.length_append, List.append_nil]",
 "example (xs : List ℕ) : (xs ++ []).length = xs.length := by simp","simp_arg_trim",tags=["simp"],source="both")
card("simp-star","Close side goals with one simp [*] / simp_all",
 "Many residual goals each closed by a short simp or assumption.",
 "all_goals simp [*] once at the end, or simp_all.",
 "example (a b : ℕ) (h : a = b) : a + 1 = b + 1 ∧ b = a := by\n  refine ⟨?_, ?_⟩\n  · rw [h]\n  · rw [h]",
 "example (a b : ℕ) (h : a = b) : a + 1 = b + 1 ∧ b = a := by\n  refine ⟨?_, ?_⟩ <;> simp [*]","simp_star",tags=["simp_all","simp [*]"],source="both",
 notes="Quadratic on big contexts; clear unrelated hypotheses first.")
card("positivity-gcongr","Use positivity / gcongr for sign and monotonicity goals",
 "0 < e, 0 ≤ e, or f x ≤ f y with the same outer shape.",
 "positivity; gcongr (then side goals ?_ are usually assumptions).",
 "example (x : ℝ) (h : 0 < x) : 0 < x ^ 2 + x := by\n  have := sq_nonneg x\n  linarith",
 "example (x : ℝ) (h : 0 < x) : 0 < x ^ 2 + x := by positivity","positivity_gcongr",tags=["positivity","gcongr"],source="both")
card("lambda-sections","Use (· op x) sections and eta-reduce lambdas",
 "fun x => f x, fun x => x + 1, fun x => g (h x).",
 "f, (· + 1), g ∘ h.",
 "example (xs : List ℕ) : (xs.map (fun x => x + 1)).length = xs.length := by simp",
 "example (xs : List ℕ) : (xs.map (· + 1)).length = xs.length := by simp","term_mode_lambda",tags=["lambda","eta"],source="both")
card("remove-parens","Remove parentheses with <| and |>",
 "Nested applications ending in a long argument; each paren pair costs 2 tokens.",
 "f <| g <| x, or x |> f. Do not mix with dot-notation chains.",
 "example (a b : ℕ) (h : a ≤ b) : a ≤ b + 1 :=\n  Nat.le_succ_of_le (Nat.le_trans h (Nat.le_refl b))",
 "example (a b : ℕ) (h : a ≤ b) : a ≤ b + 1 :=\n  Nat.le_succ_of_le <| Nat.le_trans h <| Nat.le_refl b","pipe_paren_removal",tags=["parens","<|"],source="both")
card("swap-to-library-lemma","Replace a hand-written multi-step argument by one library lemma",
 "Several steps recompute a fact (monotonicity, membership, cardinality, sum) that has a named lemma.",
 "Search with exact? / apply? / rw? on the sub-goal, or grep the lemma namespace; use the lemma directly. Prefer short, stable names.",
 "example (xs : List ℕ) (a : ℕ) (h : a ∈ xs) : a ∈ xs ++ [0] := by\n  simp [h]",
 "example (xs : List ℕ) (a : ℕ) (h : a ∈ xs) : a ∈ xs ++ [0] :=\n  List.mem_append_left _ h","lemma_swap",tags=["library","exact?"],source="both",
 notes="Check the name on Lean 4.25 and 4.33: standard-library List lemma names churn.")
card("delete-dead-step","Delete steps that do nothing",
 "A step is unused (have never referenced, tactic after goals are closed, simp that made no progress, redundant clear or intro).",
 "Delete it and recompile; use unused-variable and unusedTactic linters, or bisect the steps.",
 "example (a b : ℕ) (h : a < b) : a ≤ b := by\n  have h2 : a + 1 ≤ b := h\n  omega",
 "example (a b : ℕ) (h : a < b) : a ≤ b := by omega","step_deleted",tags=["dead","linter"],source="both")

# ---- public-only strategies from notes / paper ----
P = "public:https://leanprover-community.github.io/contribute/style.html"
card("fallback-first","Add a cheap fallback for version robustness",
 "A proof that is fragile across Lean 4.25-4.33 (grind, simp lists, renamed lemmas).",
 "first | omega | simp | grind, cheapest first (failed branches still cost heartbeats).",
 "example (a b : ℕ) (h : a < b) : a + 1 ≤ b := by grind",
 "example (a b : ℕ) (h : a < b) : a + 1 ≤ b := by first | omega | grind","", source=P,tags=["first","compat"],
 notes="Adds a few tokens; only when a cross-version gate fails.")
card("clear-before-omega","Clear irrelevant hypotheses before omega / simp_all",
 "omega or simp_all is slow because the context is large.",
 "clear h1 h2 .. or use simp only [h]; omega only reads relevant facts when the context is small.",
 "example (a b : ℕ) (big : ∀ x : ℕ, x * 0 = 0) (h : a < b) : a + 1 ≤ b := by\n  simp_all <;> omega",
 "example (a b : ℕ) (big : ∀ x : ℕ, x * 0 = 0) (h : a < b) : a + 1 ≤ b := by\n  clear big\n  omega","", source=P,tags=["omega","clear","heartbeats"])
card("with-reducible","Block expensive unfolding with with_reducible",
 "rfl or exact is slow because defeq checking unfolds definitions.",
 "with_reducible rfl / with_reducible exact h; if it fails, the unfolding was needed.",
 "example (a : ℕ) : a + 0 = a := by rfl",
 "example (a : ℕ) : a + 0 = a := by with_reducible exact Nat.add_zero a","", source=P,tags=["rfl","heartbeats","defeq"],
 notes="4.28 added with_unfolding_none; 4.32 with_implicit.")
card("decide-bounded","Bound decide to small instances",
 "decide on Nat/Finset/Fin goals blows up the kernel.",
 "Use norm_num / simp with simprocs, or reduce to a smaller range before decide.",
 "example : ∀ x ∈ Finset.range 4, x * x < 16 := by decide",
 "example : ∀ x ∈ Finset.range 4, x * x < 16 := by\n  intro x hx\n  simp only [Finset.mem_range] at hx\n  interval_cases x <;> omega","", source=P,tags=["decide","heartbeats"],
 notes="Avoid native_decide and kernel-trust options.")
card("qualified-names","Write fully qualified names",
 "A proof opens a namespace or relies on short ambiguous names.",
 "Use Nat.lt_irrefl rather than lt_irrefl guessed from open; 4.33 made some Nat.* lemmas protected.",
 "open Nat in\nexample (a : ℕ) : ¬ a < a := lt_irrefl a",
 "example (a : ℕ) : ¬ a < a := Nat.lt_irrefl a","", source=P,tags=["names","compat"],
 notes="Costs a few tokens; wins on version compatibility.")
card("avoid-auto-names","Avoid inaccessible hypothesis names",
 "rename_i, a✝ names, case tags after induction or cases.",
 "Use rcases/obtain with explicit patterns or ‹T› / assumption.",
 "example (p q : Prop) (h : p ∧ q) : p := by\n  cases h\n  rename_i hp _\n  exact hp",
 "example (p q : Prop) (h : p ∧ q) : p := by\n  obtain ⟨hp, -⟩ := h\n  exact hp","", source=P,tags=["rename_i","compat"],
 notes="Case order after match compilation changed in 4.26.")
card("assumption-by-type","Refer to a hypothesis by its type",
 "A named hypothesis is used once and its name was introduced only for that.",
 "‹T› or assumption; naming in intro becomes _.",
 "example (p q : Prop) (hp : p) (hq : q) : q := by\n  exact hq",
 "example (p q : Prop) (hp : p) (hq : q) : q := ‹q›","", source="public:https://github.com/cameronfreer/lean4-skills",tags=["assumption"])
card("leading-dot","Use leading-dot constructors and lemmas",
 "Expected type is known and constructor names are namespaced.",
 ".inl .inr .intro .refl .symm .trans instead of Or.inl, Exists.intro, Eq.refl.",
 "example (p q : Prop) (hp : p) : p ∨ q := Or.inl hp",
 "example (p q : Prop) (hp : p) : p ∨ q := .inl hp","", source="public:https://github.com/cameronfreer/lean4-skills",tags=["dot-notation"])
card("combinators-imp","Use implication combinators instead of intro + cases",
 "Goal maps a disjunction/conjunction/existential to another with a per-case function.",
 "Or.imp, And.imp, Exists.imp, Or.elim, Iff.trans, Function.comp.",
 "example (p q r s : Prop) (f : p → r) (g : q → s) : p ∨ q → r ∨ s := by\n  intro h\n  cases h with\n  | inl hp => exact Or.inl (f hp)\n  | inr hq => exact Or.inr (g hq)",
 "example (p q r s : Prop) (f : p → r) (g : q → s) : p ∨ q → r ∨ s := Or.imp f g","", source="both",tags=["Or.imp","Exists.imp"],
 notes="Mined as a repeated winning rewrite in earlier runs (see plan learnings).")
card("induction-principles","Use a ready-made induction principle",
 "Induction starts at a base other than 0, or over a well-founded order, or needs strong hypotheses.",
 "Nat.le_induction, Nat.strong_induction_on, Nat.twoStepInduction, List.rec-style via induction ... generalizing.",
 "example (n : ℕ) (h : 3 ≤ n) : 3 ≤ n * n := by\n  induction n with\n  | zero => omega\n  | succ k ih => nlinarith",
 "example (n : ℕ) (h : 3 ≤ n) : 3 ≤ n * n := by nlinarith","", source="both",tags=["induction"],
 notes="Renames: Nat.le_induction argument order differs across Mathlib releases.")
card("show-by-in-rw","Inline a side fact inside rw",
 "A rewrite needs a one-off equation proved by a short tactic.",
 "rw [show _ = _ by tac] or rw [h (by omega)].",
 "example (a b : ℕ) (h : b = 2 * a) : a + b = 3 * a := by\n  have e : a + b = a + 2 * a := by rw [h]\n  rw [e]; ring",
 "example (a b : ℕ) (h : b = 2 * a) : a + b = 3 * a := by\n  rw [h]; ring","", source="both",tags=["rw","show"])
card("split-ifs","Handle if-then-else with split_ifs or simp [if_pos]",
 "by_cases c followed by rw [if_pos]/[if_neg] in each branch.",
 "split_ifs <;> omega, or simp [h] with the decision in context.",
 "example (a b : ℕ) : (if a ≤ b then b else a) ≥ a := by\n  by_cases h : a ≤ b\n  · rw [if_pos h]; exact h\n  · rw [if_neg h]",
 "example (a b : ℕ) : (if a ≤ b then b else a) ≥ a := by\n  split_ifs <;> omega","", source="public:https://github.com/cameronfreer/lean4-skills",tags=["if","by_cases"])
card("nat-cases-pattern","Split a Nat variable into a few concrete cases with one rcases",
 "Nested cases on n for 0, 1, 2, n+3.",
 "rcases n with _ | _ | _ | n, then all_goals omega / simp, or match with | 0 | 1 => .. .",
 "example (n : ℕ) : n ≤ 2 ∨ 3 ≤ n := by\n  cases n with\n  | zero => left; omega\n  | succ k =>\n    cases k with\n    | zero => left; omega\n    | succ j =>\n      cases j with\n      | zero => left; omega\n      | succ m => right; omega",
 "example (n : ℕ) : n ≤ 2 ∨ 3 ≤ n := by\n  rcases n with _ | _ | _ | n <;> omega","", source="public:https://github.com/cameronfreer/lean4-skills",tags=["rcases","Nat"],
 notes="Stable; omega reads the numerals produced by rcases.")
card("finset-sum-closers","Close sum/product identities with simp [Finset.sum_*] or induction-free lemmas",
 "A Finset sum identity is proved by induction on the index set.",
 "simp [Finset.sum_range_succ] for small concrete ranges; Finset.sum_comm / Finset.sum_congr / Finset.sum_le_sum for structure.",
 "example : ∑ i ∈ Finset.range 4, i = 6 := by\n  decide",
 "example : ∑ i ∈ Finset.range 4, i = 6 := by\n  simp [Finset.sum_range_succ]","", source=P,tags=["Finset","sum"],
 notes="BigOperators notation ∑ i ∈ s differs from ∑ i in s on older Mathlib; check on the oldest toolchain.")
card("fun-prop-measurable","Use domain closers for side conditions",
 "Continuity / measurability / differentiability / monotonicity side goals proved by lemma threading.",
 "fun_prop, continuity, measurability, positivity, bound.",
 "example : Continuous (fun x : ℝ => x ^ 2 + 1) :=\n  (continuous_pow 2).add continuous_const",
 "example : Continuous (fun x : ℝ => x ^ 2 + 1) := by fun_prop","", source=P,tags=["fun_prop","continuity"])
card("exact-mod-simp","Replace exact + simp with simpa using",
 "have h := ..; simp at h; exact h",
 "simpa using term.",
 "example (xs : List ℕ) (h : 0 < (xs ++ []).length) : 0 < xs.length := by\n  have h' := h\n  simp at h'\n  exact h'",
 "example (xs : List ℕ) (h : 0 < (xs ++ []).length) : 0 < xs.length := by simpa using h","", source="both",tags=["simpa"])
card("at-star-merge","Merge repeated tactics with location lists",
 "The same simp/rw/norm_num is applied to several hypotheses in turn.",
 "simp at h1 h2 ⊢, rw [e] at *, norm_num at h ⊢.",
 "example (a b : ℕ) (h1 : a + 0 = 1) (h2 : b + 0 = 2) : a + b = 3 := by\n  simp at h1\n  simp at h2\n  omega",
 "example (a b : ℕ) (h1 : a + 0 = 1) (h2 : b + 0 = 2) : a + b = 3 := by omega","", source="both",tags=["at","location"])
card("subst-rfl","Eliminate equalities by substitution",
 "An equation x = e is used only to rewrite everywhere.",
 "subst or rintro rfl; then every later mention disappears.",
 "example (a b : ℕ) (h : a = b + 1) (p : ℕ → Prop) (hp : p (b + 1)) : p a := by\n  rw [h]\n  exact hp",
 "example (a b : ℕ) (h : a = b + 1) (p : ℕ → Prop) (hp : p (b + 1)) : p a := by\n  subst h; exact hp","", source="both",tags=["subst"])
card("trust-defeq","Close with rfl or exact when the statement holds by definition",
 "Goal is a unfolding of a definition or a computation on literals.",
 "rfl, or exact of the term; cheaper than simp/unfold.",
 "example (xs : List ℕ) : (0 :: xs).length = xs.length + 1 := by simp",
 "example (xs : List ℕ) : (0 :: xs).length = xs.length + 1 := rfl","", source=P,tags=["rfl","heartbeats"],
 notes="Library List.length structure changes can break rfl; test on all toolchains.")
card("tactic-ladder","Climb the tactic cost ladder from cheap to expensive",
 "Any slow step; use the profiler to locate it.",
 "Try in order: exact/rfl, rw, simp only, omega, simp, norm_num, nlinarith, aesop, grind. Use the cheapest that closes it.",
 "example (a b : ℕ) (h : a = b) : b = a := by\n  grind",
 "example (a b : ℕ) (h : a = b) : b = a := h.symm","", source=P,tags=["heartbeats","ladder"])
card("symmetric-lemma","Use .symm / ▸ / Eq.subst to avoid rewriting direction flips",
 "rw [← h] then exact, or exact h.symm after rewriting.",
 "Pass h.symm to the term that needs it.",
 "example (a b : ℕ) (h : a = b) : b = a := by\n  rw [h]",
 "example (a b : ℕ) (h : a = b) : b = a := h.symm","", source="both",tags=["symm"])
card("decide-over-cases","Use fin_cases / interval_cases / decide for small finite domains",
 "A bounded variable is split by repeated cases.",
 "interval_cases x <;> simp_all, fin_cases i <;> simp, or decide.",
 "example (x : ℕ) (h : x < 3) : x * x < 5 := by\n  cases x with\n  | zero => decide\n  | succ y =>\n    cases y with\n    | zero => decide\n    | succ z =>\n      cases z with\n      | zero => decide\n      | succ w => omega",
 "example (x : ℕ) (h : x < 3) : x * x < 5 := by\n  interval_cases x <;> decide","", source="both",tags=["interval_cases","fin_cases"])
card("one-big-closer","Replace the last few tactics by a single closer",
 "The final 2-4 lines of a proof all do arithmetic or logic simplification of the same shape.",
 "Delete from the bottom up, replace by omega / simp_all / grind / tauto and recompile; stop at the first failure.",
 "example (p q : Prop) (hp : p) (hq : q) (h : p ∧ q → ¬ ¬ p) : ¬ ¬ p := by\n  apply h\n  constructor\n  · exact hp\n  · exact hq",
 "example (p q : Prop) (hp : p) (hq : q) (h : p ∧ q → ¬ ¬ p) : ¬ ¬ p := by tauto","", source="both",tags=["tauto","simp_all","omega"])
card("generalize-hyps-in-induction","Strengthen the statement instead of adding side lemmas",
 "An induction fails or needs an extra have in each step.",
 "induction n generalizing m, so the hypothesis covers all m; delete side lemmas.",
 "example (n m : ℕ) : n + m = m + n := by\n  induction n with\n  | zero => omega\n  | succ k ih => omega",
 "example (n m : ℕ) : n + m = m + n := by\n  induction n generalizing m <;> omega","", source="both",tags=["induction","generalizing"])
card("shared-prefix","Hoist a repeated prefix out of branches",
 "Each case branch starts with the same rw/simp.",
 "Run the shared tactic before the split (or t <;> s), so it appears once.",
 "example (a b : ℕ) (h : a = b) : (a = 0 → b = 0) ∧ (b = 0 → a = 0) := by\n  constructor\n  · intro h0; rw [← h]; exact h0\n  · intro h0; rw [h]; exact h0",
 "example (a b : ℕ) (h : a = b) : (a = 0 → b = 0) ∧ (b = 0 → a = 0) := by\n  subst h; exact ⟨id, id⟩","", source="public:general-practice",tags=["hoist"])
card("exists-intro-from-lemma","Close ∃ goals by applying the lemma that already produces the witness",
 "refine ⟨_, ?_⟩ followed by providing the witness from a lemma statement.",
 "exact lemma_name args (anonymous ∃ is a structure) or obtain from the lemma and pass on.",
 "example (xs : List ℕ) (h : xs ≠ []) : ∃ a, a ∈ xs := by\n  obtain ⟨a, t, rfl⟩ := List.exists_cons_of_ne_nil h\n  exact ⟨a, List.mem_cons_self⟩",
 "example (xs : List ℕ) (h : xs ≠ []) : ∃ a, a ∈ xs := ⟨xs.head h, List.head_mem h⟩","", source="both",tags=["exists","library"],
 notes="Lemma names on lists are renamed often; verify on 4.25 and 4.33 before keeping.")

# ---- tight-proof cards: fresh generic examples ----
card("drop-helper-reclose-dependents","Drop a helper fact and re-close its dependents another way",
 "A proof is already short, and one helper fact is used by a few later steps, each for one small rewrite or one argument; the helper's own proof is a large share of the cost.",
 "Delete the helper and the steps that mention it. Close each dependent goal on its own: a direct term, a one-line closer that finds the fact itself, or the library fact the helper wrapped. Keep the deletion only if the whole proof compiles and the total is lower.",
 "example (xs : List ℕ) (h : xs ≠ []) : 0 < xs.length ∧ xs.length ≠ 0 := by\n  have hl : 0 < xs.length := List.length_pos_iff.mpr h\n  constructor\n  · exact hl\n  · exact Nat.pos_iff_ne_zero.mp hl",
 "example (xs : List ℕ) (h : xs ≠ []) : 0 < xs.length ∧ xs.length ≠ 0 :=\n  ⟨List.length_pos_iff.mpr h, by simp [h]⟩",
 tags=["have","bullets"], source="public:general-practice",
 at={"opening": "A helper stated at the start feeds every later step, so removing it changes the most; re-close the first dependents first.",
     "middle": "Check which later steps name the helper before deleting it; each of them needs its own close.",
     "closing": "A helper used only by the last steps is the easiest to fold into the final term."})
card("sibling-fact-without-premise","Find a sibling fact that needs no premise",
 "A library fact fits the goal except for a premise you do not have (a length, a bound, a nonemptiness), and proving the premise costs a step.",
 "Search by the constants in the goal, not by the failing name: look for a weaker or differently shaped fact about the same functions that states its result without the premise (a max or min form, an inequality instead of an equality, a membership form). Compile the sibling before dropping the premise step.",
 "example (n m : ℕ) (h : m ≤ n) : n ≤ n - m + m := by\n  have := Nat.sub_add_cancel h\n  omega",
 "example (n m : ℕ) (h : m ≤ n) : n ≤ n - m + m := by\n  rw [Nat.sub_add_eq_max]; exact le_max_left n m",
 tags=["library","exact?"], source="public:general-practice",
 at={"opening": "A premise established at the start is usually shared with later steps; drop it only if nothing else uses it.",
     "middle": "Search for the sibling by the goal's constants before adding a step that proves the premise.",
     "closing": "At the end the goal is fixed; a weaker sibling may close it directly without the premise."})
card("helper-must-pay","Keep an auxiliary fact only if it removes more than it adds",
 "A have or a local lemma is introduced to share work, but it is used once or twice and its statement is long.",
 "Compile the proof with the helper and without it, and compare both totals before deciding: the helper's statement and proof add cost, and each use saves only the difference to the inline form. Never judge by reading alone.",
 "example (xs : List ℕ) : (xs ++ []).length + 0 = xs.length := by\n  have h : xs ++ [] = xs := List.append_nil xs\n  rw [h]; rfl",
 "example (xs : List ℕ) : (xs ++ []).length + 0 = xs.length := by simp",
 tags=["have","set"], source="public:general-practice",
 at={"opening": "A helper at the start pays only if most later steps use it.",
     "middle": "Count the uses after the helper; two short uses rarely repay a long statement.",
     "closing": "A helper used only by the closing step can nearly always be inlined."})
card("split-chained-combinators","Split a <;> chain into all_goals lines",
 "A line chains tactics with <;> (t <;> s <;> u) so that each stage runs on every goal the stage before produced.",
 "Write each stage on its own line and put all_goals in front of the later stages: t, then all_goals s, then all_goals u. The tactics are the same; each stage is elaborated once over the goal list, and a failing stage is easy to find. Compile it: the result is the same only when t left the goals that s should run on.",
 "example (a b : ℕ) (h : a < b) : (a ≤ b ∧ a ≠ b) ∧ (a < b + 1 ∧ b ≠ 0) := by\n  refine ⟨?_, ?_⟩ <;> refine ⟨?_, ?_⟩ <;> omega",
 "example (a b : ℕ) (h : a < b) : (a ≤ b ∧ a ≠ b) ∧ (a < b + 1 ∧ b ≠ 0) := by\n  refine ⟨?_, ?_⟩\n  all_goals refine ⟨?_, ?_⟩\n  all_goals omega",
 tags=["<;>","all_goals"], source="public:general-practice",
 notes="Goal scheduling form seen to win in earlier runs; no mined move class, so no measured effect. all_goals stops at the first goal that fails, <;> does the same; use any_goals when some goals may fail.")
card("two-pass-closing","Close in two passes: any_goals assumption first, then split what is left",
 "A <;> line tries first | assumption | (a split followed by assumption) on every goal, so each goal pays for the failed alternatives before the one that closes it.",
 "Run any_goals assumption to close every goal a hypothesis already proves, then all_goals with the splitting tactic on the remaining goals, then all_goals assumption. Cheap closers run first and the failing alternatives disappear.",
 "example (a b c : ℕ) (h : a ≤ b) (h2 : b ≤ c) : a ≤ b ∧ (b ≤ c ∧ a ≤ c) := by\n  refine ⟨?_, ?_⟩ <;> first | exact h | (refine ⟨?_, ?_⟩ <;> omega)",
 "example (a b c : ℕ) (h : a ≤ b) (h2 : b ≤ c) : a ≤ b ∧ (b ≤ c ∧ a ≤ c) := by\n  refine ⟨?_, ?_⟩\n  any_goals exact h\n  all_goals refine ⟨?_, ?_⟩\n  all_goals omega",
 tags=["any_goals","all_goals","first","assumption"], source="public:general-practice",
 notes="Goal scheduling form seen to win in earlier runs; no mined move class, so no measured effect. any_goals fails when no goal succeeds, so drop it when nothing can close in the first pass.")
card("choose-then-subst","Destructure an existence fact with choose and subst instead of obtain with rfl",
 "obtain ⟨x, hx, rfl⟩ := f _ _ ‹_› (or with explicit arguments) both destructures an existential and substitutes the equation it carries.",
 "Write choose x hx h using f .. and then subst h on its own line. The same variables and facts result, but the substitution is a separate step, which can be cheaper to elaborate and lets you leave h in place when substitution is not needed.",
 "example (f : ∀ a : ℕ, 0 < a → ∃ x, x < a ∧ a = x + 1) (n : ℕ) (hn : 0 < n)\n    (p : ℕ → Prop) (hp : ∀ x, p (x + 1)) : p n := by\n  obtain ⟨x, hx, rfl⟩ := f n hn\n  exact hp x",
 "example (f : ∀ a : ℕ, 0 < a → ∃ x, x < a ∧ a = x + 1) (n : ℕ) (hn : 0 < n)\n    (p : ℕ → Prop) (hp : ∀ x, p (x + 1)) : p n := by\n  choose x hx h using f n hn\n  subst h\n  exact hp x",
 tags=["obtain","choose","subst","rfl"], source="public:general-practice",
 notes="Seen to win in earlier runs; no mined move class, so no measured effect. choose names the witness and facts in the order of the existential; check the names against the facts you use later.")
card("witness-fixing-goal-first","Close the goal that fixes a metavariable witness before the others",
 "A step spells out a witness or argument (apply f (m := w), refine with a named hole) only so that later assumption or exact calls unify.",
 "Leave the witness open and order the goals: close the one whose proof determines the witness first (swap or rotate_left to bring it forward, or exact it), then assumption on the others finds the instantiated statement. Drop the spelled witness.",
 "example (a b c : ℕ) (hx : a ≤ c) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c := by\n  apply Nat.le_trans (m := b)\n  all_goals assumption",
 "example (a b c : ℕ) (hx : a ≤ c) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c := by\n  apply Nat.le_trans\n  rotate_left\n  · exact h2\n  · assumption",
 tags=["apply","assumption","rotate_left"], source="public:general-practice",
 notes="Goal scheduling form seen to win in earlier runs; no mined move class, so no measured effect. Goal order after apply can change between releases; check it, or name the goal with case.")
GOAL = {"simp-to-simp-only": ["List.length", "List.append"], "simp-only-to-simp": ["List.length"],
        "grind-to-explicit": ["List.length"], "trim-simp-args": ["List.length", "List.append"],
        "swap-to-library-lemma": ["List.append", "∈"],
        "finset-sum-closers": ["Finset.sum", "Finset.range", "∑"], "decide-bounded": ["Finset.range"],
        "exists-intro-from-lemma": ["List.head", "∈"], "trust-defeq": ["List.length"]}

import sys
sys.path.insert(0, str(D))
import replaces
VER = json.load(open(D / "verify.json")) if (D / "verify.json").exists() else {}
def sign(down, up, n):
    if n < 3: return "unknown"
    if down / n >= 0.7: return "down"
    if up / n >= 0.7: return "up"
    return "mixed"
def merge(parts):
    return {k: sum(p[k] for p in parts) for k in ("n", "down", "up")}
pool = []
for c in C:
    c["goal_tags"] = c["goal_tags"] or GOAL.get(c["id"], [])
    m = c.pop("move"); pub = c.pop("pub")
    s = stats.get(m) if m else None
    eff = {"tokens": "unknown", "heartbeats": {b: "unknown" for b in ("opening", "middle", "closing")}, "confidence": "low"}
    if s:
        pos = s["positions"]
        tk = merge([pos[b]["tokens"] for b in pos]); eff["tokens"] = sign(tk["down"], tk["up"], tk["n"])
        for b in eff["heartbeats"]:
            h = pos.get(b, {}).get("heartbeats")
            if h: eff["heartbeats"][b] = sign(h["down"], h["up"], h["n"])
        eff["confidence"] = "high" if s["count"] >= 50 else "medium" if s["count"] >= 10 else "low"
    hb = {v for v in eff["heartbeats"].values() if v != "unknown"}
    eff["note"] = ("Heartbeat effect depends on where in the proof the edit sits; profile before deciding." if len(hb) > 1
        else "Heartbeat direction is the same at every position with data." if hb
        else "Too little mined evidence; measure with the profiler.")
    c["effect"] = eff
    c["move_class"] = m or ""
    c["source"] = c["source"] if (s or c["source"] != "mined") else "both"
    c["version_notes"] = c.pop("notes") or "Stable across 4.25-4.33 as far as known."
    pool.append(c)
for i, c in enumerate(pool, 1):
    c["replaces"] = replaces.REPLACES.get(c["id"]) or replaces.derive(c["before"], c["after"])
    c["id"] = f"S{i:02d}-{c['id']}"
order = ["id","title","tags","goal_tags","replaces","at","when","how","before","after","effect","verified","version_notes","move_class","source"]
for c in pool: c["verified"] = {f"v{tc}": v[c["id"]] for tc, v in VER.items() if c["id"] in v}
pool = [{k:c[k] for k in order} for c in pool]
def emit(v, ind=0):
    p = " " * ind
    if isinstance(v, dict):
        out = []
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x:
                out.append(f"{p}{k}:\n{emit(x, ind + 2)}")
            else:
                out.append(f"{p}{k}: {scalar(x, ind + 2)}")
        return "\n".join(out)
    if isinstance(v, list):
        return "\n".join(f"{p}- {scalar(x, ind + 2)}" if not isinstance(x, dict) else f"{p}-\n{emit(x, ind + 2)}" for x in v)
def scalar(x, ind):
    if isinstance(x, str):
        if "\n" in x:
            return "|-\n" + "\n".join(" " * ind + l if l else "" for l in x.split("\n"))
        return json.dumps(x, ensure_ascii=False)
    if isinstance(x, list):
        return json.dumps(x, ensure_ascii=False)
    if isinstance(x, dict):
        return "{}"
    return json.dumps(x)
open(D/"cards.yaml","w").write("# Generic Lean 4 proof-golfing strategy bank. See README.md.\ncards:\n" + "\n".join(emit([c], 2) for c in pool) + "\n")
print(len(pool))
open(D/"cards.json","w").write(json.dumps({"cards":pool},ensure_ascii=False,indent=1))
