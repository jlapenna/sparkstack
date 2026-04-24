# Template: Model Addition / Upgrade Plan

**Objective**: [Brief description of the model addition or upgrade, e.g., Upgrade main model to Qwen3.5 or Add embedding model]
**Target Date**: [YYYY-MM-DD]
**Target Stack Name**: `[STACK_NAME]-[YYYYMMDD]-[ITERATION]` (e.g., `core-upgrade-20260329-01`)

______________________________________________________________________

## 0. Quirk Invalidation (MANDATORY PRE-FLIGHT)

*Before building a new stack, you MUST check the `skills/stack-manager/references/*.md` files for any quirks and gotchas associated with the target model or engine.*
*Additionally, you MUST perform a web search to check Nvidia forums, vLLM issues, and current literature for the latest engine parameter recommendations (e.g., block sizes, caching modes) to capture any newly discovered optimizations.*
*Upon completion of the research, the plan MUST be re-presented to the user for approval before progressing to Phase 1.*

- **Quirk Investigated**: [Describe the quirk, e.g., SGLang Mamba Speculation Crash]
- **Web Research Summary**: [Describe findings from internet search regarding recent hardware/engine optimizations for this model]
- **Invalidation Test**: \[Describe the exact test from the docs, e.g., "Run with `--speculative-algo EAGLE3` enabled"\]
- **Result**: [Did it crash? Yes/No]
- **Action Taken**: [e.g., "Crash still present on nightly image, leaving quirk active" OR "Boot succeeded, removing quirk from documentation and re-enabling feature"]

______________________________________________________________________

## 0.5 Rollback Escape Hatch (PRE-FILLED)

*If the new deployment causes a catastrophic failure, you MUST have the exact rollback commands pre-defined here so the system can be restored instantly without further research.*

- **Previous Stable Stack Name**: [e.g., `core-upgrade-20260320`]
- **Rollback Command**: `uv run python -m scripts.set_current spark-stack-registry/spark-stack-registry/stacks/[PREVIOUS_STABLE] && cd current && docker compose up -d --force-recreate`

______________________________________________________________________

## 1. Hardware & Resource Budget (Verification of Constraints)

*Consult **stack-manager** for the strict aggregate memory laws (e.g., 108GB RAM budget) to prevent system hangs.*
*Perform empirical VRAM profiling for all model candidates to ensure constraints hold.*

- **Current Main Model (`[CURRENT_MAIN]`)**: [X]% VRAM | [Y]GB RAM
- **New/Target Model (`[NEW_MODEL]`)**: [X]% VRAM | [Y]GB RAM
- **Other Models (e.g., embedding)**: [X]% VRAM | [Y]GB RAM
- **Overhead (LiteLLM/Gateway)**: \<1% VRAM | 4GB RAM
- **Aggregate Totals**: **[TOTAL]% VRAM** | **[TOTAL]GB RAM** (Must be within limits defined in **stack-manager**).

______________________________________________________________________

## 2. Detailed Implementation Phases

### Phase 1: Model Registration (Registry Layer)

Create or verify the custom `sparkrun` recipe in the registry.

- **File**: `spark-stack-registry/models/[MODEL_ID].yaml`
- **VLLM Config Details to Verify**:
  - **Resource Allocation**: Must match the budget calculated above.
  - **Quantization Format**: Explicitly state the target format (e.g., `NVFP4`, `AWQ`, `FP8`) as this drastically dictates the VRAM footprint and throughput expectations.
  - **Engine & Architecture**: Consult the **stack-manager** "Troubleshooting & Learnings" section for model-specific engine overrides (e.g., V1 vs V0 requirements, attention backends, and reasoning parser plugins).
  - **Hardware Alignment**: Ensure `max_model_len` and `max_num_batched_tokens` are properly aligned per the latest registry standards.

### Phase 2: Infrastructure Patching (Tooling Layer)

Identify if existing scripts require patching to support the new model role.

> **Immutable Environment Check**: Wait—are new binary dependencies required? You MUST bake all new runtime dependencies into `Dockerfile.openclaw-custom`. *Never injection-hack dependencies at container startup.*

