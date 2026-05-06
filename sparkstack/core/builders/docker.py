from pathlib import Path

import yaml


class DockerComposeFileBuilder:
    def __init__(self, stack_dir: Path, compose_base: dict):
        self.stack_dir = stack_dir
        self.compose_config = compose_base

    def add_service(self, service_name: str, service_config: dict):
        self.compose_config["services"][service_name] = service_config

    def write(self):
        with (self.stack_dir / "docker-compose.yaml").open("w") as f:
            yaml.dump(self.compose_config, f, sort_keys=False)
