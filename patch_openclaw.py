with open("sparkstack/manager/update_openclaw.py") as f:
    content = f.read()

# 1. Update __init__
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
        self.settings = UpdaterSettings(""",
)

# 2. Update _get_compose_env
content = content.replace(
    """    def _get_compose_env(self) -> dict:
        env = os.environ.copy()""",
    """    def _get_compose_env(self) -> dict:
        env = self.env.copy() if self.env is not None else os.environ.copy()""",
)


# 3. Add env=self.env to all async_run_command calls that don't have env=
def replace_async_run_command(match):
    block = match.group(0)
    if "env=" in block:
        return block
    # insert env=self.env right before the closing parenthesis.
    # The block might be multiline.
    return block[:-1] + ", env=self.env)"


# Match async_run_command( ... ) spanning multiple lines, correctly balancing parentheses
# But regex for nested parentheses is hard. Let's do a simple parse:
out = []
i = 0
while True:
    idx = content.find("async_run_command(", i)
    if idx == -1:
        out.append(content[i:])
        break
    out.append(content[i:idx])

    # find closing parenthesis
    paren_count = 0
    in_str = False
    str_char = ""
    j = idx + len("async_run_command(")
    has_env = False
    arg_start = j

    while j < len(content):
        c = content[j]
        if c == "\\":
            j += 2
            continue
        if in_str:
            if c == str_char:
                in_str = False
        else:
            if c in "'\"":
                in_str = True
                str_char = c
            elif c == "(":
                paren_count += 1
            elif c == ")":
                if paren_count == 0:
                    break
                paren_count -= 1
        j += 1

    call_args = content[idx + len("async_run_command(") : j]
    if "env=" in call_args:
        out.append(content[idx : j + 1])
    else:
        # append env=self.env before the closing paren
        out.append("async_run_command(" + call_args + ", env=self.env)")
    i = j + 1

with open("sparkstack/manager/update_openclaw.py", "w") as f:
    f.write("".join(out))
print("Patched update_openclaw.py successfully")
