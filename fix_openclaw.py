import re

with open('sparkstack/manager/update_openclaw.py', 'r') as f:
    content = f.read()

content = content.replace(
"""    def __init__(
        self,
        pull_latest: bool = False,
        run_setup: str | None = None,
        project_root: Path | None = None,
        config_path: Path | None = None,
        verbose: bool = False,
    ):
        self.settings = UpdaterSettings(""",
"""    def __init__(
        self,
        pull_latest: bool = False,
        run_setup: str | None = None,
        project_root: Path | None = None,
        config_path: Path | None = None,
        verbose: bool = False,
        env: dict[str, str] | None = None,
    ):
        self.env = env
        self.settings = UpdaterSettings(""")

content = content.replace(
"""    def _get_compose_env(self) -> dict:
        env = os.environ.copy()""",
"""    def _get_compose_env(self) -> dict:
        env = self.env.copy() if self.env is not None else os.environ.copy()""")

# Now replace all async_run_command( that don't have env=
def replacer(match):
    # If the function call already contains env= anywhere before the closing paren, skip
    block = match.group(0)
    if 'env=' in block:
        return block
    # Insert env=self.env, before the closing paren
    # Wait, the closing paren is not matched by the simple regex.
    pass

# A simpler way to add env=self.env to all async_run_command calls:
# We can find each async_run_command and just regex replace the final `)` with `, env=self.env)`
# Wait, some calls are multi-line.
import ast
import builtins
# Let's just do it manually with multi_replace_file_content or a robust regex.
