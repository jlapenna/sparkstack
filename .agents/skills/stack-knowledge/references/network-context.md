# Networking context

Read for networking diagnosis or a proposed networking change, from the
[stack-knowledge skill](../SKILL.md). These facts and troubleshooting leads
were collected from prior work. Check live evidence, target revision and
current official contracts before acting; symptom similarity alone is not a
root cause or authorization for cleanup, configuration changes or restart.

## Recorded topology

> [!IMPORTANT]
> These are recorded topology facts. Revalidate host state before treating them as live; update source and evidence when the topology changes.

### Networks

| Network                 | Subnet        | Purpose                                     |
| ----------------------- | ------------- | ------------------------------------------- |
| `bridge`                | 172.17.0.0/16 | Default Docker bridge (unused)              |
| `sparkstack-net`        | 172.19.0.0/16 | Shared network for all user-facing services |
| `vllm-network`          | 172.18.0.0/16 | Gateway + prometheus only                   |
| `monitoring_monitoring` | 172.20.0.0/16 | Monitoring stack                            |
| `openclaw_default`      | 172.21.0.0/16 | OpenClaw internal                           |

### Container → Network Memberships

| Container                     | NetworkMode             | Networks                                            |
| ----------------------------- | ----------------------- | --------------------------------------------------- |
| `main_solo`                   | `sparkstack-net`        | sparkstack-net                                      |
| `embedding_solo`              | `sparkstack-net`        | sparkstack-net                                      |
| `litellm`                     | `vllm-network`          | vllm-network, sparkstack-net                        |
| `openclaw-openclaw-gateway-1` | `openclaw_default`      | openclaw_default, sparkstack-net                    |
| `prometheus`                  | `monitoring_monitoring` | monitoring_monitoring, sparkstack-net, vllm-network |
| `alloy`                       | `monitoring_monitoring` | monitoring_monitoring, sparkstack-net               |
| `nv-monitor`                  | `monitoring_monitoring` | monitoring_monitoring                               |
| `grafana`                     | `monitoring_monitoring` | monitoring_monitoring, sparkstack-net               |
| `vllm-progress-manager`       | `monitoring_monitoring` | monitoring_monitoring, sparkstack-net               |

| `tempo` | `monitoring_monitoring` | monitoring_monitoring, sparkstack-net |
| `cloudflared` | `sparkstack-net` | sparkstack-net |

### Key Routing Paths

- **OpenClaw → LLM**: openclaw-gateway → `litellm:4000` (via sparkstack-net) → backend
- **litellm → main_solo**: Uses direct container hostname `main_solo:8001` on shared `sparkstack-net` network
- **litellm → embedding_solo**: Uses direct container hostname `embedding_solo:8002` on shared `sparkstack-net` network

> **Note:** Legacy stacks may still reference `host.docker.internal`. See Rule 2 below for why this is prohibited.

### OpenClaw Volume Architecture

| Source (Host)             | Destination (Container)   | Origin                        | Purpose                                        |
| ------------------------- | ------------------------- | ----------------------------- | ---------------------------------------------- |
| `/path/to/host/.openclaw` | `/home/node/.openclaw`    | `openclaw/docker-compose.yml` | Native config access for the `node` process    |
| `/path/to/host/.openclaw` | `/path/to/host/.openclaw` | `docker-compose.override.yml` | DooD identical volume map for sandbox creation |

## Common Gotchas & Silent Failures

This is a distilled list of commonly encountered issues and silent failures extracted from the incident log. Keep these in mind when debugging or modifying the Spark Stack infrastructure:

### 1. Networking & Connectivity

- **Avoid `host.docker.internal` on Shared Networks:** If containers share a Docker network (e.g., `sparkstack-net`), ALWAYS route traffic using direct container hostnames (e.g., `main_solo:8001`). Using `host.docker.internal` forces traffic through Docker's hairpin NAT, which frequently fails with `ConnectionResetError`s.
- **Verify the Process Before the Network:** A container showing as "running" does not mean the service inside is alive. If `vllm` crashes but the container entrypoint is `sleep infinity`, the container stays up. Always run `docker exec <container> ss -tlnp` and check logs (`tail /tmp/sparkrun_serve.log`) before assuming a network issue.
- **Never Bind-Mount `/etc/resolv.conf`:** Mounting the host's `resolv.conf` into a container overwrites Docker's embedded DNS server (`127.0.0.11`), blinding the container to internal service discovery.

### 2. Docker-Out-Of-Docker (DooD) Paths

