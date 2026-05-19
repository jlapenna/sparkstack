import re

with open('sparkstack/manager/update_openclaw.py', 'r') as f:
    content = f.read()

content = content.replace('await async_run_command(', 'await self._run_cmd(')

with open('sparkstack/manager/update_openclaw.py', 'w') as f:
    f.write(content)
