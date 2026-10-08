#!/usr/bin/env python3
"""Validate route fingerprints on every stored historical proof (local Lean only, never a model call).

    collect   gather compiled proofs from past runs into runs/analysis/route-validation/proofs.jsonl
    extract   read kernel-term features of each proof (batched Lean processes) into features.jsonl
    report    cluster each theorem's proofs under the old and the new fingerprint
    robust    recompile text-level synonym rewrites of stored proofs and check they stay on their route

Proofs are keyed by the hash of their comment-stripped, whitespace-normalised text.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena import route_features, routes  # noqa: E402
from arena.engine import BENCHMARK  # noqa: E402

OUT = ROOT / "runs" / "analysis" / "route-validation"
PROOFS, FEATURES = OUT / "proofs.jsonl", OUT / "features.jsonl"
BATCH = 10
BATCH_TIMEOUT = 1500
SINGLE_TIMEOUT = 600


def rows() -> list[dict]:
    return [json.loads(line) for line in BENCHMARK.read_text(encoding="utf-8").splitlines()]


def normalise(proof: str) -> str:
    return re.sub(r"\s+", " ", routes._strip_comments(proof)).strip()


def key(proof: str) -> str:
    return hashlib.sha256(normalise(proof).encode()).hexdigest()[:16]


def era(label: str) -> str:
    if label.startswith("v6"):
        return "v6"
    if label.startswith("v5"):
        return "v5"
    if label.startswith(("baseline", "p0", "analysis")):
        return "naive" if not label.startswith("analysis") else "hybrid"
    return "pre-v5"


def theorem_of(proof: str, benchmark: list[dict]) -> str | None:
    match = [row["name"] for row in benchmark if proof.startswith(row["statement"])]
    return match[0] if match else None


def collect() -> list[dict]:
    benchmark = rows()
    found: dict[str, dict] = {}

    def add(proof: str, source: str, role: str, theorem: str | None = None) -> None:
        theorem = theorem or theorem_of(proof, benchmark)
        if not theorem or "sorry" in routes._strip_comments(proof):
            return
        entry = found.setdefault(key(proof), {"id": key(proof), "theorem": theorem, "proof": proof, "sources": [],
                                              "roles": [], "eras": [], "order": len(found)})
        entry["sources"].append(source)
        for field, value in (("roles", role), ("eras", era(source))):
            if value not in entry[field]:
                entry[field].append(value)

    for row in benchmark:
        add(row["src"], "benchmark", "original", row["name"])
    for ledger in sorted((ROOT / "runs" / "pi-budget").glob("*/ledger.jsonl")):
        directory = ledger.parent
        events = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        origin = {e["candidate_id"]: e.get("origin", "model") for e in events if e["kind"] == "candidate"}
        compiled = set()
        for e in events:
            compat = ((e.get("result") or {}).get("compat") or {}) if e["kind"] == "evaluation" else {}
            if compat and all(v.get("passed") for v in compat.values()):
                compiled.add(e["candidate_id"])
        for identifier in compiled:
            path = directory / "proofs" / f"{identifier}.lean"
            if path.exists():
                kind = origin.get(identifier, "model")
                add(path.read_text(), directory.name, "original" if kind == "reference" else
                    "auto_merge" if kind == "auto_merge" else "model")
    for pattern in ("runs/analysis/*.lean", "runs/analysis/scratch/*/*.lean", "runs/baseline/*/*proof*.txt",
                    "runs/baseline/*/arena-candidate-*.txt", "runs/p0/*/*proof*.txt", "submission/*.lean"):
        for path in sorted(ROOT.glob(pattern)):
            add(path.read_text(), "analysis/" + path.name if "analysis" in pattern else
                path.parent.parent.name + "/" + path.name, "hybrid" if "hybrid" in path.name else "other")
    for path in sorted(ROOT.glob("runs/submission-staging/*/proofs.jsonl")):
        for line in path.read_text().splitlines():
            item = json.loads(line)
            add(item["proof"], "submission-staging/" + path.parent.name, "model", item.get("name"))
    result = sorted(found.values(), key=lambda item: (item["theorem"], item["order"]))
    OUT.mkdir(parents=True, exist_ok=True)
    PROOFS.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in result))
    return result


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def extract(workers: int, only: str | None = None, limit: int | None = None) -> None:
    done = {item["id"] for item in load(FEATURES) if item.get("ok")}
    jobs: list[tuple[str, list[dict]]] = []
    by_theorem: dict[str, list[dict]] = {}
    for item in load(PROOFS):
        if item["id"] not in done and (not only or item["theorem"] == only):
            by_theorem.setdefault(item["theorem"], []).append(item)
    for theorem, items in by_theorem.items():
        items = items[:limit] if limit else items
        jobs += [(theorem, items[i:i + BATCH]) for i in range(0, len(items), BATCH)]

    def run(job: tuple[str, list[dict]]) -> list[dict]:
        theorem, items = job
        started = time.monotonic()
        got = route_features.extract(theorem, {item["id"]: item["proof"] for item in items}, BATCH_TIMEOUT)
        if all(v.get("error") == "timeout" for v in got.values()) and len(items) > 1:
            got = {}
            for item in items:
                got.update(route_features.extract(theorem, {item["id"]: item["proof"]}, SINGLE_TIMEOUT))
        seconds = time.monotonic() - started
        return [{"id": item["id"], "theorem": theorem, **got[item["id"]], "batch_seconds": round(seconds, 1),
                 "batch_size": len(items)} for item in items]

    with concurrent.futures.ThreadPoolExecutor(workers) as pool, FEATURES.open("a") as out:
        for future in concurrent.futures.as_completed([pool.submit(run, job) for job in jobs]):
            try:
                records = future.result()
            except Exception as error:  # a broken batch must not stop the others
                print("batch failed:", error, file=sys.stderr)
                continue
            for record in records:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{records[0]['theorem']}: {len(records)} proofs in {records[0]['batch_seconds']}s, "
                  f"{sum(1 for r in records if r.get('ok'))} ok", flush=True)


def old_cluster(items: list[dict], vocabulary: set[str]) -> dict[str, str]:
    """The text-feature clustering the harness used before: best match over every earlier proof, veto on recursion."""
    earlier: list[tuple[str, dict]] = []
    result: dict[str, str] = {}
    for item in items:
        print_ = routes.fingerprint(item["proof"], vocabulary, item["theorem"])
        best_route, best = None, 0.0
        for route, other in earlier:
            score = routes.text_similarity(other, print_)
            if score > best:
                best_route, best = route, score
        if best_route is not None and best >= 0.5:
            route = best_route
        else:
            route = f"r{len({r for r, _ in earlier}) + 1}"
        earlier.append((route, print_))
        result[item["id"]] = route
    return result


def new_cluster(items: list[dict], threshold: float | None = None, features: dict | None = None):
    """Route per proof under the kernel fingerprint, in arrival order; also the events and similarity to the exemplar."""
    saved = routes.SAME_ROUTE
    routes.SAME_ROUTE = saved if threshold is None else threshold
    try:
        events: list[dict] = []
        result: dict[str, str] = {}
        labels: dict[str, str] = {}
        for item in items:
            print_ = routes.fingerprint(item["proof"], frozenset(), item["theorem"], (features or {}).get(item["id"]))
            route, score = routes.assign(events, print_)
            if route not in labels:
                reference = next((e["fingerprint"] for e in events if e["route"] == "r1"), None)
                weights = routes.idf([e["fingerprint"] for e in events] + [print_])
                labels[route] = routes.label(print_, reference, weights)
            events.append({"route": route, "fingerprint": print_, "id": item["id"], "similarity": score})
            result[item["id"]] = route
        return result, labels, events
    finally:
        routes.SAME_ROUTE = saved


def excerpt(proof: str, lines: int = 7, width: int = 110) -> str:
    body = routes.proof_body(proof).strip("\n").splitlines()
    return "\n".join(line[:width] for line in body[:lines]) + ("\n  ..." if len(body) > lines else "")


def ordered(items: list[dict]) -> list[dict]:
    """Original first, then the rest in the order they were collected (runs in name order, ledger order within)."""
    return sorted(items, key=lambda item: ("original" not in item["roles"], item["order"]))


def analyse(thresholds=(0.4, 0.5, 0.6)) -> dict:
    from arena.context import cached_context

    features = {item["id"]: item for item in load(FEATURES) if item.get("ok")}
    by_theorem: dict[str, list[dict]] = {}
    failed: list[dict] = []
    for item in load(PROOFS):
        if item["id"] in features:
            by_theorem.setdefault(item["theorem"], []).append(item)
        else:
            failed.append({"id": item["id"], "theorem": item["theorem"], "error": next(
                (f.get("error") for f in load(FEATURES) if f["id"] == item["id"]), "not extracted")})
    out: dict = {"theorems": {}, "failed": failed}
    for theorem, items in by_theorem.items():
        items = ordered(items)
        vocabulary = routes.vocabulary(cached_context(theorem))
        old = old_cluster(items, vocabulary)
        new, labels, events = new_cluster(items, features=features)
        sensitivity = {str(t): len(set(new_cluster(items, t, features)[0].values())) for t in thresholds}
        sizes = lambda assignment: sorted((list(assignment.values()).count(r) for r in set(assignment.values())), reverse=True)
        out["theorems"][theorem] = {
            "proofs": len(items), "old_routes": len(set(old.values())), "new_routes": len(set(new.values())),
            "old_sizes": sizes(old), "new_sizes": sizes(new), "labels": labels, "sensitivity": sensitivity,
            "order": [item["id"] for item in items], "old": old, "new": new,
            "similarity": {e["id"]: e["similarity"] for e in events},
            "vocabulary": len(vocabulary)}
    return out


def disagreements(result: dict, per_cell: int = 3) -> list[dict]:
    """Pairs the two fingerprints judge differently: same old route but different new route, and the reverse.
    Up to `per_cell` pairs for each combination of old and new routes, chosen at random with a fixed seed."""
    import random

    rng = random.Random(11)
    proofs = {item["id"]: item for item in load(PROOFS)}
    pairs: list[dict] = []
    for theorem, row in result["theorems"].items():
        order, old, new = row["order"], row["old"], row["new"]
        cells: dict[tuple, list[tuple[str, str]]] = {}
        for index, first in enumerate(order):
            for second in order[index + 1:]:
                if (old[first] == old[second]) != (new[first] == new[second]):
                    cells.setdefault((old[first], old[second], new[first], new[second]), []).append((first, second))
        for cell, found in cells.items():
            for first, second in rng.sample(found, min(per_cell, len(found))):
                pairs.append({"theorem": theorem, "a": first, "b": second, "old": [old[first], old[second]],
                              "new": [new[first], new[second]], "old_says": "same" if old[first] == old[second] else "different",
                              "a_sources": proofs[first]["sources"][:1], "b_sources": proofs[second]["sources"][:1]})
    return pairs


def route_details(result: dict) -> str:
    """Markdown: per theorem and new route, size, label, eras and two short representative proofs."""
    proofs = {item["id"]: item for item in load(PROOFS)}
    lines: list[str] = []
    for theorem, row in result["theorems"].items():
        lines.append(f"### {theorem}\n")
        for route in sorted(set(row["new"].values()), key=lambda r: int(r[1:])):
            members = [i for i in row["order"] if row["new"][i] == route]
            eras: dict[str, int] = {}
            for i in members:
                for era_ in proofs[i]["eras"]:
                    eras[era_] = eras.get(era_, 0) + 1
            best = max(members[1:], key=lambda i: row["similarity"][i], default=None)
            lines.append(f"- **{route}**: {len(members)} proofs ({', '.join(f'{k} {v}' for k, v in eras.items())}); "
                         f"label: `{row['labels'][route]}`")
            for i in [members[0]] + ([best] if best else []):
                lines.append(f"  - `{i}` ({proofs[i]['sources'][0]}):\n\n```lean\n{excerpt(proofs[i]['proof'])}\n```\n")
        lines.append("")
    return "\n".join(lines)


def report() -> None:
    result = analyse()
    (OUT / "clusters.json").write_text(json.dumps(result, indent=1))
    (OUT / "routes.md").write_text(route_details(result))
    (OUT / "disagreements.json").write_text(json.dumps(disagreements(result), indent=1))
    print("| theorem | proofs | old routes | new routes | old sizes | new sizes | new routes at 0.4/0.5/0.6 |")
    print("|---|---|---|---|---|---|---|")
    for theorem, row in result["theorems"].items():
        print(f"| {theorem} | {row['proofs']} | {row['old_routes']} | {row['new_routes']} | {row['old_sizes']} | "
              f"{row['new_sizes']} | {'/'.join(str(v) for v in row['sensitivity'].values())} |")
    print("failed:", len(result["failed"]))


def _line_rewrite(pattern: str, replacement: str):
    expression = re.compile(pattern, re.M)
    return lambda text: expression.sub(replacement, text)


def _swap_haves(text: str) -> str:
    """Swap the first pair of consecutive one-line `have`s when the second does not use the first."""
    lines = text.split("\n")
    head = re.compile(r"^(\s*)have\s+([\w']+)\s*(?::[^\n]*)?:=\s*\S")
    for index in range(len(lines) - 1):
        first, second = head.match(lines[index]), head.match(lines[index + 1])
        if first and second and first.group(1) == second.group(1) and \
                not re.search(r"(?<![\w'])" + re.escape(first.group(2)) + r"(?![\w'])", lines[index + 1]) and \
                (index + 2 >= len(lines) or not lines[index + 2].startswith(first.group(1) + " ")):
            lines[index], lines[index + 1] = lines[index + 1], lines[index]
            break
    return "\n".join(lines)


REWRITES = {
    "exists->refine": _line_rewrite(r"^(\s*)exists\s+([^,\n]+)$", r"\1refine ⟨\2, ?_⟩"),
    "exists->use": _line_rewrite(r"^(\s*)exists\s+([^\n]+)$", r"\1use \2"),
    "use->exists": _line_rewrite(r"^(\s*)use\s+([^\n]+)$", r"\1exists \2"),
    "obtain->rcases": _line_rewrite(r"^(\s*)obtain\s+(⟨[^:\n]*⟩|\S+)\s*:=\s*([^\n]+)$", r"\1rcases \3 with \2"),
    "rcases->obtain": _line_rewrite(r"^(\s*)rcases\s+([^\n]+?)\s+with\s+(⟨[^\n]*⟩|\S+)\s*$", r"\1obtain \3 := \2"),
    "bullets->dot": lambda text: text.replace("·", "."),
    "dot->bullets": _line_rewrite(r"^(\s*)\. ", r"\1· "),
    "intros->intro": _line_rewrite(r"^(\s*)intros (\S)", r"\1intro \2"),
    "intro->intros": _line_rewrite(r"^(\s*)intro (\S)", r"\1intros \2"),
    "exact->apply": _line_rewrite(r"^(\s*)exact ", r"\1apply "),
    "by_contra->byContradiction": _line_rewrite(r"^(\s*)by_contra (\w+)\s*$",
                                                  r"\1apply Classical.byContradiction\n\1intro \2"),
    "swap-haves": _swap_haves,
}


def rewrites(proof: str) -> dict[str, str]:
    """Text-level synonym rewrites that change this proof; the combination of all of them is `all`."""
    found = {}
    combined = proof
    for name, rewrite in REWRITES.items():
        changed = rewrite(proof)
        if changed != proof:
            found[name] = changed
        combined = rewrite(combined)
    if combined != proof and len(found) > 1:
        found["all"] = combined
    return found


def robust(per_theorem: int = 8) -> None:
    """Recompile synonym rewrites of stored proofs and check each lands on the route of its source."""
    import random

    from arena.context import cached_context

    result = analyse()
    features = {item["id"]: item for item in load(FEATURES) if item.get("ok")}
    proofs = {item["id"]: item for item in load(PROOFS)}
    rng = random.Random(7)
    records = []
    for theorem, row in result["theorems"].items():
        if row["proofs"] < 3 and theorem not in ("putnam_1964_a4", "putnam_1964_b2", "putnam_1995_a3"):
            continue
        order = row["order"]
        bases = [order[0]]
        for route in sorted(set(row["new"].values())):
            members = [i for i in order if row["new"][i] == route and i != order[0]]
            bases += rng.sample(members, min(len(members), 2 if row["new_routes"] > 1 else per_theorem // 2))
        bases = list(dict.fromkeys(bases))[:per_theorem]
        variants: dict[str, tuple[str, str, str]] = {}
        for base in bases:
            for name, text in rewrites(proofs[base]["proof"]).items():
                variants[f"{base}:{name}"] = (base, name, text)
        if not variants:
            continue
        items = ordered([proofs[i] for i in order])
        ids = list(variants)
        got: dict[str, dict] = {}
        for start in range(0, len(ids), BATCH):
            chunk = ids[start:start + BATCH]
            got.update(route_features.extract(theorem, {tag: variants[tag][2] for tag in chunk}, BATCH_TIMEOUT))
        vocabulary = routes.vocabulary(cached_context(theorem))
        _, _, events = new_cluster(items, features=features)
        weights = routes.idf([e["fingerprint"] for e in events])
        route_of = {e["id"]: e["route"] for e in events}
        for tag, (base, name, text) in variants.items():
            record = {"theorem": theorem, "base": base, "rewrite": name, "ok": bool(got[tag].get("ok")),
                      "error": got[tag].get("error"), "text": text if got[tag].get("ok") else None}
            if record["ok"]:
                base_print = next(e["fingerprint"] for e in events if e["id"] == base)
                print_ = routes.fingerprint(text, frozenset(), theorem, got[tag])
                exemplar_route, score = routes.assign(events, print_)
                record.update({"base_route": route_of[base], "variant_route": exemplar_route,
                               "same_route": exemplar_route == route_of[base],
                               "similarity": round(routes.similarity(base_print, print_, weights), 3),
                               "old_similarity": round(routes.text_similarity(
                                   routes.fingerprint(proofs[base]["proof"], vocabulary, theorem),
                                   routes.fingerprint(text, vocabulary, theorem)), 3)})
            records.append(record)
    (OUT / "robustness.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    table: dict[str, list[dict]] = {}
    for record in records:
        table.setdefault(record["rewrite"], []).append(record)
    print("| rewrite | recompiled ok / tried | same route (new) | mean similarity (new) | same route (old text fingerprint) |")
    print("|---|---|---|---|---|")
    for name, rows in table.items():
        good = [r for r in rows if r["ok"]]
        if good:
            print(f"| {name} | {len(good)}/{len(rows)} | {sum(r['same_route'] for r in good)}/{len(good)} | "
                  f"{sum(r['similarity'] for r in good) / len(good):.2f} | {sum(r['old_similarity'] >= 0.5 for r in good)}/{len(good)} |")
        else:
            print(f"| {name} | 0/{len(rows)} | - | - | - |")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["collect", "extract", "report", "robust"])
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--theorem")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "collect":
        result = collect()
        counts: dict[str, int] = {}
        for item in result:
            counts[item["theorem"]] = counts.get(item["theorem"], 0) + 1
        print(len(result), "distinct proofs", counts)
    elif args.command == "extract":
        extract(args.workers, args.theorem, args.limit)
    elif args.command == "report":
        report()
    else:
        robust()


if __name__ == "__main__":
    main()
