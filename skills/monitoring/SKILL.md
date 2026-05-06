______________________________________________________________________

name: monitoring
description: Manages the Grafana/Prometheus monitoring stack, container updates, telemetry pipelines, and safe dashboard integration.
category: observability
risk: medium
source: local
compatibility: claude-code
triggers:

- update monitoring stack
- refresh grafana dashboards
- fix prometheus targets
- review dashboards
- fix grafana inaccurate data
- update grafana templates
- fix monitoring containers

______________________________________________________________________

# Observability Stack Management

## Use this skill when

- Debugging "no data" issues in Grafana or Prometheus
- Adding, reviewing, or modifying Grafana dashboards
- Upgrading or configuring monitoring containers (cAdvisor, Prometheus, Vector, nv-monitor, Node Exporter)
- Troubleshooting the `vllm-progress-manager`
- Writing or adjusting Prometheus metrics and scrape intervals

## Architecture Overview

The monitoring stack is defined in `services/monitoring/docker-compose.yml` and consists of:

- **Prometheus** (9090): Metrics database and scraping engine.
- **Grafana Alloy** (4318, 12345): OTel Collector.
- **Grafana** (3001): Visualization. Dashboards are auto-provisioned from `services/monitoring/grafana/provisioning/dashboards/`.
- **cAdvisor** (8080): Container metrics.
- **Node Exporter** (9100): Host OS metrics.
- **nv-monitor** (9101): NVIDIA GPU metrics.
- **Vector** (8125, 9102): Log and metric pipeline. Parses Docker logs and receives StatsD metrics.
- **vllm-progress-manager**: Custom Python daemon that polls model health/loading progress and pushes to Vector via StatsD.

## Key Constraints & Best Practices

### 0. Automated Updates (Zero-RAM Method)

- **Do NOT use `:latest` tags.** The `gcr.io/cadvisor/cadvisor:latest` tag is permanently broken and abandoned. Prometheus `:latest` causes unexpected configuration breakages mid-week.
- **Run Updates:** Use the `uv run python manager/update_monitoring.py` script. It queries the GitHub, Docker Hub, and GCR APIs to find the true latest stable semantic versions. It also switches Docker Hub images to `quay.io` where possible to avoid API rate limits, and pins them in `docker-compose.yml`.
- **Memory Efficiency:** This script consumes 0MB of background RAM (unlike Watchtower/Keel), preserving 100% of host resources for AI model inference.

### 1. cAdvisor Configuration

- **Version**: Use `v0.51.0` (or newer) for proper ARM64 and cgroups v2 support.
- **Docker API Version**: Must set the `DOCKER_API_VERSION` environment variable (e.g., `"1.44"`) to match the host daemon, otherwise the Docker container factory fails to register and container discovery fails.
- **Security**: Do NOT use `privileged: true`. Instead, use `cap_add: ["SYS_ADMIN", "SYS_PTRACE"]` and mount the necessary read-only volumes (`/sys/fs/cgroup`, `/var/run/docker.sock`, etc.).
- **Resources**: Apply strict memory and CPU limits (e.g., 512M, 0.5 CPU) to prevent memory leaks and host starvation during high-frequency polling.

### 2. Prometheus Configuration

- **Scrape Interval**: Use `15s` for production stability. Aggressive intervals (like 5s) cause TSDB bloat and CPU starvation.
- **Metrics Path**: Always use `/metrics` (no trailing slash). Some engines (like SGLang) will fail with connection resets or 404s if a trailing slash is appended.
- **Configuration Generation**: Do not manually edit `current/prometheus.yml` for permanent changes. Update `manager/build_stack.py` (`_generate_prometheus_config`) to ensure future stacks inherit the correct configuration.
- **Permissions**: Do not run Prometheus as `user: root`. Drop privileges and manage volume permissions natively via `nobody` or a dedicated unprivileged user.

### 3. Vector & Progress Manager

