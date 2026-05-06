# Gemma-4 (Google / NVIDIA)

## Optimization Strategy

Native Blackwell (SM 12.1) optimization is required for stable 131k context.

- **Mandatory ID**: `nvidia/Gemma-4-31B-it-NVFP4` (Base BF16 is too large for the 108GB aggregate budget).
- **Backend**: `--attention-backend TRITON_ATTN` (Required due to heterogeneous head dimensions: `head_dim=256, global_head_dim=512`).
- **KV Cache**: `--kv-cache-dtype auto` MUST be used. Do NOT use `bf16` or `bfloat16`. Using bfloat16 with NVFP4 models under the Triton backend causes a fatal `AssertionError: unsupported kv_cache_dtype`. Setting it to `auto` safely falls back to `fp8_e4m3`.
- **Tool Calling**: Requires `--enable-auto-tool-choice` and `--tool-call-parser gemma4` for stable reasoning-loop transitions.

## VRAM Calculation (NVFP4)

- **Weights**: ~31 GB.
- **KV Cache**: ~12 GB (at 131,072 max_model_len).
- **Usable Budget**: Target 0.80 utilization (~96GB usability) to stay safe within the 108GB Docker aggregate.

## Known Quirks

- **First Warmup**: The first few reasoning requests after loading may take up to 30s to compile Triton kernels.
- **Tool Schema**: Gemma-4 is sensitive to schema descriptions; keep them concise to prevent the model from drifting into "thought loops."
