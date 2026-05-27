import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class StateUpdateEvent(BaseModel):
    service: str
    status: str
    progress: float | None = None
    note: str | None = None
    event_type: Literal["state"] = "state"


class FullSyncEvent(BaseModel):
    states: dict[str, StateUpdateEvent]
    event_type: Literal["full_sync"] = "full_sync"


class LogEvent(BaseModel):
    level: str
    message: str
    timestamp: str
    service: str | None = None
    phase: str | int | None = None
    event_type: Literal["log"] = "log"


class ExitEvent(BaseModel):
    success: bool
    message: str
    event_type: Literal["exit"] = "exit"


IPCEvent = Annotated[
    StateUpdateEvent | FullSyncEvent | LogEvent | ExitEvent,
    Field(discriminator="event_type"),
]

event_adapter = TypeAdapter(IPCEvent)


def serialize_event(event: IPCEvent) -> bytes:
    return event_adapter.dump_json(event) + b"\n"


def deserialize_event(line: bytes) -> IPCEvent:
    return event_adapter.validate_json(line)


class IPCServer:
    def __init__(self):
        self._clients: set[asyncio.StreamWriter] = set()
        self._client_tasks: set[asyncio.Task] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self._states: dict[str, StateUpdateEvent] = {}
        self.local_callback: Callable[[dict[str, Any]], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def update_state(self, event: StateUpdateEvent):
        """Updates internal state and queues broadcast."""
        self._states[event.service] = event
        self.broadcast_event(event)

    def broadcast_event(self, event: IPCEvent):
        """Queues an event to be broadcast to all connected clients. Thread-safe."""
        # Use put_nowait but it is NOT thread-safe by default unless in same loop.
        # Since logs come from a separate thread, we need to schedule it on the loop.
        if self._loop:
            self._loop.call_soon_threadsafe(self.queue.put_nowait, event)
            if self.local_callback:
                with suppress(Exception):
                    self._loop.call_soon_threadsafe(self.local_callback, event.model_dump())

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
                    await asyncio.wait_for(writer.drain(), timeout=1.0)
                except Exception:
                    dead_clients.add(writer)

            for dead in dead_clients:
                self._clients.discard(dead)
                with suppress(Exception):
                    dead.close()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handles a new client connection, sending full sync immediately."""
        self._clients.add(writer)
        task = asyncio.current_task()
        if task:
            self._client_tasks.add(task)
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
            task = asyncio.current_task()
            if task:
                self._client_tasks.discard(task)
            with suppress(Exception):
                writer.close()

    @classmethod
    @asynccontextmanager
    async def serve(cls, socket_path: str):
        """Context manager to manage the IPC Server lifecycle."""
        server_instance = cls()
        server_instance._loop = asyncio.get_running_loop()

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

            # Forcefully close all connected clients so _handle_client
            # tasks unblock from reader.read() and can exit cleanly.
            for writer in list(server_instance._clients):
                with suppress(Exception):
                    writer.close()

            for task in list(server_instance._client_tasks):
                task.cancel()

            server.close()
            await server.wait_closed()

            if os.path.exists(socket_path):
                with suppress(OSError):
                    os.unlink(socket_path)
