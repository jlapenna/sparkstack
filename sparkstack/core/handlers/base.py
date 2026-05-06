from abc import ABC, abstractmethod
from typing import Any

from sparkstack.core.builders.docker import DockerComposeFileBuilder
from sparkstack.core.builders.litellm import LiteLLMBuilder
from sparkstack.core.builders.monitoring import MonitoringBuilder


class BaseServiceHandler(ABC):
    @abstractmethod
    def apply_to_builders(
        self,
        docker_builder: DockerComposeFileBuilder,
        gateway_builder: LiteLLMBuilder,
        monitoring_builder: MonitoringBuilder,
    ) -> dict[str, Any]:
        """Apply the model configuration to the respective builders and return backend config for stack.yaml"""
        pass
