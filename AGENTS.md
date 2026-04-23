# AGENTS.md

For every new session, you **MUST** do the following:

1. Before making a plan or writing code, ALWAYS use the `grep_search` tool on the `skills/` and `sparkrun/sparkrun-cc-plugin/skills/` directories for keywords related to the user's prompt to identify the correct protocol to follow. (Do NOT try to read all skills at once).
1. Read and strictly follow all rules defined in `.agents/rules/`.
1. Activate local (this repo only) skills: `stack-manager`, `submodule-development`

## Knowledge and memory.

1. Do not add any learned information to AGENTS.md or GEMINI.md.
1. Prefer creating or updating skills in the skills/ directory to keep track of learned information, processes or techniques.

## Debugging & Infrastructure Philosophy

1. **Systematic Debugging:** Always prioritize fixing issues starting from base principles. Adopt a systematic debugging and understanding approach rather than blindly applying band-aid fixes.

## Python Script Execution

1. **Idiomatic Module Execution**:
   - `package = false` in `pyproject.toml` because we do not want to require installs.
   - Scripts MUST NOT contain `sys.path.insert()` hacks.
