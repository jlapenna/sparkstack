______________________________________________________________________

name: stack-manager
description: Manages model upgrades, STT deployment, and memory rebalancing for NVIDIA Spark workstations with atomic configuration sync using a Model Registry pattern.
category: infrastructure
risk: medium
source: local
compatibility: claude-code
triggers:

- update spark models
- upgrade vllm researcher
- rebalance spark memory
- fix spark context window
- deploy model to spark
- setup stt on spark
- refactor vllm models

______________________________________________________________________

# stack-manager

## Purpose

To manage, update, and rebalance LLM and STT models on **NVIDIA Spark (GB10 Blackwell)** workstations with zero tolerance for system hangs. This skill ensures atomic configuration across `sparkrun`, Docker, LiteLLM, and OpenClaw while enforcing the verified **108GB aggregate memory limit**.

## Mandatory Workflow Protocol (Plan-Act-Verify-Finalize)

The NVIDIA Spark stack is highly sensitive to memory limits, port collisions, and schema validation. Ad-hoc or "on-the-fly" changes reliably cause system hangs, silent failures, and zombie processes. To prevent this, you MUST operate with absolute discipline.

For **ANY** model addition, upgrade, or stack modification, you MUST defer to the structured workflow defined in `skills/stack-manager/references/plan-template.md`.

**Agent Execution Rules:**

1. **Mandatory Checklist Generation**: Before taking any action, you MUST explicitly create and maintain a `task.md` tracking artifact containing checkboxes for all 7 phases laid out in `skills/stack-manager/references/plan-template.md`. Checking off each segment is strictly required.
1. **Planning & Research**: Use the structure logically defined in `skills/stack-manager/references/plan-template.md` to bootstrap your own implementation plan artifact for the current conversation. You MUST perform a web search to verify parameters and include your findings in the plan.
1. **STOP AND WAIT**: Do absolutely nothing else. Wait for the user's explicit approval of the created implementation plan before proceeding.
1. **Execution & Verification**: Once approved, execute the plan strictly as written, progressing through all infrastructure, stack orchestration, E2E Verification, and **Formal Benchmarking (Phase 4)** phases detailed in the template.
1. **ZERO HOT-PATCHING**: If a step fails, **HALT** and inform the user. Do not attempt quiet fixes or ad-hoc hacks.
1. **No Log Summarization**: You are strictly banned from summarizing verification logs in Phase 6. You must dump the literal unedited `stdout` blocks into the `plan.md` to prevent hallucinated success records.
1. **Cheat-Sheet Finalization**: For Phase 7 cleanup, the mandatory final rotation command is exactly `uv run python scripts/set_current.py stacks/<clean_stack_name>`. Execute this after stripping the iterative suffix and deleting failed iterations.

_(Refer to `skills/stack-manager/references/plan-template.md` for the exact requirements of Phase 1 through Phase 7)._

## Core Mandates (Blackwell Safety)

### 1. The Memory Law (108GB Aggregate)

- **Total Limit**: Aggregate memory limits in all containers MUST NOT exceed **108GB**.
- **GPU Utilization**: Aggregate `gpu-memory-utilization` MUST NOT exceed **0.90** (Hard limit 0.95).
- **Context Preservation**: For 128k+ context, monitor VRAM usage carefully.
- **System RAM Maximization**: Do not leave System RAM unutilized. The main LLM container/sparkrun instance MUST be allocated the lion's share of System RAM (e.g., `cpu-offload-gb: 60`) to prevent OOM during weight loading and to support KV cache CPU offloading. If GPU utilization hits the 0.90 limit, heavily leverage CPU offloading to absorb the difference.

### 2. Port & Network Integrity

- **Port Arbitration**: Start at **8001**.
- **External Networks**: `vllm-network` MUST be `external: true` in `compose-base.yaml` to prevent Prometheus disconnection.
- **Proxy-First Verification**: Verification tools (like `verify.py`) and benchmarks (like `sparkrun benchmark`) SHOULD be routed through the `vllm-gateway` (port 4000) rather than hitting internal container ports directly, to ensure proxy integrity.

### 3. Tooling & Orchestration

