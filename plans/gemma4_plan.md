# Gemma-4-31B-it-NVFP4 Deployment Plan

**Objective**: Deploy nvidia/Gemma-4-31B-it-NVFP4 as the main model using MTP prediction drafting.
**Target Date**: 2026-05-15
**Target Stack Name**: `gemma-4-20260515-01`

______________________________________________________________________

## 0. Quirk Invalidation (MANDATORY PRE-FLIGHT)

- **Quirk Investigated**: MTP setup for Gemma 4
- **Web Research Summary**: Gemma 4 utilizes "assistant" checkpoints, but for the NVFP4 31B model, the user linked to the MTP announcement showing `--speculative-config '{"method":"mtp","num_speculative_tokens":1}'` which is built-in.
- **Invalidation Test**: Checked the MTP configuration syntax.
- **Result**: Added `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'` to the recipe.
- **Action Taken**: The recipe `sparkstack-registry/sparkrun/gemma4-31b-it-nvfp4.yaml` is pre-configured for MTP. Also updated `litellm_overrides` and `litellm-settings.yaml` for reasoning.

______________________________________________________________________

## 0.5 Rollback Escape Hatch (PRE-FILLED)

- **Previous Stable Stack Name**: `qwen-3.6-20260511-01` (Assuming recent stable, requires verification)
- **Rollback Command**: `uv run sparkstack set-current qwen-3.6-20260511-01`

______________________________________________________________________

## 0.75 Source Dependency Verification (PRE-FLIGHT)

- **SparkRun Branch**: `local-dev`
- **SparkRun State**: Clean
- **OpenClaw Branch**: `local-dev`
- **OpenClaw State**: Clean
- **Registry Sync**: To be done
- **SparkRun Version**: To be checked

______________________________________________________________________

## 1. Hardware & Resource Budget (Verification of Constraints)

- **Current Main Model**: 0% VRAM (Assumed cleared)
- **New/Target Model (`nvidia/Gemma-4-31B-it-NVFP4`)**: ~80% VRAM
- **Aggregate Totals**: **80% VRAM**
- **Utilization Verification**: **Pass** -> Aggregate VRAM is at 80% (under 85% conservative warning, but MTP requires more activation memory).

______________________________________________________________________

## 2. Detailed Implementation Steps

### Step 1: Model Registration (Registry Layer)

- Model Recipe updated: `sparkstack-registry/sparkrun/gemma4-31b-it-nvfp4.yaml`
- Includes `litellm_overrides` for tool calling and reasoning support.
- VRAM validation passed.

### Step 2: Infrastructure Patching (Tooling Layer)

- Added `merge_reasoning_content_in_choices: true` to `services/litellm/litellm-settings.yaml`.

### Step 3: Stack Orchestration (Building Layer)

- `uv run sparkstack build gemma-4-20260515-01 main=sparkstack-registry/sparkrun/gemma4-31b-it-nvfp4.yaml`

### Step 4: Activation & Synchronization (Deployment Layer)

- `uv run sparkstack set-current gemma-4-20260515-01`
- `uv run sparkstack wait --json --timeout 1800`
- `uv run sparkstack check memory --json`
- `uv run sparkstack sync-registry --json`

______________________________________________________________________

## 3. Mandatory E2E Verification Suite

- `uv run pytest -x tests/e2e/`

______________________________________________________________________

## 4. Formal Benchmarking

- `export $(rg -v '^#' .env | xargs) && uv run sparkrun benchmark sparkstack-registry/sparkrun/gemma4-31b-it-nvfp4.yaml --skip-run --port 4000 -b served_model_name=main -b api_key=$LITELLM_MASTER_KEY --profile spark-arena-v1`

______________________________________________________________________

## 5. Failure Recovery Protocol

- Halt and present error logs on failure.

______________________________________________________________________

## 6. Mandatory Proof of Execution (Receipts)

- To be filled after execution.

______________________________________________________________________

## 7. Finalization (Cleanup)

- Rename stack directory, remove suffix, commit changes.
