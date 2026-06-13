---

name: stack-verification
description: Orchestrates the E2E verification testing suite for the Spark Stack using pytest.
category: testing
risk: low
source: local
compatibility: claude-code
triggers:

- run e2e tests
- verify the stack
- fix verification layers
- test wait for backends
- verify proxy connectivity

---

# Spark Stack Verification

## Purpose

To manage and execute the End-to-End (E2E) verification suite located in `tests/e2e/`. This suite tests environment portability, network topology, container connectivity, proxy (LiteLLM) health, and backend model inference readiness.

## Core Mandates

### 1. Pytest Execution Strategy

- All verification layers have been decoupled into a standard `pytest` framework within `tests/e2e/`.
- **Command**: Run tests using `uv run pytest -x tests/e2e/` to abort as soon as a test fails.
- **Environment Variables**: Always ensure `tests/e2e/conftest.py` is respected. Pass `--stack` and `--soak` CLI arguments or rely on environment variables to control portability.
- **Automated Reversion**: If tests fail, the workflow should immediately pause. Do NOT continue to the Finalize step without resolving the verification errors.
- **Test Sequencing**: Tests are strictly ordered (e.g., using `pytest-order`). Do NOT attempt to run dependent backend inference tests without first verifying that the core network and proxy gateways are healthy.

### 2. Environment Portability

- **No Hardcoded Paths**: Ensure no absolute paths to user home directories or specific hostnames are baked into tests. Rely on `E2EContext` injection.
- **Decoupled Verification**: Test suite execution should rely entirely on `pytest` fixtures mapping to the decoupled orchestration architecture.

### 3. Debugging Test Failures

- **Test Ordering**: Tests use `@pytest.mark.order` decorators for sequencing. If collection errors occur, inspect decorator import paths and ensure `pytest-order` is installed.
- **Proxy and Container Health**: When E2E verification fails on backend tests (e.g., vLLM timeouts), the root cause is almost always the proxy gateway (LiteLLM) dropping connections or container port mappings failing to resolve `127.0.0.11` internal Docker DNS. Always check `docker logs litellm` first.

## Prerequisites

1. Active Python environment (`.venv/bin/python`).
1. Stack must be actively running via `docker compose`.