- **Identical Volume Maps are Required:** When OpenClaw or an orchestrator container mounts `/var/run/docker.sock` to manage other containers (sandboxes), it passes path bindings to the host Docker daemon. If you pass container-local paths (like `/home/node/...`), the host daemon won't find them and will silently mount empty, root-owned directories. **Always rewrite internal configurations to use absolute Host paths.**
- **Purge Stale Sandboxes:** If you change volume or network policies, you must explicitly purge old sandbox containers (`docker rm -f openclaw-sbx-*`). The gateway does not automatically update existing container `HostConfigs`.
- **Sandbox Secret Resolution (Embedded Agent Crashing):** When you configure a skill to use an `env` SecretRef (e.g., `{"source": "env", "id": "GOPLACES_API_KEY"}`), the OpenClaw Secret Manager will attempt to resolve it from the local environment. Because the agent executes inside an isolated *sandbox container*, not the main gateway, an `unresolved SecretRef "env:default:GOPLACES_API_KEY"` error means the environment variable is missing *from the sandbox's environment*. You must explicitly inject these keys into `agents.defaults.sandbox.docker.env` within `openclaw.json` so the sandboxed agent's Secret Manager can successfully resolve the reference.

### 3. Configuration Drift & Agent State

- **Sync All Configuration Layers:** OpenClaw maintains agent-specific `models.json` overrides (e.g., `~/.openclaw/agents/<name>/agent/models.json`) which take precedence over the global `openclaw.json`. Modifying the global config without updating the agent overrides leads to silent configuration drift.
- **Stale Agent Config Drift:** Agent-level `models.json` overrides (`~/.openclaw/agents/<name>/agent/models.json`) take precedence over the global `openclaw.json`. If these go stale after a registry sync, agents silently use outdated `maxTokens`, API type, or capability flags. Run `openclaw doctor --fix` or purge agent overrides after any model configuration change.

### 4. Reasoning Models & `payloads=0` Errors

- **OpenClaw Requires Text Payloads:** OpenClaw's safety layer rejects turns with zero text payload (`payloads=0`). If a reasoning model spends all its context on "thinking" (`reasoning_content`) and outputs an empty `content` field, OpenClaw will crash the turn with `stopReason=stop payloads=0` or `stopReason=length payloads=0`.
- **Match Reasoning Configurations:** Do not arbitrarily set `reasoning: true` in `openclaw.json` unless the backend's tool parser and model are specifically configured to stream `reasoning_content` natively.
- **Don't Constrain Context:** Give reasoning models massive context windows (`maxTokens`). Setting a low ceiling guarantees they will hit artificial cutoffs during extensive reasoning traces.

### 5. Memory & vLLM Resource Exhaustion

- **System RAM vs. VRAM OOMs:** OOM kills during the "Resolving architecture" phase with the vLLM V1 engine are usually caused by **Host system RAM** exhaustion, not GPU VRAM. The V1 Ray DAG compilation requires massive CPU memory.
- **Watch `max_model_len`:** Context window sizes exponentially scale system RAM requirements. Never assume remote registry recipes have safe default limits for your hardware. If a recipe defaults to `262144`, and you only have 120GB of system RAM, you must explicitly override `max_model_len` (e.g., `131072`) in your `stack.yaml`.

### 6. Zombie Tasks & Locked Sessions

- **SQLite Task Database Locks:** If an agent completely stops responding to messages, check for "zombie" tasks. If the gateway crashes hard, it can leave `running` state markers in the SQLite task database (`/home/node/.openclaw/tasks/runs.sqlite`), which permanently blocks future requests for that session.
- **Orphaned Host Processes:** If you encounter 500 errors regarding model APIs, check the host machine for orphaned `litellm` processes (`ps aux | rg litellm`) that might be colliding with containerized routing tables.

### 7. Context Overflow & Event Loop Starvation

- **Gateway Single-Threaded Sensitivity:** The OpenClaw gateway is a single-threaded Node.js event loop. Any synchronous hot loop (like repeated context compaction attempts) will starve ALL other operations — Telegram hooks, WebSocket handlers, health probes, and other agent sessions all freeze.
- **Irreducible Context Overflow:** If an agent's system prompt alone (skills, plugins, injected context) exceeds the model's context window, compaction cannot help — it only removes session *history* messages. Without the `irreducible_overflow` circuit breaker (added in `local-dev`), each message to the agent triggers 3 compaction cycles × ~20s each, then a session reset, then the cycle repeats on the next message — effectively DoS-ing the entire gateway.
- **Diagnosis:** Look for `[context-overflow-precheck] route=compact_only` log lines repeating in rapid succession. If `estimatedPromptTokens` consistently exceeds `promptBudgetBeforeReserve` even with 0 history messages, the overflow is irreducible.
- **Fix:** Reduce the number of active skills/plugins for the agent, or switch to a larger-context model.

