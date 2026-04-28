# Nemotron-3

## Nemotron-3 Super

### SGLang Specifics (Recommended for Blackwell)

> **⚠️ TEMPORARY QUIRKS - HOW TO INVALIDATE (April 2026)**
> The constraints below are workarounds for upstream bugs in SGLang `v0.5.x`. When provisioning this model on a newer SGLang release, an agent MUST proactively attempt to invalidate these constraints by doing a dry-run without them:
>
> 1. **Graph Capture Hangs:** Remove `--disable-cuda-graph` and `--disable-piecewise-cuda-graph`. If the model successfully finishes "Capture piecewise CUDA graph" without crashing or hanging, the FlashInfer JIT bug is resolved. Remove these flags.
> 1. **Mamba Speculation Crash:** Re-enable `--speculative-algo EAGLE3`. If the server boots without throwing `NotImplementedError: Pattern char 'M'` in `nemotron_h_mtp.py`, SGLang has added Mamba parsing support. Remove this restriction and restore speculation.

- **Image Requirements**: Requires SGLang nightly (`lmsysorg/sglang:nightly-dev-cu13-20260401-b6fe0cca` or newer). Older versions contain a tensor shape mismatch bug during NVFP4 MoE loading.
- **Dependencies**: `modelopt_fp4` quantization requires `accelerate`.
- **Graph Capture Crashes**: The FlashInfer JIT compiler crashes during graph capture on Blackwell. You MUST use `--disable-cuda-graph` and `--disable-piecewise-cuda-graph`.
- **Speculative Decoding Bug**: SGLang's MTP parser currently does NOT support Mamba layers (`Pattern char 'M'`). Do NOT use `--speculative-algo` with Nemotron hybrid models on SGLang.
- **Radix Cache Conflict**: You MUST use `--disable-radix-cache`.
- **Flags**: Set `export SGLANG_USE_FLASHINFER_MOE_FP4=1` in the environment.

### vLLM Specifics

- **Image Requirements**: Native NVFP4 models currently require `ghcr.io/spark-arena/dgx-vllm-eugr-nightly:latest` to correctly leverage Spark-Arena DGX configurations. The stable `nvcr.io/nvidia/vllm:latest` image will fail to parse the `MIXED_PRECISION` config or lack Spark optimizations.
- **Entrypoint**: Use `sh -c` for the command execution.
- **`--attention-backend TRITON_ATTN`**: Required for NVFP4 precision execution on Blackwell GPUs.
- **`--max-num-seqs 512`**: Increased sequence cap to utilize available throughput capabilities.
- **Reasoning Parsers**: vLLM natively supports the Nemotron-3 format. Use `--reasoning-parser nemotron_v3` (Do NOT attempt to use the outdated `super_v3_reasoning_parser.py` plugin).
- **Tool Calling Parsers**: You must specify `--enable-auto-tool-choice` and `--tool-call-parser qwen3_coder` so vLLM can properly convert the model outputs to OpenAI format.

### Speculative Decoding (vLLM)

> [!WARNING]
> **EAGLE-5 with Nano-30B draft model is INCOMPATIBLE** (confirmed April 2026).
> The `NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` model fails as a draft model with `AssertionError: param_data.shape == loaded_weight.shape` during weight loading. The Nano-30B QKV projections do not match the 120B base model's expected tensor shapes for the `draft_model` code path.
> Additionally, `parallel_drafting: true` crashes because the Nano-30B `config.json` lacks `pard_token` / `ptd_token_id` fields.

- **Working configuration**: Use `ngram` speculative decoding with `--enforce-eager`:
  ```
  --speculative-config '{"model":"[ngram]","num_speculative_tokens":5}' \
  --enforce-eager
  ```
  This requires no external draft model, works with any architecture, and provides modest throughput improvement.
  - `--enforce-eager` is **required** on Blackwell to avoid a Triton JIT crash in the Mamba mixer2 `selective_state_update` kernel (`RuntimeError: Triton Error [CUDA]: an illegal memory access`).
- **Nano-4B draft models** (`NVIDIA-Nemotron-3-Nano-4B-FP8` / `BF16`): Untested as of April 2026. May have the same architecture mismatch as the 30B variant.
- **Native integrated EAGLE heads**: The NVFP4 checkpoint does not appear to expose integrated EAGLE/MTP heads that vLLM can auto-detect.

### Critical vLLM Flag Interactions

> [!CAUTION]
> **`--disable-log-stats` + OTel Tracing = INSTANT CRASH on first inference.**
> When `--disable-log-stats` is set, vLLM creates `RequestState` with `stats = None`. But when OTel tracing is enabled (via `--otlp-traces-endpoint`), the `do_tracing()` method in `output_processor.py` asserts `req_state.stats is not None` — causing an `AssertionError` on the first completed request. The server starts and appears healthy, but dies immediately on the first inference call. **Never use `--disable-log-stats` when OTel tracing is active.**

> [!WARNING]
> **`--enforce-eager` is required for Nemotron-H on Blackwell.**
> Without it, the Triton JIT compiler crashes during CUDA graph capture of the Mamba mixer2 kernel. The model loads weights (72GB+) successfully but crashes at the compilation/profiling stage. This wastes ~7 minutes per failed attempt.

## Cache Scaling

Standard transformer scaling. A 128k context window requires ~30GB - 40GB of overhead to prevent OOM during peak reasoning thinking. For SGLang on a single GB10 (121GB), a `max_model_len` of 262,144 combined with a static memory fraction of `0.85` successfully loads the 120B NVFP4 weights and allocates ~33GB for the KV cache.
