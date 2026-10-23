# Modal + Qwen 27B open-source track runbook (research, 2026-10-23)

Nothing was deployed; no Modal credits spent.

## 5. CLI check (local, read-only)
- `modal --version` -> `modal client version: 1.6.2`
- `modal profile current` -> `hrushikeshpawar96` (workspace hrushikeshpawar96; authenticated profile exists). Auth validity against the server was not exercised (that would need an API call); profile is configured.

## 1. Modal vLLM serving
Source: https://modal.com/docs/examples/vllm_inference (repo: github.com/modal-labs/modal-examples, 06_gpu_and_ml/llm-serving/vllm_inference.py). Page values as fetched:
- Image: `modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12").entrypoint([])` then `.uv_pip_install("vllm==0.21.0")`. Docs for vLLM up to v0.29 exist, so the example pin is stale; pick a recent version that supports Qwen3.8 (UNVERIFIED which minimum; Qwen3.5/3.6 recipes need a recent vLLM).
- Weight caching: two Volumes mounted at `/root/.cache/huggingface` (`huggingface-cache`) and `/root/.cache/vllm` (`vllm-cache`), both `modal.Volume.from_name(..., create_if_missing=True)`. Pre-download weights once with a small CPU function (`huggingface_hub.snapshot_download`) to avoid paying GPU seconds.
- GPU syntax: `gpu="A100-80GB"` / `gpu="A100-80GB:2"` / `gpu=f"H200:{N_GPU}"`.
- Idle: `scaledown_window=15 * MINUTES` in the example; set 2-5 min for us. Use `min_containers=0`, `max_containers=1`, `timeout` bounded. Serve via `@modal.web_server(port=8000, startup_timeout=...)` with `subprocess.Popen(["vllm","serve",MODEL,"--served-model-name","llm",...])`, `@modal.concurrent(max_inputs=N)`.
- Cold start: example has `--enforce-eager` toggle (fast boot, slower decode) vs torch.compile + CUDA graphs cached in vllm-cache volume. Memory snapshots: https://modal.com/docs/guide/memory-snapshot : `enable_memory_snapshot=True` (only for deployed Apps), GPU snapshot is alpha via `experimental_options={"enable_gpu_snapshot": True}` with `@modal.enter(snap=True)`; multi-GPU and storage model loading benefit poorly. Skip snapshots for a 2 h test.
- Note: `modal serve` gives a temporary URL but you said not to run it now; `modal deploy` needed for stable URL. Auth: put `--api-key` on vllm or use `requires_proxy_auth=True` on web_server so the public URL is not open.

