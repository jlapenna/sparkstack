import asyncio
import json
import os

import pytest
from pydantic import ValidationError

from sparkstack.core.ipc_server import (
    ExitEvent,
    FullSyncEvent,
    IPCServer,
    LogEvent,
    StateUpdateEvent,
    deserialize_event,
    serialize_event,
)

# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_state_update_roundtrip(self):
        evt = StateUpdateEvent(service="vLLM", status="running", progress=50.0, note="Loading")
        data = serialize_event(evt)
        restored = deserialize_event(data)
        assert isinstance(restored, StateUpdateEvent)
        assert restored.service == "vLLM"
        assert restored.status == "running"
        assert restored.progress == 50.0
        assert restored.note == "Loading"

    def test_log_event_roundtrip(self):
        evt = LogEvent(level="INFO", message="hello world", timestamp="2025-01-01T00:00:00")
        data = serialize_event(evt)
        restored = deserialize_event(data)
        assert isinstance(restored, LogEvent)
        assert restored.level == "INFO"
        assert restored.message == "hello world"

    def test_exit_event_roundtrip(self):
        evt = ExitEvent(success=True, message="All done")
        data = serialize_event(evt)
        restored = deserialize_event(data)
        assert isinstance(restored, ExitEvent)
        assert restored.success is True
        assert restored.message == "All done"

    def test_full_sync_roundtrip(self):
        states = {
            "svc1": StateUpdateEvent(service="svc1", status="running", progress=50.0),
            "svc2": StateUpdateEvent(service="svc2", status="complete", progress=100.0),
        }
        evt = FullSyncEvent(states=states)
        data = serialize_event(evt)
        restored = deserialize_event(data)
        assert isinstance(restored, FullSyncEvent)
        assert "svc1" in restored.states
        assert restored.states["svc1"].progress == 50.0
        assert restored.states["svc2"].status == "complete"

    def test_serialize_produces_newline_terminated_bytes(self):
        evt = StateUpdateEvent(service="x", status="y")
        data = serialize_event(evt)
        assert isinstance(data, bytes)
        assert data.endswith(b"\n")

    def test_deserialize_unknown_type_raises(self):
        bad_data = json.dumps({"event_type": "bogus"}).encode()
        with pytest.raises(
            ValidationError, match="Input tag 'bogus' found using 'event_type' does not match"
        ):
            deserialize_event(bad_data)

    def test_state_update_optional_fields(self):
        """Progress and note are optional — should serialize/deserialize as None."""
        evt = StateUpdateEvent(service="svc", status="waiting")
        data = serialize_event(evt)
        restored = deserialize_event(data)
        assert isinstance(restored, StateUpdateEvent)
        assert restored.progress is None
        assert restored.note is None


# ---------------------------------------------------------------------------
# Server lifecycle and broadcasting
# ---------------------------------------------------------------------------


@pytest.fixture
def socket_path(tmp_path):
    """Provide a unique UDS path per test."""
    return str(tmp_path / "test.sock")


@pytest.mark.asyncio
async def test_server_lifecycle(socket_path):
    """Server starts, accepts connections, and cleans up the socket on exit."""
    async with IPCServer.serve(socket_path) as ipc:
        assert ipc is not None
        # Socket file should exist while serving
        assert os.path.exists(socket_path)

    # Socket file should be cleaned up after exiting context
    assert not os.path.exists(socket_path)


