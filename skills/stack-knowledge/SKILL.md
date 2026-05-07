______________________________________________________________________

name: stack-knowledge
description: Centralized technical knowledge base for Spark Stack architectural facts, model-specific quirks, and historical system learnings.
category: documentation
risk: safe
source: local
compatibility: claude-code
triggers:

- docker networking
- container connectivity
- sparkstack-net routing
- litellm network
- fix container DNS
- why can't container reach
- hairpin NAT
- networking debug
- host.docker.internal
- docker.internal.host
- 172.17.0
- 172.18.0
- 172.19.0
- 172.20.0
- 172.21.0
- vlan address
- subnet
- container IP address
- extra_hosts
- host-gateway
- network_mode
- ConnectionResetError
- ConnectionRefusedError
- connection error docker
- resolv.conf

______________________________________________________________________

# stack-knowledge

## Purpose

To serve as the single source of truth for Docker decisions in this repository. This skill is **self-learning**: every networking diagnosis, change, or mistake MUST be appended as a new dated entry so future sessions never repeat past errors.

## Mandatory Protocol

### Before ANY Networking Change

1. **Activate the `docker-expert` skill**, then read this entire skill top-to-bottom. Every section, every incident.
1. **Identify DooD vs DinD Pathing Requirements**: Before modifying path mappings, check if an orchestrator uses Docker-out-of-Docker (mounting `/var/run/docker.sock`). If so, the orchestrator's config MUST use _Host absolute paths_ for any targets it passes to the daemon. If the orchestrator _also_ accesses those targets natively via its own FS bridge, you MUST implement an **Identical Volume Map** (`- /path:/path`) for the orchestrator container so it shares the Host's path string natively.
1. **Verify the target process is alive** before touching network config:
   ```bash
   docker exec <container> tail -n 20 /tmp/sparkrun_serve.log
   ```
1. **Verify the container is actually listening** on the expected port:
   ```bash
   docker exec <container> ss -tlnp
   ```
1. **Map the container's network memberships** against the topology below:
   ```bash
   docker inspect <container> --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
   ```

### After ANY Networking Change

1. **Append a new dated entry** to this file, documenting the exact symptom, hypothesis, testing performed, and systemic learnings.
1. **Update the topology tables** if network memberships or routing paths changed.
1. **Commit this file** alongside whatever infra change you made.

## Operational Rules

### Debugging & Infrastructure Philosophy

1. **Systematic Debugging:** Always prioritize fixing issues starting from base principles. Adopt a systematic debugging and understanding approach rather than blindly applying band-aid fixes.

### Python Script Execution

1. **Idiomatic Module Execution**:
   - `package = false` in `pyproject.toml` because we do not want to require installs.
   - Scripts MUST NOT contain `sys.path.insert()` hacks.

### OpenClaw Files (Source vs Runtime)

When interacting with OpenClaw, it is critical to distinguish between its immutable source code and its runtime environment:

1. **`../openclaw/` (Source Code)**: This is the upstream, read-only dependency located in the parent directory. NEVER modify files here. This includes source files, base documentation, and master templates. Changes here violate the OpenClaw Modification Ban unless explicitly authorized.
1. **`~/.openclaw/` (Runtime/State)**: This is the active runtime directory. It contains instantiated workspaces, sandboxes, active configuration (`.env`, `openclaw.json`), memory files, and active `BOOTSTRAP.md` copies. All state changes, runtime configurations, and template cleanups must happen here.
1. **OpenClaw CLI**: The primary CLI executable is named `openclaw` and is located at `~/bin/openclaw`. Use this for all host-level configuration and gateway management.

### OpenClaw Agent Sandbox Security

1. **Skill Injection Boundary:** Agents must access bundled skills (`wacli`, `mcporter`, `summarize`) through a strict read-only bind mount directly from the `../openclaw/skills` source directory into the sandbox (`/app/skills:ro`).
1. **State Directory Isolation:** NEVER bind the `~/.openclaw/sandboxes` directory into an agent sandbox. Doing so destroys agent isolation, allowing an agent to traverse the lateral state, sessions, and memory of all other agents in the environment.
1. **Configuration Updates:** Always use the `openclaw config set` CLI (available via `docker exec openclaw-openclaw-gateway-1 openclaw config ...`) to update `openclaw.json` (e.g. adding binds). The JSON must be rigorously validated to avoid dropping critical default behaviors or introducing parsing errors.

## Docker Rigor

