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

Attempts are compiled, closed candidates only (probe drafts, ``sorry`` drafts and failed compiles are never
queued). They are clustered in arrival order: an attempt joins the route whose first attempt (its
exemplar) it most resembles when the similarity reaches ``SAME_ROUTE``, otherwise it starts a new route. A
route is *credited* (counts as opened by the model) only when a kernel fingerprint opened it. An incomplete
attempt (holes or error-recovery sorries; only in ledgers from before this rule) lacks what will fill them, so against it only the parts it has are
compared, as containment instead of overlap. Attempts without a kernel fingerprint join the route whose text
features match best and never open one.

Depth is measured by goal states: every attempt has a signature (arena/goalstate.py) of what Lean still reports
open, and a route's depth is the number of distinct signatures its attempts produced.
"""

from __future__ import annotations

import math
import re

SAME_ROUTE = 0.5
ROUTE_DEPTH = 3     # distinct goal states that make a route explored
TEXT_EXEMPLAR_MIN = 0.7   # a kernel attempt joins a text-only exemplar's route only this close: text overlap is a weak proxy
STALE_STREAK = 5    # consecutive attempts leaving an already seen goal state
MAX_SKELETON = 24
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
    if features and (features.get("ok") or features.get("read")):
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
            "claims": sorted(set(features.get("claims", []))), "logic": sorted(clean(features.get("logic", []))),
            "holes": int(features.get("holes") or 0), "synthetic": int(features.get("synthetic") or 0)}


def incomplete(print_: dict) -> bool:
    """A kernel fingerprint of a term with `sorry` holes or error-recovery sorries."""
    kernel_ = print_.get("kernel") or {}
    return bool(kernel_.get("holes") or kernel_.get("synthetic"))


def empty(print_: dict) -> bool:
    return not any((print_.get("kernel") or {}).get(part) for part in PARTS)


def strategy(print_: dict) -> bool:
    """Whether a fingerprint carries recursion, lemmas or logic. Claims alone do not count for an incomplete proof:
    a draft that failed to parse or elaborate leaves a stray claim from error recovery, and must not open a route."""
    kernel_ = print_.get("kernel") or {}
    return any(kernel_.get(part) for part in ("recursion", "lemmas", "logic"))


def idf(prints: list[dict]) -> dict[str, dict[str, float]]:
    """Rarity weight of every item per part over the complete kernel fingerprints of one theorem's proofs: ln(1 + N/df).
    Drafts with holes or errors are left out: many near-copies of one dead end would make its items look common."""
    kernels = [item["kernel"] for item in prints if item.get("kernel") and not incomplete(item)]
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


def _contained(part: set, whole: set, weight: dict | None = None) -> float:
    weight = weight or {}
    return sum(weight.get(item, 1.0) for item in part & whole) / sum(weight.get(item, 1.0) for item in part)


def similarity(left: dict, right: dict, weights: dict[str, dict[str, float]] | None = None) -> float:
    """Weighted sum of the rarity-weighted overlaps of the four parts; text features if either proof lacks them.
    `left` is the exemplar. When one side is incomplete (holes or error-recovery sorries) only the parts it has
    count, weights renormalized over them, and each part is how much of the incomplete side the other contains."""
    if not (left.get("kernel") and right.get("kernel")):
        return text_similarity(left, right)
    weights = weights or {}
    partial = left if incomplete(left) else right if incomplete(right) else None
    if partial is not None:
        other = right if partial is left else left
        have = [part for part in PARTS if partial["kernel"][part]]
        if have:
            return sum(WEIGHTS[part] * _contained(set(partial["kernel"][part]), set(other["kernel"][part]), weights.get(part))
                       for part in have) / sum(WEIGHTS[part] for part in have)
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
    best_route, best, closest = None, 0.0, 0.0
    for route, event in first.items():
        score = similarity(event["fingerprint"], current, weights)
        closest = max(closest, score)
        # A text-only exemplar (kernel extraction failed for it) must not absorb kernel attempts it only vaguely
        # resembles: that is how a whole run once piled onto one text-labelled route.
        threshold = SAME_ROUTE if event["fingerprint"].get("kernel") or not current.get("kernel") else TEXT_EXEMPLAR_MIN
        if score > best and score >= threshold:
            best_route, best = route, score
    if best_route is not None:
        return best_route, round(best, 3)
    return f"r{len(first) + 1}", round(closest, 3)


def assign_by_text(earlier: list[dict], current: dict) -> tuple[str, float] | None:
    """The route whose exemplar's text features match `current` best (ties to the earliest), however weak; None
    when there is no route. For attempts the kernel could not read, which therefore never open a route."""
    best_route, best = None, -1.0
    for route, event in exemplars(earlier).items():
        score = text_similarity(event["fingerprint"], current)
        if score > best:
            best_route, best = route, score
    return None if best_route is None else (best_route, round(best, 3))


def _constants(print_: dict) -> set[str]:
    """The constants a fingerprint names, as opaque items (only ever counted, never shown to the model or labelled)."""
    kernel_ = print_.get("kernel")
    if kernel_:
        return set(kernel_["recursion"]) | set(kernel_["lemmas"])
    return set(print_.get("lemmas", []))


def label(print_: dict, reference: dict | None = None, weights: dict[str, dict[str, float]] | None = None) -> str:
    """A neutral, deterministic description made only of measured facts: how the fingerprint was read, how many of
    its constants differ from the original's route (r1), and its open holes. No proof-content term appears in it."""
    source = "kernel" if print_.get("kernel") else "text"
    if reference is None:
        return f"{source} fingerprint, first route"
    differ = len(_constants(print_) ^ _constants(reference))
    holes = int((print_.get("kernel") or {}).get("holes") or 0) + int((print_.get("kernel") or {}).get("synthetic") or 0)
    return f"{source} fingerprint, {differ} constants differ from r1" + (f", {holes} open holes" if holes else "")


