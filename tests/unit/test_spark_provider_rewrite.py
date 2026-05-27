"""
Unit tests for SparkProvider._rewrite_base_url_for_remote.

Validates that the base_url rewrite only fires when OPENCLAW_NODE_TARGET
refers to a *truly* remote node (not localhost / 127.0.0.1).

When openclaw is co-located via Docker (OPENCLAW_NODE_TARGET=ssh://localhost),
the container can reach LiteLLM through Docker DNS ("litellm") and the
Tailnet IP is NOT routable from the openclaw bridge, so the rewrite must
be skipped.
"""

import os
from unittest.mock import patch

import sparkstack.core.schemas as schemas_mod

# We patch the module-level constants that schemas.py reads at validator-time
# rather than trying to reload the module (which would re-read .env).
_SCHEMAS = "sparkstack.core.schemas"


def _provider(
    *,
    openclaw_target: str,
    head_tailnet_ip: str,
    worker_tailnet_ip: str,
    base_url: str | None = None,
) -> schemas_mod.SparkProvider:
    """Instantiate SparkProvider with patched module-level env constants."""
    kwargs: dict = {"models": []}
    if base_url is not None:
        kwargs["baseUrl"] = base_url

    with (
        patch(f"{_SCHEMAS}.OPENCLAW_NODE_TARGET", openclaw_target),
        patch(f"{_SCHEMAS}.SPARKSTACK_HEAD_TAILNET_IP", head_tailnet_ip),
        patch(f"{_SCHEMAS}.WORKER_TAILNET_IP", worker_tailnet_ip),
        patch.dict(
            os.environ,
            {"WORKER_TAILNET_IP": worker_tailnet_ip} if worker_tailnet_ip else {},
            clear=False,
        ),
    ):
        return schemas_mod.SparkProvider(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_rewrite_when_target_empty():
    """No OPENCLAW_NODE_TARGET → base_url stays as Docker DNS 'litellm'."""
    p = _provider(
        openclaw_target="",
        head_tailnet_ip="100.64.0.1",
        worker_tailnet_ip="",
        base_url="http://litellm:4000/v1",
    )
    assert "litellm" in p.base_url, f"Expected Docker DNS hostname, got: {p.base_url}"
    assert "100.64.0.1" not in p.base_url


def test_no_rewrite_when_target_is_localhost_ssh():
    """OPENCLAW_NODE_TARGET=ssh://localhost → simulated remote, no rewrite."""
    p = _provider(
        openclaw_target="ssh://localhost",
        head_tailnet_ip="100.64.0.1",
        worker_tailnet_ip="",
        base_url="http://litellm:4000/v1",
    )
    assert "litellm" in p.base_url, f"Expected Docker DNS hostname, got: {p.base_url}"
    assert "100.64.0.1" not in p.base_url


def test_no_rewrite_when_target_is_127_0_0_1():
    """OPENCLAW_NODE_TARGET pointing to 127.0.0.1 → no rewrite."""
    p = _provider(
        openclaw_target="ssh://127.0.0.1",
        head_tailnet_ip="100.64.0.1",
        worker_tailnet_ip="",
        base_url="http://litellm:4000/v1",
    )
    assert "litellm" in p.base_url, f"Expected Docker DNS hostname, got: {p.base_url}"
    assert "100.64.0.1" not in p.base_url


def test_rewrite_on_truly_remote_target():
    """OPENCLAW_NODE_TARGET pointing to a real remote host → rewrite to Tailnet IP."""
    p = _provider(
        openclaw_target="ssh://spark-worker",
        head_tailnet_ip="100.64.0.1",
        worker_tailnet_ip="",
        base_url="http://litellm:4000/v1",
    )
    assert "100.64.0.1" in p.base_url, f"Expected Tailnet IP in base_url, got: {p.base_url}"
    assert "litellm" not in p.base_url


def test_rewrite_replaces_worker_tailnet_ip():
    """When base_url contains WORKER_TAILNET_IP, it's replaced with HEAD Tailnet IP."""
    p = _provider(
        openclaw_target="ssh://spark-worker",
        head_tailnet_ip="100.64.0.1",
        worker_tailnet_ip="100.64.0.2",
        base_url="http://100.64.0.2:4000/v1",
    )
    assert p.base_url == "http://100.64.0.1:4000/v1", f"Unexpected base_url: {p.base_url}"


def test_rewrite_replaces_localhost_in_url():
    """When base_url contains 'localhost', it's replaced with HEAD Tailnet IP for remote."""
    p = _provider(
        openclaw_target="ssh://spark-worker",
        head_tailnet_ip="100.64.0.1",
        worker_tailnet_ip="",
        base_url="http://localhost:4000/v1",
    )
    assert p.base_url == "http://100.64.0.1:4000/v1", f"Unexpected base_url: {p.base_url}"


@patch("sparkstack.core.schemas.logger.warning")
def test_warns_when_head_ip_missing_for_remote(mock_warning):
    """Remote target + missing HEAD IP → logger warning issued, base_url unchanged."""
    p = _provider(
        openclaw_target="ssh://spark-worker",
        head_tailnet_ip="",
        worker_tailnet_ip="",
        base_url="http://litellm:4000/v1",
    )
    # base_url should remain unchanged (no head IP to rewrite to)
    assert "litellm" in p.base_url
    assert mock_warning.call_count == 1
    assert "SPARKSTACK_HEAD_TAILNET_IP is missing" in mock_warning.call_args[0][0]


def test_default_base_url_uses_head_sidecar_when_overlay_configured():
    """When overlay is configured, default URL uses sparkstack-head-sidecar (not 'litellm').

    LiteLLM runs with network_mode: container:sparkstack-head-sidecar, binding
    port 4000 in the sidecar's network namespace. The service alias 'litellm'
    only resolves within the compose project's internal network, not on the
    external sparkstack-net bridge that openclaw uses.
    """
    env_backup = os.environ.pop("VLLM_GATEWAY_URL", None)
    try:
        with (
            patch(f"{_SCHEMAS}.OPENCLAW_NODE_TARGET", ""),
            patch(f"{_SCHEMAS}.SPARKSTACK_HEAD_TAILNET_IP", "100.64.0.1"),
            patch(f"{_SCHEMAS}.WORKER_TAILNET_IP", "100.64.0.2"),
            patch(f"{_SCHEMAS}.is_overlay_configured", return_value=True),
        ):
            p = schemas_mod.SparkProvider(models=[])
    finally:
        if env_backup is not None:
            os.environ["VLLM_GATEWAY_URL"] = env_backup

    assert p.base_url == "http://sparkstack-head-sidecar:4000/v1", (
        f"Expected sidecar hostname when overlay configured, got: {p.base_url}"
    )
