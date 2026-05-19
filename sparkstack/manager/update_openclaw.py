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

from sparkstack.core.env import (
    OPENCLAW_CONFIG_DIR,
    OPENCLAW_CONFIG_PATH,
    OPENCLAW_DIR,
    OPENCLAW_ENV,
    SPARK_STACK_OPENCLAW_SKILLS_DIR,
)
from sparkstack.core.updater import BaseUpdater
from sparkstack.core.utils import ServiceHealthManager, async_run_command, parse_cli_json
from sparkstack.manager.orchestration_utils import cleanup_zombies

OPENCLAW_REPO = "https://github.com/openclaw/openclaw.git"


class UpdaterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    project_root: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent.absolute()
    )
    openclaw_dir: Path = Field(default=OPENCLAW_DIR)
    config_path: Path = Field(default=OPENCLAW_CONFIG_PATH)
    pull_latest: bool = False
    run_setup: str | None = None
    openclaw_branch: str | None = Field(default=None, alias="OPENCLAW_BRANCH")


class OpenClawUpdater(BaseUpdater):
    def __init__(
        self,
        pull_latest: bool = False,
        run_setup: str | None = None,
        project_root: Path | None = None,
        config_path: Path | None = None,
        verbose: bool = False,
        env: dict[str, str] | None = None,
    ):
        self.env = env
        self.settings = UpdaterSettings(
            pull_latest=pull_latest,
            run_setup=run_setup,
            project_root=project_root or Path(__file__).parent.parent.parent.absolute(),
            config_path=config_path or OPENCLAW_CONFIG_PATH,
        )
        self.config_path = self.settings.config_path
        self.verbose = verbose

    async def _run_cmd(self, *args, **kwargs):
        if "env" not in kwargs:
            kwargs["env"] = self.env if self.env is not None else os.environ.copy()
        return await async_run_command(*args, **kwargs)

    async def update_source(self) -> None:
        if not self.settings.pull_latest:
            logger.info("Skipping OpenClaw source update. Use --pull-latest to update.")
            return

        logger.info(f"Updating OpenClaw source in {self.settings.openclaw_dir}...")

        # 1. Ensure the repo exists
        if not self.settings.openclaw_dir.exists():
            await self._run_cmd(
                ["git", "clone", OPENCLAW_REPO, "openclaw"],
                cwd=self.settings.openclaw_dir.parent,
                stream_output=True,
            )

        if self.settings.openclaw_branch:
            logger.info(f"Updating to branch: {self.settings.openclaw_branch}")
            await self._run_cmd(
                ["git", "fetch", "origin", self.settings.openclaw_branch],
                cwd=self.settings.openclaw_dir,
                stream_output=True,
            )
            await self._run_cmd(
                ["git", "checkout", self.settings.openclaw_branch],
                cwd=self.settings.openclaw_dir,
                stream_output=True,
            )
            await self._run_cmd(
                ["git", "reset", "--hard", f"origin/{self.settings.openclaw_branch}"],
                cwd=self.settings.openclaw_dir,
                stream_output=True,
            )
            return

        # 2. Get the latest stable release tag using git ls-remote
        try:
            result = await self._run_cmd(
                [
                    "git",
                    "ls-remote",
                    "--tags",
                    "--refs",
                    "--sort=v:refname",
                    OPENCLAW_REPO,
                ],
                cwd=self.settings.project_root,
            )
            tags = []
            for line in result.stdout.strip().splitlines():
                parts = line.split("refs/tags/")
                if len(parts) == 2:
                    tag = parts[1]
                    if "beta" not in tag:
                        tags.append(tag)

            if not tags:
                raise ValueError("Failed to retrieve a valid tag from git.")
            latest_tag = tags[-1]
            logger.info(f"Latest stable release for {OPENCLAW_REPO} is {latest_tag}")
        except Exception:
            logger.exception("Could not determine latest stable release")
            raise

        # 3. Fetch tags
        await self._run_cmd(
            ["git", "fetch", "--tags", "--force"],
            cwd=self.settings.openclaw_dir,
            stream_output=True,
        )

        # 4. Preserve in-development changes: if we're on a local branch, rebase onto the latest stable tag instead of forcing checkout
        branch_result = await self._run_cmd(
            ["git", "branch", "--show-current"], cwd=self.settings.openclaw_dir
        )
        current_branch = branch_result.stdout.strip()
        if current_branch:
            # Find the old base tag
            base_tag_result = await self._run_cmd(
                ["git", "describe", "--tags", "--abbrev=0", current_branch],
                cwd=self.settings.openclaw_dir,
            )
            base_tag = base_tag_result.stdout.strip()

            logger.info(
                f"OpenClaw is on active branch '{current_branch}' (based on {base_tag}). Rebasing onto {latest_tag}."
            )
            await self._run_cmd(
                ["git", "rebase", "--onto", latest_tag, base_tag, current_branch],
                cwd=self.settings.openclaw_dir,
                stream_output=True,
            )
            return

        # 5. Otherwise checkout the specific stable release
        await self._run_cmd(
            ["git", "checkout", latest_tag], cwd=self.settings.openclaw_dir, stream_output=True
        )

    async def bootstrap_setup(self) -> None:
        """Run the initial openclaw setup.sh script and copy the resulting compose fragments."""
        logger.info(
            f"Executing official OpenClaw Docker setup script in {self.settings.run_setup} mode..."
        )
        env = self._get_compose_env()

        env.update({"CI": "1"})
        if self.settings.run_setup == "sandbox":
            # We invoke setup.sh to seamlessly validate and compile the CLI docker socket boundaries natively.
            env.update({"OPENCLAW_SANDBOX": "1"})

        await self._run_cmd(
            ["bash", "-c", "bash scripts/docker/setup.sh < /dev/null"],
            cwd=self.settings.openclaw_dir,
            env=env,
            stream_output=self.verbose,
        )

        env_example = self.settings.openclaw_dir / ".env.example"
        env_dest = self.settings.project_root / ".env"
        if env_example.exists() and not env_dest.exists():
            logger.info("Creating initial openclaw.json and .env from templates.")
            await asyncio.to_thread(shutil.copy2, env_example, env_dest)

    async def build_sandbox_image(self) -> None:
        """Rebuild the isolated sandbox image and base."""
        logger.info("Building custom OpenClaw Sandbox image (openclaw-sandbox-custom)...")

        # First ensure the un-customized sandbox base image exists
        await self._run_cmd(
            ["bash", "scripts/sandbox-setup.sh"],
            cwd=self.settings.openclaw_dir,
            env=self._get_compose_env(),
            stream_output=self.verbose,
        )

        # Prepare the skills directory for the Docker build context
        build_skills_dir = self.settings.project_root / "services/openclaw/build_skills"
        if build_skills_dir.exists():
            await asyncio.to_thread(shutil.rmtree, build_skills_dir)

        if SPARK_STACK_OPENCLAW_SKILLS_DIR.exists():
            await asyncio.to_thread(
                shutil.copytree, SPARK_STACK_OPENCLAW_SKILLS_DIR, build_skills_dir
            )
        else:
            await asyncio.to_thread(build_skills_dir.mkdir, parents=True, exist_ok=True)

        # Compile our custom override layers for agent usage
        await self._run_cmd(
            [
                "docker",
                "build",
                "-t",
                "openclaw-sandbox-custom:latest",
                "-f",
                "docker/Dockerfile.sandbox-custom",
                ".",
            ],
            cwd=self.settings.project_root / "services/openclaw",
            env=self._get_compose_env(),
            stream_output=self.verbose,
        )

    async def build_gateway_image(self) -> None:
        """Rebuild the customized gateway image with embedded ACP tools."""
        # We MUST build openclaw:local first. The upstream docker-compose.yml
        # defines `build: .` for the openclaw-gateway service. If we don't build this base
        # image explicitly, our custom Dockerfile (which uses FROM openclaw:local) will
        # fail to pull the latest source code updates.
        logger.info("Building base OpenClaw image (openclaw:local)...")
        await self._run_cmd(
            [
                "docker",
                "build",
                "-t",
                "openclaw:local",
                "-f",
                "Dockerfile",
                ".",
            ],
            cwd=self.settings.openclaw_dir,
            env=self._get_compose_env(),
            stream_output=self.verbose,
        )

        logger.info("Building custom OpenClaw Gateway image (openclaw-gateway-custom)...")
        await self._run_cmd(
            [
                "docker",
                "build",
                "-t",
                "openclaw-gateway-custom:latest",
                "-f",
                "docker/Dockerfile.gateway-custom",
                ".",
            ],
            cwd=self.settings.project_root / "services/openclaw",
            env=self._get_compose_env(),
            stream_output=self.verbose,
        )

    def _get_compose_env(self) -> dict:
        env = self.env.copy() if self.env is not None else os.environ.copy()

        # Load .env from openclaw config dir so docker compose interpolates correctly
        env.update({k: str(v) for k, v in OPENCLAW_ENV.items() if v is not None})

        # The docker-compose.override.yml requires SPARKSTACK_DIR for the
        # x-sparkstack-enforce guard.  Resolve the ``current`` symlink the
        # same way MonitoringService and _set_current do.
        stack_dir = self.settings.project_root / "current"
        if stack_dir.exists():
            env["SPARKSTACK_DIR"] = str(stack_dir.resolve())

        from sparkstack.core.env import (
            OPENCLAW_NODE_TARGET,
            SPARKSTACK_HEAD_TAILNET_IP,
            WORKER_TAILNET_IP,
        )

        if SPARKSTACK_HEAD_TAILNET_IP:
            env["SPARKSTACK_HEAD_TAILNET_IP"] = SPARKSTACK_HEAD_TAILNET_IP
        if WORKER_TAILNET_IP:
            env["WORKER_TAILNET_IP"] = WORKER_TAILNET_IP

        if OPENCLAW_NODE_TARGET:
            if "://" in OPENCLAW_NODE_TARGET:
                env["DOCKER_HOST"] = OPENCLAW_NODE_TARGET
            else:
                env["DOCKER_CONTEXT"] = OPENCLAW_NODE_TARGET

        return env

    async def run_compose_up(self) -> None:
        logger.info("Deploying OpenClaw via Docker Compose...")

        env = self._get_compose_env()

        cmd = ["docker", "compose", "-f", "docker-compose.yml"]
        override_yml = (
            self.settings.project_root
            / "services"
            / "openclaw"
            / "docker"
            / "docker-compose.override.yml"
        )
        if override_yml.exists():
            cmd.extend(["-f", str(override_yml)])
        if (self.settings.openclaw_dir / "docker-compose.extra.yml").exists():
            cmd.extend(["-f", str(self.settings.openclaw_dir / "docker-compose.extra.yml")])

        if (
            self.settings.run_setup == "sandbox"
            and (self.settings.openclaw_dir / "docker-compose.sandbox.yml").exists()
        ):
            cmd.extend(["-f", str(self.settings.openclaw_dir / "docker-compose.sandbox.yml")])

        # DO NOT use the `--build` flag here!
        # Because docker-compose.override.yml explicitly sets `image: openclaw-gateway-custom:latest`
        # and the base docker-compose.yml sets `build: .`, passing `--build` will cause Compose to
        # build the base directory (.) and erroneously tag it as our custom image name, completely
        # overwriting the custom image we just built in `build_gateway_image()`.
        cmd.extend(["up", "-d", "--force-recreate", "openclaw-gateway"])

        await self._run_cmd(
            cmd, cwd=self.settings.openclaw_dir, env=env, stream_output=self.verbose
        )

    async def verify_deployment(self) -> None:
        """Verify that OpenClaw is running and models are correctly synced."""
        logger.info("Verifying OpenClaw deployment...")

        # 1. Discover actual container name for openclaw-gateway service
        container_name = "openclaw-openclaw-gateway-1"  # Default fallback
        try:
            result = await self._run_cmd(
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
            result = await self._run_cmd(
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
            result = await self._run_cmd(
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
                    models = data.get("models", []) if isinstance(data, dict) else data
                    spark_models = [
                        m["key"]
                        for m in models
                        if isinstance(m, dict) and m.get("key", "").startswith("spark/")
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

    async def run_doctor(self) -> None:
        """Run 'openclaw doctor --fix' to auto-repair agent-level config drift.

        This catches stale agent-level models.json files, split-brain state
        directories, and other misconfigurations that accumulate between
        deployments.  Without this, agent-level overrides silently go stale
        and can cause parameter mismatches (wrong maxTokens, API type, etc.).
        """
        logger.info("Running OpenClaw doctor --fix --non-interactive...")
        try:
            result = await self._run_cmd(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "openclaw-gateway",
                    "node",
                    "dist/index.js",
                    "doctor",
                    "--fix",
                    "--non-interactive",
                ],
                cwd=self.settings.openclaw_dir,
                env=self._get_compose_env(),
                check=False,
            )
            if result.returncode == 0:
                logger.info("✅ OpenClaw doctor completed successfully.")
            else:
                logger.warning(f"OpenClaw doctor returned non-zero exit code {result.returncode}")
                if result.stderr:
                    logger.debug(f"Doctor stderr: {result.stderr}")
            if result.stdout:
                for line in result.stdout.strip().splitlines():
                    logger.info(f"  doctor: {line}")
        except Exception:
            logger.exception("OpenClaw doctor failed")

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
                await self._run_cmd(
                    ["rsync", "-a", f"{upstream_skills_dir}/", f"{local_skills_dir}/"], check=False
                )
            except Exception as e:
                logger.warning(f"Failed to synchronize skills: {e}")

    async def run_events(self):
        """Full automated update lifecycle, yielding progress events."""
        try:
            yield ("Initializing", 10)
            await self.update_source()

            yield ("Updating source", 30)
            await self.sync_local_skills()
            if self.settings.run_setup:
                await self.bootstrap_setup()

            yield ("Building gateway image", 45)
            await self.build_gateway_image()

            yield ("Building sandbox image", 60)
            await self.build_sandbox_image()

            # Clean up build context
            build_skills_dir = self.settings.project_root / "services/openclaw/build_skills"
            if build_skills_dir.exists():
                shutil.rmtree(build_skills_dir)

            yield ("Cleaning up zombies", 75)
            await cleanup_zombies()

            yield ("Deploying", 80)
            await self.run_compose_up()

            yield ("Verifying deployment", 90)
            await self.verify_deployment()

            yield ("Running doctor", 95)
            await self.run_doctor()

            logger.info("OpenClaw update completed successfully.")
            yield ("Complete", 100)
        except Exception:
            logger.exception("OpenClaw update failed")
            raise


if __name__ == "__main__":
    import argparse
    import asyncio
    from pathlib import Path

    from sparkstack.core.utils import run_with_lock

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

    async def _cli_run():
        async for _ in updater.run_events():
            pass

    run_with_lock(".sparkstack-update-openclaw.lock", _cli_run())
