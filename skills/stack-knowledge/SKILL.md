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
- proxy-tier routing
- vllm-gateway network
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
| `proxy-tier`            | 172.19.0.0/16 | Shared network for all user-facing services |
| `vllm-network`          | 172.18.0.0/16 | Gateway + prometheus only                   |
| `monitoring_monitoring` | 172.20.0.0/16 | Monitoring stack                            |
| `openclaw_default`      | 172.21.0.0/16 | OpenClaw internal                           |

### Container → Network Memberships

| Container                     | NetworkMode             | Networks                                        |
| ----------------------------- | ----------------------- | ----------------------------------------------- |
| `main_solo`                   | `proxy-tier`            | proxy-tier                                      |
| `embedding_solo`              | `proxy-tier`            | proxy-tier                                      |
| `vllm-gateway`                | `vllm-network`          | vllm-network, proxy-tier                        |
| `openclaw-openclaw-gateway-1` | `proxy-tier`            | proxy-tier                                      |
| `prometheus`                  | `monitoring_monitoring` | monitoring_monitoring, proxy-tier, vllm-network |
| `grafana`                     | `monitoring_monitoring` | monitoring_monitoring, proxy-tier               |
| `cloudflared`                 | `proxy-tier`            | proxy-tier                                      |

### Key Routing Paths

- **OpenClaw → LLM**: openclaw-gateway → `vllm-gateway:4000` (via proxy-tier) → backend
- **vllm-gateway → main_solo**: Currently configured as `host.docker.internal:8001` in litellm-config.yaml
- **vllm-gateway → embedding_solo**: Currently configured as `host.docker.internal:8002` in litellm-config.yaml

### `host.docker.internal` Resolution

`host.docker.internal` resolves to `172.17.0.1` (the docker0 bridge gateway IP), NOT the host's real IP. This is set via `extra_hosts: host.docker.internal:host-gateway` in the gateway's docker-compose.yaml.

### OpenClaw Volume Architecture

| Source (Host)              | Destination (Container)    | Origin                        | Purpose                                        |
| -------------------------- | -------------------------- | ----------------------------- | ---------------------------------------------- |
| `/path/to/host/.openclaw` | `/home/node/.openclaw`     | `openclaw/docker-compose.yml` | Native config access for the `node` process    |
| `/path/to/host/.openclaw` | `/path/to/host/.openclaw`  | `docker-compose.override.yml` | DooD identical volume map for sandbox creation |

## Technical References

Model-specific quirks, engine optimizations, and hardware-specific configurations are documented in the `references/` directory:

- **Deployment Protocol**: [skills/stack-manager/references/plan-template.md](../stack-manager/references/plan-template.md)
- **Model Quirks**: `skills/stack-knowledge/references/*.md` (e.g. `cascade-2-30b-nvfp4.md`, `nemotron-3-super.md`)

## Hard Rules

These rules are distilled from real incidents. They are non-negotiable.

### Rule 1: Verify the Process Before Touching the Network

> **Before touching any network configuration, verify the target process is alive.**

The single most expensive debugging mistake in this repo's history was spending 45+ minutes chasing networking hypotheses when the vllm backend process had silently crashed inside its container. The container stayed "running" because `sleep infinity` was the entrypoint.

**The diagnostic that should always be run first:**

```bash
docker exec <container> tail -n 20 /tmp/sparkrun_serve.log
```

### Rule 2: Use Container Names on Shared Networks, Not `host.docker.internal`

When containers share a network (e.g., `proxy-tier`), route traffic using **direct container names**. `host.docker.internal` routing depends on Docker's hairpin NAT which can and does fail with `ConnectionResetError`.

```yaml
# WRONG (fragile — hairpin NAT):
api_base: http://host.docker.internal:8001/v1

# CORRECT (direct routing on shared proxy-tier network):
api_base: http://main_solo:8001/v1
```

### Rule 3: Never Bind-Mount `/etc/resolv.conf`

Bind-mounting the host's `/etc/resolv.conf` into a container (`/run/systemd/resolve/resolv.conf:/etc/resolv.conf:ro`) forcibly overrides Docker's embedded DNS server (`127.0.0.11`). This blinds the container to Docker-internal service discovery.

Let Docker natively inject its `127.0.0.11` resolver.

### Rule 4: Never Use Magic IPs

Never use internal Docker IPs (e.g. `172.19.x.x`) in configuration, verification, or benchmarking. Use hostnames (`main_solo`) or route through the proxy (`localhost:4000`).

### Rule 5: Read the Actual Error Before Hypothesizing

Do not invent networking hypotheses from symptoms. Find the actual error message in the logs first. `LLM request failed: network connection error` does NOT mean the network is broken — the process might simply not be listening.

## Diagnostic Playbook

When a container can't reach another container, run these steps **in order**:

### Step 1: Is the target process alive?

```bash
docker exec <target> tail -n 20 /tmp/sparkrun_serve.log
docker exec <target> ss -tlnp
```

If the process crashed or isn't listening → this is NOT a networking problem.

### Step 2: Are both containers on a shared network?

```bash
docker inspect <source> --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
docker inspect <target> --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
```

If they share a network → use the container name directly.

