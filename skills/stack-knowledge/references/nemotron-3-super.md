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

## Cache Scaling

Standard transformer scaling. A 128k context window requires ~30GB - 40GB of overhead to prevent OOM during peak reasoning thinking. For SGLang on a single GB10 (121GB), a `max_model_len` of 262,144 combined with a static memory fraction of `0.85` successfully loads the 120B NVFP4 weights and allocates ~33GB for the KV cache.