- **Dependency Probing (Pre-flight)**: Ensure required engines (`sglang`, `vllm`, `accelerate`) exist on the exact image tag before building.
- **LiteLLM Routing (`scripts.build_stack`)**: Verify routing logic and schema validation requirements (e.g., role_map exclusions or encoding_format injections).
- **Health Checks (`utils.py`, `vllm_health.py`)**: Ensure endpoints are probe-ready.

### Phase 3: Stack Orchestration (Building Layer)

Generate the multi-container configuration using the iterative naming convention.

- **Action**: Use `uv run python -m scripts.build_stack` to generate the new stack configuration.

### Phase 4: Activation & Synchronization (Deployment Layer)

Atomically rotate the containers and sync OpenClaw per the **stack-manager** protocol.

1. **Shutdown/Cleanup**: Perform clean shutdown of previous containers.
1. **Launch**: Activate the new stack.
1. **Sync**: Synchronize the OpenClaw configuration.
1. **Network Resolution**: Restart edge networking if necessary to clear tunnel IP caches.
1. **Telemetry Verification**: Ensure `vllm_model_load_progress` metrics are successfully pushing through the SSH reverse-tunnel (`-R 8125:127.0.0.1:8125`) to Vector by querying the Prometheus `/targets` UI.

### Phase 5: OpenClaw / Application Configuration

Configure consumers to utilize the new model via the OpenClaw CLI.

______________________________________________________________________

## 3. Mandatory E2E Verification Suite

*Consult the **stack-verifier** skill for the full E2E baseline protocol. The following integration suite MUST be executed to verify the new stack.*

- **Action**: `uv run python -m scripts.verify --stack [TARGET_STACK_NAME]`
- **Expect**: ✅ ALL verification stages pass.
- **Verification Coverage**:
  - Layer 0: Pre-flight Memory Law Compliance (`check_memory_law.py`)
  - Infrastructure Health & Backend Pulse.
  - Gateway Routing & Proxy Integrity.
  - Functional Role Verification (Reasoning/Embeddings).
  - OpenClaw System Diagnosis.
  - Consumer Readiness (End-to-End Agent Verification).
  - Telemetry Verification (Prometheus Targets).
  - Performance Benchmarking (`llama-benchy`) & Delta Analysis.

______________________________________________________________________

## 4. Formal Benchmarking

*While `scripts.verify` checks anti-repetition regression and system resilience, an explicit throughput/latency performance benchmark MUST be run to record the baseline performance delta of the newly configured model.*

- **Action**: Run `uv run sparkrun benchmark [MODEL_NAME] --skip-run` (Note: telemetry defaults to `SparkrunConfig` output directories and auto-derives the inference alias).
- **Cleanup Requirement**: The benchmark utility dumps `.csv`, `.json`, and `.yaml` result files into the repository root. You MUST immediately move them by running `mv benchmark_* benchmarks/` to maintain repository hygiene.
- **Expect**: Securely capture Output Tokens per Second (T/s), Time to First Token (TTFT), and End-to-End Latency.
- **Baseline Capture**:
  - **Throughput (Tokens/s)**: [Record T/s]
  - **TTFT (ms)**: [Record Latency]
  - **Success Rate**: [Record %]

______________________________________________________________________

## 5. Failure Recovery Protocol

If `uv run python -m scripts.verify` or `sparkrun benchmark` reports any failures:

1. **Halt execution immediately.**
1. **Inform the user** with the exact `stdout`/`stderr` of the failing layer. Do not attempt any automatic rollback or live-patching without explicit user permission.

______________________________________________________________________

## 6. Mandatory Proof of Execution (Receipts)

*Verification is NOT complete until you have provided the EXACT raw terminal output of the verify script to the user. Do NOT summarize. Do NOT just say "Verification passed." You MUST paste the exact `stdout` and `stderr` here as undeniable proof.*

______________________________________________________________________

## 7. Finalization (Cleanup)

Once verified functional:

1. **Document Learnings**: Ensure this executed plan is completely filled out and saved as `plan.md` in the stack's directory (and update the files in `skills/stack-manager/references/` if new technical constraints were discovered).
1. **Cleanup**: Remove all failed iterative stack directories from the `spark-stack-registry/stacks/` folder.
1. **Standardize Name**: Rename the working stack directory to remove the iterative suffix (e.g., `core-upgrade-20260329-01` -> `core-upgrade-20260329`).
1. **Reset Current**: Finalize symlinks to ensure they point to the clean name.