### Step 3: Can the source resolve the target?

```bash
docker exec <source> getent hosts <target_name>
```

### Step 4: Can the source reach the target?

```bash
docker exec <source> python3 -c "import urllib.request; print(urllib.request.urlopen('http://<target_name>:<port>/v1/models').read())"
```

### Step 5: Check hairpin NAT (if using host.docker.internal)

```bash
docker exec <source> python3 -c "import socket; print(socket.getaddrinfo('host.docker.internal', None))"
docker exec <source> python3 -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:<port>/v1/models').read())"
```

If this fails with `ConnectionResetError [Errno 104]` → hairpin NAT issue. Switch to direct container name routing.

## Incident Log

> [!NOTE]
> Append new entries below using the template. Most recent entries go last.
> **Tip:** You should use the helper script `uv run python skills/stack-knowledge/scripts/append_incident.py` to interactively append your log accurately without mangling previous entries.
> Every entry must include: date, scenario, hypothesis, action taken, result, and learnings.

### Template

```markdown
## YYYY-MM-DDTHH:MM — <Short Title>

- **Scenario**: What was observed
- **Hypothesis**: What was suspected
- **Action**: What was done
- **Result**: What actually happened (include whether the hypothesis was correct or wrong)

**Learnings:**

- Bullet-pointed takeaways that future agents should know
```

### 2026-04-10T12:38 — Changed litellm backend URLs to host.docker.internal

- **Scenario**: OpenClaw agent sessions were failing. The vllm-gateway couldn't reach sparkrun model backends.
- **Hypothesis**: sparkrun launches containers on host network, making them unreachable via Docker-internal DNS from the bridge-networked gateway. Using `host.docker.internal` would route through the host's port bindings.
- **Action**: Changed `build_stack.py` to generate litellm config with `host.docker.internal:PORT` instead of container hostnames.
- **Result**: Appeared to work initially. Chat completions returned 200 OK from the host. **Hypothesis was wrong** — the containers were actually on `proxy-tier` bridge, not host network.

**Learnings:**

- Did NOT verify connectivity from inside vllm-gateway container — only tested from host
- Did NOT check what network mode sparkrun actually put the containers on
- Assumed sparkrun uses host network based on previous session context, never verified

### 2026-04-10T13:25 — Changed openclaw sandbox workspaceAccess to "rw"

- **Scenario**: OpenClaw gateway logs showed `[tools] write failed: Sandbox path is read-only`
- **Hypothesis**: `workspaceAccess: "none"` in openclaw.json was preventing sandbox containers from writing files
- **Action**: Changed `workspaceAccess` from `"none"` to `"rw"`, restarted gateway, killed old sandbox containers
- **Result**: New sandbox containers now mount `/workspace` with `RW: true`. **This was a real fix** but unrelated to the agent timeout.

**Learnings:**

- Sandbox containers (`openclaw-sbx-*`) use `networkMode: none` — completely isolated, no networking
- The workspace access fix was correct but did not address the actual agent timeout issue

### 2026-04-10T13:40 — Changed tools.exec.timeoutSec from 30 to 300

- **Scenario**: Agent still stuck in `processing` state after sandbox fix
- **Hypothesis**: The 30s exec timeout was killing tool calls mid-stream, which caused the LLM loop to break
- **Action**: Bumped `tools.exec.timeoutSec` to 300 in openclaw.json
- **Result**: **Wrong diagnosis.** The actual error in the logs was `LLM request failed: network connection error. rawError=Connection error.` — the gateway literally cannot reach the LLM backend. Shell timeouts are irrelevant.

**Learnings:**

- Read the actual error message before hypothesizing
- `tools.exec.timeoutSec` controls sandbox shell command duration, not LLM request timeouts
- The agent timeout was caused by the LLM backend being unreachable, not by tool execution limits

### 2026-04-10T13:43 — Diagnosed actual connectivity failure

- **Scenario**: vllm-gateway returns `InternalServerError: Connection error` when proxying to backends
- **Hypothesis**: `host.docker.internal:8001` from inside vllm-gateway can't reach the sparkrun model container
- **Action**: Systematic testing from inside vllm-gateway:
  1. `host.docker.internal` resolves to `172.17.0.1` (docker0 bridge) — confirmed
  1. `urllib.request.urlopen('http://host.docker.internal:8001/...')` → **ConnectionResetError [Errno 104]**
  1. `urllib.request.urlopen('http://main_solo:8001/...')` → **ConnectionRefused [Errno 111]**
  1. From host: `curl localhost:8001/v1/models` → **200 OK** (works through Docker port publishing)
  1. Both `vllm-gateway` and `main_solo` are on `proxy-tier` network
- **Result**: Docker hairpin NAT causes `ConnectionResetError`. Direct container name fails because vllm process inside `main_solo` crashed silently (`ValueError: KV cache too small`).

**Learnings:**

- `host.docker.internal` routing is fragile — it depends on Docker's hairpin NAT which can fail
- When containers share a network (proxy-tier), use direct container names for routing
- The vllm process crashed silently — the container stayed "running" because `sleep infinity` was the entrypoint, masking the actual failure
- Always check `ss -tlnp` or equivalent inside the target container to verify the process is actually listening
- The `update_services` script may have restarted containers with parameters that exceed available GPU memory

