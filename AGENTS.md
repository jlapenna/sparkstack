# AGENTS.md

For every new session, you **MUST** do the following:

1. Before making a plan or writing code, ALWAYS use the `grep_search` tool on the `skills/` and `sparkrun/sparkrun-cc-plugin/skills/` directories for keywords related to the user's prompt to identify the correct protocol to follow. (Do NOT try to read all skills at once).
1. Read and strictly follow all rules defined in `.agents/rules/`.
1. Activate local (this repo only) skills: `stack-manager`, `source-dependency-dev`, `monitoring`, `stack-upkeep`, `stack-debugging`
1. When working with Python, Docker, or architecture, explicitly search for and load relevant skills like `python-pro`, `async-python-patterns`, `docker-expert`, and `senior-architect` to apply modern best practices.

## Knowledge and memory.

1. Do not add any learned information to AGENTS.md or GEMINI.md.
1. Prefer creating or updating skills in the skills/ directory to keep track of learned information, processes or techniques.

## Debugging & Infrastructure Philosophy

1. **Systematic Debugging:** Always prioritize fixing issues starting from base principles. Adopt a systematic debugging and understanding approach rather than blindly applying band-aid fixes.

## Python Script Execution

1. **Idiomatic Module Execution**:
   - `package = false` in `pyproject.toml` because we do not want to require installs.
   - Scripts MUST NOT contain `sys.path.insert()` hacks.

## OpenClaw Files (Source vs Runtime)

When interacting with OpenClaw, it is critical to distinguish between its immutable source code and its runtime environment:

1. **`../openclaw/` (Source Code)**: This is the upstream, read-only dependency located in the parent directory. NEVER modify files here. This includes source files, base documentation, and master templates. Changes here violate the OpenClaw Modification Ban unless explicitly authorized.
1. **`~/.openclaw/` (Runtime/State)**: This is the active runtime directory. It contains instantiated workspaces, sandboxes, active configuration (`.env`, `openclaw.json`), memory files, and active `BOOTSTRAP.md` copies. All state changes, runtime configurations, and template cleanups must happen here.
1. **OpenClaw CLI**: The primary CLI executable is named `openclaw` and is located at `~/bin/openclaw`. Use this for all host-level configuration and gateway management.

## OpenClaw Agent Sandbox Security

1. **Skill Injection Boundary:** Agents must access bundled skills (`wacli`, `mcporter`, `summarize`) through a strict read-only bind mount directly from the `../openclaw/skills` source directory into the sandbox (`/app/skills:ro`).
1. **State Directory Isolation:** NEVER bind the `~/.openclaw/sandboxes` directory into an agent sandbox. Doing so destroys agent isolation, allowing an agent to traverse the lateral state, sessions, and memory of all other agents in the environment.
1. **Configuration Updates:** Always use the `openclaw config set` CLI (available via `docker exec openclaw-openclaw-gateway-1 openclaw config ...`) to update `openclaw.json` (e.g. adding binds). The JSON must be rigorously validated to avoid dropping critical default behaviors or introducing parsing errors.

______________________________________________________________________

# Project Overview: Spark Services Orchestrator

Spark Services Orchestrator (`spark-stack`) is a high-performance deployment orchestrator for the Spark ecosystem. It manages a suite of AI services, including the **OpenClaw** backend gateway, the **SparkRun** orchestrator, and various local LLM inference stacks (powered by **vLLM**).

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
- **Registry:** `spark-stack-registry` for deployment recipes and model configurations.

## Building and Running

The project relies on `uv` for dependency management and script execution.

- **Initialization:**
  ```bash
  make setup  # Synchronizes dependencies and installs pre-commit hooks
  ```
- **Deploying/Updating the Stack:**
  ```bash
  uv run manager/update_services.py  # Main orchestration entry point
  ```
- **Updating Specific Components:**
  ```bash
  uv run manager/update_openclaw.py  # Updates OpenClaw source and service
  uv run manager/update_sparkrun.py  # Updates SparkRun source
  ```
- **Stack Verification:**
  ```bash
  uv run pytest tests/e2e/  # Mandatory verification after any changes
  ```
- **Manual Launch:**
  ```bash
  uv run manager/launch.py
  ```

## Development Conventions

### Source Dependency Policy

- **OpenClaw (`../openclaw/`)**: Treated as an **immutable upstream source dependency**. NEVER modify source files here. Solve configuration issues by modifying inputs (like `jq` filtering) or host-level settings.
- **SparkRun (`../sparkrun/`)**: Treated as an editable source dependency. **CRITICAL:** You must ensure the `local-dev` branch is checked out before making any modifications or running tests. You **MUST** strictly follow the "Trunk-Based Feature Integration" workflow documented in the `source-dependency-dev` skill for any `sparkrun` changes (creating feature branches from `main`, merging them into `local-dev`, and rebasing `local-dev` via the orchestration script).

### Runtime vs. Source (OpenClaw)

- **Source Code**: Located in `../openclaw/`.
- **Runtime Environment**: Located in `~/.openclaw/`. This directory contains active configurations (`openclaw.json`), logs, and database files. All state changes must occur here.
- **CLI**: Use `~/bin/openclaw` for host-level gateway management.

### Scripting Standards

- **Idiomatic Execution**: Use `uv run` for all scripts. Avoid `sys.path.insert()` hacks.
- **Context Awareness**: Scripts should be domain-agnostic and use Pydantic schemas from `core/schemas.py`.
- **Zombie Protocol**: The orchestration scripts include a cleanup phase to purge stuck tasks and stale containers, ensuring a clean state for the stack.

### Planning and Verification

- **Planning**: For tasks related to `stack-manager`, use the templates in `skills/stack-manager/references/plan-template.md`.
- **Verification**: No infrastructure change is complete without a passing run of `uv run pytest tests/e2e/`.

## Directory Structure

- `core/`: Shared async utilities, health probes, and Pydantic configuration schemas.
- `manager/`: High-level orchestration scripts for building, updating, and syncing the stack.
- `services/`: Configuration fragments, `docker-compose.yml` files, and service-specific managers.
- `skills/`: Local AI agent skills (e.g., `stack-manager`, `source-dependency-dev`).
- `../spark-stack-registry/`: Source dependency containing model and stack deployment recipes.
- `tests/`: End-to-end and unit tests (Requires `pytest`).
- `benchmarks/`: Performance testing and evaluation suites.

## Host Configuration

This project requires specific host-level tuning (SSH protection, increased `inotify` limits) to prevent networking conflicts during Docker teardowns. See `DEVELOPMENT.md` for the full setup guide.
ing Docker teardowns. See `DEVELOPMENT.md` for the full setup guide.
