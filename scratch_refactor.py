from pathlib import Path

# Move build_stack.py to core/builders/stack.py, and simplify build_stack.py
build_stack_path = Path("manager/build_stack.py")
stack_builder_path = Path("core/builders/stack.py")

with open(build_stack_path) as f:
    content = f.read()

# We need to extract StackBuilder, ModelRegistry, ModelIDExtractor
# But wait, ModelRegistry and ModelIDExtractor are already in core/registry.py

# Replace import of ComposeBuilder, LiteLLMBuilder, PrometheusBuilder
content = content.replace(
    "from core.builders.compose import ComposeBuilder",
    "from core.builders.docker import DockerComposeFileBuilder",
)
content = content.replace(
    "from core.builders.litellm import LiteLLMBuilder",
    "from core.builders.apigateway import ApiGatewayBuilder",
)
content = content.replace(
    "from core.builders.prometheus import PrometheusBuilder",
    "from core.builders.monitoring import MonitoringBuilder",
)

content = content.replace("ComposeBuilder(", "DockerComposeFileBuilder(")
content = content.replace("LiteLLMBuilder(", "ApiGatewayBuilder(")
content = content.replace("PrometheusBuilder(", "MonitoringBuilder(")
content = content.replace("self.compose_builder", "self.docker_builder")
content = content.replace("self.litellm_builder", "self.gateway_builder")

# Create a new version of build_stack.py
new_build_stack = """#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio
from core.builders.stack import StackBuilder

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an AI service stack for NVIDIA Blackwell.")
    parser.add_argument("stack_name", help="Unique name for the stack")
    parser.add_argument("models", nargs="+", help="List of models/aliases")
    parser.add_argument(
        "--allow-no-embedding",
        action="store_true",
        help="Allow building a stack without an embedding model",
    )
    args = parser.parse_args()
    asyncio.run(
        StackBuilder(
            args.stack_name, args.models, allow_no_embedding=args.allow_no_embedding
        ).build()
    )
"""

with open(build_stack_path, "w") as f:
    f.write(new_build_stack)