### 2026-04-10 Retrospective — None of this was a networking problem

- **Scenario**: Full retrospective of the debugging session
- **Hypothesis**: N/A — retrospective analysis
- **Action**: Reviewed entire debugging timeline
- **Result**: The OpenClaw agent was timing out because **the vllm backend process crashed** (KV cache OOM). The container stayed "running" because sparkrun's entrypoint is `sleep infinity` with vllm as a background child process.

**Learnings:**

Every networking change made during this session was chasing a phantom:

1. Changing backend URLs to `host.docker.internal` — unnecessary, containers share `proxy-tier`
1. Changing sandbox `workspaceAccess` — real fix, but unrelated to the agent timeout
1. Changing `tools.exec.timeoutSec` — wrong diagnosis entirely
1. Investigating hairpin NAT — real phenomenon but not the cause; vllm wasn't listening

**The diagnostic that should have been run first:**

```bash
docker exec main_solo tail -n 20 /tmp/sparkrun_serve.log
```

This would have immediately shown the crash. Instead, 45+ minutes were spent on networking hypotheses.

## DONE — Correct Architecture (Fixed 2026-04-24)

`build_stack.py` now generates **direct container names on proxy-tier** for `litellm-config.yaml`:

```yaml
# build_stack.py now generates:
api_base: http://main_solo:8001/v1
api_base: http://embedding_solo:8002/v1
```

This eliminates the Docker hairpin NAT issue entirely. Both containers are on proxy-tier and can reach each other directly.

### 2026-04-12T13:50 — Integration Test Hard-Freeze on host.docker.internal

- **Scenario**: The `pytest tests/e2e/` end-to-end integration test completely froze for 3 hours at "Loading host.docker.internal... 0%".
- **Hypothesis**: The underlying `vllm` backend processes had crashed out of memory or failed to load tensor parallel blocks.
- **Action**: Interrogated the native container loop using `docker exec main_solo tail -n 20 /tmp/sparkrun_serve.log` and revealed full health and hundreds of HTTP 200 polls over 3 hours. Then audited the `tests/e2e/utils.py` polling routine `get_active_services` to see why it could not read the 100% telemetry status.
- **Result**: `get_active_services` scrapes `litellm-config.yaml` to derive container names via the URL. Because the stack uses `host.docker.internal` as the cross-platform proxy bypass, the integration tester literally passed the string `"host.docker.internal"` to the progress-manager dictionary lookup. The daemon obviously indexes targets by their exact container name (`main_solo`), locking the polling script into tracking a non-existent container forever. I hard-excluded `host.docker.internal` from being parsed as a fallback container string.

**Learnings:**

- Just because a downstream monitor says 0% readiness does not guarantee the upstream target is dead. Integration proxies parse keys strictly. The daemon correctly indexed `main_solo`, but tests queried `host.docker.internal`.
- Always verify container health directly with `ps aux` and `tail` before assuming a workload fault.

### 2026-04-15T18:30 — OpenClaw Sandbox Freeze vs DooD Path Crash

- **Scenario**: Agents kept losing read/write access to their sandboxes. When `workspaceAccess` was manually hardcoded to `"rw"`, the agents suddenly crashed and timed out when evaluating tools.
- **Hypothesis**: `setup.sh` defaults to generating `"workspaceAccess": "none"`. If restored to `"rw"`, the Gateway executes a Docker-out-of-Docker (DooD) mount explicitly. However, because `setup.sh` generates container-local path topologies (`/home/node/...`), the Host-side Docker daemon evaluates that path literally, finds it missing on the Host, and mounts empty, root-owned substitute directories. The Sandbox cannot see the Gateway's heartbeat files, causing silent session timeouts.
- **Action**: Injected dual logic inside `update_openclaw.py`: (1) Explicitly lock `workspaceAccess: rw`; and (2) Recursively sweep the schema to rewrite `/home/node/` back to identical Host-absolute strings.
- **Result**: The sandboxes launch flawlessly. The identical mappings successfully traverse the DooD boundary, delivering functional RW access to the agents.

**Learnings:**

- Any Docker-out-of-Docker implementation demands exact Host namespace consistency. Inner-container paths passed to a Docker socket will break catastrophically but silently on the other side.
- Be careful with orchestrator default setups (like `setup.sh`). Do not fight them continually on every build; decouple them. For example, `update_openclaw.py` delegates `setup.sh` strictly to a manual `--run-setup [sandbox|standard]` mode, and surfaces the generated compose fragments to the repo root to prevent configuration overwrite loops.

### 2026-04-16T08:50 — OpenClaw Sandbox Containers Lacking Internet Access

- **Scenario**: OpenClaw sandbox containers were isolated from the internet by default, preventing agents from making external network requests or downloading tools.
- **Hypothesis**: The default sandbox configuration inside `openclaw.json` (often injected by `setup.sh`) applies `"network": "none"` for maximum isolation. Switching it to `"bridge"` restores default Docker NAT routing to the internet.
- **Action**: Modified `update_openclaw.py` to securely enforce `docker_conf["network"] = "bridge"` on deployment. After pushing the config, killed the old `openclaw-sbx-*` containers so OpenClaw reconstructs them from scratch.
- **Result**: Agent sandboxes successfully attach to the `bridge` network upon recreation, instantly enabling persistent egress internet access natively.