@pytest.mark.asyncio
async def test_full_sync_on_connect(socket_path):
    """New clients receive a FullSyncEvent with current state on connection."""
    async with IPCServer.serve(socket_path) as ipc:
        # Pre-populate state
        ipc.update_state(
            StateUpdateEvent(service="Alpha", status="running", progress=33.0, note="Working")
        )
        ipc.update_state(
            StateUpdateEvent(service="Beta", status="complete", progress=100.0, note="Done")
        )

        reader, writer = await asyncio.open_unix_connection(socket_path)
        line = await asyncio.wait_for(reader.readline(), timeout=3)
        event = json.loads(line)

        assert event["event_type"] == "full_sync"
        assert "Alpha" in event["states"]
        assert "Beta" in event["states"]
        assert event["states"]["Alpha"]["progress"] == 33.0
        assert event["states"]["Beta"]["status"] == "complete"

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_state_broadcast(socket_path):
    """State updates are broadcast to connected clients after full_sync."""
    async with IPCServer.serve(socket_path) as ipc:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        # Consume the initial full_sync (empty states)
        line = await asyncio.wait_for(reader.readline(), timeout=3)
        sync = json.loads(line)
        assert sync["event_type"] == "full_sync"

        # Push a state update
        ipc.update_state(
            StateUpdateEvent(service="vLLM", status="running", progress=42.0, note="Loading model")
        )

        line = await asyncio.wait_for(reader.readline(), timeout=3)
        event = json.loads(line)
        assert event["event_type"] == "state"
        assert event["service"] == "vLLM"
        assert event["progress"] == 42.0

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_log_broadcast(socket_path):
    """LogEvents are broadcast to connected clients."""
    async with IPCServer.serve(socket_path) as ipc:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        # Consume full_sync
        await asyncio.wait_for(reader.readline(), timeout=3)

        ipc.broadcast_event(
            LogEvent(level="WARNING", message="disk space low", timestamp="2025-06-01T12:00:00")
        )

        line = await asyncio.wait_for(reader.readline(), timeout=3)
        event = json.loads(line)
        assert event["event_type"] == "log"
        assert event["level"] == "WARNING"
        assert event["message"] == "disk space low"

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_exit_broadcast(socket_path):
    """ExitEvents are broadcast to connected clients."""
    async with IPCServer.serve(socket_path) as ipc:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        # Consume full_sync
        await asyncio.wait_for(reader.readline(), timeout=3)

        ipc.broadcast_event(ExitEvent(success=False, message="service failure"))

        line = await asyncio.wait_for(reader.readline(), timeout=3)
        event = json.loads(line)
        assert event["event_type"] == "exit"
        assert event["success"] is False
        assert event["message"] == "service failure"

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_multiple_clients(socket_path):
    """Multiple clients each receive broadcasts."""
    async with IPCServer.serve(socket_path) as ipc:
        readers_writers = []
        for _ in range(3):
            r, w = await asyncio.open_unix_connection(socket_path)
            # Consume full_sync
            await asyncio.wait_for(r.readline(), timeout=3)
            readers_writers.append((r, w))

        # Broadcast one state update
        ipc.update_state(StateUpdateEvent(service="Test", status="running", progress=10.0))

        for r, _w in readers_writers:
            line = await asyncio.wait_for(r.readline(), timeout=3)
            event = json.loads(line)
            assert event["event_type"] == "state"
            assert event["service"] == "Test"

        for _r, w in readers_writers:
            w.close()
            await w.wait_closed()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_broken_client_handled_gracefully(socket_path):
    """A disconnected client doesn't crash the broadcaster or block other clients."""
    async with IPCServer.serve(socket_path) as ipc:
        # Client 1: connect and immediately close
        _r1, w1 = await asyncio.open_unix_connection(socket_path)
        w1.close()
        await w1.wait_closed()
        await asyncio.sleep(0.1)  # Let the server detect disconnection

        # Client 2: connect normally
        r2, w2 = await asyncio.open_unix_connection(socket_path)
        await asyncio.wait_for(r2.readline(), timeout=3)  # full_sync

        # Broadcasting should still work for client 2
        ipc.update_state(StateUpdateEvent(service="Survivor", status="running", progress=1.0))

        line = await asyncio.wait_for(r2.readline(), timeout=3)
        event = json.loads(line)
        assert event["service"] == "Survivor"

        w2.close()
        await w2.wait_closed()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_state_accumulation(socket_path):
    """update_state accumulates and a later client gets full state."""
    async with IPCServer.serve(socket_path) as ipc:
        # Push multiple service states before any client connects
        ipc.update_state(StateUpdateEvent(service="A", status="complete", progress=100.0))
        ipc.update_state(StateUpdateEvent(service="B", status="running", progress=50.0))
        ipc.update_state(StateUpdateEvent(service="C", status="waiting"))

        # Now connect — should get all three in the full_sync
        reader, writer = await asyncio.open_unix_connection(socket_path)
        line = await asyncio.wait_for(reader.readline(), timeout=3)
        event = json.loads(line)

        assert event["event_type"] == "full_sync"
        assert len(event["states"]) == 3
        assert event["states"]["A"]["status"] == "complete"
        assert event["states"]["B"]["progress"] == 50.0
        assert event["states"]["C"]["status"] == "waiting"

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
