#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3

import asyncio
import re
import subprocess
from pathlib import Path

import httpx
from loguru import logger
from ruamel.yaml import YAML

from sparkstack.core.utils import run_with_lock

COMPOSE_FILE = Path("services/monitoring/docker-compose.yml")


async def get_latest_github_release(client: httpx.AsyncClient, repo: str) -> str | None:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.json()["tag_name"]
    except Exception as e:
        logger.error(f"Error fetching {repo}: {e}")
        return None


async def get_latest_gcr_tag(client: httpx.AsyncClient, repo: str) -> str | None:
    url = f"https://gcr.io/v2/{repo}/tags/list"
    try:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        data = response.json()
        tags = [
            t
            for t in data["tags"]
            if t.startswith("v0.") and "test" not in t and "containerd" not in t
        ]
        tags.sort(key=lambda s: [int(x) for x in re.findall(r"\d+", s)], reverse=True)
        return tags[0] if tags else None
    except Exception as e:
        logger.error(f"Error fetching GCR {repo}: {e}")
        return None


async def get_latest_dockerhub_tag(
    client: httpx.AsyncClient, namespace: str, repo: str, suffix: str = ""
) -> str | None:
    url = f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags/?page_size=100"
    try:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        data = response.json()
        tags = [t["name"] for t in data["results"]]

        valid_tags = []
        for t in tags:
            if any(x in t.lower() for x in ["rc", "beta", "alpha", "test"]):
                continue
            if suffix and not t.endswith(suffix):
                continue

            base_t = t.replace(suffix, "") if suffix else t
            if re.match(r"^v?\d+\.\d+\.\d+$", base_t):
                valid_tags.append(t)

        valid_tags.sort(key=lambda s: [int(x) for x in re.findall(r"\d+", s)], reverse=True)
        if valid_tags:
            return valid_tags[0]
    except Exception as e:
        logger.error(f"Error fetching {namespace}/{repo}: {e}")
    return None


async def fetch_updates() -> dict[str, str | None]:
    async with httpx.AsyncClient() as client:
        prom_task = get_latest_github_release(client, "prometheus/prometheus")
        grafana_task = get_latest_dockerhub_tag(client, "grafana", "grafana")
        alloy_task = get_latest_github_release(client, "grafana/alloy")

        prom_tag, grafana_tag, alloy_tag = await asyncio.gather(prom_task, grafana_task, alloy_task)

        return {
            "quay.io/prometheus/prometheus": f"quay.io/prometheus/prometheus:{prom_tag}"
            if prom_tag
            else None,
            "grafana/grafana": f"grafana/grafana:{grafana_tag}" if grafana_tag else None,
            "grafana/alloy": f"grafana/alloy:{alloy_tag}" if alloy_tag else None,
        }


async def main():
    logger.info("🔍 Checking for latest monitoring container versions...\n")

    logger.info("🛠️ Building overview dashboard from template...")
    try:
        subprocess.run(["python3", "services/monitoring/build_dashboards.py"], check=True)
    except Exception as e:
        logger.error(f"❌ Failed to build dashboards: {e}")

    if not COMPOSE_FILE.exists():
        logger.error(f"❌ Error: {COMPOSE_FILE} not found.")
        exit(1)

    yaml = YAML()
    yaml.preserve_quotes = True

    with open(COMPOSE_FILE) as f:
        data = yaml.load(f)

    # We need to swap out docker hub images for quay.io versions where applicable before processing
    for _, svc_config in data.get("services", {}).items():
        if "image" in svc_config and svc_config["image"].startswith("prom/prometheus"):
            svc_config["image"] = svc_config["image"].replace("prom/prometheus", "quay.io/prometheus/prometheus")

    updates = await fetch_updates()

    changes = 0
    for image_base, new_image in updates.items():
        logger.info(f"Checking {image_base}...")
        if not new_image or "None" in new_image:
            logger.warning("  ❌ Failed to resolve latest version.")
            continue

        found = False
        for _, svc_config in data.get("services", {}).items():
            if "image" not in svc_config:
                continue

            current_image = svc_config["image"]
            if current_image.startswith(f"{image_base}:"):
                found = True
                if current_image != new_image:
                    logger.info(f"  🚀 Updating: {current_image} -> {new_image}")
                    svc_config["image"] = new_image
                    changes += 1
                else:
                    logger.info(f"  ✅ Already up to date: {current_image}")

        if not found:
            logger.warning("  ⚠️ Not found in compose file.")

    if changes > 0:
        with open(COMPOSE_FILE, "w") as f:
            yaml.dump(data, f)
        logger.info(f"\n🎉 Updated dependencies and registries in {COMPOSE_FILE}.")
        logger.info("👉 Run 'cd services/monitoring && docker compose up -d' to apply the updates.")
    else:
        logger.info("\n✨ Everything is up to date! No updates needed.")


if __name__ == "__main__":
    run_with_lock(".sparkstack-update-monitoring.lock", main())