- **build_stack.py**: Use `build_stack.py` to generate the stack directory. It handles predictable naming and resource orchestration.
- **Predictable Naming**: ALWAYS use the `--name {role}` flag in `sparkrun run` (e.g., `--name main`) so containers are named `{role}_solo`. This is required for `vllm-progress-manager` and `verify.py` discovery.
- **Explicit Reasoning Config**: Do NOT rely on automatic `thinking_format` detection. Always specify `thinking_format: openai` (for Gemma/Nemotron) or `thinking_format: qwen-chat-template` (for Qwen models) in the `litellm_overrides` section of the recipe.

### 4. OpenClaw Hygiene

- **Sync Tooling**: ALWAYS use `~/bin/oc config set` for manual edits to ensure schema validation.

### 5. Git & Repository Hygiene

- **No Binary Blobs in Repo**: NEVER commit or store downloaded model weights, binary blobs, or Hugging Face cache directories.

### 6. Mandatory Pre-Flight Checks

- **Download Accessibility**: The `stack-manager` MUST confirm the target model's physical weights are actively accessible (e.g. valid HuggingFace `repo_id`) before initiating a `build_stack` command and definitively before touching existing production containers via `docker compose down`. Deployments must never be started if the necessary components cannot be downloaded.
- **Physical Math Verification**: The `stack-manager` MUST invoke `sparkrun recipe vram <recipe>` every single time a recipe file is scaffolded or modified _before_ confirming success to the user.
- **Cluster vs. Standalone Validation**: VRAM estimation calculates load by distributing weight via `shard_factor` (TP\*PP). This is mathematically correct *only* if the user possesses a physical deployment cluster of Spark nodes corresponding to that factor. If deploying to a *single* standalone workstation, do not allow parallelism settings to falsely validate a model footprint that exceeds the single-node 121GB unified limit.
- **Immediate Failure Halting**: If the VRAM simulator outputs an OOM condition or flags a misaligned distributed size (`TP=1` on a 1T model), you MUST immediately halt and inform the user of the error rather than blindly deploying.

## Troubleshooting & Learnings

### 1. 0% Loading Progress (High Context)

High-context models (1M+) spend significant time (up to 5 minutes) in the "Memory Profiling" and "CUDA Graph Capture" phase before reporting any loading progress.

- **Fix**: Check `docker exec {container} tail -f /tmp/sparkrun_serve.log` to confirm the engine is active.
- **Indicator**: If `vllm-progress-manager` reports `FAILED` (-1), the model likely hit a VRAM allocation error (see "OOM on Startup").

### 2. OOM on Startup (VRAM Collision)

If `gpu-memory-utilization` is set too high (e.g. 0.85) and another process (like an embedding model) already occupies memory, vLLM will fail to initialize. Note that 120GB Blackwell node drivers cap maximally free memory per-GPU to ~101.73 GiB upon initialization overhead limit.

- **Fix**: Check `tail -n 100 /tmp/sparkrun_serve.log` for `ValueError: Free memory ... is less than desired`. Decrease `gpu_memory_utilization` by 0.02 increments until stable. When co-locating an embedding model alongside a dense model on Blackwell, **use 0.81** as the ceiling limit for the primary dense model.

### 3. WhatsApp Plugin TypeError

OpenClaw gateway may crash with `TypeError: Cannot read properties of undefined (reading 'resolveWhatsAppGroupIntroHint')`.

- **Fix**: This is a schema mismatch. Update the OpenClaw source code to the latest `main` branch and rebuild the gateway container. Ensure `openclaw.json` does not contain a top-level `version` key if using older releases.

### 4. Docker DNS Breakage (resolv.conf override)

If containers cannot resolve internal hostnames (e.g. `vllm-gateway`) despite being on the same custom network (like `proxy-tier`):

- **Cause**: Bind-mounting the host's `/etc/resolv.conf` into the container (`/run/systemd/resolve/resolv.conf:/etc/resolv.conf:ro`) forcibly overrides Docker's embedded DNS server (`127.0.0.11`). It blinds the container to internal Docker service discovery.
- **Fix**: NEVER bind-mount `/etc/resolv.conf` locally when using Docker bridge networks. Let Docker natively inject its `127.0.0.11` resolver to ensure container restarts and dynamic IP mapping work correctly.

