#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
"""
update_sparkrun.py - Source Dependency management and rebase logic for SparkRun.
"""

import argparse
from pathlib import Path

# Add parent directory to path to allow importing core
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sparkstack.core.env import PROJECT_ROOT, SPARKRUN_DIR
from sparkstack.core.git import sync_sparkrun_repo
from sparkstack.core.updater import BaseUpdater
from sparkstack.core.utils import async_run_command
from sparkstack.core.utils.locking import run_with_lock


class SparkrunSettings(BaseSettings):
    """Configuration for SparkRun updates."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_root: Path = Field(default=PROJECT_ROOT)
    sparkrun_dir: Path = Field(default=SPARKRUN_DIR)
    pull_latest: bool = False


class SparkrunUpdater(BaseUpdater):
    def __init__(self, pull_latest: bool = False, project_root: Path | None = None):
        self.settings = SparkrunSettings(
            pull_latest=pull_latest, project_root=project_root or PROJECT_ROOT
        )

    async def update_source(self) -> None:
        """Maintains the SparkRun source_dependency."""
        if not self.settings.pull_latest:
            logger.info("Skipping SparkRun source update. Use --pull-latest to update.")
            return

        logger.info(f"Updating SparkRun source in {self.settings.sparkrun_dir}...")

        if not self.settings.sparkrun_dir.exists():
            logger.error(f"SparkRun directory not found at {self.settings.sparkrun_dir}")
            return

        try:
            await sync_sparkrun_repo(self.settings.sparkrun_dir)
            logger.info("SparkRun source update cycle complete.")
        except Exception as e:
            logger.error(f"SparkRun update failed: {e}")
            raise

    async def run_install(self) -> None:
        """
        Updates the installed sparkrun package via uv.
        """
        logger.info("Synchronizing sparkrun dependencies via uv...")
        # Since it's a local dependency in the project's pyproject.toml, uv sync handles it
        await async_run_command(["uv", "sync"], cwd=self.settings.project_root)

    async def run_events(self):
        """Maintains the SparkRun source and dependencies, yielding events."""
        yield ("Updating source & Rebase", 40)
        await self.update_source()
        yield ("Installing", 80)
        await self.run_install()
        yield ("Complete", 100)


async def main():
    parser = argparse.ArgumentParser(description="SparkRun source_dependency manager.")
    parser.add_argument("--pull-latest", action="store_true", help="Pull latest/rebase.")
    args = parser.parse_args()

    updater = SparkrunUpdater(pull_latest=args.pull_latest)
    await updater.run_cli()


if __name__ == "__main__":
    run_with_lock(".spark-stack-update-sparkrun.lock", main())
