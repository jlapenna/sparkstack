# Gemma-4 (Google / NVIDIA)

## Primary Sources

- **Official Recipes**: [vLLM Gemma-4 Recipe](https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html#pip-amd-rocm-mi300x-mi325x-mi350x-mi355x)
- **Draft Model Configuration**: [NVIDIA Dev Forum - Gemma4 Assistant Models](https://forums.developer.nvidia.com/t/how-to-run-the-gemma4-assistant-models-using-eugrs-custom-vllm-fork/370194)

## Optimization Strategy

Native Blackwell (SM 12.1) optimization is required for stable 131k context.

- **Mandatory ID**: `nvidia/Gemma-4-31B-it-NVFP4` (Base BF16 is too large for the 108GB aggregate budget).
- **Backend Environment Variables**:
  We use `FLASHINFER` as our backend instead of TRITON. Key required environment variables for optimal performance on Blackwell hardware are:
  - `VLLM_ATTENTION_BACKEND: FLASHINFER`
  - `VLLM_FLASHINFER_MOE_BACKEND: latency`
  - `VLLM_BLACKWELL_LAYOUT: '1'`
  - `VLLM_BLACKWELL_UMA_OVERLAP: '1'`
  - `VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8: '1'`
  - `VLLM_USE_DEEP_GEMM: '0'`
- **KV Cache**: Use `--kv-cache-dtype fp8` (Avoid `bf16` or `bfloat16` to prevent fatal unsupported `kv_cache_dtype` errors).
- **Tool Calling & Reasoning**: Requires `--enable-auto-tool-choice`, `--tool-call-parser gemma4`, and `--reasoning-parser gemma4` for stable reasoning-loop transitions.
- **Speculative Decoding**: Employs the `google/gemma-4-31B-it-assistant` draft model for speculative decoding acceleration using the `speculative-config` argument (e.g. `{"model": "google/gemma-4-31B-it-assistant", "num_speculative_tokens": 4}`).

## VRAM Calculation (NVFP4)

- **Weights**: ~31 GB.
- **KV Cache**: ~12 GB (at 131,072 max_model_len).
- **Usable Budget**: Target 0.70 utilization (`gpu_memory_utilization: 0.7`) to stay safely within memory bounds alongside speculative models.

## Known Quirks

- **First Warmup**: The first few reasoning requests after loading may take time to compile kernels.
- **Tool Schema**: Gemma-4 is sensitive to schema descriptions; keep them concise to prevent the model from drifting into "thought loops."
