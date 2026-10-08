"""Route fingerprints: which proof strategy a compiled candidate uses, computed by the harness.

A route is a family of proofs with the same strategy. The model never labels routes, so renaming an
idea cannot hide or fake one. The fingerprint is read from the compiled proof term (arena/lean/route.lean
reads the declaration's kernel value, so tactic synonyms collapse and the lemmas automation uses are
visible), in four parts:

* ``recursion`` (0.25): the recursors and induction principles it uses, with their inductive type;
* ``lemmas`` (0.45): the lemma families it uses, weighted by how rare they are among this theorem's proofs;
* ``claims`` (0.20): the statements of its ``have`` binders and ``calc`` steps, hashed;
* ``logic`` (0.10): contradiction, case split on ``Or``, existential witnesses, ``calc``, extensionality.

An empty part is a normal value, not a veto. When extraction fails the fingerprint falls back to text
features (``source: "text"``): whether the proof recurses, the vocabulary lemmas it names, and the head
tactic of each top-level line.

Candidates are clustered in arrival order: a new proof joins the route whose first proof (its exemplar)
it most resembles when the similarity reaches ``SAME_ROUTE``, otherwise it starts a new route.
"""

from __future__ import annotations

import math
import re

SAME_ROUTE = 0.5
MAX_SKELETON = 24
LABEL_LEMMAS = 3
WEIGHTS = {"recursion": 0.25, "lemmas": 0.45, "claims": 0.20, "logic": 0.10}
PARTS = tuple(WEIGHTS)
# Logic plumbing that every proof by rewriting or simplification carries, whatever its strategy.
PLUMBING = frozenset({
    "Eq.mpr", "Eq.mp", "Eq.rec", "Eq.ndrec", "Eq.recOn", "Eq.casesOn", "Eq.subst", "Eq.substr", "Eq.symm",
    "Eq.trans", "Eq.refl", "Eq.propIntro", "HEq.refl", "congrArg", "congrFun", "congr", "of_eq_true",
    "of_eq_false", "eq_self", "eq_true", "eq_false", "id", "rfl", "propext", "True.intro", "Iff.mpr", "Iff.mp",
    "Iff.intro", "Iff.rfl", "Iff.refl", "Iff.symm", "Iff.trans", "implies_congr", "implies_congr_ctx",
    "forall_congr", "implies_true", "ne_eq", "not_false_eq_true", "letFun", "inferInstance", "inferInstanceAs",
    "cast", "Not", "Not.intro", "Unit", "Unit.unit", "outParam", "optParam", "autoParam", "sorryAx",
    # what `simp`, `decide` and `grind` leave behind whichever lemmas they were given
    "Ne", "ne_eq", "not_not", "false_and", "true_and", "and_false", "and_true", "or_false", "false_or", "or_true",
    "true_or", "and_self", "or_self", "not_true_eq_false", "eq_self_iff_true", "Bool.false_eq_true", "Bool.true_eq_false",
    "ite_cond_eq_true", "ite_cond_eq_false", "ite_true", "ite_false", "dite_true", "dite_false", "if_true", "if_false",
    "decide_true", "decide_false", "Decidable.decide", "of_decide_eq_true", "of_decide_eq_false", "eq_false'", "eq_true'",
    "congrFun'", "and_imp", "imp_self", "iff_self", "iff_true", "iff_false", "true_iff", "false_iff", "noConfusion_of_Nat"})
_AUXILIARY = re.compile(r"\.(congr_simp|ctorIdx|noConfusion|noConfusionType|injEq|inj|inj_iff|sizeOf_spec|eq_\d+|eq_def)$")
_VARIANT_SUFFIX = re.compile(r"_(left|right|symm|mpr|mp)$")
_NAT_INT = re.compile(r"^(Nat|Int)\.")
_PRIVATE = re.compile(r"_private\.[^\s@]*?\.0\.")

