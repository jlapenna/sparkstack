"""Regression test: orchestrator → IPC → client event stream.

Simulates the orchestrator broadcasting state transitions, log lines,
and an exit event through the IPCServer, then verifies a connected client
receives the correct event sequence including a full_sync on connect.
"""

import asyncio
import json
import os
import tempfile

import pytest

from sparkstack.core.ipc_server import (
    ExitEvent,
    IPCServer,
    LogEvent,
    StateUpdateEvent,
)


async def _read_event(reader: asyncio.StreamReader, timeout: float = 3.0) -> dict:
    """Read a single newline-delimited JSON event from a stream."""
    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    return json.loads(line)


@pytest.mark.asyncio
async def test_orchestrator_event_stream():
    """Simulate a full orchestrator lifecycle and verify the client event stream.

    Flow:
    1. Start IPCServer
    2. Push initial state for 3 services (simulating Orchestrator.ServiceState)
    3. Connect a client (should receive full_sync with those states)
    4. Push state transitions (building → healthy)
    5. Push log lines
    6. Push exit event
    7. Verify client received all events in order
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "test-orchestration.sock")

        async with IPCServer.serve(socket_path) as ipc:
            # --- Phase 1: Seed initial state (before client connects) ---
            services = ["openclaw", "sparkrun", "vllm-main"]
            for svc in services:
                ipc.update_state(StateUpdateEvent(service=svc, status="pending"))

            # Small delay for state to settle
            await asyncio.sleep(0.05)

            # --- Phase 2: Client connects (should get full_sync) ---
            reader, writer = await asyncio.open_unix_connection(socket_path)

            full_sync = await _read_event(reader)
            assert full_sync["event_type"] == "full_sync"
            assert len(full_sync["states"]) == 3
            sync_names = set(full_sync["states"].keys())
            assert sync_names == set(services)

            # --- Phase 3: State transitions (simulating orchestrator loop) ---
            transitions = [
                StateUpdateEvent(service="openclaw", status="building", progress=0.0),
                StateUpdateEvent(service="openclaw", status="building", progress=50.0),
                StateUpdateEvent(service="openclaw", status="healthy", progress=100.0),
                StateUpdateEvent(
                    service="vllm-main",
                    status="loading",
                    note="Loading model weights",
                ),
                StateUpdateEvent(service="sparkrun", status="healthy"),
                StateUpdateEvent(service="vllm-main", status="healthy", progress=100.0),
            ]

            received_states = []
            for t in transitions:
                ipc.update_state(t)
                event = await _read_event(reader)
                assert event["event_type"] == "state"
                received_states.append(event)

            assert len(received_states) == 6

            # Verify final state of each service from received events
            final_states = {}
            for e in received_states:
                final_states[e["service"]] = e["status"]
            assert final_states == {
                "openclaw": "healthy",
                "vllm-main": "healthy",
                "sparkrun": "healthy",
            }

            # --- Phase 4: Log lines ---
            log_messages = [
                LogEvent(
                    level="INFO", message="All containers started", timestamp="2026-01-01T00:00:00"
                ),
                LogEvent(
                    level="INFO",
                    message="Waiting for backends to load",
                    timestamp="2026-01-01T00:00:01",
                ),
                LogEvent(
                    level="INFO", message="All backends healthy", timestamp="2026-01-01T00:00:02"
                ),
            ]

            received_logs = []
            for log in log_messages:
                ipc.broadcast_event(log)
                event = await _read_event(reader)
                assert event["event_type"] == "log"
                received_logs.append(event)

            assert len(received_logs) == 3
            assert received_logs[-1]["message"] == "All backends healthy"

            # --- Phase 5: Exit event ---
            ipc.broadcast_event(ExitEvent(success=True, message="Update complete"))
            exit_event = await _read_event(reader)
            assert exit_event["event_type"] == "exit"
            assert exit_event["success"] is True
            assert exit_event["message"] == "Update complete"

            writer.close()
            await writer.wait_closed()


@pytest.mark.asyncio
async def test_late_connect_gets_current_state():
    """Verify a client connecting mid-orchestration receives accumulated state.

    Simulates joining the status TUI after the orchestrator is already
    partway through an update cycle.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "test-late-connect.sock")

        async with IPCServer.serve(socket_path) as ipc:
            # Orchestrator has already processed several state transitions
            ipc.update_state(StateUpdateEvent(service="openclaw", status="healthy"))
            ipc.update_state(StateUpdateEvent(service="vllm-main", status="loading", progress=60.0))
            ipc.update_state(StateUpdateEvent(service="sparkrun", status="pending"))
            await asyncio.sleep(0.05)

            # Late client connects
            reader, writer = await asyncio.open_unix_connection(socket_path)

            full_sync = await _read_event(reader)

            assert full_sync["event_type"] == "full_sync"
            assert len(full_sync["states"]) == 3

            # Verify the accumulated state reflects the latest values
            states = full_sync["states"]
            assert states["openclaw"]["status"] == "healthy"
            assert states["vllm-main"]["status"] == "loading"
            assert states["vllm-main"]["progress"] == 60.0
            assert states["sparkrun"]["status"] == "pending"

            writer.close()
            await writer.wait_closed()


@pytest.mark.asyncio
async def test_client_disconnect_does_not_crash_server():
    """Verify the server continues operating after a client abruptly disconnects."""
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "test-disconnect.sock")

        async with IPCServer.serve(socket_path) as ipc:
            # Client connects then immediately drops
            reader, writer = await asyncio.open_unix_connection(socket_path)
            # Read full_sync
            await _read_event(reader)
            # Abrupt close without reading further
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.1)

            # Server should still be able to accept events without error
            ipc.update_state(StateUpdateEvent(service="test", status="ok"))
            await asyncio.sleep(0.05)

            # And accept new clients
            reader2, writer2 = await asyncio.open_unix_connection(socket_path)
            sync = await _read_event(reader2)
            assert sync["event_type"] == "full_sync"
            # The state we pushed should be in the sync
            assert "test" in sync["states"]
            assert sync["states"]["test"]["status"] == "ok"

            writer2.close()
            await writer2.wait_closed()
