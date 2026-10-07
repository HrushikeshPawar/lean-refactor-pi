# 08: Integrated evaluation and manual submission package

**What to build:** An operator can run v6 across different pinned theorem families, compare replicated results, and hand the user a complete, locally checked first warm-up submission package made only from v6 model-produced proofs.

**Blocked by:** 07: Ideas, finish and run accounting.

**Status:** ready-for-agent

- [ ] Run the full campaign path on at least Core and PhysLib with certified packets, tool round trips, a cheap live Langfuse preflight, complete exact traces, local Lean checks and the stable request gate. An absent mandatory observation or packet section stops evaluation before paid runs.
- [ ] Compare at least two theorem rows and use three sequential replicates per configuration before claiming a score gain. Report score distribution, helper discovery, truly unattempted ideas, preventable tool errors, cache outcomes, corrected bookkeeping plus rejected spend and all-call per-problem cost. The targets are zero preventable tool errors and under 5% combined overhead.
- [ ] Select only complete, locally verified, model-produced v6 candidates. No v5 proof, analyst-combined hybrid, incomplete proof or unverifiable provenance enters the submission set.
- [ ] Produce and validate warm-up proof JSONL with exact benchmark identifiers, full declarations and prohibited-construct checks. Recompute each proof hash and join it to candidate/run IDs, pinned source/toolchains, model/provider/version, Langfuse trace identities and **every** charged API attempt, including retries and discarded candidates.
- [ ] Enforce the closed-track $3 per-problem ceiling and confirm eligibility of each actually used model. Prepare a code archive with top-level reproduction instructions and pinned dependencies, plus the official-template report containing Approach, Models, Budget accounting and Reproduction with the actual run data.
- [ ] Stage the final proof JSONL, provenance, archive and report for the user's manual Hugging Face and OpenReview actions. Do not upload or submit automatically. Record local checks and leave the official worker result as the final calibration after the user uploads.

