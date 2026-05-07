# AGENTS.md

For every new session, you **MUST** do the following:

1. Before making a plan or writing code, ALWAYS use the `grep_search` tool on the `skills/` and `sparkrun/sparkrun-cc-plugin/skills/` directories for keywords related to the user's prompt to identify the correct protocol to follow. (Do NOT try to read all skills at once).
1. Read and strictly follow all rules defined in `.agents/rules/`.
1. Activate local (this repo only) skills: `stack-manager`, `source-dependency-dev`, `monitoring`, `stack-upkeep`, `stack-debugging`
1. When working with Python, Docker, or architecture, explicitly search for and load relevant skills like `python-pro`, `async-python-patterns`, `docker-expert`, and `senior-architect` to apply modern best practices.

## Knowledge and memory.

1. Do not add operational learnings, incident findings, or debugging discoveries to AGENTS.md or GEMINI.md. The static project documentation below is intentional — do not confuse it with accumulated knowledge.
1. Prefer creating or updating skills in the skills/ directory to keep track of learned information, processes or techniques.

______________________________________________________________________

# Project Overview: Spark Services Orchestrator

Spark Services Orchestrator (`sparkstack`) is a high-performance deployment orchestrator for the Spark ecosystem. It manages a suite of AI services, including the **OpenClaw** backend gateway, the **SparkRun** orchestrator, and various local LLM inference stacks (powered by **vLLM**).

The project is designed for Linux hosts, utilizing Docker and Docker Compose for secure service isolation and networking. It focuses on robust, async-first orchestration scripts to manage the full lifecycle of the AI stack.

## Core Technologies

