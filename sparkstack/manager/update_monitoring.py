#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3

import asyncio
import re
from pathlib import Path

import httpx
from loguru import logger

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

    if not COMPOSE_FILE.exists():
        logger.error(f"❌ Error: {COMPOSE_FILE} not found.")
        exit(1)

    content = COMPOSE_FILE.read_text()

    # We need to swap out docker hub images for quay.io versions where applicable before processing
    content = content.replace("image: prom/prometheus", "image: quay.io/prometheus/prometheus")

    updates = await fetch_updates()

    changes = 0
    for image_base, new_image in updates.items():
        logger.info(f"Checking {image_base}...")
        if not new_image or "None" in new_image:
            logger.warning("  ❌ Failed to resolve latest version.")
            continue

        pattern = rf"(image:\s*){image_base}:[a-zA-Z0-9_.-]+"
        match = re.search(pattern, content)

        if match:
            current_image = match.group(0).split(":", 1)[1].strip()
            if current_image != new_image:
                logger.info(f"  🚀 Updating: {current_image} -> {new_image}")
                content = re.sub(pattern, rf"image: {new_image}", content)
                changes += 1
            else:
                logger.info(f"  ✅ Already up to date: {current_image}")
        else:
            logger.warning("  ⚠️ Not found in compose file.")

    # Force write if we just swapped to quay.io, even if versions didn't change
    if changes > 0 or "quay.io" in content:
        COMPOSE_FILE.write_text(content)
        logger.info(f"\n🎉 Updated dependencies and registries in {COMPOSE_FILE}.")
        logger.info("👉 Run 'cd services/monitoring && docker compose up -d' to apply the updates.")
    else:
        logger.info("\n✨ Everything is up to date! No updates needed.")


if __name__ == "__main__":
    run_with_lock(".sparkstack-update-monitoring.lock", main())