- NEVER simply switch a container's network types, IP addresses, or host references without a ground-up evaluation of the intended and correct state of the world. Understand the base principles behind the existing Docker networks and topology first.
- **Before making ANY Docker changes**, activate and review this file. It contains the current topology, past mistakes, and learnings. Add a new dated entry to the skill's Incident Log for every change you make, following the template in the doc.

## Current Topology

> [!IMPORTANT]
> This section is the live reference. Update it when the topology changes.

### Networks

| Network                 | Subnet        | Purpose                                     |
| ----------------------- | ------------- | ------------------------------------------- |
| `bridge`                | 172.17.0.0/16 | Default Docker bridge (unused)              |
| `sparkstack-net`       | 172.19.0.0/16 | Shared network for all user-facing services |
| `vllm-network`          | 172.18.0.0/16 | Gateway + prometheus only                   |
| `monitoring_monitoring` | 172.20.0.0/16 | Monitoring stack                            |
| `openclaw_default`      | 172.21.0.0/16 | OpenClaw internal                           |

### Container → Network Memberships

| Container                     | NetworkMode             | Networks                                             |
| ----------------------------- | ----------------------- | ---------------------------------------------------- |
| `main_solo`                   | `sparkstack-net`       | sparkstack-net                                      |
| `embedding_solo`              | `sparkstack-net`       | sparkstack-net                                      |
| `litellm`                     | `vllm-network`          | vllm-network, sparkstack-net                        |
| `openclaw-openclaw-gateway-1` | `openclaw_default`      | openclaw_default, sparkstack-net                    |
| `prometheus`                  | `monitoring_monitoring` | monitoring_monitoring, sparkstack-net, vllm-network |
| `alloy`                       | `monitoring_monitoring` | monitoring_monitoring, sparkstack-net               |
| `nv-monitor`                  | `monitoring_monitoring` | monitoring_monitoring                                |
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

## Technical References

Model-specific quirks, engine optimizations, and hardware-specific configurations are documented in the `references/` directory:

- **Deployment Protocol**: [skills/stack-manager/references/plan-template.md](../stack-manager/references/plan-template.md)
- **Model Quirks**: `skills/stack-knowledge/references/*.md` (e.g. `cascade-2-30b-nvfp4.md`, `nemotron-3-super.md`)

## Hard Rules

These rules are distilled from real incidents. They are non-negotiable.

### Rule 1: Use Container Names on Shared Networks, Not `host.docker.internal`

When containers share a network (e.g., `sparkstack-net`), route traffic using **direct container names**. `host.docker.internal` routing depends on Docker's hairpin NAT which can and does fail with `ConnectionResetError`.

```yaml
# WRONG (fragile — hairpin NAT):
api_base: http://host.docker.internal:8001/v1

# CORRECT (direct routing on shared sparkstack-net network):
api_base: http://main_solo:8001/v1
```

### Rule 2: Never Bind-Mount `/etc/resolv.conf`

Bind-mounting the host's `/etc/resolv.conf` into a container (`/run/systemd/resolve/resolv.conf:/etc/resolv.conf:ro`) forcibly overrides Docker's embedded DNS server (`127.0.0.11`). This blinds the container to Docker-internal service discovery.

Let Docker natively inject its `127.0.0.11` resolver.

### Rule 3: Never Use Magic IPs

Never use internal Docker IPs (e.g. `172.19.x.x`) in configuration, verification, or benchmarking. Use hostnames (`main_solo`) or route through the proxy (`localhost:4000`).

### Rule 4: Consult Core Specifications Before Generalizing

When making configuration changes to core infrastructure components (like OpenAI API endpoints, OpenClaw properties, or LiteLLM mappings), do not apply generalized LLM heuristics. Always consult the official specification (e.g., OpenAI API docs or the specific backend documentation) to understand default behaviors. For example, the Responses API uses `max_output_tokens` (not `max_tokens`), and its default behavior differs from Chat Completions — omitting it defaults to the model's full context window rather than a fixed limit. Always verify parameter names and defaults against the actual API you are targeting.

### Rule 5: Sync All Configuration Layers

> **When updating model configuration, sync ALL layers — not just the global config.**

OpenClaw resolves model settings with agent-level overrides taking precedence over global defaults. If `sync_registry.py` updates `openclaw.json` but leaves agent-level `models.json` files stale, agents will silently use outdated settings (e.g., wrong `maxTokens`, stale API type, or missing capabilities).

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

## Incident Log

The incident log has grown too large and has been moved to a separate file. Please see [INCIDENT_LOG.md](./INCIDENT_LOG.md) for all historical incidents, and continue to append new entries there.
