# Architecture

sparkstack is the control plane for a local AI service stack. It turns reviewed
source and registry recipes into coordinated Docker services, emits structured
progress, and verifies the resulting system. This document identifies the
owner of each concern; it is not an operational runbook.

## Control Flow

```text
sparkstack CLI
  |-- core schemas, discovery, environment, git, IPC
  |-- manager build/update/launch/sync operations
  |       |-- read sparkstack-registry recipes
  |       |-- integrate sibling OpenClaw and SparkRun sources
  |       `-- render/apply services/* Compose configuration
  |-- JSON-Lines stdout for automation
  `-- UDS events for sparkstack status TUI
                         |
                         v
                 Docker service stack
          OpenClaw -> LiteLLM -> vLLM backends
                         |
                         v
              Prometheus/Grafana/Tempo
```

The CLI and TUI consume the same event model. Automated callers use `--json`;
they must not scrape Rich or Textual output.

## Ownership Map

| Concern | Source of truth | Evidence |
| --- | --- | --- |
| CLI surface | `sparkstack/cli/` | unit tests and command help |
| Shared configuration and events | `sparkstack/core/` | unit/regression tests |
| Lifecycle orchestration | `sparkstack/manager/` | manager unit tests and IPC regressions |
| Service definitions | `services/` | Compose/config checks and prepared-stack E2E |
| Model/stack recipes | sibling `sparkstack-registry` | registry validation and memory-law checks |
| SparkRun behavior | sibling `sparkrun` | its repository workflow plus integration tests |
| OpenClaw behavior | sibling `openclaw` | its repository workflow plus gateway E2E |
| Network topology and incident learning | `stack-knowledge` skill | live topology diagnostics |
| Deployment workflow | `stack-manager` skill | approved plan, benchmark, and E2E evidence |

## Source and Runtime Boundaries

- Repository source is declarative intent and orchestration code. Running
  containers, `~/.openclaw`, secrets, sockets, logs, and generated stack state
  are external mutable runtime state.
- The OpenClaw source checkout is distinct from `~/.openclaw` runtime state.
- Docker-out-of-Docker consumers require host-valid absolute paths and
  identical volume mappings where both host and container access are needed.
- Service-to-service traffic uses shared-network names, never fixed container
  IPs or host hairpin routing.
- The registry's main-only policy and sibling branch prerequisites live in
  `.agents/rules/`; do not infer or duplicate them here.

## Change Classes and Proof

Documentation and source-only contract changes can use unit, regression,
format, lint, type, and pre-commit evidence. A change to infrastructure,
configuration, a model, or the running stack additionally requires the
ordered live E2E protocol after its prerequisites are satisfied.

Do not run live E2E against an arbitrary environment: first satisfy the source
dependency branch rules and the selected skill's preparation steps.

## Proof Ladder

1. Run the narrow unit or regression test for the changed owner.
2. Run formatting, linting, type, and security checks defined by hooks.
3. Run the complete non-live unit/regression suite.
4. For infrastructure or live-stack changes, prepare the stack and run the
   ordered E2E verification skill.
5. Require CI on the exact reviewed commit.
6. For deployment work, record live configuration and benchmark evidence as
   required by the stack-manager plan.
