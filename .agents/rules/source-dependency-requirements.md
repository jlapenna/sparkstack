______________________________________________________________________

## trigger: always_on

## Mandatory Branch Verification

IMMUTABLE RULE: You CANNOT run `update_services`, E2E tests (`pytest tests/e2e/`), or `set_current` unless BOTH `sparkrun` (`../sparkrun`) and `openclaw` (`../openclaw`) are on their `local-dev` branches.

Before executing any of these commands, you MUST verify the current branch of both repositories and switch them to `local-dev` if they are on any other branch (such as `main`).