## 2. Kernels / quantization (A100 vs H100)
Mostly from general vLLM knowledge; official pages not confirmed here -> UNVERIFIED unless noted.
- Attention: A100 (sm80) uses FlashAttention-2 (FA3 is Hopper only; FA4 Blackwell). Qwen3.8 is hybrid: per model card 16 x (3 Gated DeltaNet + 1 gated attention), so only 16 layers use full attention; DeltaNet uses fla/triton kernels (works on Ampere, UNVERIFIED speed).
- FP8: A100 has no FP8 tensor cores; vLLM falls back to weight-only FP8 via Marlin (W8A16), giving memory savings but not compute speedup (UNVERIFIED for this model; docs redirect to docs.vllm.ai/en/latest/features/quantization/llm_compressor/fp8/). Official `Qwen/Qwen3.8-27B-FP8` exists (block size 128 fine-grained FP8, https://huggingface.co/Qwen/Qwen3.8-27B-FP8). Block-wise FP8 on Ampere via Marlin: UNVERIFIED that it works for this architecture.
- int4: AWQ/GPTQ Marlin kernels are well supported on Ampere. No official Qwen int4 seen; community quants exist (model card lists 1,500+). Quality unknown; prefer official FP8 first.
- KV sizing (computed from model card): 16 attn layers x 4 KV heads x 256 dim x 2 (K,V) x 2 B (bf16) = 64 KiB/token -> ~8 GiB at 128K, ~16 GiB at 256K per sequence. DeltaNet state is small and constant. So context is cheap.
- Fit: BF16 weights ~54 GB; on 1xA100-80GB leaves ~15 GB after overhead = one 128K seq, tight. FP8 (~28 GB) on 1xA100-80 gives ~35+ GB KV = several 128K seqs. BF16 TP=2 (2xA100-80, ~$5/h) is the no-quant-risk option. Use `--language-model-only` to skip vision encoder (from vLLM Qwen3.5/3.6 recipe, https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html).
- MTP speculative decoding: `--speculative-config '{"method":"mtp","num_speculative_tokens":1}'` is recommended in the Qwen3.6 recipe for latency; unverified for Qwen3.8 on A100.

## 3. Qwen model specifics
Source: https://huggingface.co/Qwen/Qwen3.8-27B (exists; fetched). Note: a generic web search found only Qwen3.6-27B (April 2026) and no mention of 3.8, but the HF page fetch succeeded, so 3.8 is real per the card. Newer than 3.8: none found (not exhaustively searched).
- HF id `Qwen/Qwen3.8-27B` (BF16), `Qwen/Qwen3.8-27B-FP8`. 27B causal LM with vision encoder, 64 layers, hidden 5120, MTP trained.
- Context 262,144 native; YaRN to 1M needs `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` + `--hf-overrides` (not needed for us; hurts short text).
- Thinking on by default. Off: `chat_template_kwargs: {"enable_thinking": false}`. `reasoning_effort` in {xhigh (default), medium, low}. `preserve_thinking` default on (keeps thinking of prior turns; set false to keep only latest user turn's thinking, which saves context in long agent traces).
- Sampling: thinking: temp 1.0, top_p 0.95, top_k 20, min_p 0, presence_penalty 0, repetition_penalty 1.0. Non-thinking: temp 0.7, top_p 0.8, top_k 20, presence_penalty 1.5.
- vLLM flags: model card gives no parser flags. Qwen3.5/3.6 recipe: `--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder`. Community Qwen3.8 repo (https://huggingface.co/nrrso/Qwen3-Chat-Template-vLLM-Fixes, unofficial) says `qwen3_xml` + `qwen3` reasoning parser, fallback `qwen3_coder` on older vLLM; reasoning parser required because template pre-fills `<think>`. Which tool parser is right for 3.8: UNVERIFIED; test both in the replay (qwen3_xml uses tool JSON schemas for type coercion, loose schemas give string args).
- Chat template caveats (same community source, unofficial): official template crashes ("Can only get item pairs from a mapping") when clients echo `arguments` as JSON strings (Pi/OpenAI clients do send strings), dangling `<think>` before `<tool_call>` in echoed history, `reasoning_effort: "high"` throws (use xhigh/medium/low), `developer` role not accepted. The community template needs vLLM only. Verify with our recorded traces; consider that template as a candidate.

## 4. Prices (https://modal.com/pricing, per-second x 3600)
| GPU | $/s | $/h |
|---|---|---|
| A100 40GB | 0.000583 | 2.10 |
| A100 80GB | 0.000694 | 2.50 |
| L40S | 0.000542 | 1.95 |
| H100 | 0.001097 | 3.95 |
| H200 | 0.001261 | 4.54 |
| B200 | 0.001736 | 6.25 |
(CPU/memory billed separately, small; excludes the free monthly credit question.)
Costs (GPU only):
- (a) 2 h trace replay: 1xA100-80 FP8 = $5; 2xA100-80 BF16 TP2 = $10; 1xH100 = $7.9. Add ~10-20 min cold starts (first load downloads ~28-54 GB to Volume).
- (b) 1-row 1 h agent run: $2.50 (1 GPU) to $5 (TP2).
- (c) 48 h x 4 xA100-80 = 4 x 2.5 x 48 = $480 (8x our $60). $60 buys about 6 h of 4 GPUs, or 24 h of one. Full rehearsal is not affordable; and a single-GPU 48 h would still be $120.
Budget plan: ~$15 for replay experiments leaves ~$45 for a few agent rows.

## Recommended launch recipe
GPU: 1x A100-80GB, `Qwen/Qwen3.8-27B-FP8`, max-model-len 131072 (fallback: BF16 on `A100-80GB:2`, `--tensor-parallel-size 2`, if FP8 fails on Ampere).
vLLM flags: `--served-model-name llm --max-model-len 131072 --gpu-memory-utilization 0.92 --language-model-only --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder --enable-prefix-caching --max-num-seqs 4` (try `qwen3_xml` second; optionally `--chat-template` from the community fix).

```python
import subprocess, modal
MIN = 60
MODEL = "Qwen/Qwen3.8-27B-FP8"
image = (modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install("vllm", "huggingface_hub[hf_transfer]")  # pin a recent version, UNVERIFIED which
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_ALLOW_LONG_MAX_MODEL_LEN": "0"}))
hf = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vc = modal.Volume.from_name("vllm-cache", create_if_missing=True)
app = modal.App("qwen38-replay")

@app.function(image=image, volumes={"/root/.cache/huggingface": hf}, timeout=30*MIN)
def download():  # CPU-only, run once
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL); hf.commit()

@app.function(image=image, gpu="A100-80GB", timeout=3*60*MIN, scaledown_window=3*MIN,
              min_containers=0, max_containers=1,
              volumes={"/root/.cache/huggingface": hf, "/root/.cache/vllm": vc})
@modal.concurrent(max_inputs=8)
@modal.web_server(port=8000, startup_timeout=15*MIN, requires_proxy_auth=True)
def serve():
    subprocess.Popen(["vllm","serve",MODEL,"--served-model-name","llm",
        "--host","0.0.0.0","--port","8000","--max-model-len","131072",
        "--gpu-memory-utilization","0.92","--language-model-only",
        "--reasoning-parser","qwen3","--enable-auto-tool-choice",
        "--tool-call-parser","qwen3_coder","--enable-prefix-caching","--max-num-seqs","4"])
```
Run order (user does it): `modal run` download once, `modal serve` for the 2 h test (stops when you Ctrl-C; avoid leaving deployed), then stop app with `modal app stop`. Client: base_url = the web URL + /v1, model "llm", temp 1.0/top_p 0.95/top_k 20, ensure `chat_template_kwargs` per request. requires_proxy_auth needs Modal-Key/Modal-Secret headers (create a proxy auth token in the dashboard); drop it if Pi can't send headers and use a vLLM `--api-key` instead.
