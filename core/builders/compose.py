from pathlib import Path

import yaml


class ComposeBuilder:
    def __init__(self, stack_dir: Path, compose_base: dict):
        self.stack_dir = stack_dir
        self.compose_config = compose_base

    def set_gateway_memory(self, memory: str = "8G"):
        gw = self.compose_config["services"]["gateway"]
        gw["networks"] = ["vllm-network", "proxy-tier"]
        gw.setdefault("deploy", {}).setdefault("resources", {}).setdefault("limits", {})[
            "memory"
        ] = memory
        self.compose_config.setdefault("networks", {})["proxy-tier"] = {"external": True}

    def add_service(self, service_name: str, service_config: dict):
        self.compose_config["services"][service_name] = service_config

    def write(self):
        if "gateway" in self.compose_config["services"]:
            self.compose_config["services"]["gateway"]["extra_hosts"] = [
                "host.docker.internal:host-gateway"
            ]
        with (self.stack_dir / "docker-compose.yaml").open("w") as f:
            yaml.dump(self.compose_config, f, sort_keys=False)
