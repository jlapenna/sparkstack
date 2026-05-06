import asyncio
import json
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass
class StateUpdateEvent:
    service: str
    status: str
    progress: float | None = None
    note: str | None = None
    event_type: Literal["state"] = "state"


@dataclass
class FullSyncEvent:
    states: dict[str, StateUpdateEvent]
    event_type: Literal["full_sync"] = "full_sync"


@dataclass
class LogEvent:
    level: str
    message: str
    timestamp: str
    service: str | None = None
    phase: str | int | None = None
    event_type: Literal["log"] = "log"


@dataclass
class ExitEvent:
    success: bool
    message: str
    event_type: Literal["exit"] = "exit"


def serialize_event(event: Any) -> bytes:
    return (json.dumps(asdict(event)) + "\n").encode("utf-8")


def deserialize_event(line: bytes) -> Any:
    data = json.loads(line)
    etype = data.pop("event_type", None)
    if etype == "state":
        return StateUpdateEvent(**data)
    if etype == "full_sync":
        states_data = data.pop("states", {})
        states = {k: StateUpdateEvent(**v) for k, v in states_data.items()}
        return FullSyncEvent(states=states, **data)
    if etype == "log":
        return LogEvent(**data)
    if etype == "exit":
        return ExitEvent(**data)
    raise ValueError(f"Unknown event type: {etype}")


class IPCServer:
    def __init__(self):
        self._clients: set[asyncio.StreamWriter] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self._states: dict[str, StateUpdateEvent] = {}
        self.local_callback: Callable[[dict[str, Any]], None] | None = None

    def update_state(self, event: StateUpdateEvent):
        """Updates internal state and queues broadcast."""
        self._states[event.service] = event
        self.broadcast_event(event)

    def broadcast_event(self, event: Any):
        """Queues an event to be broadcast to all connected clients. Thread-safe."""
        # Use put_nowait but it is NOT thread-safe by default unless in same loop.
        # Since logs come from a separate thread, we need to schedule it on the loop.
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(self.queue.put_nowait, event)
        if self.local_callback:
            with suppress(Exception):
                loop.call_soon_threadsafe(self.local_callback, asdict(event))

    async def _broadcaster_task(self):
        """Background task that reads from queue and broadcasts to all clients."""
        while True:
            event = await self.queue.get()
            try:
                data = serialize_event(event)
            except Exception as e:
                logging.getLogger("ipc_server").error(f"Failed to serialize event: {e}")
                continue

            dead_clients = set()
            for writer in self._clients:
                try:
                    writer.write(data)
                    await writer.drain()
                except Exception:
                    dead_clients.add(writer)

            for dead in dead_clients:
                self._clients.discard(dead)
                with suppress(Exception):
                    dead.close()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handles a new client connection, sending full sync immediately."""
        self._clients.add(writer)
        try:
            # Send full sync on connect
            sync_event = FullSyncEvent(states=self._states)
            writer.write(serialize_event(sync_event))
            await writer.drain()

            # Keep connection open and read. If client disconnects, read returns empty.
            while True:
                data = await reader.read(1024)
                if not data:
                    break
        except Exception:
            pass
        finally:
            self._clients.discard(writer)
            with suppress(Exception):
                writer.close()

    @classmethod
    @asynccontextmanager
    async def serve(cls, socket_path: str):
        """Context manager to manage the IPC Server lifecycle."""
        server_instance = cls()

        if os.path.exists(socket_path):
            with suppress(OSError):
                os.unlink(socket_path)

        server = await asyncio.start_unix_server(server_instance._handle_client, path=socket_path)
        broadcaster = asyncio.create_task(server_instance._broadcaster_task())

        try:
            yield server_instance
        finally:
            broadcaster.cancel()
            with suppress(asyncio.CancelledError):
                await broadcaster

            server.close()
            await server.wait_closed()

            if os.path.exists(socket_path):
                with suppress(OSError):
                    os.unlink(socket_path)
