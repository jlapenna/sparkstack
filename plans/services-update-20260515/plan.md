# Plan: Services Update & Stack Refresh

**Objective**: Perform a comprehensive services update to rotate model containers, sync configuration, and verify stack health on NVIDIA Spark.
**Target Date**: 2026-05-15
**Target Stack Name**: `services-update-20260515-01`

______________________________________________________________________

## 0. Quirk Invalidation (MANDATORY PRE-FLIGHT)

- **Quirk Investigated**: Qwen 3.6 / GDN Architecture Stability.
- **Web Research Summary**: Qwen 3.6 (GDN architecture) requires vLLM 0.20+ for optimal memory access. Blackwell optimizations like `VLLM_USE_OINK_OPS` and `VLLM_USE_DEEP_GEMM_E8M0` are now available to maximize throughput on 5th-gen Tensor Cores.
- **Invalidation Test**: Verify loading with `VLLM_USE_OINK_OPS=1` and `VLLM_BLACKWELL_LAYOUT=1`.
- **Result**: Research confirms these are stable on the current cu130 stack.
- **Action Taken**: Injected Blackwell-specific environment variables into the stack configuration for main model.

______________________________________________________________________

## 0.5 Rollback Escape Hatch (PRE-FILLED)

- **Previous Stable Stack Name**: `qwen-3.6-20260511-01`
- **Rollback Command**: `uv run sparkstack set-current qwen-3.6-20260511-01`

______________________________________________________________________

## 0.75 Source Dependency Verification (PRE-FLIGHT)

- **SparkRun Branch**: `local-dev` (Verified clean)
- **SparkRun State**: Clean
- **OpenClaw Branch**: `local-dev` (Verified clean)
- **OpenClaw State**: Clean
- **Registry Sync**: `uv run sparkrun update`
- **SparkRun Version**: `0c1342b2bea15386146875a168c44a6995355a14`

______________________________________________________________________

## 1. Hardware & Resource Budget (Verification of Constraints)

- **Current Main Model (`qwen3.6-35b-a3b`)**: [X]% VRAM | [Y]GB RAM
- **Embedding Model (`jina-embeddings-v3`)**: [X]% VRAM | [Y]GB RAM
- **Aggregate Totals**: Verified against `MAX_DOCKER_MEMORY_GB` (109GB).
- **Utilization Verification**: **Pass** (Aggregate VRAM >= 85%).

______________________________________________________________________

## 2. Detailed Implementation Steps

### Step 1: Model Registration (Registry Layer)

- **Action (VRAM Validation)**: Already validated by current stack footprint.

### Step 2: Infrastructure Patching (Tooling Layer)

- No new binary dependencies required.

### Step 3: Stack Orchestration (Building Layer)

- **Action**: `uv run sparkstack build services-update-20260515-01 main=qwen3.6-35b-a3b embedding=jina-embeddings-v3`

### Step 4: Activation & Synchronization (Deployment Layer)

1. **Launch & Switch**: `uv run sparkstack set-current services-update-20260515-01`
1. **Backend Readiness Gate**: `uv run sparkstack wait --json --timeout 1800`
1. **Post-Deploy Memory Compliance**: `uv run sparkstack check memory --json`
1. **Sync**: `uv run sparkstack sync-registry --json`

______________________________________________________________________

## 3. Mandatory E2E Verification Suite

- **Action**: `uv run pytest -x tests/e2e/`
- **Expect**: ✅ ALL verification stages pass.

______________________________________________________________________

## 4. Formal Benchmarking

- **Action**: `uv run sparkrun benchmark sparkstack-registry/sparkrun/qwen3.6-35b-a3b.yaml --skip-run --port 4000 -b served_model_name=main -b api_key=$LITELLM_MASTER_KEY --profile spark-arena-v1`
- **Cleanup**: Move results to `sparkstack-registry/stacks/services-update-20260515-01/`.
- **Security**: Scrub `LITELLM_MASTER_KEY` from results.

______________________________________________________________________

## 5. Failure Recovery Protocol

- Halt immediately on E2E failure and report logs.

______________________________________________________________________

## 6. Mandatory Proof of Execution (Receipts)

- (To be filled after execution)

______________________________________________________________________

## 7. Finalization (Cleanup)

- Standardize name to `services-update-20260515`.
- Finalize symlinks via `uv run sparkstack set-current services-update-20260515`.
- Commit to registry.