def short_label(print_: dict, reference: dict | None = None, weights: dict[str, dict[str, float]] | None = None) -> str:
    """Compact form of `label` for the viewer legend."""
    if reference is None:
        return "first route"
    return f"\u0394{len(_constants(print_) ^ _constants(reference))} vs r1"


def vocabulary(context: dict) -> set[str]:
    """Lemma names worth fingerprinting: the file's earlier theorems and defs, and non-library constants of the proof."""
    names = {item["name"] for item in context.get("earlier", []) if item.get("decl") in ("theorem", "def")}
    names |= {item["name"] for item in context.get("constant", [])
              if item.get("kind") in ("theorem", "def") and item.get("tag") not in ("core", "generated", "instance", "tactic")}
    return names


def attempt_results(history: list[dict]) -> dict[str, tuple[str, dict | None]]:
    """Per attempt id: ("probe" | "candidate", the compile result of its first probe or evaluation)."""
    found: dict[str, tuple[str, dict | None]] = {}
    for event in history:
        if event.get("kind") == "probe":
            found.setdefault(event["proof_id"], ("probe", event.get("result")))
        elif event.get("kind") == "evaluation":
            found.setdefault(event["candidate_id"], ("candidate", event.get("result")))
    return found


def route_table(history: list[dict]) -> list[dict]:
    """Per route: label, number of model attempts (compiled candidates and probe drafts), best candidate and proxy,
    and depth: distinct goal-state signatures (arena/goalstate.py), the fewest open holes, the stale streak (latest
    consecutive attempts whose signature the route had already seen), whether it is explored (a compiled proof or
    `ROUTE_DEPTH` goal states) and whether the model credited it (a kernel fingerprint opened it). Pure function of the ledger."""
    from arena import goalstate

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
    results = attempt_results(history)
    table: dict[str, dict] = {}
    seen: dict[str, set[str]] = {}
    for event in history:
        if event.get("kind") != "route":
            continue
        identifier = event["proof_id"]
        kind = origin.get(identifier)
        route = event["route"]
        # Credit is for compiled proofs only: the attempt must be a candidate whose compile passed with no error and no
        # sorry. A draft, a hole-carrying skeleton or a failed compile never opens or credits a route (also in old ledgers).
        earned = identifier in results and results[identifier][0] == "candidate" and goalstate.closed(results[identifier][1])
        if route not in table:
            credited = event.get("credited")
            if credited is None:  # an event from before credit existed: a kernel route opened by a model attempt
                credited = bool(event.get("new") and event.get("source") == "kernel" and kind in (None, "model"))
            table[route] = {"route": route, "label": event.get("label") or route,
                           "short_label": event.get("short_label") or event.get("label") or route, "original": False, "attempts": 0,
                            "best_candidate": None, "best_proxy": None, "verified": False,
                            "depth": 0, "new_states": 0, "min_holes": None, "stale_streak": 0, "compiled": False,
                            "explored": False, "stale": False, "credited": bool(credited) and earned and kind != "reference",
                            "skeleton": bool(event.get("skeleton"))}
            seen[route] = set()
        row = table[route]
        if kind == "reference":
            # The reference may be filed after attempts that already opened its route (a late fingerprint): the
            # route is then the original's, and not one the model opened.
            row["original"] = row["compiled"] = row["explored"] = True
            row["credited"] = False
            seen[route].add(goalstate.CLOSED)
            continue
        if kind == "auto_merge":
            continue
        if (not row["original"] and event.get("assigned_by", "kernel") == "kernel" and event.get("source") == "kernel"
                and not event.get("errored") and earned and not event.get("holes") and not event.get("synthetic")):
            row["credited"] = True  # a later compiled proof credits a route an uncredited attempt opened
            row["skeleton"] = row["skeleton"] or bool(event.get("skeleton"))
        row["attempts"] += 1
        if identifier in score and (row["best_proxy"] is None or (score[identifier][0], score[identifier][1]) >
                                    (row["verified"], row["best_proxy"])):
            row["verified"], row["best_proxy"] = score[identifier]
            row["best_candidate"] = labels.get(identifier)
        if identifier not in results:
            continue
        sig = goalstate.signature(results[identifier][1])
        if sig == goalstate.CLOSED:
            row["compiled"], open_holes = True, 0
        else:
            open_holes = (event.get("holes") or 0) + (event.get("synthetic") or 0) if "holes" in event else None
        if open_holes is not None and (row["min_holes"] is None or open_holes < row["min_holes"]):
            row["min_holes"] = open_holes
        if sig in seen[route]:
            row["stale_streak"] += 1
        else:
            seen[route].add(sig)
            row["depth"] += 1
            row["new_states"] += 1
            row["stale_streak"] = 0
        row["explored"] = row["compiled"] or row["depth"] >= ROUTE_DEPTH
    for row in table.values():
        row["stale"] = row["stale_streak"] >= STALE_STREAK
    return list(table.values())