**Learnings:**

- OpenClaw sandbox containers default to zero egress (`network: none`).
- To adjust sandbox baseline properties persistently, map those properties firmly inside the `update_openclaw.py` injection process; direct host edits to `openclaw.json` are fragile because any explicit run of `setup.sh` (e.g., via `--run-setup`) will violently overwrite sandbox and network default settings.
- Stale agent sandbox containers must be purged explicitly and completely (`docker rm -f`) so the gateway regenerates them with new network or volume policies upon next invocation.

### 2026-04-17T17:50 — OpenClaw Split-Brain Session Persistence

- **Scenario**: `openclaw doctor` continuously reported: "Multiple state directories detected. This can split session history. ~/.openclaw vs Active state dir: /path/to/host/.openclaw".
- **Hypothesis**: Because the internal `openclaw-gateway` container executes natively as `node`, its fallback string for `~/.openclaw` implicitly targets `/home/node/.openclaw`. While major sandbox/log paths were successfully rewritten as Host-absolute to obey identical volume maps, implicit undocumented engine fallbacks (like `.cache` or `.db`) continue slipping into `/home/node/` which is not mapped externally.
- **Action**: Modified `docker-compose.override.yml` to explicitly pass `OPENCLAW_STATE_DIR=${OPENCLAW_CONFIG_DIR}` into the gateway's environment payload, forcing the engine's hidden fallbacks onto the bound volume.
- **Result**: Injecting `OPENCLAW_STATE_DIR` correctly silences the `openclaw doctor` warning and homogenizes all internal container write streams directly onto the explicit identically-bound Docker volume, preventing stateless deletion upon container rebuilds.

**Learnings:**

- Do not ignore split-brain directory diagnostics if one of the targets happens to fall completely outside persistent `volume:` block mount definitions.
- For Dockerized OpenClaw instances running under the `node` user runtime, you should rely on explicitly bounding hidden engine fallbacks via `OPENCLAW_STATE_DIR`, rather than relying on `openclaw.json` property overrides alone.

### 2026-04-18T03:35 — LiteLLM 500 Loop vs Host Process Collision

- **Scenario**: LiteLLM proxy (vllm-gateway) was returning 500 Internal Server Error for `POST /model/new` and `POST /model/delete`. Logged error: `No DB Connected`. Simultaneously, OpenClaw gateway failed to inspect sandbox images due to missing Docker socket access.
- **Hypothesis**: (1) Orphaned `litellm` and `autodiscover` processes on the host were attempting to register models with the containerized LiteLLM. Since the container lacks the virtual-keys database, it failed. (2) The gateway container lacked `/var/run/docker.sock` mount required for DooD sandbox management.
- **Action**: (1) Terminated orphaned host processes using `pkill -f litellm` and `pkill -f autodiscover`. (2) Modified `openclaw/docker-compose.yml` to mount `/var/run/docker.sock:/var/run/docker.sock`. (3) Verified gateway was on `proxy-tier` and binding to `lan`.
- **Result**: LiteLLM 500 loop stopped immediately. Gateway successfully regained control over sandbox image inspection. Connectivity restored end-to-end via Cloudflare.

**Learnings:**

- Host-side "ghost" processes (orphaned litellm/autodiscover) can collide with containerized model management APIs. Always check `ps aux | rg litellm` on the host if model registration fails with 500 errors.
- Docker-out-of-Docker (DooD) configurations MUST have `/var/run/docker.sock` mounted if the containerized service (like OpenClaw Gateway) needs to inspect or create other containers on the host.
- Verification receipts injected into Docker logs are a reliable "proof of life" for restoration tasks.

### 2026-04-18T03:15 — DooD Paradox: Permission Denied Writing to Workspace

- **Scenario**: Agents received "Permission denied writing to workspace" after switching to full tool profile. Investigation revealed the sandbox mounted an empty, root-owned directory at /workspace.
- **Hypothesis**: The Gateway passed container-local paths (/home/node/...) to the host Docker daemon via the socket. The host daemon evaluated these against the host FS where they did not exist, leading to dummy mounts.
- **Action**:
  1. Updated `scripts/update_openclaw.py` to robustly rewrite all internal `/home/node` and `~` paths in `openclaw.json` to identical host-absolute paths.
  1. Verified the gateway has an Identical Volume Map for the state directory.
  1. Purged stale `openclaw-sbx-*` containers to force recreation with correct binds.
- **Result**: **Correct.** New sandboxes correctly mount the host workspace directory with RW permissions. Agents can now persist state.

**Learnings**:

- Even if a container image defaults to `/home/node`, the configuration *passed to Docker* for volume mounts must be Host-absolute to survive the DooD boundary.
- Always purge old sandbox containers when changing volume or network policy; the gateway does not auto-update existing container HostConfigs.

### 2026-04-18T03:30 — Zombie Tasks and Stuck Sessions

