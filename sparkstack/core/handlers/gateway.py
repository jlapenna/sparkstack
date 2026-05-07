from sparkstack.core.builders.docker import DockerComposeFileBuilder


class ApiGatewayServiceConfigurator:
    """Configures the litellm API Gateway container inside the generic docker compose builder."""

    @staticmethod
    def configure(docker_builder: DockerComposeFileBuilder, memory: str = "2G"):
        if "litellm" not in docker_builder.compose_config["services"]:
            return

        gw = docker_builder.compose_config["services"]["litellm"]
        gw["networks"] = ["vllm-network", "sparkstack-net"]
        gw.setdefault("deploy", {}).setdefault("resources", {}).setdefault("limits", {})[
            "memory"
        ] = memory

        # Ensure sparkstack-net network is defined as external
        docker_builder.compose_config.setdefault("networks", {})["sparkstack-net"] = {
            "external": True
        }
