______________________________________________________________________

## trigger: always_on

## Mandatory Task Completion Verification

A task is NEVER considered complete unless you have successfully executed a full stack verification sweep.

**Verification Command:**

```bash
uv run scripts/verify.py
```

You MUST run this command after any infrastructure change, configuration update, or model rotation, and ensure it passes (Exit Code 0) before claiming success or ending a session.
