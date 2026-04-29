# Template: Model Addition / Upgrade Plan

**Objective**: [Brief description of the model addition or upgrade, e.g., Upgrade main model to Qwen3.5 or Add embedding model]
**Target Date**: [YYYY-MM-DD]
**Target Stack Name**: `[STACK_NAME]-[YYYYMMDD]-[ITERATION]` (e.g., `core-upgrade-20260329-01`)

______________________________________________________________________

## 0. Quirk Invalidation (MANDATORY PRE-FLIGHT)

*Before building a new stack, you MUST check the `skills/stack-knowledge/references/*.md` files for any quirks and gotchas associated with the target model or engine.*
*Additionally, you MUST perform a web search to check Nvidia forums, vLLM issues, and current literature for the latest engine parameter recommendations (e.g., block sizes, caching modes) to capture any newly discovered optimizations.*
*Upon completion of the research, the plan MUST be re-presented to the user for approval before progressing to Phase 1.*

- **Quirk Investigated**: [Describe the quirk, e.g., SGLang Mamba Speculation Crash]
- **Web Research Summary**: [Describe findings from internet search regarding recent hardware/engine optimizations for this model]
- **Invalidation Test**: [Describe the exact test from the docs, e.g., "Run with `--speculative-algo EAGLE3` enabled"]
- **Result**: [Did it crash? Yes/No]
- **Action Taken**: [e.g., "Crash still present on nightly image, leaving quirk active" OR "Boot succeeded, removing quirk from documentation and re-enabling feature"]

______________________________________________________________________

## 0.5 Rollback Escape Hatch (PRE-FILLED)

*If the new deployment causes a catastrophic failure, you MUST have the exact rollback commands pre-defined here so the system can be restored instantly without further research.*

- **Previous Stable Stack Name**: [e.g., `core-upgrade-20260320`]
- **Rollback Command**: `uv run python manager/set_current.py spark-stack-registry/stacks/[PREVIOUS_STABLE]`

______________________________________________________________________

## 0.75 Source Dependency Verification (PRE-FLIGHT)

*Verify that sparkrun, the registry, and all source dependencies are synchronized before building. A stale CLI or recipe cache will cause silent deployment failures.*

- **SparkRun Branch**: `cd ../sparkrun && git branch --show-current` → Must be `local-dev`
- **SparkRun State**: `cd ../sparkrun && git status --porcelain` → Must be empty
- **Registry Sync**: `uv run sparkrun update` → Ensure recipe cache is current
- **SparkRun Version**: `uv run sparkrun --version` → Record version hash: [_______]

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

## 2. Detailed Implementation Steps

### Step 1: Model Registration (Registry Layer)

Create or verify the custom `sparkrun` recipe in the registry.

- **File**: `spark-stack-registry/sparkrun/[MODEL_ID].yaml`
- **VLLM Config Details to Verify**:
  - **Resource Allocation**: Must match the budget calculated above.
  - **Quantization Format**: Explicitly state the target format (e.g., `NVFP4`, `AWQ`, `FP8`) as this drastically dictates the VRAM footprint and throughput expectations.
  - **Engine & Architecture**: Consult the **stack-manager** "Troubleshooting & Learnings" section for model-specific engine overrides (e.g., V1 vs V0 requirements, attention backends, and reasoning parser plugins).
  - **Hardware Alignment**: Ensure `max_model_len` and `max_num_batched_tokens` are properly aligned per the latest registry standards.
- **Action (Model Accessibility)**: `uv run python manager/verify_hf_model.py <repo_id>`
  - **Expect**: ✅ "VERIFIED: Repository ... physically exists on Hugging Face."
- **Action (VRAM Validation)**: `uv run sparkrun recipe vram spark-stack-registry/sparkrun/[MODEL_ID].yaml --tp 1`
  - **Expect**: Estimated VRAM within the budget calculated in Phase 1. No OOM flags.

### Step 2: Infrastructure Patching (Tooling Layer)

Identify if existing scripts require patching to support the new model role.

> **Immutable Environment Check**: Wait—are new binary dependencies required? You MUST bake all new runtime dependencies into `Dockerfile.openclaw-custom`. *Never injection-hack dependencies at container startup.*

- **Dependency Probing (Pre-flight)**: Ensure required engines (`sglang`, `vllm`, `accelerate`) exist on the exact image tag before building.
- **LiteLLM Routing (`manager/build_stack.py`)**: Verify routing logic and schema validation requirements (e.g., role_map exclusions or encoding_format injections).
- **Health Checks (`core/health.py`, `core/vllm_health.py`)**: Ensure endpoints are probe-ready.

### Step 3: Stack Orchestration (Building Layer)

Generate the multi-container configuration using the iterative naming convention.

- **Action**: Use `uv run python manager/build_stack.py` to generate the new stack configuration.

### Step 4: Activation & Synchronization (Deployment Layer)

Atomically rotate the containers and sync OpenClaw per the **stack-manager** protocol.