def progress(table: list[dict]) -> dict:
    """Run-level depth metrics of a route table: credited and explored routes, and the share of model attempts
    that produced a goal state new to their route."""
    rows = [row for row in table if row["attempts"]]
    attempts = sum(row["attempts"] for row in rows)
    new = sum(row["new_states"] for row in rows)
    return {"credited_routes": sum(row["credited"] for row in rows), "explored_routes": sum(row["explored"] for row in rows),
            "new_state_attempts": new, "new_state_share": round(new / attempts, 3) if attempts else None}


def routes_text(table: list[dict]) -> str:
    """One line for the model: neutral facts per route (id, original or credited, attempts, goal states, best proxy).
    The label is for humans and never appears here, so no route is named or framed."""
    parts = []
    for row in table:
        if not row["attempts"] and not row["original"]:
            continue
        best = f"best proxy {row['best_proxy']} ({row['best_candidate']})" if row["best_proxy"] is not None else "no scored proof"
        tag = (" (original's route)" if row["original"] else " (credited)" if row.get("credited")
               else " (not credited)" if "credited" in row or "depth" in row else "")
        states = f" \u00b7 {row['depth']} goal state{'s' if row['depth'] != 1 else ''}" if row.get("depth") is not None else ""
        parts.append(f"{row['route']}{tag} \u00b7 {row['attempts']} attempt{'s' if row['attempts'] != 1 else ''}{states} \u00b7 {best}")
    return "; ".join(parts) if parts else "none"


