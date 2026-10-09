---

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

---

# stack-knowledge

## Purpose

To serve as the single source of truth for Docker decisions in this repository. This skill is **self-learning**: every networking diagnosis, change, or mistake MUST be appended as a new dated entry so future sessions never repeat past errors.

## Mandatory Protocol

### Before ANY Networking Change

1. **Activate the `docker-expert` skill**, then read this skill and its linked networking context. Retrieve incidents relevant to the symptom and proposed change.
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

## Conditional networking context

For networking diagnosis or changes, read
[network-context.md](references/network-context.md) for recorded topology and
troubleshooting leads, then retrieve the relevant entries from
[INCIDENT_LOG.md](INCIDENT_LOG.md). Historical observations need current
corroboration; container membership and past agent explanations are not proof
of a live service or root cause.

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

## Incident Log

The incident log has grown too large and has been moved to a separate file. Please see [INCIDENT_LOG.md](./INCIDENT_LOG.md) for all historical incidents, and continue to append new entries there.

## Harness upkeep

Use the [shared harness-maintenance workflow](https://github.com/jlapenna/repo-tools/blob/main/plugins/repo-tools/skills/harness-maintenance/SKILL.md), adapted from
[Ryan Lopopolo's field guide](https://github.com/lopopolo/harness-engineering/tree/226c8d35fb6ea3ed55467753dba6dea2b5fd5778). Corroborate a failure with
source and measured evidence before recording a general rule. Put current
invariants in their code/configuration owner and concise skill guidance; keep
chronology in the incident log. Retrieve topology and troubleshooting detail
conditionally instead of expanding always-loaded context.

Follow [ARCHITECTURE.md](../../../ARCHITECTURE.md)'s proof boundary: source-only
documentation maintenance uses non-live checks; infrastructure/configuration
changes retain their full operational verification gates. A documented desired
state or passing static check cannot establish a running model, successful
request or deployed health. No maintenance pass grants new runtime authority.