- **Language:** Python 3.13+ (Async-first)
- **Package Manager:** [uv](https://github.com/astral-sh/uv)
- **Containerization:** Docker & Docker Compose V2
- **Key Services:**
  - **OpenClaw:** Backend gateway and API router (Managed as a read-only Git source dependency in ../openclaw).
  - **SparkRun:** Automated orchestration and evaluation (Managed as an editable path source dependency in ../sparkrun).
  - **vLLM:** High-throughput LLM inference backend.
- **Monitoring:** Prometheus, Grafana, and Tempo (Managed via Grafana Alloy).
- **Registry:** `sparkstack-registry` for deployment recipes and model configurations.

## Building and Running

The project is a Python package (`sparkstack`) managed by `uv`. All operations use the unified `sparkstack` CLI.

- **Initialization:**
  ```bash
  make setup  # Synchronizes dependencies and installs pre-commit hooks
  ```
- **Deploying/Updating the Stack:**
  ```bash
  sparkstack update [SERVICES]...   # Full service update orchestration (e.g. sparkstack update openclaw)
  sparkstack update --json          # Same, with JSON-Lines output (headless)
  sparkstack set-current <n>        # Switch active stack and restart services
  sparkstack launch <path>          # Launch services for a specific stack
  sparkstack status                 # Live deployment monitor TUI (connects via UDS)
  ```
- **Building:**
  ```bash
  sparkstack build <recipe> [--gpu-filter <ids>]
  ```
- **Utilities:**
  ```bash
  sparkstack wait                   # Wait for backend models to load
  sparkstack sync-registry          # Sync model registry into OpenClaw
  sparkstack update-monitoring      # Apply monitoring stack updates
  sparkstack check memory           # Audit memory usage vs budget
  sparkstack verify-model <repo>    # Check HF model exists
  sparkstack clear-sessions         # Reset stuck OpenClaw sessions
  ```
- **Stack Verification:**
  ```bash
  uv run pytest tests/e2e/  # Run e2e tests only after you've updated services
  ```

### Headless / Scripted Usage (`--json`)

Most commands accept `--json` to emit structured **JSON-Lines** to stdout instead of
interactive Rich/TUI output. This is the **preferred interface for automated agents
and CI pipelines** — do NOT attempt to parse or navigate the interactive TUI
programmatically.

**Commands supporting `--json`:** `update`, `build`, `wait`, `set-current`, `launch`, `check`, `sync-registry`.

Each line is a self-contained JSON object:

```json
{"event_type": "log", "level": "INFO", "message": "Deploying stack", "timestamp": "...", "service": "vLLM", "phase": "Restarting stack"}
```

**Usage patterns:**

```bash
# Run a full update headlessly, pipe events to jq
sparkstack update --json | jq -r 'select(.level == "ERROR") | .message'

# Wait for backends with structured progress
sparkstack wait --json

# Build and capture result
sparkstack build my-recipe --json > build_events.jsonl
```

When `--json` is active:

- Human-readable Rich progress bars and spinners are suppressed.
- All log events are written as JSON-Lines to **stdout**.
- Errors and debug logs are still written to `update_services.log`.
- The IPC UDS socket (`/tmp/sparkstack.sock`) still broadcasts events for any connected TUI clients.

## Development Conventions

### Source Dependency Policy

- **OpenClaw (`../openclaw/`)**: Treated as a source dependency mainly maintained on the `local-dev` branch, which gets rebased against a tagged stable release. When working with OpenClaw, ensure you are on `local-dev` and follow a similar PR feature integration workflow as SparkRun if modifications are needed.
- **SparkRun (`../sparkrun/`)**: Treated as an editable source dependency. **CRITICAL:** You must ensure the `local-dev` branch is checked out before making any modifications or running tests. You **MUST** strictly follow the "Trunk-Based Feature Integration" workflow documented in the `source-dependency-dev` skill for any `sparkrun` changes (creating feature branches from `main`, merging them into `local-dev`, and rebasing `local-dev` via the orchestration script).

### Scripting Standards

- **Idiomatic Execution**: Use `sparkstack <command>` (or `uv run sparkstack <command>`) for all operations. `package = true` in `pyproject.toml`.
- **Headless Execution**: Always use `--json` when calling `sparkstack` from scripts or automated agents. Never rely on parsing interactive terminal output.
- **Context Awareness**: Scripts should be domain-agnostic and use Pydantic schemas from `core/schemas.py`.

### Planning and Verification

- **Planning**: For tasks related to `stack-manager`, use the templates in `skills/stack-manager/references/plan-template.md`.
- **Verification**: Only run e2e tests (`uv run pytest tests/e2e/`) after you've run `update_services.py`.

## IPC Monitoring Architecture

`sparkstack update` embeds an IPC server broadcasting JSON-Lines events over a UNIX Domain Socket (`/tmp/sparkstack.sock`). There are two ways to consume these events:

1. **Interactive TUI:** `sparkstack status` — a Textual app that connects to the UDS for live dashboard monitoring.
1. **Headless JSON:** `sparkstack update --json` — emits the same events as JSON-Lines to stdout, suitable for piping into `jq`, logging aggregators, or automated agents.

```
sparkstack update (Orchestrator + IPCServer)  ──UDS──▶  sparkstack status (Textual TUI)
                                              ──stdout──▶  --json (JSON-Lines for scripts)
```

- **Protocol:** Newline-delimited JSON over UDS. Event types: `state`, `full_sync`, `log`, `exit`.
- **Headless safe:** When no TUI client is connected, the orchestrator operates identically.
- **IPC Server:** `sparkstack/core/ipc_server.py` — async UDS server with per-client full_sync on connect.

## Directory Structure

- `sparkstack/cli/`: Unified Click CLI entry point (`sparkstack` command).
- `sparkstack/cli/_status.py`: Textual TUI client for live deployment monitoring.
- `sparkstack/core/`: Shared async utilities, health probes, and Pydantic configuration schemas.
- `sparkstack/core/ipc_server.py`: IPC server for UDS event broadcasting during updates.
- `sparkstack/manager/`: High-level orchestration scripts for building, updating, and syncing the stack.
- `services/`: Configuration fragments, `docker-compose.yml` files, and service-specific managers.
- `skills/`: Local AI agent skills (e.g., `stack-manager`, `source-dependency-dev`).
- `../sparkstack-registry/`: Source dependency containing model and stack deployment recipes.
- `tests/`: End-to-end and unit tests (Requires `pytest`).
- `benchmarks/`: Performance testing and evaluation suites.

## Host Configuration

This project requires specific host-level tuning (SSH protection, increased `inotify` limits) to prevent networking conflicts during Docker teardowns. See `DEVELOPMENT.md` for the full setup guide.
