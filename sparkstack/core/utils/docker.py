from sparkstack.core.utils.shell import async_run_command


class DockerClient:
    """Generic wrapper for Docker CLI operations."""

    @staticmethod
    async def get_status(container: str) -> tuple[str, str]:
        """Returns (state, health) for a container."""
        try:
            result = await async_run_command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                    container,
                ],
                check=False,
            )
            if result.returncode != 0:
                return "not_found", "none"
            parts = result.stdout.strip().split()
            if not parts:
                return "unknown", "none"
            return (parts[0], parts[1]) if len(parts) >= 2 else (parts[0], "none")
        except Exception:
            return "unknown", "none"