### 5. Benchmark Rejected by Proxy (Invalid model name)

If `sparkrun benchmark` (using `llama-benchy`) fails immediately with `HTTP 400 ... Invalid model name passed` against port 4000:

- **Cause**: The `vllm-gateway` (LiteLLM) protects access by enforcing mapped dictionary names (e.g., `main` or `embedding`). By default, `llama-benchy` passes the literal HuggingFace path to the endpoint.
- **Fix**: You must pass the internal mapped name through sparkrun by appending `-b served_model_name=main` to your `sparkrun benchmark` command.

## Maintenance & Recovery

### 1. Rebuild & Rotate Protocol (STRICT)

- **Atomic Update**: To apply changes to `build_stack.py` or the OpenClaw gateway, you MUST rebuild the images/stack and rotate the containers.
- **Zombie Protocol**: The `update_services.py` script automatically clears stuck tasks and prunes stale containers. If sessions are hung, run a full update cycle to reset the state.
- **Clean Sweep**: Before rotation, run `docker rm -f $(docker ps -a -q -f "name=sparkrun|vllm")` to clear port bindings if the automatic protocol fails.

### ✅ Operational Guidelines: Dos and Do-Nots

#### 👍 The Dos

- **Internal Log Tailing**: Always tail `/tmp/sparkrun_serve.log` inside model containers for high-signal diagnostics.
- **Direct Benchmark Overrides**: Use `-o max_model_len={n}` in `sparkrun benchmark` to match the target stack's configuration.
- **Benchmark Hygiene**: Since `sparkrun benchmark` hard-dumps its results in the repository root, you MUST immediately move the telemetry output files (`benchmark_*`) into the active stack's directory (e.g., `stacks/<stack_name>/`) to keep the repository base clean.

#### 👎 The Do-Nots

- **No Magic IPs**: Never use internal Docker IPs (e.g. 172.19.x.x) in verification or benchmarking. Use hostnames (`main_solo`) or route through the proxy (`localhost:4000`).
- **No Manual Port Forwarders**: Do not use `socat` or bridge containers. Use proper Docker port mappings or proxy routing.
- **NEVER Run `llama-benchy` Directly**: Do not bypass `sparkrun benchmark` to manually call `llama-benchy` (e.g., via `uvx`). The orchestrator MUST handle all benchmark orchestration and telemetry exports automatically. If you need to override `llama-benchy` specific args, use the `-b key=value` override flag inside `sparkrun benchmark` (e.g., `-b served_model_name=main`).

## Prerequisites (Depth Gates)

1. You MUST verify that the physical model weights or valid `repo_id` are actively accessible on HuggingFace Hub or locally before touching existing active deployments.
1. You MUST verify the 108GB aggregate Spark constraint rule is maintained before initiating Phase 1 of `plan-template.md`.

## When NOT to use this skill (Negative Triggers)

- Do NOT use this skill for routine OpenClaw or SparkRun source code updates. Use `stack-upkeep` instead.
- Do NOT use this skill to debug unexpected port collision network topology errors. Use `stack-knowledge` instead.

## Examples

### Anti-Pattern: Direct Benchmarking

```bash
# BAD: Bypasses the proxy schema mapping and fails with HTTP 400
uv run sparkrun benchmark /path/recipe.yaml --port 4000
```

### Correct Pattern: Routed Benchmarking

```bash
# GOOD: Explicitly maps the internal container target (main) via the override flag
uv run sparkrun benchmark /path/recipe.yaml --port 4000 -b served_model_name=main
```

## Output Format

When concluding this skill's workflow, your final message MUST strictly include:

```markdown
### 1. Phase Completion Status
*(Confirm if all 7 phases from `plan-template.md` were executed successfully, or which phase aborted)*

### 2. Live Configuration State
*(Dump the precise Docker CLI state: e.g., active ports, loaded container names, running models)*

### 3. Exact Benchmark Metrics
*(Provide the literal unedited `stdout` performance latency jitter scores retrieved during Phase 4 without summarization)*
```
