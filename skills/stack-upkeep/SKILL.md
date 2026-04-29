______________________________________________________________________

name: stack-upkeep
description: A maintenance skill dedicated to keeping the NVIDIA Spark stack and OpenClaw ecosystem up to date with the latest stable releases and recipes.
category: infrastructure
risk: medium
source: local
compatibility: claude-code
triggers:

- update sparkrun
- update openclaw
- update the stack
- check for openclaw updates
- upgrade my system
- keep the stack current

______________________________________________________________________

# stack-upkeep

## Purpose

To cleanly and safely update the various components of the AI ecosystem. This includes checking for and applying the latest stable OpenClaw gateway updates from GitHub, and pulling the latest docker container images for the underlying models.

## Update Protocol

This skill dictates the exact sequence of commands to execute when a user asks to update the system.

### 1. Update Sparkrun

- **Command:** `uv run python manager/update_sparkrun.py`
- **Behavior:** This script automatically fetches the tip of tree from GitHub, rebases local changes, and runs `uv sync` from the project root to ensure the local path dependency is updated.

### 2. Update OpenClaw (Gateway & CLI)

OpenClaw receives updates through branch maintenance. Do NOT perform tag-based updates, as they interfere with active development in the `local-dev` branch.

- **Command:** `./manager/update_openclaw.py` (Do NOT pass `--pull-latest` as it will overwrite local development changes with upstream release tags. Do NOT pass `--run-setup` during routine updates unless you intentionally want to execute `setup.sh`.)
- **Behavior:** This ensures local development branches and in-progress PRs are preserved without being forcibly detached to upstream tags.

### 3. Update Model Weights & Images

The underlying vLLM and LiteLLM containers may have received upstream patches.

- **Command:**
  ```bash
  cd ./current && docker compose pull
  ```
- **Behavior:** Ensures the latest container images are downloaded.

### 3.1 Rollback Protocol (If Stack Breaks)

If pulling the latest container image introduces a breaking registry change or stability issue, you must rollback to a known-good configuration immediately:

- **Command:** `uv run python manager/set_current.py spark-stack-registry/stacks/<previous_stable_stack_directory>`
- **Behavior:** This resets the `current` symlink and rebuilds the active docker-compose configuration using the older, verified images and recipes. Run `cd spark-stack-registry/stacks/current && docker compose up -d --force-recreate` to solidify the restore.

### 4. Manual Version Discovery & Pinning (When Renovate Fails)

While Renovate handles automated PRs for dependencies, you will sometimes need to manually discover and pin the latest stable releases for containers, images, or software versions.

- **Docker Images**:
  - Do NOT blindly use `:latest` as it breaks determinism.
  - Find the latest stable semantic tag (e.g., `v1.2.3`) using Skopeo: `skopeo list-tags docker://<registry>/<image>` or query the registry API (GitHub Container Registry, Quay.io, Docker Hub).
  - Explicitly edit `docker-compose.yml`, `.env`, or the stack recipe files to replace the old tag with the newly discovered stable tag.
- **Centralized Version Manifests**:
  - Update `package.json` for NPM tool dependencies.
  - Update `build-versions.json` for Go/Python binary tools.
  - The `update_openclaw.py` workflow will automatically parse these manifests during Docker builds to construct `Dockerfile.gateway-custom` and `Dockerfile.sandbox-custom`.
- **Python/uv Dependencies**:
  - Run `uv pip list --outdated` to discover stale packages.
  - Pin the exact version in `pyproject.toml` or `requirements.txt`.
- **Monitoring Stack**:
  - For Grafana, Prometheus, or cAdvisor, explicitly run `uv run python manager/update_monitoring.py`. This script securely queries GitHub/GCR APIs to find the true latest stable semantic versions and automatically pins them in the compose files.
