"""Push local Grafana dashboard JSONs to a remote Grafana instance.

Uses the Grafana HTTP API ``POST /api/dashboards/db`` endpoint to upsert
each dashboard, overwriting if it already exists.  The target Grafana URL
is resolved from ``REMOTE_GRAFANA_URL`` (derived from ``SPARK_MONITORING_HOST``)
unless an explicit *target* is provided.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from loguru import logger

from sparkstack.core.env import REMOTE_GRAFANA_URL

DASHBOARDS_DIR = (
    Path(__file__).parent.parent.parent
    / "services"
    / "monitoring"
    / "grafana"
    / "provisioning"
    / "dashboards"
)


async def sync_dashboards(
    *,
    target: str | None = None,
    api_key: str | None = None,
    folder: str = "sparkstack",
) -> None:
    """Upload all local dashboard JSONs to a remote Grafana instance.

    Args:
        target: Grafana base URL (e.g. ``http://monitor.lan:3001``).
                Defaults to ``REMOTE_GRAFANA_URL`` when *None*.
        api_key: Optional Grafana API key / service-account token.
                 When *None*, requests are sent without auth (works for
                 anonymous-admin setups common in homelab environments).
        folder: Grafana folder to create dashboards in.
    """
    grafana_url = (target or REMOTE_GRAFANA_URL).rstrip("/")
    if not grafana_url:
        logger.error(
            "No target specified and SPARK_MONITORING_HOST is not set. "
            "Use --target or set SPARK_MONITORING_HOST."
        )
        raise SystemExit(1)

    logger.info(f"Syncing dashboards to {grafana_url}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Resolve or create the target folder
    folder_id = await _ensure_folder(grafana_url, headers, folder)

    # Discover dashboard JSON files (skip templates and the provisioning YAML)
    dashboard_files = sorted(
        p
        for p in DASHBOARDS_DIR.glob("*.json")
        if not p.name.endswith(".template.json")
    )

    if not dashboard_files:
        logger.warning(f"No dashboard JSON files found in {DASHBOARDS_DIR}")
        return

    logger.info(f"Found {len(dashboard_files)} dashboard(s) to sync")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for path in dashboard_files:
            await _upsert_dashboard(client, grafana_url, headers, path, folder_id)

    logger.info("✅ Dashboard sync complete")


async def _ensure_folder(
    grafana_url: str,
    headers: dict[str, str],
    folder_title: str,
) -> int | None:
    """Create a Grafana folder if it doesn't exist, return its ID."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Check if folder exists
        resp = await client.get(f"{grafana_url}/api/folders", headers=headers)
        if resp.status_code == 200:
            for f in resp.json():
                if f.get("title", "").lower() == folder_title.lower():
                    logger.info(f"Using existing folder: {f['title']} (id={f['id']})")
                    return f["id"]

        # Create folder
        resp = await client.post(
            f"{grafana_url}/api/folders",
            headers=headers,
            json={"title": folder_title},
        )
        if resp.status_code in (200, 412):
            data = resp.json()
            folder_id = data.get("id")
            logger.info(f"Created folder: {folder_title} (id={folder_id})")
            return folder_id

        logger.warning(
            f"Could not create folder '{folder_title}': {resp.status_code} {resp.text}. "
            "Dashboards will be placed in General."
        )
        return None


async def _upsert_dashboard(
    client: httpx.AsyncClient,
    grafana_url: str,
    headers: dict[str, str],
    path: Path,
    folder_id: int | None,
) -> None:
    """Push a single dashboard JSON to Grafana."""
    dashboard = json.loads(path.read_text())

    # Strip provisioned id/uid so Grafana assigns its own on first import
    dashboard.pop("id", None)

    payload: dict = {
        "dashboard": dashboard,
        "overwrite": True,
        "message": f"Synced from sparkstack ({path.name})",
    }
    if folder_id is not None:
        payload["folderId"] = folder_id

    resp = await client.post(
        f"{grafana_url}/api/dashboards/db",
        headers=headers,
        json=payload,
    )

    if resp.status_code == 200:
        slug = resp.json().get("slug", path.stem)
        logger.info(f"  ✅ {path.name} → {slug}")
    else:
        logger.error(f"  ❌ {path.name}: {resp.status_code} {resp.text}")
