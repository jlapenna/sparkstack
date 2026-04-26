# Qwen 3.5 / Qwen3 Coder Next (Hybrid Gated DeltaNet/MoE)

> [!WARNING]
> **STATUS: DEPRECATED (April 2026)**
> These models have been observed to "fall in on themselves" when processing long context or complex reasoning tasks on Blackwell hardware.
> **Observed Symptom**: Infinite repetitive looping ("linkage bridge link tie bond attachment...").
> Avoid using these in the primary stack in favor of Gemma-4.

## Architecture-Specific Tuning

- **`--mamba-cache-mode align`**: Required for efficient prefix caching.
- **`--mamba-block-size 8`**: Typical default requirement for optimal performance in vLLM hybrid kernels.

## Cache Scaling

Extremely efficient. KV cache scaling is nearly flat. A 1M context window requires significantly less overhead than traditional transformer architectures, allowing massive context windows (up to 1,048,576) on Blackwell hardware while maintaining acceptable VRAM budgets.