- **Scenario**: Telegram agent stopped responding. Logs showed "stuck sessions" in `state=processing` and `status --deep` reported 5 active tasks, but `tasks list` showed no active work.
- **Hypothesis**: The gateway crashed or was forcefully restarted, leaving "running" state markers in the SQLite task database (`/home/node/.openclaw/tasks/runs.sqlite`). These zombie markers blocked new requests in those sessions.
- **Action**:
  1. Restarted the gateway container to clear in-memory locks.
  1. Manually updated the SQLite database from the host: `UPDATE task_runs SET status = 'failed', error = 'Zombie task detected...' WHERE status = 'running'`.
  1. Verified `status --deep` now shows 0 active tasks.
- **Result**: **Correct.** The agent immediately resumed processing Telegram messages.

**Learnings**:

- `status --deep` reads from the task database, which can contain stale "running" entries if the gateway did not shut down gracefully.
- If an agent is not responding and logs mention "stuck sessions", check the task database for zombie runs.

### 2026-04-18T13:20 — Dockerfile Optimizatons: Layer Bloat, Permissions, & Security

- **Scenario**: The `Dockerfile.sandbox-custom` image build was suffering from slow duplicate apt-updates, `curl | bash` security risks, and permission denied errors for unprivileged users trying to run native `uv` tools.
- **Hypothesis**: The Dockerfile had layered operations organically but inefficiently: (1) Multiple `apt-get update` blocks, (2) Global `ENV` variable hijacking for `uv`, and (3) Blind binary installations.
- **Action**:
  1. Consolidated all external Apt keyrings (GitHub, Docker, Google Cloud) into a small top layer, and crushed all subsequent packages into a **single** `apt-get update && apt-get install` command.
  1. Changed `ENV UV_TOOL_DIR=/opt...` to an inline prefix `RUN UV_TOOL_DIR=/opt... uv tool install`.
  1. Replaced `npm install -g bun` with `COPY --from=oven/bun:1 /usr/local/bin/bun /usr/local/bin/bun`.
  1. Gutted `curl | bash` for Opencode and replaced it with an explicit Github Release asset extraction via `tar`.
- **Result**: **Successful.** The container build time dropped drastically due to single apt cache layers. The `sandbox` user regained standard `$HOME/.local/` pathing for personal `uv` operations without triggering root permission denied errors, and two unverified web scripts were removed from root execution.

**Learnings**:

- **Apt-get Layering**: Never chain multiple `apt-get install` blocks separated by lines of config. Run a prerequisites layer (curl, gnupg), fetch your keys, and then execute a single unified `apt-get update && apt-get install` to optimize caching and shrink image bloat.
- **Environment Hijacking**: Never globally export `ENV` paths intended only for a one-time build step. Polluting `ENV` persists to unprivileged users; inject those variables locally to the `RUN` command instead.
- **Multi-Stage Trumps Package Managers**: Always use `COPY --from=image:tag` to inject binaries (like Node, Go, or Bun) rather than executing `npm install -g` or `apt-get`. It avoids enormous wrapper bloat and registry delays.
- **No Blind Piped Execution**: Never use `curl https://... | bash` in a Dockerfile. Find the exact asset URL (e.g., `tar.gz`) from the GitHub release API and extract the binary securely.

### 2026-04-18T18:25 — LLM request failed: network connection error (ConnectionResetError via Litellm)

- **Scenario**: Agents failed to run models via the Litellm proxy. OpenClaw logged `LLM request failed: network connection error. rawError=500 litellm.InternalServerError: InternalServerError: OpenAIException - Connection error..`.
- **Hypothesis**: The litellm gateway (vllm-gateway) was sending requests to the `sparkrun` proxy containers (`main_solo` and `embedding_solo`) using `http://host.docker.internal:PORT`, violating the container-direct communication rule and invoking Docker's hairpin NAT. This led to intermittent ConnectionResetErrors.
- **Action**: Modified `litellm-config.yaml` to point `api_base` to the direct container network hostnames (`http://main_solo:8001/v1` and `http://embedding_solo:8002/v1`). Restarted `vllm-gateway` and `openclaw-gateway-1`.
- **Result**: **Successful.** The hairpin NAT traversal was eliminated, and all OpenClaw requests now safely land on the model endpoints across the shared `proxy-tier` network.

**Learnings**:

- When setting up downstream configuration files (like `litellm-config.yaml`), NEVER use `host.docker.internal` if the target containers share a Docker network (e.g., `proxy-tier`).
- Direct container names ensure robust, DNS-native service discovery and bypass the host network stack, eliminating the risk of unexplainable 500 reset errors.

### 2026-04-18T19:44 — Lost Agent Write Access via Pydantic Validator Removal

- **Scenario**: Agents received "Permission denied writing to workspace" errors in their sandboxes.
- **Hypothesis**: The removal of Pydantic schema validation inside `update_openclaw.py` unintentionally removed the logic that consistently rewrites internal `/home/node/` and `~` paths to absolute Host-paths before deploying `.openclaw/openclaw.json`. Without that active rewriting logic, the configuration naturally preserved the string `~/.openclaw/workspaces/...`. Because the sandbox lifecycle executes inside the gateway container (which runs as user `node`), this resolved to `/home/node/...` natively. Upon passing this path through the Docker socket (DooD) for the sandbox mount, the host daemon found no `/home/node/` workspace and silently substituted an empty, root-owned directory, stripping agent write permissions.
- **Action**: Performed a manual surgical text rewrite inside `~/.openclaw/openclaw.json` to hardcode absolute Host paths (replacing `"workspace": "~/.openclaw/..."` with `"workspace": "/absolute/path/to/host/.openclaw/..."`).
- **Result**: **Successful**. Absolute host-side paths correctly bind against the host filesystem, restoring read/write privileges.

