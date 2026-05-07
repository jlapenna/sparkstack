# Model Registry

This structure contains the modular definitions for the AI service stack on the **NVIDIA Spark (GB10 Blackwell)** workstation.

## Architecture

The stack is composed using a "Model Registry" pattern:

- **`services/litellm/`**: Global settings for LiteLLM and base Docker Compose network/volumes.
- **`sparkstack-registry/sparkrun/`**: Individual YAML files for each model recipe (LLM or STT).
- **`scripts/build_stack.py`**: Composes these modules into a functional stack under `sparkstack-registry/stacks/`.

## Modern Blackwell Standards (March 2026)

### 1. Base Images

- **NVIDIA Containers**: Use explicit tags from the [NGC Catalog](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm/tags) (e.g., `26.02-py3`). These images are built with the SM 12.1 compiler stack and include Blackwell-native kernels. **NEVER use `:latest`**.
- **Qwen 3.5 Exception**: Use `vllm/vllm-openai:cu130-nightly` for Qwen 3.5 models until the architecture is merged into the stable NVIDIA NGC release.

### 2. Mandatory Environment Variables

Ensure these are present in all vLLM service definitions:

```yaml
- VLLM_ATTENTION_BACKEND=FLASHINFER
- VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8=1
- VLLM_BLACKWELL_LAYOUT=1
- VLLM_BLACKWELL_UMA_OVERLAP=1
- VLLM_USE_DEEP_GEMM=0  # Disabled for stability on some SM 12.1 builds
```

### 3. Precision & Quantization

- **Dtype**: Use `--dtype auto` to let vLLM select the best precision.
- **KV Cache**: Always use `--kv-cache-dtype fp8` to maximize context window capacity on Blackwell.
- **NVFP4**: For Nemotron models, utilize native `NVFP4` checkpoints for maximum throughput.

### 4. Loading & Driver Safety (NEW)

- **Loader Preference**: **NEVER** use `--load-format fastsafetensors` on the current SM 12.1 driver stack. It causes persistent loading hangs at 0%. Use `auto` or omit the flag.
- **Model Selection**: Prefer `nvidia/*-NVFP4` model IDs over base `google/*` or `Qwen/*` IDs. The native FP4 weights are ~30GB (vs 60GB BF16) and are required to fit within the 108GB RAM aggregate while loading.
- **Attention Backend**: For models with heterogeneous head dimensions (like Gemma-4), `TRITON_ATTN` is mandatory for numerical stability.

### `Qwen Model Repetitive Looping`

As of April 2026, several Qwen models (3.5 and 3.6 variants) have been observed to "fall in on themselves" when processing long context or complex reasoning tasks.

- **Observed Symptoms**: The model begins producing highly repetitive, nonsensical strings of words (e.g., "contribute while others don't... linkage bridge link tie bond attachment...").
- **Current Status**: **Deprecated**. These models have been removed from active rotation in the primary stack in favor of Gemma-4.
- **Root Cause Hypothesis**: Likely related to the interaction between Blackwell-native flashinfer kernels and the specific heterogeneous head dimensions or activation patterns of the Qwen architecture in current nightly builds.

## Memory Law

Aggregate Docker memory limits across all services MUST NOT exceed **108GB**.
Aggregate `gpu-memory-utilization` MUST NOT exceed **0.90** (Hard limit 0.95).

### 5. The "Zombie Process" Protocol (NEW)

`docker rm -f` is sometimes insufficient. If model loading hangs or the system reports low memory despite few active containers:

1. **Check for Orphans**: Run `ps aux | grep EngineCore`.
1. **Force Cleanup**: Execute `pkill -u $USER -9 -f "VLLM|sparkrun|vllm"`.
1. **Verify Recovery**: Run `free -h` to ensure available RAM has returned to baseline (~110Gi+).

## Troubleshooting

### `500 litellm.InternalServerError: Cannot connect to host`

If you receive this error when querying the LiteLLM gateway, it indicates that the backend vLLM container (e.g., `nemotron`) has not yet finished loading its model weights into VRAM and has not bound to its port (e.g., `8001+`).

- **Massive Models (120B+):** Models like `NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` can take **7+ minutes** to compile kernels and load weights on a GB10 GPU.
- **Resolution:** Run `docker logs <container_name> -f` and wait for the `Application startup complete` message before interacting with the gateway.
