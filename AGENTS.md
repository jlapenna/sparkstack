# sparkstack Agent Guide

This file routes work to the smallest authoritative context. Do not accumulate
incident history or duplicate skill procedures here.

## Start Here

- Read every file in `.agents/rules/`; those rules are always in force.
- Search `.agents/skills/`, `skills/`, and
  `sparkrun/sparkrun-cc-plugin/skills/` for the task's domain, then read the
  matching skill completely before acting.
- Read `ARCHITECTURE.md` for component ownership and source-dependency
  boundaries. Use `docs/README.md` to find durable guidance.
- Use a dedicated linked worktree for repository changes. Do not mutate
  sibling source dependencies unless the task explicitly requires it and the
  matching skill permits it.

## Task Routes

| Task                                | Read first                                               | Proof                                            |
| ----------------------------------- | -------------------------------------------------------- | ------------------------------------------------ |
| Build, rotate, or rebalance a stack | `stack-manager`                                          | its approved plan and full verification protocol |
| Update OpenClaw or SparkRun source  | `stack-upkeep`, `source-dependency-dev`                  | skill-defined integration proof                  |
| Debug a stack                       | `stack-debugging`, then the matching domain skill        | focused diagnosis before mutation                |
| Change Docker/network topology      | `stack-knowledge` and Docker guidance                    | topology checks and incident record              |
| Change observability                | `monitoring`                                             | metrics/config validation                        |
| Change Python orchestration         | `python-pro`, `async-python-patterns`, `ARCHITECTURE.md` | focused unit/regression tests                    |
| Verify a running stack              | `stack-verification`                                     | ordered `tests/e2e/` evidence                    |
| Change source dependency workflow   | `source-dependency-dev`                                  | branch and integration evidence                  |

## Ownership Boundaries

- `sparkstack/` owns the CLI, orchestration, schemas, IPC, and health logic.
- `services/` owns Compose fragments and service-specific managers.
- `tests/unit/` and `tests/regression/` prove source behavior without a live
  stack; `tests/e2e/` proves the explicitly prepared live stack.
- `sparkstack-registry` owns recipes and model configurations; its branching
  rule is exceptional and defined in `.agents/rules/`.
- `sparkrun` and `openclaw` are sibling source dependencies with their own
  branch and mutation policies.
- Runtime state, secrets, logs, model weights, and generated benchmark data do
  not belong in this repository.

When a durable rule changes, update the owning skill, architecture document,
or executable check. Keep this router compact.