**Learnings**:

- Bypassing heavy validations allows surgical JSON edits but removes structural safety nets that might implicitly rewrite Docker volume paths into Host-absolute context.
- When decoupling deployments from orchestrators, you MUST ensure that sandbox workspace binds inside `openclaw.json` strictly specify absolute host-side paths.
- Avoid `~` syntax inside Docker bind configs because runtime evaluation ownership (`node` vs host user) will skew the expected execution path during Docker-out-of-Docker evaluation.

### 2026-04-19T11:20 — Telegram 400 Error vs Qwen Protocol Mismatch

- **Scenario**: Telegram agent returned "Something went wrong" for all requests. Logs showed 400 Bad Request from vLLM backend.
- **Hypothesis**: The stack builder was hardcoding `thinkingFormat: qwen-chat-template` for all reasoning models. vLLM (running Gemma 4) rejected the Qwen-specific `chat_template_kwargs` parameter.
- **Action**:
  1. Updated `core/builders/litellm.py` to support explicit `thinking_format` overrides from recipes.
  1. Modified Gemma and Nemotron recipes to explicitly set `thinking_format: openai`.
  1. Implemented the "Zombie Protocol" in `update_services.py` to clear stuck tasks causing session locks.
- **Result**: **Successful**. Gemma 4 now uses standard OpenAI protocols, and Telegram sessions are no longer blocked by zombie task markers.

**Learnings**:

- Protocol mismatches (sending Qwen params to Gemma) result in immediate 400 errors that block the entire session.
- Always use explicit `thinking_format` in recipes for reasoning-enabled models to avoid builder-side guessing.
- Session locks in messaging channels are often caused by "running" state markers in the SQLite task database surviving gateway crashes.

### 2026-04-19T19:55 — Cloudflare Tunnel Crash vs Missing Environment

- **Scenario**: The `cloudflared` container was stuck in a `Restarting (255)` loop. Logs reported: `"cloudflared tunnel run" requires the ID or name of the tunnel to run as the last command line argument or in the configuration file.`
- **Hypothesis**: The container was started without the `CLOUDFLARE_TUNNEL_TOKEN` environment variable, likely due to running `docker compose` in the `cloudflare/` directory without specifying the root `.env` file where the token is defined.
- **Action**: Restarted the container using the helper script `cloudflare/tunnel.sh up -d --force-recreate`, which explicitly passes the parent `.env` file to the docker compose command.
- **Result**: **Successful.** The container successfully received the token, authenticated with Cloudflare, and established the tunnel connections.

**Learnings:**

- Always use the provided helper scripts (like `tunnel.sh`) when they exist, as they often handle complex environment or path mappings required for the stack.
- Verify container environment variables using `docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}'` to confirm that secrets and tokens are actually being injected.
- A `Restarting (255)` loop with usage errors in the logs is a strong indicator of missing configuration or credentials.

### 2026-04-20T03:50 — Traces Broken via Tempo Localhost Bind

- **Scenario**: Traces were not appearing in Grafana. OpenClaw logs showed OTel was enabled, but Tempo reported 0 spans received.
- **Hypothesis**: Tempo's OTLP receivers were binding to `localhost` inside the container, making them unreachable from the `openclaw-gateway` container even though they shared the `proxy-tier` network.
- **Action**: Modified `monitoring/tempo.yaml` to explicitly bind OTLP HTTP and gRPC receivers to `0.0.0.0`.
- **Result**: **Successful**. Connectivity verified via `curl` from the gateway, and `spans_received_total` metrics began incrementing. Traces are now visible in Grafana.

**Learnings:**

- "Default" bindings in observability tools often target `localhost` for security, which is a "dead end" in multi-container Docker bridge networking.
- Always verify connectivity using a tool inside the *source* container (e.g., `docker exec gateway curl ...`) rather than assuming shared network membership is sufficient.
- Check `tempo_distributor_spans_received_total` in Tempo's `/metrics` endpoint to confirm if the issue is ingestion (network/bind) or storage/query.

### 2026-04-20T04:15 — Tempo Trace Disappearance via 1h Retention

- **Scenario**: Traces were visible in Tempo initially but disappeared within an hour, making it difficult to debug intermittent agent failures.
- **Hypothesis**: The default `block_retention` in `monitoring/tempo.yaml` was set to `1h`, which is too aggressive for human debugging workflows.
- **Action**: Increased `block_retention` to `24h` in `monitoring/tempo.yaml`.
- **Result**: **Successful**. Traces now persist for a full day, allowing for retrospective analysis of agent behavior.

**Learnings:**

