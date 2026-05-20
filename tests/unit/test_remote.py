from unittest.mock import AsyncMock, patch

import pytest

from sparkstack.manager.remote import (
    _get_sidecar_ip_local,
    _is_sidecar_healthy_local,
    _is_sidecar_healthy_remote,
    _remove_container_if_exists_local,
    _wait_for_sidecar_local,
    deploy_head_sidecar,
    deploy_worker_sidecar,
    get_headscale_auth_key,
    poll_sidecar_health,
    read_sidecar_state,
    resolve_head_tailnet_ip,
    resolve_worker_tailnet_ip,
    run_ssh_command,
    sidecar_name,
    teardown_sidecars,
    write_sidecar_state,
)


def test_sidecar_name():
    assert sidecar_name("spark") == "sparkstack-sidecar-spark"
    assert sidecar_name("host-1") == "sparkstack-sidecar-host-1"


def test_read_write_sidecar_state(tmp_path):
    # Test writing and reading state
    cluster_name = "test-cluster"
    sidecars = {
        "spark": {
            "container_name": "sparkstack-sidecar-spark",
            "tailnet_ip": "100.64.0.2",
            "role": "worker",
        }
    }

    # Read non-existent state should return empty dict
    assert read_sidecar_state(tmp_path) == {}

    # Write and then read state
    write_sidecar_state(tmp_path, cluster_name, sidecars)

    state = read_sidecar_state(tmp_path)
    assert state["cluster_name"] == cluster_name
    assert state["sidecars"] == sidecars
    assert "deployed_at" in state


@pytest.mark.asyncio
async def test_run_ssh_command_success():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"output\n", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        res = await run_ssh_command("user@host", "echo hello")
        assert res == "output"
        mock_exec.assert_called_once_with(
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            "user@host",
            "echo hello",
            stdout=-1,
            stderr=-1,
        )


@pytest.mark.asyncio
async def test_run_ssh_command_failure():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"permission denied\n")
    mock_proc.returncode = 255

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        pytest.raises(RuntimeError, match="SSH command failed on user@host"),
    ):
        await run_ssh_command("user@host", "invalid command")


@pytest.mark.asyncio
async def test_get_headscale_auth_key():
    mock_proc_user = AsyncMock()
    mock_proc_user.communicate.return_value = (b"", b"")
    mock_proc_user.returncode = 0

    mock_proc_key = AsyncMock()
    mock_proc_key.communicate.return_value = (b"some-auth-key\n", b"")
    mock_proc_key.returncode = 0

    # Mocking create_subprocess_exec side effect for the two sequential commands
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = [mock_proc_user, mock_proc_key]

        key = await get_headscale_auth_key("test-user")
        assert key == "some-auth-key"
        assert mock_exec.call_count == 2


