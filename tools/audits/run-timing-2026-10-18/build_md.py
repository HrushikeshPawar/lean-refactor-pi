#!/usr/bin/env python3
"""Render the agent-facing findings from the offline timing scan."""

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = json.loads((HERE / "summary.json").read_text())
RUNS = DATA["runs"]
TOTAL = DATA["aggregate"]["totals"]["observed_wall_s"]


def table(headers, records):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                     + ["| " + " | ".join(str(v) for v in row) + " |" for row in records])


def short(theorem):
    names = {
        "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius": "Fiberwise",
        "Binius.BinaryBasefold.fold_advances_evaluation_poly": "Binius fold",
        "interleaved_affine_gaps_imply_tensor_gaps": "Interleaved",
        "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress": "Fsub progress",
        "Cslib.SKI.parallelReduction_diamond": "SKI diamond",
        "Cslib.CCS.bisimilarity_congr_choice": "CCS choice",
        "Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema": "Electromagnetism",
        "FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time": "WickAlgebra",
    }
    return names.get(theorem, theorem or "Unknown")


def main():
    totals = DATA["aggregate"]["totals"]
    parts = [("LLM request intervals", "llm_union_s"), ("Tool execution, merged", "tool_exclusive_s"),
             ("Before first request / setup-only records", "before_first_request_s"),
             ("After last trace event", "after_last_trace_s"),
             ("Unattributed gaps inside interaction", "interactive_unattributed_s")]
    overall = table(["Category", "Run-hours", "Share"],
                    [(name, f"{totals[key]/3600:.2f}", f"{100*totals[key]/TOTAL:.2f}%") for name,key in parts])
    family = table(["Family", "Runs", "Span, min", "LLM, min (%)", "Tools, min", "Pre-call, min", "Tail, min", "Gaps, min"],
                   [(name, value["runs"], f"{value['totals']['observed_wall_s']/60:.1f}",
                     f"{value['totals']['llm_union_s']/60:.1f} ({100*value['totals']['llm_union_s']/value['totals']['observed_wall_s']:.1f}%)",
                     *[f"{value['totals'][key]/60:.1f}" for key in
                       ("tool_exclusive_s", "before_first_request_s", "after_last_trace_s", "interactive_unattributed_s")])
                    for name,value in DATA["families"].items()])
    models = table(["Model", "Matched calls", "Total, h", "Median, s", "p90, s", "p95, s", "Max, s", "Failed attempts"],
                   [(name, row["duration"]["n"], f"{row['duration']['sum_s']/3600:.2f}",
                     *[f"{row['duration'][key]:.2f}" for key in ("p50_s", "p90_s", "p95_s", "max_s")], row["failed"])
                    for name,row in DATA["aggregate"]["models"].items()])
    tools = table(["Tool", "Calls", "Accumulated min", "Median, s", "p95, s", "Max, s", "Tool errors"],
                  [(name, row["n"], f"{row['sum_s']/60:.2f}",
                    *[f"{row[key]:.2f}" for key in ("p50_s", "p95_s", "max_s")], row["failed"])
                   for name,row in sorted(DATA["aggregate"]["tools"].items(), key=lambda pair:-pair[1]["sum_s"])])
    v8c = table(["Theorem", "Observed min", "LLM min", "Tools min", "Pre-call min", "Tail min"],
                [(short(row["theorem"]), *[f"{row[key]/60:.2f}" for key in
                  ("observed_wall_s", "llm_union_s", "tool_exclusive_s", "before_first_request_s", "after_last_trace_s")])
                 for row in RUNS if row["family"] == "v8c"])
    by_theorem = defaultdict(list)
    for row in RUNS:
        by_theorem[short(row["theorem"])].append(row)
    theorems = table(["Theorem", "Runs", "Span h", "LLM h", "Tools h", "Pre-call min", "Tail min"],
                     [(name, len(rows), *[f"{sum(r[key] for r in rows)/3600:.2f}" for key in
                       ("observed_wall_s", "llm_union_s", "tool_exclusive_s")],
                       *[f"{sum(r[key] for r in rows)/60:.2f}" for key in
                         ("before_first_request_s", "after_last_trace_s")])
                      for name,rows in sorted(by_theorem.items(), key=lambda pair:-sum(r["observed_wall_s"] for r in pair[1]))])
    output = f"""# v7 / v8 run timing: agent reference — 2026-10-18

Read this before changing run scheduling, model-turn policy, Lean worker reuse, or finalization based on historical timing. This is an offline analysis of **all `runs/pi-budget/v7*` and `v8*` directories** in the saved snapshot. It changes no runtime policy and launches no Lean or provider work.

## Findings to use

Across 66 run directories, the summed **observed activity spans** total **45.03 run-hours**: **35.14 h LLM (78.05%)**, **6.78 h foreground tool execution (15.07%)**, and **3.10 h pre-call, tail, and unattributed gaps (6.88%)**. This is elapsed client-side activity accounting, not CPU time and not exact process lifetime. Parallel runs overlap: the union of their recorded windows is **25.15 h**, rather than 45.03 h.

v7 is predominantly model-bound. v8c is different: **38.50% LLM, 26.68% tools, 24.11% tail**, with 10.45% before the first request. Fiberwise and Interleaved account for most of its tool and tail time. Optimize by workload and family; the whole-archive average conceals those rows.

{overall}

## Reproduce and inspect

1. Run `uv run --no-sync python tools/audits/run-timing-2026-10-18/scan.py`. Completion: zero parse errors and all partition assertions pass.
2. Run `uv run --no-sync python tools/audits/run-timing-2026-10-18/build_md.py` and `uv run --no-sync python tools/audits/run-timing-2026-10-18/build_html.py` to regenerate reports.
3. Filter [runs.csv](../../tools/audits/run-timing-2026-10-18/runs.csv) for the relevant theorem/model. Inspect exact request/tool IDs, intervals, and file SHA-256s in [summary.json](../../tools/audits/run-timing-2026-10-18/summary.json).
4. Follow an outlier's IDs to its `trace-journal.jsonl` and `ledger.jsonl`. Completion: distinguish observed durations from attribution hypotheses before proposing a change.

The [interactive HTML report](V7_V8_TIMING_2026-10-18.html) gives family filters, distributions, and per-run drill-down. [scan.py](../../tools/audits/run-timing-2026-10-18/scan.py) is the accounting source of truth.

## Accounting rules and coverage

- **79 matching directories = 66 runs + 13 campaign containers.** Containers are listed in the JSON and excluded from the run denominator. Of 66 runs, 63 have trace journals, 65 have summaries/health reports, and 61 have at least one completed request interval. Setup failures and interrupted runs remain included.
- **6,125 request rows; 6,111 matched request/completion pairs; 14 unmatched starts.** Pair `request.id` with `response.id`. Ten synthetic response rows have no matching provider request; their stale stamped `request_id` must not overwrite a real completion. Unfinished attempts remain unknown; their unmeasured remainder is not imputed as model or harness time.
- **LLM latency** is `response.ts - request.ts`, both Unix milliseconds recorded by the Pi extension. It includes provider waiting, generation/reasoning, streaming, and local completion-hook overhead. HTTP response-header arrival is not stream completion or the first generated token.
- **Tool latency** is `tool_result.ts - tool_call.ts`, paired by `tool_call_id`. All 6,249 matched intervals are accounted for; two starts lack results. Tool errors count the tool-level `is_error` flag, not every rejected proof. Proof diagnostics commonly return through successful tool transport.
- **Observed span** is the earliest valid own-run ledger/health/session/trace/cost timestamp through the latest. It excludes process work before the first recorded timestamp and after the last. No file modification time substitutes for a missing runtime boundary.
- **Seeded histories:** two `-s1` runs inherit ancestor ledgers. Their 887 inherited events are excluded from timing and work totals; otherwise ancestor timestamps would create nearly ten fictitious pre-call hours. The current run starts from its own health/session/trace evidence.
- Merge intervals **within each run** before computing shares. Tools can overlap each other: accumulated tool durations total 7.12 h, while their elapsed union is 6.78 h. No matched LLM/tool overlap remains in this snapshot. Across runs, overlap is expected and is not removed from run-hour totals.
- Full checks can copy known fast results, and probes/promotions can retain identical compiler records. Saved `.lean.seconds` values therefore are not additive proof-work totals. Background salvage/profile/step-goal durations overlap model waits and foreground tools; report them separately.
- The persisted historical ledgers have **no runtime phase/job events**. Exact process launch/exit, per-phase lock wait, and background overlap cannot be reconstructed. There are no compaction cost-settle rows in these runs; unmatched requests are not silently labeled compaction.
- Percentiles use linear interpolation over the observed samples. Families/models/theorems have different budgets and workloads; comparisons are descriptive, not controlled speed benchmarks.

## Family distribution

Minutes are summed per-run observed time. Shares are weighted by those spans, rather than averages of run percentages. The original `v8` family contains startup/interrupt attempts and no matched completion, so it is not a meaningful model-performance cohort.

{family}

## LLM latency distribution

{models}

There are **398 calls over 60 s**, occupying **11.30 h / 32.15%** of all matched LLM time. Eighty exceed 120 s and occupy 4.19 h. Seven exceed 300 s and occupy 0.83 h. DeepSeek contributes 12.42 million recorded output tokens, versus 0.70 million for Sol and 2.15 million for MiMo; output may include reasoning. Task mix, output volume, provider, and policy differ, so these totals cannot isolate model throughput.

Median response-header arrival is 2.94 s for DeepSeek, 2.04 s for Sol, and 2.63 s for MiMo. Their mean remaining interval after headers is 24.07 / 9.55 / 13.09 s among calls with header records. Thus measuring only HTTP response latency misses most of the wait. MiMo has 53 recorded failed attempts and 53 retry-marked matched requests; DeepSeek 4/4, Sol 15/13. These counters overlap and should not be added.

There are **1,593 context-only tool-producing requests** (tools drawn from read/search/goal, without compile/scratch/fill/finish). Their LLM intervals total **7.23 h**, about **20.6% of matched LLM time**. This is a turn-reduction experiment target, not evidence that the context was unnecessary. Multi-tool batches count as one request.

## Tool latency distribution

These are accumulated per-call durations; simultaneous tools overlap, so this table is not a partition of wall time.

{tools}

Compile represents about **79.6% of accumulated tool time**. Sixteen token-only compile calls consumed just 6.50 seconds altogether. The large target is Lean-backed compile latency, not token counting.

The longest compile is **259.585 s** in `v8c-interleaved_affine_gaps_imply_tensor_gap-gpt-6.1-sol-r1`, tool ID `call_Ta1HRlcpDbJmClVmh5urcP7a|fc_07706d755d8329c8016ad1ed92a63087d2acf98901113213ab`. Its saved probe records **257.03 s** on the session path, with partial progress and `warm_kept=true`. Two salvage results finish during that interval. This proves overlapping background activity, but the historical record lacks queue/header/check splits, so CPU contention versus queueing cannot be isolated. It does show that Python filing alone does not explain this outlier.

## v8c: latest substantial cohort

{v8c}

Fiberwise's last-trace-to-ledger tail is **1,835.19 s / 30.59 min**. After the last trace, salvage completes at +197.96, +423.60, +659.87, and +810.71 seconds; a full result arrives at +565.49; step goals at +862.44; the closing-drain event at +903.05; golf at +1,571.50; and two cold verifications at +1,701.02 and +1,835.19. The golf record itself reports 642.98 s.

Interleaved's tail is **1,227.81 s / 20.46 min**. Its full result arrives at +34.02, salvage at +263.83, closing-drain event at +475.82, golf at +1,093.76, and cold verification at +1,227.81. Golf reports 617.91 s.

Those two runs account for **88.0%** of the v8c tail. Their `closing_drain.seconds` values are only 0.23 and 0.25 seconds. The recorded timer therefore does not account for the much longer period before the drain event. Missing historical phase boundaries prevent an exact split among background shutdown, locks, and other finalizer work. The observed salvage completions are retained as evidence rather than filling that gap with an invented duration.

Historical v8b/v8c golf records total **29.62 min**, of which v8c contributes **27.23 min**. Automatic post-run golf is already disabled in the current working-tree runner; these historical runs predate that change. The data does not measure current-code savings, and some golfing changed candidates, so this is not an equal-proof speed comparison. Preserve cold acceptance on every pin.

## Theorem distribution across all runs

Different theorem/model sample counts and budgets make this a workload inventory, not a theorem difficulty ranking. Full exact theorem names are in the CSV/JSON.

{theorems}

## Optimization order and acceptance evidence

1. **Reduce unnecessary model round trips in model-bound cohorts.** Test batched context requests and reduced tool-turn reasoning on the same rows, budgets, and pinned models. The measured target is 35.14 run-hours of LLM time, including 7.23 h attached to context-only turns. A hypothetical 10% reduction in matched LLM latency saves at most 3.51 run-hours, or 7.8% of the recorded total, before interaction effects. Require equivalent proof coverage and final cold acceptance; quality loss is not a speed improvement.
2. **Re-measure heavy-row finalization on current code.** Fiberwise and Interleaved carry a combined 51.05 min post-interaction tail in v8c. Keep the existing golf removal, cooperative salvage yield, checker shutdown, demand-driven allocation, and memory-admission fixes. Use explicit phase/lock events on the next bounded replay to distinguish shutdown wait, drain wait, active salvage, and cold checks. Preserve all-version cold checks and report changed proof choices separately.
3. **Target Lean-backed compile and worker contention before cheap bookkeeping.** Compile dominates tool time; the 259.6-second outlier is almost entirely in its recorded session call. Capture queue/header/check fields under representative foreground/background and multi-pin load before choosing a larger worker pool. More resident workers can trade queue wait for memory pressure. The earlier [worker report](HEAVY_WORKER_CONTENTION_2026-10-17.md) has only single-pin model-lane contention coverage.
4. **Investigate goal queries on otherwise fast rows.** Core's v8c foreground tool union is 190.58 s; its eight goal calls accumulate 114.44 s even though its summary compile p95 is 0.38 s. Time LSP goal queries and surrounding locks/formatting explicitly; compilation percentiles alone miss this latency.
5. **Instrument outer boundaries and waits.** Persist process launch/exit, cold verification, background cancellation/join, candidate/Lean/autocheck lock waits, and setup stages. Complete every request with an outcome or a clearly censored status. Then reproduce this report with monotonic duration fields and wall timestamps used only for joining intervals. This is measurement work, not a reason to bypass validation gates.

## Source map and validation

- [Request and tool lifecycle capture](../../packages/arena-pi/extensions/arena.ts): `before_provider_request`, `after_provider_response`, `message_end`, `tool_execution_start/end`; timestamps are `Date.now()` milliseconds.
- [Runner lifecycle](../../arena/cli/run.py): setup, health gate, Pi launch, closing drain, summary/submission. Current phase instrumentation is newer than this saved corpus.
- [Health gate](../../arena/lean_health.py): `started`, `finished`, `wall_seconds` and per-pin reference checks.
- [Evaluation and cold checks](../../arena/engine.py), [campaign recording and background jobs](../../arena/campaign.py): exact-proof result reuse, serial pin loops, and nested durations.
- Representative raw evidence: `runs/pi-budget/v8c-Core.InitsUpdatesComm-gpt-6.1-sol-r1/trace-journal.jsonl`, and the Fiberwise/Interleaved v8c ledgers named above. The JSON manifest hashes every consumed input artifact.

The scanner checks interval merging, intersection, and gap handling with overlapping synthetic intervals, then asserts per-run partition conservation on the corpus. All 66 run files parsed without a malformed JSON row. An independent raw-ID join reproduced all 6,111 matched requests; the seeded-history and synthetic-response exclusions were checked separately.

The HTML passed local Chromium checks for desktop/mobile rendering, all 66 rows, family filters and KPI updates, search, sorting, timeline drill-down, and zero JavaScript errors or page network requests. [verify_html.py](../../tools/audits/run-timing-2026-10-18/verify_html.py) uses Playwright installed through `uv`; run it with `uv run --no-project --python .venv/bin/python --with playwright python tools/audits/run-timing-2026-10-18/verify_html.py`. The browser executable is a pre-existing local Chromium cache. Playwright installation downloaded dependencies from PyPI; the audit scanner and generated report use only local data. Scoped Ruff and inline JavaScript syntax checks passed.

No Lean, provider inference, or benchmark campaign was invoked. This audit does not verify a new runtime speedup.
"""
    (ROOT / "docs/reports/V7_V8_TIMING_2026-10-18.md").write_text(output)


if __name__ == "__main__":
    main()
