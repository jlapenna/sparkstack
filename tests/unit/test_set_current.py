import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sparkstack.manager.set_current import main


@pytest.mark.asyncio
async def test_set_current_escapes_root(tmp_path):
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    # Target outside root_dir
    target_dir = tmp_path / "outside_target"
    target_dir.mkdir()

    mock_args = MagicMock()
    mock_args.target = str(target_dir)

    with (
        patch("argparse.ArgumentParser.parse_args", return_value=mock_args),
        patch("sparkstack.manager.set_current.ROOT_DIR", root_dir),
        patch("sparkstack.manager.set_current.STACKS_DIR", root_dir / "stacks"),
        pytest.raises(SystemExit) as excinfo,
    ):
        await main()
    assert excinfo.value.code == 1


@pytest.mark.asyncio
async def test_set_current_nonexistent(tmp_path):
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    mock_args = MagicMock()
    mock_args.target = "stacks/nonexistent"

    with (
        patch("argparse.ArgumentParser.parse_args", return_value=mock_args),
        patch("sparkstack.manager.set_current.ROOT_DIR", root_dir),
        patch("sparkstack.manager.set_current.STACKS_DIR", root_dir / "stacks"),
        pytest.raises(SystemExit) as excinfo,
    ):
        await main()
    assert excinfo.value.code == 1


@pytest.mark.asyncio
async def test_set_current_success(tmp_path):
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    stacks_dir = root_dir / "sparkstack-registry" / "stacks"
    stacks_dir.mkdir(parents=True)

    # Create outgoing stack
    outgoing_stack = stacks_dir / "old-stack"
    outgoing_stack.mkdir()

    # Create sidecar state in old stack
    state_file = outgoing_stack / ".state.json"
    state_data = {
        "cluster_name": "old-cluster",
        "sidecars": {
            "spark": {
                "container_name": "sparkstack-sidecar-spark",
                "tailnet_ip": "100.64.0.2",
                "role": "worker",
            }
        },
    }
    with open(state_file, "w") as f:
        json.dump(state_data, f)

    # Symlink current to outgoing stack
    current_symlink = root_dir / "current"
    current_symlink.symlink_to(outgoing_stack)

    # Create target stack (new stack)
    target_stack = stacks_dir / "new-stack"
    target_stack.mkdir()
    (target_stack / "stack.yaml").write_text("backends: []")

    mock_args = MagicMock()
    mock_args.target = "sparkstack-registry/stacks/new-stack"

    mock_run = AsyncMock()
    mock_run.return_value.stdout = "container1 container2"
    mock_run.return_value.returncode = 0

    mock_compose = AsyncMock()
    mock_launch = AsyncMock()
    mock_teardown = AsyncMock()

    # Make network inspect fail to trigger network create
    async def run_cmd_side_effect(cmd, *args, **kwargs):
        if "network" in cmd and "inspect" in cmd:
            mock_res = MagicMock()
            mock_res.returncode = 1
            mock_res.stdout = ""
            return mock_res
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "container1 container2"
        return mock_res

    mock_run.side_effect = run_cmd_side_effect

    with (
        patch("argparse.ArgumentParser.parse_args", return_value=mock_args),
        patch("sparkstack.manager.set_current.ROOT_DIR", root_dir),
        patch("sparkstack.manager.set_current.STACKS_DIR", stacks_dir),
        patch("sparkstack.manager.set_current.async_run_command", mock_run),
        patch("sparkstack.manager.set_current.async_run_compose", mock_compose),
        patch("sparkstack.manager.set_current.launch_stack", mock_launch),
        patch("sparkstack.manager.remote.teardown_sidecars", mock_teardown),
        patch("sparkstack.manager.set_current.is_monitoring_external", return_value=False),
    ):
        await main()

        # Verify symlink swapped
        assert current_symlink.is_symlink()
        assert current_symlink.resolve() == target_stack

        # Verify Tier 1 teardown (sparkrun stop called)
        stop_calls = [c[0][0] for c in mock_run.call_args_list if "stop" in c[0][0]]
        assert len(stop_calls) == 1
        assert "--cluster" in stop_calls[0]
        assert "old-cluster" in stop_calls[0]

        # Verify Tier 2 teardown (teardown_sidecars called)
        mock_teardown.assert_called_once_with(outgoing_stack, hosts_to_keep=set())

        # Verify lingering local containers cleared
        rm_calls = [c[0][0] for c in mock_run.call_args_list if "rm" in c[0][0]]
        # At least one call to docker rm -f container1 container2, and one for litellm
        assert any("container1" in c for c in rm_calls)
        assert any("litellm" in c for c in rm_calls)

        # Verify network pruned and created
        prune_calls = [c[0][0] for c in mock_run.call_args_list if "prune" in c[0][0]]
        assert len(prune_calls) == 1
        create_calls = [c[0][0] for c in mock_run.call_args_list if "create" in c[0][0]]
        assert len(create_calls) == 1

        # Verify launch_stack called
        mock_launch.assert_called_once_with(target_stack)

        # Verify compose calls for monitoring
        assert mock_compose.call_count == 2
        # First calls compose rm, then compose up
        monitor_dir = root_dir / "services" / "monitoring"
        mock_compose.assert_any_call(monitor_dir, "rm", "-fsv", "prometheus", check=False)
        mock_compose.assert_any_call(monitor_dir, "up", "-d", check=False)


@pytest.mark.asyncio
async def test_set_current_no_hybrid_service(tmp_path):
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    stacks_dir = root_dir / "sparkstack-registry" / "stacks"
    stacks_dir.mkdir(parents=True)

    # Create target stack (no stack.yaml, just compose stack)
    target_stack = stacks_dir / "new-stack"
    target_stack.mkdir()

    mock_args = MagicMock()
    mock_args.target = "sparkstack-registry/stacks/new-stack"

    mock_run = AsyncMock()
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    mock_compose = AsyncMock()
    mock_launch = AsyncMock()

    current_symlink = root_dir / "current"

    with (
        patch("argparse.ArgumentParser.parse_args", return_value=mock_args),
        patch("sparkstack.manager.set_current.ROOT_DIR", root_dir),
        patch("sparkstack.manager.set_current.STACKS_DIR", stacks_dir),
        patch("sparkstack.manager.set_current.async_run_command", mock_run),
        patch("sparkstack.manager.set_current.async_run_compose", mock_compose),
        patch("sparkstack.manager.set_current.launch_stack", mock_launch),
        patch("sparkstack.manager.set_current.is_monitoring_external", return_value=False),
    ):
        await main()

        # Verify symlink swapped
        assert current_symlink.is_symlink()
        assert current_symlink.resolve() == target_stack

        # Verify systemd service commands called since stack.yaml is not present
        daemon_reload_call = next(
            c[0][0] for c in mock_run.call_args_list if "daemon-reload" in c[0][0]
        )
        assert "systemctl" in daemon_reload_call

        service_start_call = next(
            c[0][0] for c in mock_run.call_args_list if "vllm-active.service" in c[0][0]
        )
        assert "systemctl" in service_start_call
        assert "start" in service_start_call

        # launch_stack should not have been called
        mock_launch.assert_not_called()
