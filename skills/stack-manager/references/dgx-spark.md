# DGX Spark Hardware Guide (Blackwell Memory Tuning Guide (March 2026))

Technical reference for calculating VRAM requirements on the NVIDIA DGX Spark (128GB Unified Memory).

## 1. Weight Sizing (Precision Matters)

Blackwell is optimized for 4-bit and 8-bit native inference. Using higher precision (BF16) is discouraged as it doubles the memory footprint with minimal gain.

| Precision         | Multiplier | Calculation                        |
| :---------------- | :--------- | :--------------------------------- |
| **NVFP4 (4-bit)** | **0.5x**   | `Parameters (B) * 0.5 = VRAM (GB)` |
| **FP8 (8-bit)**   | **1.0x**   | `Parameters (B) * 1.0 = VRAM (GB)` |
| **BF16 (16-bit)** | **2.0x**   | `Parameters (B) * 2.0 = VRAM (GB)` |

### Example: Nemotron Super 49B

- **NVFP4:** `49 * 0.5 = 24.5 GB`
- **FP8:** `49 * 1.0 = 49.0 GB`

## 2. KV Cache Scaling

KV cache consumption depends on the model architecture (Attention Heads) and the requested context window.

## 3. Safe Harbor Distribution (108GB Budget)

To prevent DGX OS hangs, the aggregate limit for all Docker containers must not exceed **108GB**.

### Example Distribution:

For a high-context setup:

- **Main (Powerhouse):** 80GB Limit.
- **Researcher (Coding):** 28GB Limit.
- **Total:** 108GB.

## 4. vLLM Configuration Flags

Use `--gpu-memory-utilization` to control the pre-allocation size.

- Formula: `Target Memory (GB) / 128 (Total GB) = Utilization Value`.
- Example for 51GB: `51 / 128 = 0.40`.

## 6. The "Blackwell Laws" (Stability Guardrails)

Critical operational constraints identified for the NVIDIA Spark (GB10) on the March 2026 driver/vLLM stack:

### A. The "FastSafe" Trap

**NEVER** use `--load-format fastsafetensors`. This causes persistent 0% loading hangs on the SM 12.1 driver stack. Use `auto` or omit the flag.

### B. The "NVFP4" Mandate

For models >30B parameters, **NVFP4 (4-bit native)** is mandatory. Standard BF16 models (60GB+) often trigger host memory pressure during the initial weight-shuffling phase, even if they technically fit in the 108GB aggregate budget.

### C. The "Zombie" Protocol

Orphaned `VLLM::EngineCore` processes can survive container removal (`docker rm -f`). If loading is slow or RAM is squatting, a manual purge is required:
`pkill -u $USER -9 -f "VLLM|sparkrun|vllm"`

### D. Attention Backends

For models with heterogeneous head dimensions (e.g., Gemma-4), use **`--attention-backend TRITON_ATTN`** for numerical stability and kernel compatibility.
