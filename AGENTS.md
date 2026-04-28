# AGENTS.md

For every new session, you **MUST** do the following:

1. Before making a plan or writing code, ALWAYS use the `grep_search` tool on the `skills/` and `sparkrun/sparkrun-cc-plugin/skills/` directories for keywords related to the user's prompt to identify the correct protocol to follow. (Do NOT try to read all skills at once).
1. Read and strictly follow all rules defined in `.agents/rules/`.
1. Activate local (this repo only) skills: `stack-manager`, `submodule-dev`, `monitoring`, `stack-upkeep`, `stack-debugging`
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

1. **`openclaw/` (Source Code)**: This is the upstream, read-only dependency. NEVER modify files here. This includes source files, base documentation, and master templates. Changes here violate the OpenClaw Modification Ban unless explicitly authorized.
2. **`~/.openclaw/` (Runtime/State)**: This is the active runtime directory. It contains instantiated workspaces, sandboxes, active configuration (`.env`, `openclaw.json`), memory files, and active `BOOTSTRAP.md` copies. All state changes, runtime configurations, and template cleanups must happen here.
3. **OpenClaw CLI**: The primary CLI executable is named `openclaw` and is located at `~/bin/openclaw`. Use this for all host-level configuration and gateway management.

## OpenClaw Agent Sandbox Security

1. **Skill Injection Boundary:** Agents must access bundled skills (`wacli`, `mcporter`, `summarize`) through a strict read-only bind mount directly from the `openclaw/skills` source directory into the sandbox (`/app/skills:ro`). 
2. **State Directory Isolation:** NEVER bind the `~/.openclaw/sandboxes` directory into an agent sandbox. Doing so destroys agent isolation, allowing an agent to traverse the lateral state, sessions, and memory of all other agents in the environment.
3. **Configuration Updates:** Always use the `openclaw config set` CLI (available via `docker exec openclaw-openclaw-gateway-1 openclaw config ...`) to update `openclaw.json` (e.g. adding binds). The JSON must be rigorously validated to avoid dropping critical default behaviors or introducing parsing errors.
