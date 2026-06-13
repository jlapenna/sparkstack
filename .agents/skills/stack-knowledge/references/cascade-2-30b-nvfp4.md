# Cascade-2-30B-A3B-NVFP4

## Specifics (Recommended for Blackwell)

- **Architecture**: 52 layers, 2 KV heads, 128 head_dim.
- **Engine**: vLLM is the primary tested engine for this format.
- **Quantization Format**: Native `nvfp4` weights with `fp8` KV cache (`--kv-cache-dtype fp8`).
- **Attention Backend**: FlashInfer/Cutlass is utilized.
- **Load Format**: `--load-format fastsafetensors` has been successfully verified without triggering the older 0% loading hang on Blackwell.
- **Context Window**: Default configuration is `262,144` with prefix caching enabled.

### Performance Observations (April 2026)

- **VRAM Footprint**: ~24.51 GB total for model + KV cache. Fits easily on a single DGX node.
- **Throughput**: ~58-60 Tokens/sec under single concurrency.
- **TTFT**: ~640ms.
