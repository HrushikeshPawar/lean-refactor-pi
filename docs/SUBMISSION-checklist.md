# Submission checklist (moved from submission/README.md, 2026-10-10)

Kept for the code-archive and report deadlines. `arena submit` (ticket 19) prepares files under `runs/submission/<name>/`; the owner uploads.


Status (historical, written before v6): preparing the first **manual** warm-up submission. The user chose not to
upload v5 proofs. No JSONL in this directory is ready for upload yet.

Official source: https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena (Tracks & Rules and Submit tabs).

## Files to produce from v6 runs

1. `proofs.jsonl`: one JSON object per submitted benchmark row, exactly `{"name": "<benchmark id>",
   "proof": "<full original statement and replacement proof>"}`. Use the best verified model-produced candidate
   from the selected runs. Cross-run hybrids are allowed when disclosed (D13); `arena submit` also writes a no-hybrids file. Every name must match `benchmark/original/warmup.jsonl`;
   proof text must preserve that row's statement and contain no prohibited construct. The Space's upload limit is
   8 MB, and its worker is the final calibration for compilation and score.
2. `provenance.json`: for each row, record the selected run ID, candidate ID, model/provider/version, pinned theorem
   source and toolchains, proof hash, local verification, and **every** API call charged to producing it, including
   retries and discarded candidates. Record public-list-price spend per problem and its maximum; the closed-track
   maximum is $3/problem. Preserve the run's Langfuse trace IDs and local ledger paths. This file supports the
   report and reproduction; upload only the proof JSONL to Submit → Proofs.
3. A single code archive (`.zip` or `.tar.gz`) containing the complete harness, a **top-level README** with exact
   commands to regenerate the submitted JSONL, pinned Lean toolchains and dependency revisions, and configuration
   that identifies every model used. The Space says Submit → Code opens on **November 1, 2026**; prepare the
   archive from the final v6 implementation and upload it under the same username.
4. A technical report in the official competition LaTeX template, submitted to
   https://openreview.net/group?id=NeurIPS.cc/2026/Workshop/VERICODEGEN . Its mandatory sections, in order, are
   **Approach**, **Models**, **Budget accounting**, **Reproduction**. Include all models, providers and versions;
   per-problem cost total/mean/maximum and the full table in an appendix; and the code archive's reproduction
   procedure. The report uses the official `neurips_2026_vericode_workshop_competition.tex` and
   `neurips_2026_vericode_competition.sty` bundle linked on the Space, with a 3–9 page body. Do not use `final`
   or `preprint` options for review. The review is single-blind, so author names belong in the report.

## Manual upload sequence

1. Verify that `proofs.jsonl` and `provenance.json` agree and the per-problem spend stays within the chosen
   track's limit. Record local checks and the matching Langfuse trace IDs.
2. The user uploads `proofs.jsonl` under Submit → Proofs and chooses the eligible track. A first successful
   submission claims the username and shows a key **once**; save that key privately. Later submissions under
   the same name need it and replace the current leaderboard entry.
3. Compare the official worker's theorem-by-theorem result with the local proxy. A subset upload is allowed,
   but unsubmitted benchmark rows score zero in the overall average.
4. Upload the code archive when the Code tab opens, and submit the report to OpenReview by **November 8, 2026**.

Do not assume a hosted model is eligible for a track merely from its brand name: confirm the actual model's
weights/API status first. The closed track explicitly permits arbitrary harnesses but requires disclosure of
every model used; the open track requires public weights and a full run within 48 hours on at most 4× 80 GB A100s.