def routes_detail_text(table: list[dict]) -> str:
    """`routes_text` with each route's depth: goal states, fewest holes, stale streak, explored/opened, credit."""
    parts = []
    for row in table:
        if not row["attempts"] and not row["original"]:
            continue
        best = f"best proxy {row['best_proxy']} ({row['best_candidate']})" if row["best_proxy"] is not None else "no scored proof"
        tag = " [the original proof's route]" if row["original"] else ""
        states = row.get("depth", 0)
        extra = [f"{states} goal state{'s' if states != 1 else ''}"]
        if row.get("min_holes") is not None:
            extra.append(f"min holes {row['min_holes']}")
        if row.get("stale_streak"):
            extra.append(f"stale streak {row['stale_streak']}")
        extra.append("explored" if row.get("explored") else "opened")
        if row.get("credited"):
            extra.append("credited" + (" (opened by a skeleton)" if row.get("skeleton") else ""))
        parts.append(f"{row['route']} \"{row['label']}\"{tag}: {row['attempts']} attempt{'s' if row['attempts'] != 1 else ''}, "
                     f"{', '.join(extra)}, {best}")
    return "; ".join(parts) if parts else "none"


def file_attempt(earlier: list[dict], proof_id: str, print_: dict, features: dict | None, origin: str | None, probe: bool) -> dict:
    """The route event for one attempt. `origin` is the candidate's (None for a probe draft). Only an attempt with a
    kernel fingerprint of a complete proof that matches no exemplar opens a credited route. A probe draft, an
    incomplete (holes or errors) or kernel-less attempt joins the route whose text features match best, starts r1 only
    when there is none, and is never credited."""
    complete = not probe and not incomplete(print_) and not (features or {}).get("errored")
    by_kernel = print_["source"] == "kernel" and complete
    found = None if by_kernel else assign_by_text(earlier, print_)
    route, similarity = found or (assign(earlier, print_) if by_kernel else ("r1", 0.0))
    new = route not in {item["route"] for item in earlier}
    reference = next((item["fingerprint"] for item in earlier if item["route"] == "r1"), None)
    event = {"kind": "route", "proof_id": proof_id, "route": route, "new": new,
             "similarity": similarity, "source": print_["source"], "fingerprint": print_,
             "assigned_by": "kernel" if by_kernel else "text", "attempt_kind": "probe" if probe else "candidate",
             # Credit is for a compiled, complete proof only: a probe draft, a skeleton with holes or an errored draft
             # never opens a route (it joins the closest existing one by text, and is never credited).
             "credited": new and by_kernel and origin == "model",
             "label": label(print_, reference, idf([item["fingerprint"] for item in earlier] + [print_])) if new else next(
                 item["label"] for item in earlier if item["route"] == route),
             "short_label": short_label(print_, reference, idf([item["fingerprint"] for item in earlier] + [print_])) if new else next(
                 item.get("short_label") or item["label"] for item in earlier if item["route"] == route)}
    if print_["source"] == "kernel":
        kernel_ = print_["kernel"]
        event.update(holes=kernel_["holes"], synthetic=kernel_["synthetic"], skeleton=kernel_["holes"] > 0,
                     errored=bool((features or {}).get("errored")))
    return event
