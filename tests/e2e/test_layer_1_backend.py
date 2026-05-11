import json

import pytest
from loguru import logger

from sparkstack.core.discovery import get_active_services
from sparkstack.core.utils import async_run_command
from tests.e2e.context import E2EContext


@pytest.mark.order(4)
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_layer_1_backend(ctx: E2EContext):
    """Test the LLM backends directly, bypassing the LiteLLM gateway."""
    services = await get_active_services(ctx.stack_dir)
    if not services:
        logger.error(f"❌ Failure: No active services discovered in '{ctx.stack_dir.name}/'")
        raise AssertionError("No active services")

    # Filter out non-sparkrun backends
    sparkrun_services = [
        svc for svc in services if svc.get("type") == "sparkrun" and svc.get("port")
    ]

    if not sparkrun_services:
        logger.info("✅ Pass: No sparkrun backends to test")
        return

    logger.info(f"Layer 1: Testing {len(sparkrun_services)} backends directly...")

    for svc in sparkrun_services:
        port = svc["port"]
        container = svc.get("container", f"port-{port}")
        model_id = svc.get("name", "").replace("backend:", "")

        logger.info(f"Testing backend {container} directly on port {port}...")

        async def docker_curl(
            path: str, method: str = "GET", data: dict | None = None, c=container, p=port
        ):
            cmd = [
                "docker",
                "run",
                "--rm",
                "--network",
                "sparkstack-net",
                "curlimages/curl",
                "-s",
                "-w",
                "\\n%{http_code}",
            ]
            if method == "POST":
                cmd.extend(
                    ["-X", "POST", "-H", "Content-Type: application/json", "-d", json.dumps(data)]
                )
            cmd.append(f"http://{c}:{p}{path}")
            res = await async_run_command(cmd, capture_output=True, check=False)
            if not res.stdout:
                return 0, ""
            lines = res.stdout.strip().split("\n")
            status_code = int(lines[-1])
            body = "\n".join(lines[:-1])
            return status_code, body

        try:
            # Wait for models to return via /v1/models directly
            status_code, body = await docker_curl("/v1/models")
            if status_code != 200:
                logger.error(f"❌ Failure: /v1/models returned {status_code} for {container}")
                raise AssertionError(f"Backend models endpoint failed for {container}")

            if "embedding" in model_id:
                status_code, body = await docker_curl(
                    "/v1/embeddings",
                    method="POST",
                    data={"model": model_id, "input": "Say hi"},
                )
            else:
                status_code, body = await docker_curl(
                    "/v1/chat/completions",
                    method="POST",
                    data={
                        "model": model_id,
                        "messages": [{"role": "user", "content": "Say hi"}],
                        "max_tokens": 5,
                    },
                )

            if status_code == 200:
                logger.info(f"✅ Layer 1 direct test passed for {container}")
            else:
                logger.error(f"❌ Layer 1 direct inference failed for {container}: {body}")
                raise AssertionError(f"Direct inference failed for {container}")
        except Exception as e:
            logger.error(f"❌ Layer 1 direct request failed for {container}: {e}")
            raise AssertionError(f"Direct request failed for {container}: {e}") from e
