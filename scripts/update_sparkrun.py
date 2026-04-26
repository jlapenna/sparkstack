#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
"""
update_sparkrun.py - Submodule management and rebase logic for SparkRun.
"""

import argparse
import asyncio
from pathlib import Path

# Add parent directory to path to allow importing core
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.env import PROJECT_ROOT
from core.utils import CommandError, async_run_command


class SparkrunSettings(BaseSettings):
    """Configuration for SparkRun updates."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_root: Path = Field(default=PROJECT_ROOT)
    sparkrun_dir: Path = Field(default=PROJECT_ROOT / "sparkrun")
    pull_latest: bool = False


class SparkrunUpdater:
    def __init__(self, pull_latest: bool = False, project_root: Path | None = None):
        self.settings = SparkrunSettings(
            pull_latest=pull_latest, project_root=project_root or PROJECT_ROOT
        )

    async def update_source(self) -> None:
        """
        Maintains the SparkRun submodule by pulling the latest main branch.
        """
        if not self.settings.pull_latest:
            logger.info("Skipping SparkRun source update. Use --pull-latest to update.")
            return

        logger.info(f"Updating SparkRun source in {self.settings.sparkrun_dir}...")

        if not self.settings.sparkrun_dir.exists():
            logger.error(f"SparkRun directory not found at {self.settings.sparkrun_dir}")
            return

        try:
            # 1. Check current branch
            res = await async_run_command(
                ["git", "branch", "--show-current"], cwd=self.settings.sparkrun_dir
            )
            current_branch = res.stdout.strip()

            await async_run_command(["git", "fetch", "origin"], cwd=self.settings.sparkrun_dir)

            if current_branch == "local-dev" or current_branch.startswith("local/"):
                logger.warning(
                    f"Detected {current_branch} branch integration. Skipping checkout to develop and hard reset to origin/develop."
                )
            else:
                await async_run_command(
                    ["git", "checkout", "-f", "develop"], cwd=self.settings.sparkrun_dir
                )
                await async_run_command(
                    ["git", "reset", "--hard", "origin/develop"], cwd=self.settings.sparkrun_dir
                )

            await async_run_command(["git", "clean", "-fd"], cwd=self.settings.sparkrun_dir)

            logger.info("SparkRun source update cycle complete.")

        except CommandError as e:
            logger.error(f"SparkRun update failed: {e.stderr}")
            raise

    async def run_install(self) -> None:
        """
        Updates the installed sparkrun package via uv.
        """
        logger.info("Synchronizing sparkrun dependencies via uv...")
        # Since it's a local dependency in the project's pyproject.toml, uv sync handles it
        await async_run_command(["uv", "sync"], cwd=self.settings.project_root)


async def main():

    parser = argparse.ArgumentParser(description="SparkRun submodule manager.")
    parser.add_argument("--pull-latest", action="store_true", help="Pull latest/rebase.")
    args = parser.parse_args()

    updater = SparkrunUpdater(pull_latest=args.pull_latest)
    await updater.update_source()
    await updater.run_install()


if __name__ == "__main__":
    asyncio.run(main())