- Observability storage parameters must balance disk usage against the expected investigation window. A 1h window is only suitable for real-time dashboards, not retrospective debugging.
- Always check the `compactor` section in Tempo config for retention policies.

______________________________________________________________________

### 2026-04-19T23:41 — Restarted vllm-gateway without VLLM_PORT context

- **Scenario**: Restarting vllm-gateway after enabling OTEL tracing via \`docker compose up\` resulted in the gateway binding to a random port instead of 4000.
- **Hypothesis**: The VLLM_PORT environment variable was missing because \`docker compose\` in the spark-stack-registry/stacks/... directory does not natively traverse upwards to find the repository root \`.env\` file.
- **Action**: Recreated container using \`docker compose --env-file ../../.env up -d gateway\`, adhering to the standard \`launch.sh\` behavior.
- **Result**: Gateway properly inherited the mapping to host port 4000.

**Learnings:**

- Always run \`docker compose\` with \`--env-file ../../.env\` when operating manually inside the active \`spark-stack-registry/stacks/current\` directory to guarantee port bindings map correctly.

### 2026-04-24T07:10 — Dashboard Telemetry Freeze vs Ephemeral Metrics

- **Scenario**: The "SparkRun Cluster Provisioning" Grafana panel was stuck at 66.7% permanently, and other panels exhibited text clipping.
- **Hypothesis**: The dashboard queried `vllm_vllm_sparkrun_deploy_progress`, which is an ephemeral metric emitted via StatsD by the `sparkrun` CLI only during the provisioning phase. Once the CLI exits, the metric goes stale but Prometheus retains the last value. Additionally, `stat` panels with `graphMode: area` and small heights (`h=3`) clip the text.
- **Action**:
  1. Updated dashboard JSONs to use `avg(vllm_model_load_progress) or max(vllm_vllm_sparkrun_deploy_progress)` so it prioritizes the live metric.
  1. Increased panel heights to `h=4` and disabled sparklines (`graphMode: "none"`) for deployment progress panels.
- **Result**: **Successful.** Dashboards now correctly show 100% when models are fully loaded, and no text is clipped.

**Learnings:**

- **Monitoring:** Do not rely on ephemeral CLI-emitted metrics for long-lived dashboard status panels without providing a fallback to a persistent metric. *(Update: Fixed by setting `flush_period_secs: 60` in the Vector `prometheus_exporter` sink so that stale CLI metrics time out automatically, adhering to the original design proposal.)*
- **Grafana Layouts:** `stat` panels displaying percentages require `h >= 4` to prevent clipping, and should avoid `graphMode: area` (sparklines) if historical tracking is not relevant to the displayed value.

### 2026-04-24T07:33 — Hairpin NAT Resolution via Container Names

- **Scenario**: The LiteLLM gateway (`vllm-gateway`) was failing to route traffic to the vLLM backends, resulting in `ConnectionResetError`s.
- **Hypothesis**: `scripts/build_stack.py` was generating `api_base: http://host.docker.internal:8001/v1` for the LiteLLM config, triggering Docker's hairpin NAT limitations on Linux.
- **Action**: Modified `build_stack.py` to use direct container names (`http://main_solo:8001/v1`) since both containers share the `proxy-tier` Docker network.
- **Result**: **Successful.** Gateway reliably routes to the backends with no connection resets.

**Learnings:**

- **Routing:** Always use direct container hostnames when orchestrating services that reside on the same custom Docker network (e.g., `proxy-tier`). *(Update: Added CI test in `test_proxy_integrity.py` to explicitly assert that generated configs never fall back to `host.docker.internal`.)*
- **Code Gen:** Configuration generators (`build_stack.py`) must respect the network topology and not default to `host.docker.internal` for internal-only traffic.

### 2026-04-24T08:15 — Tool Parser Whitelist Conflict (nemotron_json vs qwen3_coder)

- **Scenario**: E2E verification failed on tool calling tests because the vLLM engine rejected the `nemotron_json` parser.
- **Hypothesis**: vLLM has a strict, hardcoded whitelist in `validate_api_server_args` for valid tool parsers. `nemotron_json` was not supported in the active vLLM version.
- **Action**: Updated `nemotron-3-super-nvfp4-vllm.yaml` recipe to use `qwen3_coder` parser instead.
- **Result**: **Successful.** Tool calling tests passed flawlessly.

**Learnings:**

- **Validation:** Tool parser configurations in registry recipes must align with the target vLLM container's specific whitelist. *(Update: Implemented static whitelist validation feature directly in `build_stack.py` to prevent orchestrating containers with invalid parsers.)*
- **Tooling:** Future iterations of `sparkrun` or the stack builder should statically validate the parser argument against the container's known whitelist before attempting deployment.

### 2026-04-26T08:30 — OpenClaw "Incomplete Turn" vs Reasoning Parsers

