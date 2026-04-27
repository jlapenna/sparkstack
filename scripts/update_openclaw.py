#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
"""
update_openclaw.py - Secure, schema-safe OpenClaw configuration management.
"""

import asyncio
import os
import shutil
from pathlib import Path

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.env import OPENCLAW_CONFIG_DIR, OPENCLAW_CONFIG_PATH, OPENCLAW_ENV
from core.utils import ServiceHealthManager, async_run_command, parse_cli_json

OPENCLAW_REPO = "https://github.com/google/openclaw.git"


class UpdaterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.absolute())
    openclaw_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.absolute() / "openclaw"
    )
    config_path: Path = Field(default=OPENCLAW_CONFIG_PATH)
    pull_latest: bool = False
    run_setup: str | None = None
    openclaw_branch: str | None = Field(default=None, alias="OPENCLAW_BRANCH")


class OpenClawUpdater:
    def __init__(
        self,
        pull_latest: bool = False,
        run_setup: str | None = None,
        project_root: Path | None = None,
        config_path: Path | None = None,
        verbose: bool = False,
    ):
        self.settings = UpdaterSettings(
            pull_latest=pull_latest,
            run_setup=run_setup,
            project_root=project_root or Path(__file__).parent.parent.absolute(),
            config_path=config_path or OPENCLAW_CONFIG_PATH,
        )
        self.config_path = self.settings.config_path
        self.verbose = verbose

    async def update_source(self) -> None:
        if not self.settings.pull_latest:
            logger.info("Skipping OpenClaw source update. Use --pull-latest to update.")
            return

        logger.info(f"Updating OpenClaw source in {self.settings.openclaw_dir}...")

        # 1. Ensure the repo exists
        if not self.settings.openclaw_dir.exists():
            await async_run_command(
                ["git", "clone", OPENCLAW_REPO, "openclaw"],
                cwd=self.settings.project_root,
                stream_output=True,
            )

        if self.settings.openclaw_branch:
            logger.info(f"Updating to branch: {self.settings.openclaw_branch}")
            await async_run_command(
                ["git", "fetch", "origin", self.settings.openclaw_branch],
                cwd=self.settings.openclaw_dir,
                stream_output=True,
            )
            await async_run_command(
                ["git", "checkout", self.settings.openclaw_branch],
                cwd=self.settings.openclaw_dir,
                stream_output=True,
            )
            await async_run_command(
                ["git", "reset", "--hard", f"origin/{self.settings.openclaw_branch}"],
                cwd=self.settings.openclaw_dir,
                stream_output=True,
            )
            return

        # Preserve in-development changes: if we're on a local branch, just rebase instead of forcing an upstream tag
        try:
            branch_result = await async_run_command(
                ["git", "branch", "--show-current"], cwd=self.settings.openclaw_dir
            )
            current_branch = branch_result.stdout.strip()
            if current_branch:
                logger.info(
                    f"OpenClaw is on active branch '{current_branch}'. Pulling updates via rebase."
                )
                await async_run_command(
                    ["git", "pull", "--rebase"],
                    cwd=self.settings.openclaw_dir,
                    stream_output=True,
                )
                return
        except Exception as e:
            logger.debug(f"Branch check failed: {e}")

        # 2. Get the latest stable release tag using gh
        try:
            result = await async_run_command(
                [
                    "gh",
                    "release",
                    "view",
                    "--repo",
                    OPENCLAW_REPO,
                    "--json",
                    "tagName",
                    "--jq",
                    ".tagName",
                ],
                cwd=self.settings.project_root,
            )
            latest_tag = result.stdout.strip()
            if not latest_tag:
                raise ValueError("Failed to retrieve a valid tag from GitHub.")
            logger.info(f"Latest stable release for {OPENCLAW_REPO} is {latest_tag}")
        except Exception:
            logger.exception("Could not determine latest stable release")
            raise

        # 3. Fetch tags and checkout the specific stable release
        await async_run_command(
            ["git", "fetch", "--tags", "--force"],
            cwd=self.settings.openclaw_dir,
            stream_output=True,
        )
        await async_run_command(
            ["git", "checkout", latest_tag], cwd=self.settings.openclaw_dir, stream_output=True
        )

    async def bootstrap_setup(self) -> None:
        """Run the initial openclaw setup.sh script and copy the resulting compose fragments."""
        logger.info(
            f"Executing official OpenClaw Docker setup script in {self.settings.run_setup} mode..."
        )
        env = os.environ.copy()

        env.update({"CI": "1"})
        if self.settings.run_setup == "sandbox":
            # We invoke setup.sh to seamlessly validate and compile the CLI docker socket boundaries natively.
            env.update({"OPENCLAW_SANDBOX": "1"})

        await async_run_command(
            ["bash", "-c", "bash scripts/docker/setup.sh < /dev/null"],
            cwd=self.settings.openclaw_dir,
            env=env,
            stream_output=self.verbose,
        )

        for fragment in ["docker-compose.extra.yml", "docker-compose.sandbox.yml"]:
            src = self.settings.openclaw_dir / fragment
            dest = self.settings.project_root / fragment
            if src.exists():
                logger.info(f"Copying {fragment} to project root.")
                shutil.copy2(src, dest)
            elif fragment == "docker-compose.sandbox.yml" and self.settings.run_setup != "sandbox":
                if dest.exists():
                    logger.info(
                        "Removing stale docker-compose.sandbox.yml from project root (sandbox mode disabled)."
                    )
                    dest.unlink()

    async def build_sandbox_image(self) -> None:
        """Rebuild the isolated sandbox image and base."""
        logger.info("Building custom OpenClaw Sandbox image (openclaw-sandbox-custom)...")

        # First ensure the un-customized sandbox base image exists
        await async_run_command(
            ["bash", "scripts/sandbox-setup.sh"],
            cwd=self.settings.openclaw_dir,
            stream_output=self.verbose,
        )

        # Compile our custom override layers for agent usage
        await async_run_command(
            [
                "docker",
                "build",
                "-t",
                "openclaw-sandbox-custom:latest",
                "-f",
                "Dockerfile.sandbox-custom",
                ".",
            ],
            cwd=self.settings.project_root,
            stream_output=self.verbose,
        )

    async def build_gateway_image(self) -> None:
        """Rebuild the customized gateway image with embedded ACP tools."""
        logger.info("Building custom OpenClaw Gateway image (openclaw-gateway-custom)...")
        await async_run_command(
            [
                "docker",
                "build",
                "-t",
                "openclaw-gateway-custom:latest",
                "-f",
                "Dockerfile.gateway-custom",
                ".",
            ],
            cwd=self.settings.project_root,
            stream_output=self.verbose,
        )

    def _get_compose_env(self) -> dict:
        env = os.environ.copy()

        # Load .env from openclaw config dir so docker compose interpolates correctly
        env.update({k: str(v) for k, v in OPENCLAW_ENV.items() if v is not None})

        return env

    async def run_compose_up(self) -> None:
        logger.info("Deploying OpenClaw via Docker Compose...")

        env = self._get_compose_env()

        cmd = ["docker", "compose", "-f", "docker-compose.yml"]
        override_yml = self.settings.project_root / "docker-compose.override.yml"
        if override_yml.exists():
            cmd.extend(["-f", str(override_yml)])
        if (self.settings.project_root / "docker-compose.extra.yml").exists():
            cmd.extend(["-f", str(self.settings.project_root / "docker-compose.extra.yml")])
        if (self.settings.project_root / "docker-compose.sandbox.yml").exists():
            cmd.extend(["-f", str(self.settings.project_root / "docker-compose.sandbox.yml")])

        cmd.extend(["up", "-d", "--build", "--force-recreate", "openclaw-gateway"])

        await async_run_command(
            cmd, cwd=self.settings.openclaw_dir, env=env, stream_output=self.verbose
        )

    async def cleanup_zombies(self) -> None:
        """The 'Zombie Protocol' - cleans up stuck tasks and stale containers."""
        logger.info("Executing OpenClaw Zombie Protocol...")

        # 1. Clear stuck OpenClaw tasks

        task_db = OPENCLAW_CONFIG_DIR / "tasks" / "runs.sqlite"
        if task_db.exists():
            logger.info(f"Clearing zombie tasks in {task_db}")
            try:
                await async_run_command(
                    [
                        "sqlite3",
                        str(task_db),
                        "UPDATE task_runs SET status = 'failed', error = 'Zombie task cleared by update_openclaw' WHERE status = 'running';",
                    ],
                    check=False,
                )
            except Exception as e:
                logger.warning(f"Failed to clear zombie tasks: {e}")

        # 2. Cleanup stale containers (orphaned or exited long ago)
        logger.info("Cleaning up stale containers and networks...")
        try:
            await async_run_command(["docker", "container", "prune", "-f"], check=False)
            await async_run_command(["docker", "network", "prune", "-f"], check=False)
        except Exception as e:
            logger.warning(f"Docker cleanup failed: {e}")

    async def verify_deployment(self) -> None:
        """Verify that OpenClaw is running and models are correctly synced."""
        logger.info("Verifying OpenClaw deployment...")

        # 1. Discover actual container name for openclaw-gateway service
        container_name = "openclaw-openclaw-gateway-1"  # Default fallback
        try:
            result = await async_run_command(
                ["docker", "compose", "ps", "openclaw-gateway", "--format", "{{.Name}}"],
                cwd=self.settings.openclaw_dir,
                env=self._get_compose_env(),
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                container_name = result.stdout.strip()
                logger.debug(f"Discovered container name: {container_name}")
        except Exception:
            logger.exception("Could not discover container name")
            # Using fallback: {container_name}

        # 2. Wait for container health (Docker status + Log scan)
        manager = ServiceHealthManager(container_name)
        if not await manager.wait_for_ready(timeout=120):
            logger.error(f"Container {container_name} failed to reach healthy state.")
            raise RuntimeError("Deployment verification failed: Container not healthy.")

        # 3. Check internal status via CLI
        logger.info("Checking OpenClaw internal status...")
        try:
            # We run 'status --all' to verify core services
            result = await async_run_command(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "openclaw-gateway",
                    "node",
                    "dist/index.js",
                    "status",
                    "--all",
                ],
                cwd=self.settings.openclaw_dir,
                env=self._get_compose_env(),
                check=False,
            )
            if result.returncode != 0:
                logger.warning(f"Internal status check returned non-zero code {result.returncode}")
                logger.debug(f"Stderr: {result.stderr}")
            else:
                logger.info("✅ Internal status check passed.")
        except Exception:
            logger.exception("Could not run internal status check")

        # 3. Verify models are synced
        logger.info("Verifying model synchronization...")
        try:
            result = await async_run_command(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "openclaw-gateway",
                    "node",
                    "dist/index.js",
                    "models",
                    "list",
                    "--json",
                ],
                cwd=self.settings.openclaw_dir,
                env=self._get_compose_env(),
                check=False,
            )
            if result.returncode == 0:
                try:
                    data = parse_cli_json(result.stdout)
                    models = data.get("models", [])
                    spark_models = [
                        m["key"] for m in models if m.get("key", "").startswith("spark/")
                    ]
                    if spark_models:
                        logger.info(
                            f"✅ Model sync verified. Spark models: {', '.join(spark_models)}"
                        )
                    else:
                        logger.warning(
                            "No Spark models found in 'models list'. Sync might have failed or pending reload."
                        )
                except ValueError as e:
                    logger.warning(f"Could not parse JSON from 'models list' output: {e}")
            else:
                logger.warning(f"Failed to list models via CLI: {result.stderr}")
        except Exception:
            logger.exception("Error during model verification")

    async def sync_local_skills(self) -> None:
        """Synchronize new or updated skills from upstream to the local skills directory."""

        local_skills_dir = OPENCLAW_CONFIG_DIR / "skills"
        upstream_skills_dir = self.settings.openclaw_dir / "skills"

        if upstream_skills_dir.exists():
            logger.info(f"Synchronizing upstream skills to {local_skills_dir}...")
            local_skills_dir.mkdir(parents=True, exist_ok=True)
            try:
                # -a: archive mode (preserves permissions, times, etc)
                # We don't use --delete so custom local skills remain.
                # Trailing slash ensures we copy contents into the target directory.
                await async_run_command(
                    ["rsync", "-a", f"{upstream_skills_dir}/", f"{local_skills_dir}/"], check=False
                )
            except Exception as e:
                logger.warning(f"Failed to synchronize skills: {e}")

    async def run(self) -> None:
        """Full automated update lifecycle."""
        try:
            await self.update_source()
            await self.sync_local_skills()
            if self.settings.run_setup:
                await self.bootstrap_setup()
            await self.build_gateway_image()
            await self.build_sandbox_image()
            await self.cleanup_zombies()
            await self.run_compose_up()
            await self.verify_deployment()
            logger.info("OpenClaw update completed successfully.")
        except Exception:
            logger.exception("OpenClaw update failed")
            raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pull-latest", action="store_true", help="Pull latest OpenClaw source and rebuild images"
    )
    parser.add_argument(
        "--run-setup",
        choices=["sandbox", "standard"],
        help="Run the OpenClaw bootstrap setup script in the specified mode (sandbox or standard). Overwrites configs/fragments.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Stream Docker build/compose output to the terminal",
    )
    args = parser.parse_args()

    updater = OpenClawUpdater(
        pull_latest=args.pull_latest, run_setup=args.run_setup, verbose=args.verbose
    )
    asyncio.run(updater.run())
