"""What each card's move rewrites: regexes (Python `re`, applied to a proof step's text) for the code a card replaces.

Retrieval (arena/patterns.py) ranks a card first when its patterns occur in the step being edited. Keys are card ids
without the numeric prefix. A card with no entry gets `derive(before, after)`: the tactic heads that occur more often in
its `before` than in its `after`. Entries here are hand-written where that derivation is too generic (rw, exact, have,
simp occur in almost every step) or where the replaced form is not a tactic head (S62: an equation used by rw).
"""
import re

HEADS = ("obtain", "rcases", "cases", "intro", "rintro", "have", "set", "let", "generalize", "simp_all", "simpa", "simp",
         "rwa", "rw", "omega", "linarith", "nlinarith", "aesop", "grind", "constructor", "apply", "refine", "exact",
         "induction", "calc", "decide", "norm_num", "show", "change", "ext", "funext", "by_contra", "push_neg",
         "subst", "split", "all_goals", "any_goals", "first", "try", "clear", "unfold", "congr", "convert", "use",
         "rename_i", "fun", "match", "by_cases", "interval_cases", "positivity", "tauto")
_BULLET = r"(?m)^\s*[·•]"


def derive(before: str, after: str) -> list[str]:
    """Patterns for the tactic heads that the card's `after` uses less often than its `before`."""
    def count(head: str, body: str) -> int:
        return len(re.findall(rf"(?<![\w.]){head}(?![\w'])", body))
    return [rf"(?<![\w.]){head}(?![\w'])" for head in HEADS if count(head, before) > count(head, after)]