- **Scenario**: Agents consistently failed with "⚠️ Agent couldn't generate a response" and OpenClaw logs reported "incomplete turn detected: ... payloads=0".
- **Hypothesis**: Reasoning-enabled models (like Cascade2/Nemotron) put 100% of their output into the `reasoning_content` field, leaving the OpenAI `content` field empty. OpenClaw's safety layer rejects zero-payload (empty content) turns as failures.
- **Action**: 
  1. Disabled reasoning in `openclaw.json` as a temporary stability fix.
  2. Research revealed that vLLM's native `nemotron_v3` parser isolates thinking from the answer.
  3. Switched the Cascade2 recipe to use the custom `super_v3_reasoning_parser.py` plugin which moves reasoning to content if the answer is empty.
  4. Enabled `force_nonempty_content: true` in LiteLLM/vLLM overrides.
- **Result**: **Successful**. The agent now provides a valid text payload (containing the thought process) that satisfies OpenClaw's validation, preventing the crash while preserving model intelligence.

**Learnings:**

- **OpenClaw Safety**: OpenClaw requires at least one payload (text/tool) in the `content` bucket. Pure reasoning responses are treated as "incomplete."
- **Hybrid Parsers**: Use the `super_v3` parser for Nemotron/Cascade2 models to ensure the reasoning trace is duplicated or moved into the content field when the model hasn't produced a final answer yet.
- **Configuration Precedence**: Model-specific `reasoning: true/false` in `openclaw.json` must match the backend's parser capabilities to avoid schema-driven recovery loops.

### 2026-04-26T09:35 — Tool Call Leakage and qwen3_xml Parser Transition

- **Scenario**: XML-style function calls (`<function=exec>...</function>`) were leaking into the chat output instead of being intercepted. Additionally, the `vllm-gateway` was crash-looping with `Is a directory: '/app/config.yaml'`, causing sporadic 500 network connection errors in OpenClaw.
- **Hypothesis**: The `qwen3_coder` tool parser and the legacy `super_v3` parser do not correctly intercept `<function>` tags generated by Cascade-2-30B. Furthermore, the gateway volume mount was mapped to a directory rather than the generated `litellm-config.yaml`.
- **Action**: 
  1. Updated `cascade2-30b-nvfp4-vllm.yaml` to use `--tool-call-parser qwen3_xml` and `--reasoning-parser nemotron_v3`.
  2. Whitelisted `qwen3_xml` in `scripts/build_stack.py`.
  3. Corrected `compose-litellm.yaml` volume mount from `litellm-settings.yaml` to `litellm-config.yaml`.
- **Result**: **Successful**. The `qwen3_xml` parser correctly intercepts the XML tool calls and converts them to OpenAI tool formats. The gateway configuration is fixed, and E2E tool calling tests pass successfully.

**Learnings:**

- **Parser Matching**: You must match the tool call parser to the exact format the model outputs. For models generating `<function>` XML tags, `qwen3_xml` is the correct parser.
- **Gateway Hygiene**: Ensure `docker-compose` volume mounts point to explicit files, not directories, when replacing configuration files, to prevent `Is a directory` errors.

### 2026-04-26T10:05 — OpenClaw payloads=0 vs Reasoning Content Split

- **Scenario**: OpenClaw agents consistently failed with "⚠️ Agent couldn't generate a response" and logs showed `incomplete turn detected... stopReason=stop payloads=0`. Direct LiteLLM API calls returned `content: null` with all output in `reasoning_content`.
- **Hypothesis**: When `reasoning: true` is set in `openclaw.json`, OpenClaw sends requests in reasoning mode. The vLLM backend (Cascade-2 with `nemotron_v3` reasoning parser) separates thinking from the answer into `reasoning_content` and `content` fields. When the model's internal reasoning consumes all tokens or the model finishes reasoning without producing a final answer, `content` remains `null`. OpenClaw's payload validator requires at least one non-empty text payload and rejects the response.
- **Action**:
  1. Added `merge_reasoning_content_in_choices: true` to `registry/litellm/litellm-settings.yaml` so LiteLLM merges reasoning into content as a fallback.
  2. Patched `~/.openclaw/openclaw.json` to set `reasoning: false` and remove `thinkingFormat` for the main model.
  3. Updated `scripts/build_stack.py` to **never** set `model_info["reasoning"] = True` for the OpenClaw model config, even when a reasoning parser is detected. `supports_reasoning` is still set in the LiteLLM model_info.
- **Result**: **Successful**. The model now returns non-empty `content` in all responses. Tool calling test passes. Consumer readiness test returns content (no more payloads=0).

**Learnings:**

- **OpenClaw reasoning flag**: `reasoning: true` in `openclaw.json` tells OpenClaw to *request* reasoning mode from the LLM, which causes the response to split into `reasoning_content` + `content`. OpenClaw then validates that `content` is non-empty. If the model doesn't produce a final answer (only thinking), `content` stays null and OpenClaw crashes with `payloads=0`.
- **Separation of concerns**: The `supports_reasoning` flag in LiteLLM model_info tells LiteLLM the model *can* reason. The `reasoning` flag in OpenClaw model config tells OpenClaw to *use* reasoning mode. These are independent — you can have a reasoning-capable model without requesting reasoning mode.
- **merge_reasoning_content_in_choices**: This LiteLLM setting ensures that when `content` is empty, reasoning output gets merged into the content field as a safety net. Always enable it for reasoning-capable models.
- **Build system invariant**: The build system must NEVER auto-set `reasoning: true` for OpenClaw model configs based on parser detection. This was the root cause of the regression loop.
