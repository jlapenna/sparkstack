from sparkstack.core.builders.docker import DockerComposeFileBuilder


class ApiGatewayServiceConfigurator:
    """Configures the litellm API Gateway container inside the generic docker compose builder.

    When the Headscale overlay network is active, LiteLLM is configured to
    share the head node's Tailscale sidecar network namespace
    (``network_mode: container:sparkstack-head-sidecar``).  This gives
    LiteLLM direct access to the encrypted Tailnet mesh without any host-level
    Tailscale installation, while keeping it reachable on ``sparkstack-net``
    via the sidecar's container name.

    In non-overlay mode the existing bridge-network attachment is used
    (``networks: [vllm-network, sparkstack-net]``), preserving backward
    compatibility with single-node deployments.
    """

    HEAD_SIDECAR_NAME = "sparkstack-head-sidecar"

    @staticmethod
    def configure(docker_builder: DockerComposeFileBuilder, memory: str = "2G") -> None:
        from sparkstack.core.env import is_overlay_configured  # noqa: PLC0415

        if "litellm" not in docker_builder.compose_config["services"]:
            return

        gw = docker_builder.compose_config["services"]["litellm"]
        gw.setdefault("deploy", {}).setdefault("resources", {}).setdefault("limits", {})[
            "memory"
        ] = memory

        if is_overlay_configured():
            # Share the head sidecar's network namespace so LiteLLM can route
            # to remote backends over the Tailnet.  The sidecar is attached to
            # both ``sparkstack-net`` and ``vllm-network``, so OpenClaw can still
            # reach LiteLLM via ``http://sparkstack-head-sidecar:4000``.
            gw.pop("networks", None)
            gw.pop("ports", None)
            gw.pop("extra_hosts", None)
            gw["network_mode"] = f"container:{ApiGatewayServiceConfigurator.HEAD_SIDECAR_NAME}"
            # Remove any top-level network declarations for this service —
            # they are incompatible with network_mode.
            docker_builder.compose_config.setdefault("networks", {}).setdefault(
                "sparkstack-net", {"external": True}
            )
        else:
            # Single-node mode: use bridge networks directly.
            gw["networks"] = ["vllm-network", "sparkstack-net"]
            gw.pop("network_mode", None)
            docker_builder.compose_config.setdefault("networks", {})["sparkstack-net"] = {
                "external": True
            }
