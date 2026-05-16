# Pre-Commit Checks

Before committing changes to this repository, you **MUST** run the pre-commit hooks to catch lint, formatting, and type errors before they block `git push`:

```bash
uv run pre-commit run --all-files --hook-stage pre-push
```

Fix any reported issues before staging and committing. Do **not** commit with known hook failures.
