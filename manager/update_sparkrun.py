#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
"""
update_sparkrun.py - Source Dependency management and rebase logic for SparkRun.
"""

import argparse
import asyncio
from pathlib import Path

# Add parent directory to path to allow importing core
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.env import PROJECT_ROOT, SPARKRUN_DIR
from core.utils import CommandError, async_run_command


class SparkrunSettings(BaseSettings):
    """Configuration for SparkRun updates."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_root: Path = Field(default=PROJECT_ROOT)
    sparkrun_dir: Path = Field(default=SPARKRUN_DIR)
    pull_latest: bool = False


class SparkrunUpdater:
    def __init__(self, pull_latest: bool = False, project_root: Path | None = None):
        self.settings = SparkrunSettings(
            pull_latest=pull_latest, project_root=project_root or PROJECT_ROOT
        )

    async def update_source(self) -> None:
        """
        Maintains the SparkRun source_dependency by pulling the latest main branch.
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
                logger.info(
                    f"Detected {current_branch} branch integration. Attempting to sync and rebase upstream/main."
                )

                # Check for upstream remote and sync if present
                res_remotes = await async_run_command(
                    ["git", "remote"], cwd=self.settings.sparkrun_dir
                )
                if "upstream" in res_remotes.stdout:
                    logger.info("Fetching from upstream...")
                    await async_run_command(
                        ["git", "fetch", "upstream"], cwd=self.settings.sparkrun_dir
                    )

                    logger.info(f"Rebasing {current_branch} onto upstream/main...")
                    try:
                        await async_run_command(
                            ["git", "rebase", "upstream/main"], cwd=self.settings.sparkrun_dir
                        )
                    except CommandError:
                        logger.error(
                            f"Rebase failed. You may have conflicts. Please resolve them in {self.settings.sparkrun_dir} and run 'git rebase --continue'."
                        )
                        raise
                else:
                    logger.warning(
                        "No 'upstream' remote configured. Skipping upstream sync. "
                        "To enable automatic syncs, run: git remote add upstream https://github.com/spark-arena/sparkrun.git"
                    )
            else:
                await async_run_command(
                    ["git", "checkout", "-f", "main"], cwd=self.settings.sparkrun_dir
                )
                await async_run_command(
                    ["git", "reset", "--hard", "origin/main"], cwd=self.settings.sparkrun_dir
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
    async def _cli_run():
        async for _ in updater.run_events():
            pass

    await _cli_run()


if __name__ == "__main__":
    asyncio.run(main())
