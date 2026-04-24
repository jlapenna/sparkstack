import contextlib
import os
from pathlib import Path
from urllib.parse import urlparse

import yaml

from core.discovery import get_container_name_by_port


async def get_active_services(stack_dir: Path):
    compose_file = stack_dir / "docker-compose.yaml"
    litellm_file = stack_dir / "litellm-config.yaml"

    services = []
    if not stack_dir.exists():
        return services

    if compose_file.exists():
        with open(compose_file) as f:
            config = yaml.safe_load(f)
        for svc_id, svc_config in config.get("services", {}).items():
            name = svc_config.get("container_name", svc_id)
            port = None
            ports = svc_config.get("ports", [])
            if ports:
                p = ports[0]
                if isinstance(p, str):
                    p = os.path.expandvars(p)
                    parts = p.split(":")
                    port_str = parts[-2] if len(parts) >= 2 else parts[0]
                    if "/" in port_str:
                        port_str = port_str.split("/")[0]
                    with contextlib.suppress(ValueError):
                        port = int(port_str)
                elif isinstance(p, dict):
                    port = p.get("published") or p.get("target")
                elif isinstance(p, int):
                    port = p
            services.append({"name": name, "port": port, "type": "compose"})

    if litellm_file.exists():
        with open(litellm_file) as f:
            config = yaml.safe_load(f)
        for model in config.get("model_list", []):
            api_base = model.get("litellm_params", {}).get("api_base", "")
            parsed_url = urlparse(api_base)
            port = parsed_url.port

            if port:
                # Prioritize hostname from URL as the container name if it's not localhost
                hostname = parsed_url.hostname
                container = None
                if hostname and hostname not in ["localhost", "127.0.0.1", "host.docker.internal"]:
                    container = hostname
                else:
                    container = await get_container_name_by_port(port)

                services.append(
                    {
                        "name": f"backend:{model.get('model_name')}",
                        "port": port,
                        "container": container or f"sparkrun-port-{port}",
                        "type": "sparkrun",
                    }
                )
    return services
