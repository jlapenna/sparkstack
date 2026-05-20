"""
vLLM and Sparkrun specific container discovery.
"""

import contextlib
import os
from pathlib import Path
from urllib.parse import urlparse

import yaml
from loguru import logger

from sparkstack.core.utils import async_run_command


async def get_container_name_by_port(port: int, *, is_remote: bool = False) -> str | None:
    """Find a container name that is publishing or listening on a specific port.

    For remote backends the container lives on a different host, so local
    ``docker ps`` is meaningless.  Pass ``is_remote=True`` to short-circuit
    immediately (the caller already has the container name from state).
    """
    if is_remote:
        return None

    try:
        # 1. Check for docker containers publishing this port normally
        result = await async_run_command(
            ["docker", "ps", "--format", "{{.Names}}|{{.Ports}}"], check=False
        )
        for line in result.stdout.splitlines():
            if not line:
                continue
            name, ports = line.split("|")
            if f":{port}->" in ports or f":{port}" in ports:
                return name

        # 2. Check for sparkrun/host-network containers (using OR filter)
        result = await async_run_command(
            [
                "docker",
                "ps",
                "-f",
                "name=sparkrun",
                "-f",
                "name=solo",
                "-f",
                "name=main",
                "-f",
                "name=embedding",
                "--format",
                "{{.Names}}",
            ],
            check=False,
        )
        for container in result.stdout.splitlines():
            if not container:
                continue
            # 1. Check process list
            ps_res = await async_run_command(
                ["docker", "exec", container, "ps", "aux"], check=False
            )
            if f"--port {port}" in ps_res.stdout or f"--port={port}" in ps_res.stdout:
                return container

            # 2. Check the launch script (sparkrun specific)
            script_res = await async_run_command(
                ["docker", "exec", container, "cat", "/tmp/sparkrun_serve.sh"], check=False
            )
            if f"--port {port}" in script_res.stdout or f"--port={port}" in script_res.stdout:
                return container
    except Exception:
        logger.exception(f"Error resolving container for port {port}")

    return None


async def get_active_services(stack_dir: Path) -> list[dict]:
    """Inspects the given stack directory to discover active services.

    For remote backends (those whose LiteLLM ``api_base`` resolves to a
    Tailnet IP recorded in ``.state.json``), the returned service dict is
    enriched with:

    - ``is_remote`` (bool)
    - ``target_host`` — SSH-reachable hostname (e.g. ``"spark"``)
    - ``tailnet_ip`` — Tailnet IP used for application routing
    - ``container`` — Docker container name on the *remote* host (from state),
      **not** an IP address.  This ensures ``docker logs`` calls use the
      correct name.
    """
    from sparkstack.manager.remote import read_sidecar_state  # noqa: PLC0415

    compose_file = stack_dir / "docker-compose.yaml"
    litellm_file = stack_dir / "litellm-config.yaml"

    services = []
    if not stack_dir.exists():
        return services

    # Build reverse map: Tailnet IP → sidecar metadata
    state = read_sidecar_state(stack_dir)
    sidecars = state.get("sidecars", {})
    # {tailnet_ip: {hostname, container_name, ...}}
    ip_to_sidecar: dict[str, dict] = {}
    for hostname, info in sidecars.items():
        ip = info.get("tailnet_ip", "")
        if ip:
            ip_to_sidecar[ip] = {"hostname": hostname, **info}

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
                hostname_str = parsed_url.hostname or ""

                if hostname_str in ip_to_sidecar:
                    # Remote backend: ip matches a known Tailnet IP in state.
                    sidecar_info = ip_to_sidecar[hostname_str]
                    svc_hostname = sidecar_info["hostname"]
                    container = sidecar_info.get("container_name", f"sparkrun-port-{port}")
                    services.append(
                        {
                            "name": f"backend:{model.get('model_name')}",
                            "port": port,
                            "container": container,
                            "type": "sparkrun",
                            "is_remote": True,
                            "target_host": svc_hostname,
                            "tailnet_ip": hostname_str,
                        }
                    )
                elif hostname_str in ["localhost", "127.0.0.1", "host.docker.internal", ""]:
                    # Local backend: discover container by probing the local daemon.
                    container = await get_container_name_by_port(port)
                    services.append(
                        {
                            "name": f"backend:{model.get('model_name')}",
                            "port": port,
                            "container": container or f"sparkrun-port-{port}",
                            "type": "sparkrun",
                            "is_remote": False,
                        }
                    )
                else:
                    # Non-local hostname that isn't a known Tailnet IP.
                    # Treat as a named container / Docker DNS entry.
                    services.append(
                        {
                            "name": f"backend:{model.get('model_name')}",
                            "port": port,
                            "container": hostname_str,
                            "type": "sparkrun",
                            "is_remote": False,
                        }
                    )
    return services