@pytest.mark.asyncio
async def test_resolve_worker_tailnet_ip():
    with patch("sparkstack.manager.remote.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
        mock_ssh.return_value = "100.64.0.2\n"
        ip = await resolve_worker_tailnet_ip("user@spark", "spark")
        assert ip == "100.64.0.2"
        mock_ssh.assert_called_once_with(
            "user@spark",
            "docker exec sparkstack-sidecar-spark tailscale ip -4",
            timeout=15,
        )


@pytest.mark.asyncio
async def test_poll_sidecar_health_healthy():
    with patch(
        "sparkstack.manager.remote._is_sidecar_healthy_remote", new_callable=AsyncMock
    ) as mock_healthy:
        mock_healthy.return_value = True
        is_healthy = await poll_sidecar_health("user@spark", "spark")
        assert is_healthy is True
        mock_healthy.assert_called_once_with("user@spark", "sparkstack-sidecar-spark")


@pytest.mark.asyncio
async def test_poll_sidecar_health_unhealthy():
    with patch(
        "sparkstack.manager.remote._is_sidecar_healthy_remote", new_callable=AsyncMock
    ) as mock_healthy:
        mock_healthy.return_value = False
        is_healthy = await poll_sidecar_health("user@spark", "spark")
        assert is_healthy is False


@pytest.mark.asyncio
async def test_teardown_sidecars(tmp_path):
    cluster_name = "test-cluster"
    sidecars = {
        "spark": {
            "container_name": "sparkstack-sidecar-spark",
            "tailnet_ip": "100.64.0.2",
            "role": "worker",
        },
        "spark-2": {
            "container_name": "sparkstack-sidecar-spark-2",
            "tailnet_ip": "100.64.0.3",
            "role": "worker",
        },
    }
    write_sidecar_state(tmp_path, cluster_name, sidecars)

    with patch("sparkstack.manager.remote.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
        # Keep 'spark', tear down 'spark-2'
        await teardown_sidecars(tmp_path, hosts_to_keep={"spark"}, ssh_user="ssh-user@")

        mock_ssh.assert_called_once_with(
            "ssh-user@spark-2",
            "docker rm -f sparkstack-sidecar-spark-2 2>/dev/null || true",
            timeout=15,
        )

        # State should be updated
        state = read_sidecar_state(tmp_path)
        assert "spark" in state["sidecars"]
        assert "spark-2" not in state["sidecars"]


@pytest.mark.asyncio
async def test_deploy_head_sidecar_already_healthy():
    with (
        patch(
            "sparkstack.manager.remote._is_sidecar_healthy_local", new_callable=AsyncMock
        ) as mock_healthy,
        patch("sparkstack.manager.remote.get_headscale_url", return_value="http://127.0.0.1:8080"),
        patch("sparkstack.core.env.SPARKSTACK_HEADSCALE_AUTH_KEY", "test-auth-key"),
    ):
        mock_healthy.return_value = True

        # When healthy, it should return immediately without starting container
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            await deploy_head_sidecar()
            mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_deploy_head_sidecar_new():
    mock_proc_run = AsyncMock()
    mock_proc_run.communicate.return_value = (b"", b"")
    mock_proc_run.returncode = 0

    mock_proc_connect = AsyncMock()
    mock_proc_connect.communicate.return_value = (b"", b"")
    mock_proc_connect.returncode = 0

    with (
        patch(
            "sparkstack.manager.remote._is_sidecar_healthy_local", new_callable=AsyncMock
        ) as mock_healthy,
        patch(
            "sparkstack.manager.remote._remove_container_if_exists_local", new_callable=AsyncMock
        ) as mock_rm,
        patch(
            "sparkstack.manager.remote._wait_for_sidecar_local", new_callable=AsyncMock
        ) as mock_wait,
        patch("sparkstack.manager.remote.get_headscale_url", return_value="http://127.0.0.1:8080"),
        patch("sparkstack.core.env.SPARKSTACK_HEADSCALE_AUTH_KEY", "test-auth-key"),
    ):
        # Initially not healthy
        mock_healthy.return_value = False

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [mock_proc_run, mock_proc_connect]

            await deploy_head_sidecar()

            mock_rm.assert_called_once_with("sparkstack-head-sidecar")
            assert mock_exec.call_count == 2
            mock_wait.assert_called_once_with("sparkstack-head-sidecar", timeout=60)


@pytest.mark.asyncio
async def test_deploy_worker_sidecar_already_healthy():
    with patch(
        "sparkstack.manager.remote._is_sidecar_healthy_remote", new_callable=AsyncMock
    ) as mock_healthy:
        mock_healthy.return_value = True

        # Should return immediately and not run ssh command
        with patch("sparkstack.manager.remote.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            await deploy_worker_sidecar(
                target="user@spark",
                hostname="spark",
                auth_key="test-key",
                headscale_url="http://127.0.0.1:8080",
            )
            mock_ssh.assert_not_called()


@pytest.mark.asyncio
async def test_deploy_worker_sidecar_new():
    with (
        patch(
            "sparkstack.manager.remote._is_sidecar_healthy_remote", new_callable=AsyncMock
        ) as mock_healthy,
        patch("sparkstack.manager.remote.run_ssh_command", new_callable=AsyncMock) as mock_ssh,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        # Unhealthy initially (idempotency), unhealthy on 1st poll, healthy on 2nd poll
        mock_healthy.side_effect = [False, False, True]

        await deploy_worker_sidecar(
            target="user@spark",
            hostname="spark",
            auth_key="test-key",
            headscale_url="http://127.0.0.1:8080",
        )

        # Expect two SSH commands: container removal and container start
        assert mock_ssh.call_count == 2
        mock_ssh.assert_any_call(
            "user@spark",
            "docker rm -f sparkstack-sidecar-spark 2>/dev/null || true",
        )
        mock_sleep.assert_called_once_with(3)


@pytest.mark.asyncio
async def test_resolve_head_tailnet_ip():
    with patch(
        "sparkstack.manager.remote._get_sidecar_ip_local", new_callable=AsyncMock
    ) as mock_get_ip:
        mock_get_ip.return_value = "100.64.0.1"
        ip = await resolve_head_tailnet_ip()
        assert ip == "100.64.0.1"
        mock_get_ip.assert_called_once_with("sparkstack-head-sidecar")


@pytest.mark.asyncio
async def test_is_sidecar_healthy_local_healthy():
    mock_ps = AsyncMock()
    mock_ps.communicate.return_value = (b"12345\n", b"")
    mock_ps.returncode = 0

    mock_status = AsyncMock()
    mock_status.communicate.return_value = (b'{"BackendState": "Running"}\n', b"")
    mock_status.returncode = 0

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = [mock_ps, mock_status]
        res = await _is_sidecar_healthy_local("test-container")
        assert res is True
        assert mock_exec.call_count == 2


@pytest.mark.asyncio
async def test_is_sidecar_healthy_local_not_running():
    mock_ps = AsyncMock()
    mock_ps.communicate.return_value = (b"", b"")
    mock_ps.returncode = 0

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = mock_ps
        res = await _is_sidecar_healthy_local("test-container")
        assert res is False
        mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_is_sidecar_healthy_local_backend_not_running():
    mock_ps = AsyncMock()
    mock_ps.communicate.return_value = (b"12345\n", b"")
    mock_ps.returncode = 0

    mock_status = AsyncMock()
    mock_status.communicate.return_value = (b'{"BackendState": "Stopped"}\n', b"")
    mock_status.returncode = 0

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = [mock_ps, mock_status]
        res = await _is_sidecar_healthy_local("test-container")
        assert res is False


@pytest.mark.asyncio
async def test_is_sidecar_healthy_remote_healthy():
    with patch("sparkstack.manager.remote.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
        mock_ssh.return_value = '{"BackendState": "Running"}'
        res = await _is_sidecar_healthy_remote("user@spark", "sparkstack-sidecar-spark")
        assert res is True
        mock_ssh.assert_called_once_with(
            "user@spark",
            "docker exec sparkstack-sidecar-spark tailscale status --json 2>/dev/null || echo '{}'",
            timeout=15,
        )


@pytest.mark.asyncio
async def test_is_sidecar_healthy_remote_unhealthy():
    with patch("sparkstack.manager.remote.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
        mock_ssh.return_value = '{"BackendState": "NeedsLogin"}'
        res = await _is_sidecar_healthy_remote("user@spark", "sparkstack-sidecar-spark")
        assert res is False


@pytest.mark.asyncio
async def test_is_sidecar_healthy_remote_failure():
    with patch("sparkstack.manager.remote.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
        mock_ssh.side_effect = RuntimeError("SSH connection failed")
        res = await _is_sidecar_healthy_remote("user@spark", "sparkstack-sidecar-spark")
        assert res is False


@pytest.mark.asyncio
async def test_remove_container_if_exists_local():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await _remove_container_if_exists_local("test-container")
        mock_exec.assert_called_once_with(
            "docker",
            "rm",
            "-f",
            "test-container",
            stdout=-1,
            stderr=-1,
        )


@pytest.mark.asyncio
async def test_wait_for_sidecar_local_success():
    with patch(
        "sparkstack.manager.remote._is_sidecar_healthy_local", new_callable=AsyncMock
    ) as mock_healthy:
        mock_healthy.return_value = True
        await _wait_for_sidecar_local("test-container")
        mock_healthy.assert_called_once_with("test-container")


@pytest.mark.asyncio
async def test_wait_for_sidecar_local_timeout():
    with (
        patch(
            "sparkstack.manager.remote._is_sidecar_healthy_local", new_callable=AsyncMock
        ) as mock_healthy,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_healthy.return_value = False
        with pytest.raises(
            RuntimeError, match="Sidecar 'test-container' did not connect to the Tailnet"
        ):
            await _wait_for_sidecar_local("test-container", timeout=2)


@pytest.mark.asyncio
async def test_get_sidecar_ip_local_success():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"100.64.0.1\n", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        ip = await _get_sidecar_ip_local("test-container")
        assert ip == "100.64.0.1"
        mock_exec.assert_called_once_with(
            "docker",
            "exec",
            "test-container",
            "tailscale",
            "ip",
            "-4",
            stdout=-1,
            stderr=-1,
        )


@pytest.mark.asyncio
async def test_get_sidecar_ip_local_failure():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"container not found\n")
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         pytest.raises(RuntimeError, match="Failed to get Tailnet IP for 'test-container'"):
        await _get_sidecar_ip_local("test-container")


@pytest.mark.asyncio
async def test_get_sidecar_ip_local_empty():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"\n", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         pytest.raises(ValueError, match="Empty Tailnet IP for 'test-container'"):
        await _get_sidecar_ip_local("test-container")