REPLACES = {
    # Only a hypothesis name on the right: projections do not apply to an application such as `f _ _ ‹_›`.
    "obtain-to-projection": [r"(?m)\b(?:obtain|rcases)\b[^\n:]*:=\s*[\w']+\s*$", r"(?m)\brcases\s+[\w']+\s+with\b", r"\bcases\s+[\w']+\s+with\b"],
    "rintro-merge": [r"(?m)^\s*intro\b[^\n]*\n\s*(?:obtain|rcases)\b"],
    "inline-single-use-have": [r"(?m)^\s*have\s+[\w']+\s*:"],
    "inline-have-as-show-rw": [r"(?s)\bhave\s+[\w']+\s*:.*?\n\s*rw\s*\["],
    "merge-have-chain": [r"(?ms)^\s*have\b.*?^\s*have\b"],
    "drop-set-let": [r"(?m)^\s*(?:set|let|letI|generalize)\b"],
    "simp-to-simp-only": [r"\bsimp(?![\w?!'])(?!\s+only)"],
    "simp-only-to-simp": [r"\bsimp\s+only\s*\[[^\]]{40,}\]"],
    "grind-closer": [r"<;>\s*(?:omega|simp_all|simp|linarith|aesop)\b", r"(?m)^\s*(?:constructor|split)\s*$"],
    "grind-to-explicit": [r"\bgrind\b"],
    "omega-for-arith": [r"\b(?:le_trans|lt_of_lt_of_le|lt_of_le_of_lt|Nat\.succ_le_of_lt|Nat\.le_of_lt_succ|add_lt_add|add_le_add)\b",
                        r"\bcalc\b"],
    "nonlinear-to-omega-or-positivity": [r"\b(?:nlinarith|linarith)\b"],
    "aesop-to-script": [r"\baesop\b"],
    "rw-merge": [r"(?s)\brw\s*\[[^\]]*\]\s*(?:\n\s*|;\s*)rw\s*\["],
    "rw-to-simp-only": [r"(?s)\brw\s*\[\s*([\w.']+)[^\]]*\].*?\brw\s*\[\s*\1\b", r"\b(?:nth_rewrite|nth_rw|conv)\b"],
    "rw-to-transport": [r"\brw\s*\[[^\]]*\](?:\s*\n\s*|\s*;\s*)exact\b"],
    "rwa-simpa": [r"\b(?:rw|simp)\b[^\n]*\bat\s+([\w']+)[^\n]*(?:\n\s*|;\s*)exact\s+\1\b",
                  r"\brw\s*\[[^\]]*\](?:\s*\n\s*|\s*;\s*)assumption\b"],
    "intro-to-fun": [r"(?m)^\s*intro\b[^\n]*\n\s*exact\b"],
    "constructor-to-anonymous": [r"(?m)^\s*constructor\s*$", r"\brefine\s*⟨[^\n]*\?_"],
    "bullets-to-combinators": [r"(?ms)^\s*[·•].*?^\s*[·•]"],
    "drop-bullets": [r"(?ms)^\s*[·•]\s*exact\b.*?^\s*[·•]\s*exact\b"],
    "explicit-to-underscore": [r"\(\s*[\w']+\s*:=\s*[^)]+\)"],
    "drop-type-ascription": [r"\bfun\s*\(\s*[\w']+\s*:", r"\(\s*[\w']+\s*:\s*[^()]+\)\s*(?:=>|↦)", r"\(\s*\d+\s*:\s*\S+\)"],
    "drop-show-change": [r"(?m)^\s*(?:show|change)\b"],
    "unwrap-exact-by": [r"\bexact\s*\(\s*by\b", r"\bby\s+exact\b", r":=\s*by\s+(?:rfl|exact)\b"],
    "refine-holes": [r"\bexact\b[^\n]*\(by\b[^\n]*\(by\b", r"(?m)^\s*apply\b[^\n]*\n\s*apply\b"],
    "apply-exact-merge": [r"(?m)^\s*apply\b[^\n]*(?:\n\s*[·•]?\s*|;\s*)(?:exact|assumption)\b"],
    "restructure-induction-as-match": [r"(?m)^\s*\|\s*[\w.]+[^\n]*=>\s*$", r"(?ms)\bcases\b.*\bcases\b", r"\b(?:cases|induction)\s+[\w']+"],
    "drop-induction": [r"\binduction\b"],
    "by-contra-bang": [r"\bby_contra\b(?!!)[^\n]*(?:\n\s*|;\s*)push_neg", r"\bpush_neg\b"],
    "calc-to-trans": [r"\bcalc\b"],
    "calc-fewer-steps": [r"(?s)\bcalc\b.*\n\s*_\s*[=≤<≥>].*\n\s*_\s*[=≤<≥>]"],
    "numeric-closers": [r"\bsimp\s+arith\b", r"(?ms)^\s*[·•]\s*(?:rfl|norm_num|decide)\b.*?^\s*[·•]\s*(?:rfl|norm_num|decide)\b"],
    "cast-tactics": [r"\bNat\.cast_\w+", r"\bInt\.(?:ofNat|natCast|cast)_\w+", r"\bInt\.coe_nat\w*"],
    "convert-congr": [r"\bcongrArg\b", r"\bcongrFun\b", r"\bcongr\b(?!!)"],
    "use-witness": [r"\brefine\s*⟨[^\n]*\?_", r"\bexists\b"],
    "drop-ext": [r"\b(?:ext|funext)\b", r"\b(?:Subtype|Fin)\.ext\b"],
    "trim-simp-args": [r"\bsimp(?:_all)?\s*(?:only\s*)?\[[^\]]*,[^\]]*,[^\]]*\]"],
    "simp-star": [r"(?ms)^\s*[·•]\s*(?:simp|rw)\b.*?^\s*[·•]\s*(?:simp|rw)\b"],
    "positivity-gcongr": [r"\b(?:sq_nonneg|mul_pos|add_pos|pow_pos|mul_nonneg|add_nonneg|pow_le_pow_left|mul_le_mul)\b"],
    "lambda-sections": [r"\bfun\s+([\w']+)\s*(?:=>|↦)\s*[\w.]+\s+\1\b", r"\bfun\s+[\w']+\s*(?:=>|↦)\s*[\w']+\s*[+\-*]"],
    "remove-parens": [r"\([^()\n]*\([^()\n]*\([^()\n]*\)[^()\n]*\)[^()\n]*\)"],
    "swap-to-library-lemma": [r"\bsimp\b[^\n]*\[[^\]]*\bmem_\w+", r"\bFinset\.card_\w+"],
    "delete-dead-step": [r"\bskip\b", r"(?m)^\s*clear\b", r"\btry\s+\w+", r"\bhave\s+_\b"],
    "fallback-first": [r"\bgrind\b", r"\bnlinarith\b"],
    "clear-before-omega": [r"\bsimp_all\b[^\n]*<;>", r"<;>\s*omega\b"],
    "with-reducible": [r"\bexact\s+rfl\b", r"(?m)^\s*rfl\s*$", r"\bby\s+rfl\b", r"\bunfold\b"],
    "decide-bounded": [r"\bdecide\b"],
    "qualified-names": [r"(?m)^\s*open\b", r"\bopen\s+\w+\s+in\b"],
    "avoid-auto-names": [r"\brename_i\b", r"✝"],
    "assumption-by-type": [r"(?m)\bexact\s+h[\w']*\s*$"],
    "leading-dot": [r"\b(?:Or\.inl|Or\.inr|Exists\.intro|Eq\.refl|Eq\.symm|Eq\.trans|And\.intro|Iff\.intro)\b"],
    "combinators-imp": [r"(?m)^\s*\|\s*in[lr]\b", r"\brcases\b[^\n]*\bwith\b\s*\(?[\w']+\)?\s*\|", r"\bOr\.elim\b"],
    "induction-principles": [r"\binduction\b"],
    "show-by-in-rw": [r"(?s)\bhave\s+[\w']+\s*:[^\n]*=[^\n]*\n\s*rw\s*\[\s*[\w']+\s*\]"],
    "split-ifs": [r"\bif_pos\b", r"\bif_neg\b", r"\bby_cases\b"],
    "nat-cases-pattern": [r"(?ms)\bcases\b.*\bcases\b.*\bcases\b", r"\|\s*(?:Nat\.)?succ\b"],
    "finset-sum-closers": [r"\bFinset\.(?:sum|prod)_\w+"],
    "fun-prop-measurable": [r"\b(?:continuous_\w+|Continuous\w*\.\w+|measurable_\w+|Measurable\w*\.\w+|differentiable_\w+)"],
    "exact-mod-simp": [r"\bsimp\b[^\n]*\bat\s+([\w']+)[^\n]*(?:\n\s*|;\s*)exact\s+\1\b"],
    "at-star-merge": [r"(?m)^\s*(simp|norm_num|rw)\b[^\n]*\bat\s+[\w']+\s*$\n\s*\1\b[^\n]*\bat\b"],
    # An equation used only to rewrite: rw [h], or a pattern that ends in rfl and so already substitutes.
    "subst-rfl": [r"\brw\s*\[\s*←?\s*h[\w']*\s*\]", r"\bobtain\b[^\n]*\brfl\b", r"\brcases\b[^\n]*\brfl\b"],
    "trust-defeq": [r"\bunfold\b", r"\bdsimp\b", r"(?m)^\s*simp\s*$"],
    "tactic-ladder": [r"\b(?:grind|aesop|nlinarith)\b"],
    "symmetric-lemma": [r"\brw\s*\[\s*←", r"\bexact\b[^\n]*\.symm\b"],
    "decide-over-cases": [r"(?ms)\bcases\b.*\bcases\b"],
    "one-big-closer": [r"(?m)^\s*(?:constructor|apply|refine)\b[^\n]*\n(?:\s*[·•][^\n]*\n?){2,}"],
    "generalize-hyps-in-induction": [r"\binduction\b(?![^\n]*\bgeneralizing\b)"],
    "shared-prefix": [r"(?ms)^\s*[·•]\s*(\w+[^\n;]{3,}?)\s*[;\n].*^\s*[·•]\s*\1\b"],
    "exists-intro-from-lemma": [r"\bobtain\b[^\n]*:=\s*[\w.]+[^\n]*\n\s*(?:exact|refine|use)\b[^\n]*⟨", r"\brefine\s*⟨[^\n]*\?_"],
    "drop-helper-reclose-dependents": [r"(?ms)^\s*have\s+[\w']+\s*:.*^\s*[·•]"],
    "sibling-fact-without-premise": [r"(?m)^\s*have\s+[\w']+\s*:\s*(?:0\s*<|[\w.()]+\s*≠)", r"\bexact\?"],
    "helper-must-pay": [r"(?m)^\s*have\s+[\w']+\s*:[^\n]*:=\s*by\s*$", r"(?m)^\s*set\b"],
    # Goal scheduling.
    "split-chained-combinators": [r"<;>[^\n]*<;>"],
    "two-pass-closing": [r"\bfirst\s*\|[^\n]*\b(?:assumption|exact)\b|<;>\s*(?:try\s+)?assumption"],
    "choose-then-subst": [r"\bobtain\s*⟨[^\n]*\brfl\b[^\n]*⟩\s*:=", r"\brcases\b[^\n]*\brfl\b"],
    "witness-fixing-goal-first": [r"\b(?:apply|refine|exact)\b[^\n]*\(\s*[\w']+\s*:=", r"\brefine\b[^\n]*\?[A-Za-z]\w*",
                                  r"\bapply\b[^\n]*(?:\n\s*[·•]|<;>)"],
}
