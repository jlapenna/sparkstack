# Plan: Deploy Qwen3.6-35B NVFP4 Blackwell Stack

**Objective**: Deploy the Qwen3.6-35B-A3B model using native NVFP4 quantization for maximum Blackwell throughput and 262K context window.
**Target Date**: 2026-04-17
**Target Stack Name**: `qwen3.6-35b-nvfp4-20260417-01`

______________________________________________________________________

## 0. Quirk Invalidation (MANDATORY PRE-FLIGHT)

- **Quirk Investigated**: MTP (Multi-Token Prediction) stability on Qwen3.6 NVFP4.
- **Web Research Summary**: MTP is natively supported in the Qwen3.6 series and is highly recommended for Blackwell (GDDR7) systems to saturate memory bandwidth. Using `FLASHINFER` is mandatory for optimal hybrid DeltaNet/Attention kernel performance.
- **Invalidation Test**: VRAM Simulation + vLLM 0.12.0 compatibility check.
- **Result**: Validated.

______________________________________________________________________

## 1. Hardware & Resource Budget (Verification of Constraints)

- **Main Model (`qwen3.6-35b-nvfp4-vllm`)**: 80GB RAM Limit, ~25GB VRAM (Weights + KV).
- **Embedding Model (`bge-m3`)**: 4GB RAM Limit, ~2GB VRAM.
- **Overhead (LiteLLM/Gateway)**: 8GB RAM Limit.
- **Aggregate Totals**: **92GB RAM** (Passed: < 108GB limit).
- **GPU Utilization**: ~0.30 (Passed: < 0.90 limit).

______________________________________________________________________

## 2. Detailed Implementation Phases

### Phase 1: Model Registration (Registry Layer)

- Create `registry/models/qwen3.6-35b-nvfp4-vllm.yaml` pointing to `RedHatAI/Qwen3.6-35B-A3B-NVFP4`. (COMPLETED)

### Phase 2: Infrastructure Patching (Tooling Layer)

- Verify `build_stack.py` and `scripts/detect_api.py` are operational. (COMPLETED)

### Phase 3: Stack Orchestration (Building Layer)

- Run `uv run python scripts/build_stack.py qwen3.6-35b-nvfp4-20260417-01 main=qwen3.6-35b-nvfp4-vllm embedding=bge-m3`.

### Phase 4: Activation & Synchronization (Deployment Layer)

1. **Shutdown**: `docker rm -f $(docker ps -a -q -f "name=sparkrun|vllm")`.
1. **Launch**: Execute `stacks/qwen3.6-35b-nvfp4-20260417-01/launch.sh`.
1. **Sync**: `~/bin/oc config set` to update model names and context windows.

### Phase 5: OpenClaw / Application Configuration

- Update OpenClaw config to reflect the new model IDs and 262K context.
- **Fix**: Set `thinkingFormat: qwen` and `requiresAssistantAfterToolResult: true` to resolve ordering conflicts.
- **Fix**: Add `litellm_overrides` with Qwen-specific stop tokens.

______________________________________________________________________

## 3. Mandatory E2E Verification Suite

- `uv run python -m scripts.verify --stack qwen3.6-35b-nvfp4-20260417-01`

______________________________________________________________________

## 4. Formal Benchmarking

- `uv run sparkrun benchmark main --skip-run -b served_model_name=main`

______________________________________________________________________

## 5. Failure Recovery Protocol

If initialization fails (OOM or kernel crash), revert to `verify-expansion-20260412-01`.

______________________________________________________________________

## 6. Mandatory Proof of Execution (Receipts)

(To be populated during Phase 4-6)

______________________________________________________________________

## 7. Finalization (Cleanup)

- `uv run python scripts/set_current.py stacks/qwen3.6-35b-nvfp4-20260417-01`