_COMMENT_BLOCK = re.compile(r"/-.*?-/", re.S)
_COMMENT_LINE = re.compile(r"--[^\n]*")
_IDENT = re.compile(r"[A-Za-z_Ͱ-Ͽ][A-Za-z0-9_'.!?₀-₉]*")
_RECURSION = re.compile(r"(?<![\w.])(induction'?|induct|fun_induction|fun_cases|termination_by|decreasing_by)(?![\w'])"
                        r"|\.(rec|recOn|casesOn|brecOn)(?![\w'])")


def _strip_comments(text: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", text))


def proof_body(proof: str) -> str:
    """The text after the declaration's own `:=` (the first one outside brackets)."""
    text = _strip_comments(proof)
    depth = 0
    for index, char in enumerate(text):
        if char in "([{⟨":
            depth += 1
        elif char in ")]}⟩":
            depth = max(0, depth - 1)
        elif char == ":" and depth == 0 and text.startswith(":=", index):
            return text[index + 2:]
    return text


def _heads(body: str) -> list[str]:
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        return []
    first, rest = lines[0], lines[1:]
    # `:= by tac` keeps its first tactic on the statement line; it has no indentation of its own.
    top = [re.sub(r"^\s*by\b", "", first).strip()] if re.sub(r"^\s*by\b", "", first).strip() else []
    if rest:
        indent = min(len(line) - len(line.lstrip()) for line in rest)
        top += [line.strip() for line in rest if len(line) - len(line.lstrip()) == indent]
    heads: list[str] = []
    for line in top:
        if line.startswith("|"):  # a case arm of the preceding induction or match, not a tactic
            continue
        line = re.sub(r"^[·.<;>()\s*]+", "", line)
        match = re.match(r"[A-Za-z_][A-Za-z0-9_'?!]*", line)
        head = match.group(0) if match else line[:1]
        if head and (not heads or heads[-1] != head):
            heads.append(head)
    return heads[:MAX_SKELETON]


def fingerprint(proof: str, vocabulary: set[str] | frozenset[str] = frozenset(), theorem: str | None = None,
                features: dict | None = None) -> dict:
    """Route fingerprint of one proof. `features` is the Lean extractor's record for the compiled proof; without
    a successful one the fingerprint carries text features only. `vocabulary` is the set of lemma names (qualified
    or short) the text features count."""
    body = proof_body(proof)
    short = {name.rsplit(".", 1)[-1] for name in vocabulary}
    lemmas = set()
    recursive = bool(_RECURSION.search(body))
    own = theorem.rsplit(".", 1)[-1] if theorem else None
    for token in _IDENT.findall(body):
        token = token.rstrip(".")
        tail = token.rsplit(".", 1)[-1]
        if own and tail == own:
            recursive = True
        elif token in vocabulary or tail in short:
            lemmas.add(tail)
    print_ = {"source": "text", "induction": recursive, "lemmas": sorted(lemmas), "skeleton": _heads(body)}
    if features and features.get("ok"):
        print_["source"], print_["kernel"] = "kernel", kernel(features)
    return print_


def _jaccard(left: set, right: set, weight: dict | None = None) -> float:
    union = left | right
    if not union:
        return 1.0
    weight = weight or {}
    return sum(weight.get(item, 1.0) for item in left & right) / sum(weight.get(item, 1.0) for item in union)


def family(name: str) -> str:
    """A lemma name with its variants merged: no trailing primes, no `_left`/`_right`/`_symm`/`_mp`/`_mpr`,
    and `Nat.` and `Int.` duplicates sharing one tail."""
    name = name.rstrip("'")
    name = _VARIANT_SUFFIX.sub("", name)
    return _NAT_INT.sub("NatInt.", name)


def kernel(features: dict) -> dict:
    """The comparable part of the extractor's record: lemma families without plumbing, the other parts as they are."""
    def clean(names) -> set[str]:
        return {_PRIVATE.sub("", name) for name in names}  # a private name embeds the module it was compiled in

    lemmas = {family(name) for name in clean(features.get("lemmas", [])) if name not in PLUMBING and not _AUXILIARY.search(name)}
    return {"recursion": sorted(clean(features.get("recursion", []))), "lemmas": sorted(lemmas),
            "claims": sorted(set(features.get("claims", []))), "logic": sorted(clean(features.get("logic", [])))}


def idf(prints: list[dict]) -> dict[str, dict[str, float]]:
    """Rarity weight of every item per part over the kernel fingerprints of one theorem's proofs: ln(1 + N/df)."""
    kernels = [item["kernel"] for item in prints if item.get("kernel")]
    weights: dict[str, dict[str, float]] = {}
    for part in PARTS:
        counts: dict[str, int] = {}
        for item in kernels:
            for name in set(item[part]):
                counts[name] = counts.get(name, 0) + 1
        weights[part] = {name: math.log(1 + len(kernels) / count) for name, count in counts.items()}
    return weights


def text_similarity(left: dict, right: dict) -> float:
    """Fallback on text features: 0 when exactly one proof recurses; else lemma overlap, or skeleton overlap if neither uses lemmas."""
    if bool(left["induction"]) != bool(right["induction"]):
        return 0.0
    lemmas = (set(left["lemmas"]), set(right["lemmas"]))
    if lemmas[0] or lemmas[1]:
        return _jaccard(*lemmas)
    return _jaccard(set(left["skeleton"]), set(right["skeleton"]))


def similarity(left: dict, right: dict, weights: dict[str, dict[str, float]] | None = None) -> float:
    """Weighted sum of the rarity-weighted overlaps of the four parts; text features if either proof lacks them."""
    if not (left.get("kernel") and right.get("kernel")):
        return text_similarity(left, right)
    weights = weights or {}
    return sum(WEIGHTS[part] * _jaccard(set(left["kernel"][part]), set(right["kernel"][part]), weights.get(part))
               for part in PARTS)


def exemplars(earlier: list[dict]) -> dict[str, dict]:
    """The first proof of each route, in arrival order: the fixed point later proofs are compared to."""
    first: dict[str, dict] = {}
    for event in earlier:
        first.setdefault(event["route"], event)
    return first


def assign(earlier: list[dict], current: dict) -> tuple[str, float]:
    """Route id for `current` given earlier route events ({route, fingerprint}); a new id if none is close enough."""
    first = exemplars(earlier)
    weights = idf([event["fingerprint"] for event in earlier] + [current])
    best_route, best = None, 0.0
    for route, event in first.items():
        score = similarity(event["fingerprint"], current, weights)
        if score > best:
            best_route, best = route, score
    if best_route is not None and best >= SAME_ROUTE:
        return best_route, round(best, 3)
    return f"r{len(first) + 1}", round(best, 3)


def _recursion_name(item: str) -> str:
    kind, _, rest = item.partition(":")
    return f"{rest}.rec" if kind == "rec" else rest


def _ranked(items, weight: dict) -> list[str]:
    return sorted(items, key=lambda name: (-weight.get(name, 1.0), name))


def label(print_: dict, reference: dict | None = None, weights: dict[str, dict[str, float]] | None = None) -> str:
    """A short deterministic name: how it recurses plus the lemmas that set it apart from the original."""
    if print_.get("kernel"):
        return _kernel_label(print_["kernel"], reference["kernel"] if reference and reference.get("kernel") else None,
                             (weights or {}).get("lemmas", {}))
    own = print_["lemmas"]
    fresh = [name for name in own if not reference or name not in reference["lemmas"]] or own
    kind = "induction" if print_["induction"] else "no induction"
    return kind + (": " + ", ".join(fresh[:LABEL_LEMMAS]) if fresh else "")


def _kernel_label(own: dict, reference: dict | None, weight: dict) -> str:
    recursion = [_recursion_name(item) for item in own["recursion"]]
    if reference is None:
        lemmas = _ranked(own["lemmas"], weight)[:LABEL_LEMMAS]
        return "; ".join(["recursion: " + (", ".join(recursion) or "none")] + ([", ".join(lemmas)] if lemmas else []))
    parts = []
    before = [_recursion_name(item) for item in reference["recursion"]]
    if recursion != before:
        parts.append("recursion: " + (", ".join(recursion) or "none") + " instead of " + (", ".join(before) or "none"))
    added = _ranked(set(own["lemmas"]) - set(reference["lemmas"]), weight)[:LABEL_LEMMAS]
    removed = _ranked(set(reference["lemmas"]) - set(own["lemmas"]), weight)[:LABEL_LEMMAS]
    if added or removed:
        parts.append(" ".join([f"+{name}" for name in added] + [f"\u2212{name}" for name in removed]))
    if not parts:
        parts.append("same recursion and lemmas, different claims" if own["claims"] != reference["claims"]
                     else "same recursion and lemmas, different logic")
    return "; ".join(parts)


def vocabulary(context: dict) -> set[str]:
    """Lemma names worth fingerprinting: the file's earlier theorems and defs, and non-library constants of the proof."""
    names = {item["name"] for item in context.get("earlier", []) if item.get("decl") in ("theorem", "def")}
    names |= {item["name"] for item in context.get("constant", [])
              if item.get("kind") in ("theorem", "def") and item.get("tag") not in ("core", "generated", "instance", "tactic")}
    return names


def route_table(history: list[dict]) -> list[dict]:
    """Per route: label, number of model proof attempts, best candidate and proxy. Pure function of the ledger."""
    labels: dict[str, str] = {}
    origin: dict[str, str] = {}
    for event in history:
        if event.get("kind") == "candidate":
            labels[event["candidate_id"]] = f"#{len(labels) + 1}"
            origin[event["candidate_id"]] = event.get("origin", "model")
    score: dict[str, tuple[bool, float]] = {}
    for event in history:
        if event.get("kind") != "evaluation":
            continue
        metrics = (event.get("result") or {}).get("metrics") or {}
        verified = event.get("mode") == "full" and metrics.get("proxy") is not None
        value = metrics.get("proxy") if verified else metrics.get("estimated_proxy")
        if value is not None and (event["candidate_id"] not in score or (verified, value) > score[event["candidate_id"]]):
            score[event["candidate_id"]] = (verified, value)
    table: dict[str, dict] = {}
    for event in history:
        if event.get("kind") != "route":
            continue
        row = table.setdefault(event["route"], {"route": event["route"], "label": event.get("label") or event["route"],
                                                "original": False, "attempts": 0, "best_candidate": None,
                                                "best_proxy": None, "verified": False})
        identifier = event["proof_id"]
        kind = origin.get(identifier)
        if kind == "reference":
            row["original"] = True
            continue
        if kind == "auto_merge":
            continue
        row["attempts"] += 1
        if identifier in score and (row["best_proxy"] is None or (score[identifier][0], score[identifier][1]) >
                                    (row["verified"], row["best_proxy"])):
            row["verified"], row["best_proxy"] = score[identifier]
            row["best_candidate"] = labels.get(identifier)
    return list(table.values())


def routes_text(table: list[dict]) -> str:
    """One line for the model: the routes with attempts and best proxy (the original's route is marked)."""
    parts = []
    for row in table:
        if not row["attempts"] and not row["original"]:
            continue
        best = f"best proxy {row['best_proxy']} ({row['best_candidate']})" if row["best_proxy"] is not None else "no scored proof"
        tag = " [the original proof's route]" if row["original"] else ""
        parts.append(f"{row['route']} \"{row['label']}\"{tag}: {row['attempts']} attempt{'s' if row['attempts'] != 1 else ''}, {best}")
    return "; ".join(parts) if parts else "none"