- **Community Grafana Dashboards**:
  - The vLLM and SGLang ecosystems update their Grafana dashboards frequently (e.g., migrating from `vllm_` prefixes to `vllm:` OpenMetrics standard).
  - To update **vLLM**, fetch `performance_statistics.json` and `query_statistics.json` from `https://raw.githubusercontent.com/vllm-project/vllm/main/examples/observability/dashboards/grafana/`.
  - To update **SGLang**, fetch `sglang-dashboard.json` from `https://raw.githubusercontent.com/sgl-project/sglang/main/examples/monitoring/grafana/dashboards/json/sglang-dashboard.json`.
  - ALWAYS validate the downloaded files are valid JSON (`python3 -c "import json; json.load(open('file.json'))"`) before overwriting `services/monitoring/grafana/provisioning/dashboards/`.
  - Restart the Grafana container (`docker restart grafana`) to force the provisioning engine to reload the templates, and monitor `docker logs grafana` for `provisioning.dashboard` errors to verify success.

### 4. Automatic Maintenance (Zombie Protocol)

All update scripts (`update_services.py`, `update_openclaw.py`) now execute the **Zombie Protocol** automatically.

- **Behavior:**
  - Clears stuck tasks from `~/.openclaw/tasks/runs.sqlite`.
  - Prunes exited containers and unused networks.
  - Purges orphaned host processes (`vllm`, `sparkrun`).
- **Manual Trigger:** If sessions are hung without an update, run `uv run manager/update_services.py`.

### 5. Update SparkRun Recipes

The `sparkrun` registry receives frequent updates to optimization parameters.

- **Command:** `uv run sparkrun update`
- **Behavior:** Syncs the local recipe cache with the upstream `official` and `eugr` registries.

### 5. Re-apply Configuration (If necessary)

If any model configuration changes were detected upstream, rebuild and restart the stack to apply them.

- **Commands:**
  ```bash
  # Assuming the active stack is 'spark-stack-registry/stacks/official-main-20260325'
  uv run python manager/set_current.py spark-stack-registry/stacks/official-main-20260325
  ```

### 6. Final Verification (MANDATORY)

After any update, you MUST invoke the `stack-verifier` skill to ensure the system didn't break during the upgrade process.

### 7. Performance Benchmarking

After applying updates and verifying functionality, run the full `spark-arena-v1` performance suite to gather regression metrics on the main model:

- **Command:**
  ```bash
  uv run sparkrun benchmark /path/to/spark-stack-registry/sparkrun/<YOUR_ACTIVE_MAIN_MODEL>.yaml \
      --profile spark-arena-v1 \
      --skip-run \
      --port 8001 \
      -o served_model_name=main \
      -b tokenizer=<YOUR_ACTIVE_MODEL_TOKENIZER>
  ```
- **Behavior:** This profiles the token generation speed, prefill times, and latency jitter after the update, without tearing down the containers. It serves as a performance regression baseline.

### 8. Container Build & Runtime Tool Persistence

When modifying Docker images (e.g., `Dockerfile.openclaw-custom`), you MUST consult the **openclaw-image-manager** skill to understand the dual-persistence pattern and prevent tools from being masked by volume mounts.

## Important Safety Notes

- **Never modify `openclaw/` directory contents directly.** OpenClaw is an immutable upstream dependency managed purely by Git tags and Docker builds.
- Always run the `stack-verifier` pipeline after applying updates to catch breaking changes from upstream.

## Prerequisites

1. You MUST execute `git status` inside the `services/` directory and ensure the git tree is entirely clean before triggering upstream pulls or update cycles.

## When NOT to use this skill (Negative Triggers)

- Do NOT use this skill to tweak, debug, or deploy inference parameters or recipes into `sparkrun`. Use `stack-manager` or `model-recommender` instead.

## Examples

### Anti-Pattern: Forced Tag Fetching

```bash
# BAD: Tears developer away from local-dev branch and hard resets tree
./manager/update_openclaw.py --pull-latest
```

### Correct Pattern: Safe Maintenance Cycle

```bash
# GOOD: Applies stable background updates while preserving the developer's worktree
./manager/update_openclaw.py
```

## Output Format

When maintenance concludes, your final report MUST follow this exact format:

```markdown
### 1. Components Upgraded
*(List the versions/SHAs of openclaw, sparkrun, or containers before and after the cycle)*

### 2. Zombies Cleared
*(List any orphaned processes, containers, or sqlite tasks purged during the zombie sweep)*

### 3. Baseline Verification
*(Summarize the output of the mandatory `spark-arena-v1` performance suite confirming the system survived the update)*
```
