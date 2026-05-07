______________________________________________________________________

## trigger: always_on

______________________________________________________________________

## trigger: always_on

## Spark Stack Registry Branching Policy

IMMUTABLE RULE: You CANNOT create branches or git worktrees for `spark-stack-registry` (`./workspaces/spark-stack-registry` or `spark-stack-registry/`).

All updates and operations on the `spark-stack-registry` MUST be done directly on the `main` branch.
Do not attempt to check out feature branches or use `git worktree add` for the registry repository under any circumstances.