- **Flow**: `vllm-progress-manager` queries the health of the model containers and sends loading percentages to Vector via StatsD (port 8125). Vector converts these to Prometheus metrics (e.g., `vllm_model_load_progress`) exposed on port 9102.
- **SSH Reverse Tunnel Architecture**: Worker nodes push telemetry to the central Vector aggregator securely via an SSH reverse tunnel (`-R 8125:127.0.0.1:8125`) initialized by `sparkrun`. This preserves the agentless execution model by avoiding resident daemons on worker nodes.
- **Troubleshooting**: If `vllm_model_load_progress` is missing from Prometheus, explicitly test the pipeline:
  1. Test StatsD reception inside Vector: `docker exec -it vector nc -u -v localhost 8125`
  1. Verify Prometheus targets are alive: Query `up` in the Prometheus UI to ensure jobs are correctly discovered.
  1. Check the progress manager logs: `docker compose logs vllm-progress-manager`.
- **Deadlock Shields**: System deadlocks can be triggered by `vllm-progress-manager` or resource contention during Docker container startup. Ensure `gpu_memory_utilization` limits are strictly respected to prevent the host OS or orchestrator from hanging during heavy CUDA graph capture.

### 4. Decoupled Orchestration Integration (`build_stack.py`)

The orchestration tool `manager/build_stack.py` integrates seamlessly via a metadata-driven approach without hard coupling container names:

- **Prometheus Dynamic Discovery**: `build_stack.py` populates `/prometheus/targets.json` using File-based Service Discovery (File SD). `services/monitoring/docker-compose.yml` provides a static `prometheus.yml` that monitors this JSON file. The orchestration layer adds metadata labels explicitly to the SD config dict, cleanly registering models with the monitoring database.
- **Progress Manager Decoupling**: Progress Manager now discovers monitoring-eligible containers natively using docker labels `sparkrun.monitoring=true` natively via filters (`docker ps -f label=sparkrun.monitoring=true`), avoiding implicit regex naming matches. The metrics fallback `model_id` uses the `sparkrun.role` label securely populated at instantiation.
- **Architecture Standard**: Any new orchestrator or wrapper connecting to this repository's monitoring tools MUST apply the labels `sparkrun.monitoring=true` and `sparkrun.role=X` to its containers to ensure automatic inclusion into Grafana dashboards and stat-piping streams.

______________________________________________________________________

## Grafana Upkeep & Dashboard Modernization

Our environment is a **composite multi-engine proxy stack**. Traffic is ingested by a gateway router (LiteLLM) which applies custom labeling (`$Deployment_id`, `$model`, user spend), and then routed to underlying execution engines (vLLM, SGLang).

Because of this, our top-level LLM dashboards (`overview.json`, `vllm-query-statistics.json`, `vllm-performance-statistics.json`) are heavily customized to **merge Gateway metrics with backend execution metrics**.

> [!WARNING]
> You must **NEVER** blindly download standard vLLM or LiteLLM community dashboards and completely overwrite the workspace's LLM dashboard JSON files. Doing so will permanently destroy the custom composite visibility routing layer built into those dashboards.

### 1. Identify and Categorize Dashboards

Scan the provisioning directory (e.g. `services/monitoring/grafana/provisioning/dashboards/`) and categorize the JSON files into:

- **Standard Infrastructure** (Safe to Overwrite): Examples include Node Exporter, nv-monitor, cAdvisor.
- **Composite AI Dashboards** (Surgical Update Required): Examples include `overview`, `vllm-query-statistics`, `sglang-dashboard`, `openclaw-gateway`.

### 2. Force-Update Infrastructure Dashboards

Standard dashboards rarely carry custom proxy tracking and can be completely refreshed to leverage new exporter capabilities.