1. **Shutdown/Cleanup**: Perform clean shutdown of previous containers.
1. **Launch**: Activate the new stack via `uv run python manager/set_current.py spark-stack-registry/stacks/[STACK_NAME]`.
1. **Backend Readiness Gate**: Wait for all model backends to complete loading and pass post-load smoke tests.
   - **Action**: `uv run python manager/wait_for_backends.py --timeout 1800`
   - **Expect**: ✅ "Backend Readiness (All models loaded)" + passing smoke tests for each backend.
   - **Failure Mode**: If any backend reports `-1` (crash), HALT immediately. Tail `/tmp/sparkrun_serve.log` inside the crashed container and report findings to the user.
1. **Post-Deploy Memory Compliance**:
   - **Action**: `uv run python manager/check_memory_law.py`
   - **Expect**: ✅ "Memory Law compliant across both RAM and VRAM dimensions."
1. **Sync**: Synchronize the OpenClaw configuration.
1. **Network Resolution**: Restart edge networking if necessary to clear tunnel IP caches.
1. **Telemetry Verification**:
   - **Metrics Pipeline**: Verify `vllm_model_load_progress` metrics are pushing through to Prometheus: `curl -s http://localhost:9102/metrics | rg vllm_model_load_progress` → Must return metric lines for all deployed models.
   - **Prometheus Targets**: Confirm all scrape targets are UP via the Prometheus `/targets` UI.
   - **Tracing**: Send a test request through the gateway and verify a linked trace appears in Grafana Tempo.

### Step 5: OpenClaw / Application Configuration

Configure consumers to utilize the new model via the OpenClaw CLI.

- **Action**: Use `~/bin/openclaw config set` to update model routing in the OpenClaw configuration.
- **Verify**: Confirm the new model is reachable through the gateway endpoint.

______________________________________________________________________

## 3. Mandatory E2E Verification Suite

*The following integration suite MUST be executed to verify the new stack.*

- **Action**: `uv run pytest tests/e2e/`
- **Expect**: ✅ ALL verification stages pass.
- **Verification Coverage**:
  - Memory Law Compliance (`test_memory_law.py`)
  - Infrastructure Health & Backend Pulse (`test_system_health.py`)
  - Gateway Routing & Proxy Integrity (`test_wait_for_backends.py`)
  - Functional Role Verification — Reasoning (`test_tool_calling.py`, `test_long_conversation.py`)
  - Functional Role Verification — Embeddings (`test_functional_embeddings.py`)
  - OpenClaw System Diagnosis (`test_openclaw_diagnosis.py`)
  - Consumer Readiness (`test_consumer_readiness.py`)
  - Telemetry Verification (`test_telemetry.py`, `test_tracing.py`)

______________________________________________________________________

## 4. Formal Benchmarking

*While E2E tests check anti-repetition regression and system resilience, an explicit throughput/latency performance benchmark MUST be run to record the baseline performance delta of the newly configured model.*

- **Action**: Run:
  ```bash
  export $(rg -v '^#' .env | xargs) && uv run sparkrun benchmark \
    spark-stack-registry/sparkrun/[MODEL_NAME].yaml \
    --skip-run --port 4000 \
    -b served_model_name=main \
    -b api_key=$LITELLM_MASTER_KEY \
    --profile spark-arena-v1
  ```
  *(Note: telemetry defaults to `SparkrunConfig` output directories and auto-derives the inference alias.)*
- **Cleanup Requirement**: The benchmark utility dumps `.csv`, `.json`, and `.yaml` result files into the repository root. You MUST immediately move them into the active stack's directory:
  ```bash
  mv benchmark_* spark-stack-registry/stacks/[STACK_NAME]/
  ```
- **Expect**: Securely capture Output Tokens per Second (T/s), Time to First Token (TTFT), and End-to-End Latency.
- **Baseline Capture**:
  - **Throughput (Tokens/s)**: [Record T/s]
  - **TTFT (ms)**: [Record Latency]
  - **Success Rate**: [Record %]

______________________________________________________________________

## 5. Failure Recovery Protocol

If `uv run pytest tests/e2e/` or `sparkrun benchmark` reports any failures:

1. **Halt execution immediately.**
1. **Inform the user** with the exact `stdout`/`stderr` of the failing layer. Do not attempt any automatic rollback or live-patching without explicit user permission.

______________________________________________________________________

## 6. Mandatory Proof of Execution (Receipts)

*Verification is NOT complete until you have provided the EXACT raw terminal output of the verify script to the user. Do NOT summarize. Do NOT just say "Verification passed." You MUST paste the exact `stdout` and `stderr` here as undeniable proof.*

______________________________________________________________________

## 7. Finalization (Cleanup)

Once verified functional:

1. **Document Learnings**: Ensure this executed plan is completely filled out and saved as `plan.md` in the stack's directory (and update the files in `skills/stack-knowledge/references/` if new technical constraints were discovered).
1. **Cleanup**: Remove all failed iterative stack directories from the `spark-stack-registry/stacks/` folder.
1. **Standardize Name**: Rename the working stack directory to remove the iterative suffix (e.g., `core-upgrade-20260329-01` -> `core-upgrade-20260329`).
1. **Reset Current**: Run `uv run python manager/set_current.py spark-stack-registry/stacks/<clean_stack_name>` to finalize symlinks to the clean name.
1. **Post-Rename Verification**: Re-run `uv run pytest tests/e2e/test_memory_law.py tests/e2e/test_system_health.py` to confirm the renamed stack is still functional.
1. **Commit**: Stage and commit the finalized stack directory and updated symlink changes to the `spark-stack-registry`.
