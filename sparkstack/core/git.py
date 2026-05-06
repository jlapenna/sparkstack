"""
core/git.py - Shared async git operations for source dependency management.
"""

from pathlib import Path

from loguru import logger

from sparkstack.core.utils.shell import CommandError, async_run_command


async def sync_sparkrun_repo(repo_dir: Path) -> None:
    """Sync SparkRun repository maintaining local-dev rebase workflow."""
    res = await async_run_command(["git", "branch", "--show-current"], cwd=repo_dir)
    current_branch = res.stdout.strip()

    await async_run_command(["git", "fetch", "origin"], cwd=repo_dir)

    if current_branch == "local-dev" or current_branch.startswith("local/"):
        logger.info(
            f"Detected {current_branch} branch integration. Attempting to sync and rebase upstream/main."
        )
        res_remotes = await async_run_command(["git", "remote"], cwd=repo_dir)
        if "upstream" in res_remotes.stdout:
            logger.info("Fetching from upstream...")
            await async_run_command(["git", "fetch", "upstream"], cwd=repo_dir)

            logger.info(f"Rebasing {current_branch} onto upstream/main...")
            try:
                await async_run_command(["git", "rebase", "upstream/main"], cwd=repo_dir)
            except CommandError:
                logger.error(
                    f"Rebase failed. You may have conflicts. Please resolve them in {repo_dir} and run 'git rebase --continue'."
                )
                raise
        else:
            logger.warning(
                "No 'upstream' remote configured. Skipping upstream sync. "
                "To enable automatic syncs, run: git remote add upstream https://github.com/spark-arena/sparkrun.git"
            )
    else:
        await async_run_command(["git", "checkout", "-f", "main"], cwd=repo_dir)
        await async_run_command(["git", "reset", "--hard", "origin/main"], cwd=repo_dir)

    await async_run_command(["git", "clean", "-fd"], cwd=repo_dir)


async def sync_openclaw_repo(
    repo_dir: Path,
    target_branch: str | None = None,
    repo_url: str = "https://github.com/jlapenna/openclaw.git",
    project_root: Path | None = None,
) -> None:
    """Sync OpenClaw repository, respecting local changes or fetching the latest stable tag."""
    if not repo_dir.exists():
        await async_run_command(
            ["git", "clone", repo_url, "openclaw"],
            cwd=repo_dir.parent,
            stream_output=True,
        )

    if target_branch:
        logger.info(f"Updating to branch: {target_branch}")
        await async_run_command(
            ["git", "fetch", "origin", target_branch], cwd=repo_dir, stream_output=True
        )
        await async_run_command(
            ["git", "checkout", target_branch], cwd=repo_dir, stream_output=True
        )
        await async_run_command(
            ["git", "reset", "--hard", f"origin/{target_branch}"], cwd=repo_dir, stream_output=True
        )
        return

    # Preserve in-development changes
    try:
        branch_result = await async_run_command(["git", "branch", "--show-current"], cwd=repo_dir)
        current_branch = branch_result.stdout.strip()
        if current_branch:
            logger.info(
                f"OpenClaw is on active branch '{current_branch}'. Pulling updates via rebase."
            )
            await async_run_command(["git", "pull", "--rebase"], cwd=repo_dir, stream_output=True)
            return
    except Exception as e:
        logger.debug(f"Branch check failed: {e}")

    # Get latest stable release
    try:
        result = await async_run_command(
            [
                "gh",
                "release",
                "view",
                "--repo",
                repo_url,
                "--json",
                "tagName",
                "--jq",
                ".tagName",
            ],
            cwd=project_root if project_root else repo_dir,
        )
        latest_tag = result.stdout.strip()
        if not latest_tag:
            raise ValueError("Failed to retrieve a valid tag from GitHub.")
        logger.info(f"Latest stable release for {repo_url} is {latest_tag}")
    except Exception:
        logger.exception("Could not determine latest stable release")
        raise

    await async_run_command(["git", "fetch", "--tags", "--force"], cwd=repo_dir, stream_output=True)
    await async_run_command(["git", "checkout", latest_tag], cwd=repo_dir, stream_output=True)