1. Download the latest official JSON templates from Grafana.com API (e.g. Node Exporter #1860, DCGM #12239):
   ```bash
   curl -sL https://grafana.com/api/dashboards/1860/revisions/latest/download -o /tmp/node-exporter.json
   ```
1. Inject the proper `uid` to match existing dashboard definitions so they overwrite cleanly in the UI:
   ```bash
   jq '.uid = "spark-host-os" | .title = "Spark Host OS"' /tmp/node-exporter.json > dashboards/spark-host-os.json
   ```
1. Remove any redundant or deprecated dashboards that track the exact same infrastructure layer.

### 3. Surgically Audit AI Dashboards

For specialized LLM and Gateway dashboards:

1. **Fetch Latest Upstream References**: Download the latest raw JSON dashboards directly from the engine's GitHub repositories (`sgl-project/sglang`, `vllm-project/vllm`, `BerriAI/litellm`) to `/tmp/`.
1. **Metric Parity Analysis**: Search the downloaded templates for core metric changes.
   - *Example*: Did vLLM change their TTFT metric from `vllm:time_to_first_token_seconds` to something else? Did LiteLLM drop the `api_latency` notation?
1. **Targeted JSON Patching**: Surgically replace outdated metric schemas inside your local `overview.json` or `vllm-*` JSONs based on upstream changes.
1. **Merge New Panels (Optional)**: If the upstream repo added entirely new, valuable panels (like "KV Cache Fragmentation"), copy those JSON panel blocks individually and inject them into the local layout grid, adjusting `gridPos` coordinates (`x`, `y`, `w`, `h`) cleanly so panels do not overlap. Total width of the Grafana grid is 24.
1. **SGLang vs vLLM Compatibility**: Both SGLang and vLLM export their core inference metrics using the `vllm:` prefix (e.g., `vllm:request_prompt_tokens_bucket`). You do not need to use expensive `{__name__=~"(vllm|sglang):..."}` regex lookups, which cause severe performance degradation on high-cardinality histograms. Use the direct `vllm:` metric name.
1. **Container Name Changes**: The dashboard decoupled from container name regexes. Model container metrics (like `container_cpu_usage_seconds_total`) now rely on the `container_label_sparkrun_monitoring="true"` label attached to all model workloads by the orchestration tools. If a panel breaks, verify the orchestrator (`build_stack.py` or Sparkrun Plugins) correctly attaches these labels to the `docker run` execution.
1. **Label Matching**: Ensure dashboard variables (like `$model` and `$instance`) correctly map to the labels exported by the respective engines and the LiteLLM proxy. Check Prometheus explicitly (`label_values(...)`) if panels show "no data".

### 4. Verification & Reload

Always apply your changes and verify Grafana reloads them predictably.

- **Lint the JSON**: Before applying any raw JSON dashboard edits, ALWAYS run `jq empty < dashboards/your-dashboard.json` to statically verify there are no dangling formatting errors (like missing commas or unclosed brackets). Broken JSON will crash the provisioning reload silently!
- **Tidy Up The UI**: After making changes or inserting new panels, ensure you did not leave ugly empty spaces or overlapping panels in the layout. Always verify and re-organize the `gridPos` coordinates (`w` width and `x/y` placement) to cleanly fill out the horizontal 24-column grid.
- Run `docker restart grafana` (or equivalent orchestrator command) to flush the provisioning cache.
- Ensure no file parsing errors or "No Data" fields are returned for the modified metrics.

## Prerequisites

1. You MUST confirm access to the Prometheus configuration files (`current/prometheus.yml`) or the Grafana dashboard active APIs before attempting to propose a telemetry change.

## When NOT to use this skill (Negative Triggers)

- Do NOT use this skill to debug vLLM memory configurations, OOM errors, or proxy topology rules. Use `stack-manager` or `stack-knowledge` instead.

## Examples

### Anti-Pattern: Overwriting Composite Dashboards

```bash
# BAD: Completely overwriting the custom composite router UI with standard metrics
curl -sL https://grafana.com/api/dashboards/1860/revisions/latest/download > dashboards/overview.json
```

### Correct Pattern: Surgical JSON Patching

```bash
# GOOD: Extracting the new panel upstream and injecting it to the local grid
jq '.panels += [new_panel]' dashboards/overview.json > /tmp/merged.json
```

## Output Format

When you complete tasks utilizing this skill, you MUST terminate your response with the following structured Markdown format:

```markdown
### 1. Summary of Changes
*(Briefly summarize the telemetry or dashboard modifications made)*

### 2. Modified Dashboard UIDs
*(List the exact UIDs of the dashboards updated, e.g. `spark-host-os`)*

### 3. Prometheus Metric Impact
*(List any newly added or adjusted metrics, or explicit target ports verified)*
```
