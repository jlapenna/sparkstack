import pytest

from sparkstack.core.utils.shell import CommandError, async_run_command


@pytest.mark.asyncio
async def test_async_run_command_success():
    result = await async_run_command(["echo", "hello"])
    assert result.returncode == 0
    assert result.stdout == "hello"
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_async_run_command_failure():
    with pytest.raises(CommandError) as excinfo:
        await async_run_command(["false"])
    assert excinfo.value.returncode == 1


@pytest.mark.asyncio
async def test_async_run_command_cwd(tmp_path):
    (tmp_path / "test.txt").write_text("content")
    result = await async_run_command(["cat", "test.txt"], cwd=tmp_path)
    assert result.stdout == "content"


@pytest.mark.asyncio
async def test_async_run_command_env():
    result = await async_run_command(["sh", "-c", "echo $TEST_VAR"], env={"TEST_VAR": "val"})
    assert result.stdout == "val"
