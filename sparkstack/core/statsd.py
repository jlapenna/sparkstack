import asyncio
import contextlib
import logging
from typing import Literal

logger = logging.getLogger(__name__)


class StatsdClient:
    """Async StatsD client supporting both UDP and TCP protocols."""

    def __init__(self, host: str, port: int, protocol: Literal["udp", "tcp"] = "udp") -> None:
        self.host = host
        self.port = port
        self.protocol = protocol.lower()
        self.addr = (self.host, self.port)

        self._lock = asyncio.Lock()

        # UDP state
        self._udp_sock: asyncio.DatagramTransport | None = None
        self._udp_protocol: asyncio.DatagramProtocol | None = None

        # TCP state
        self._tcp_writer: asyncio.StreamWriter | None = None

    async def _ensure_udp_socket(self) -> None:
        if self._udp_sock is not None and not self._udp_sock.is_closing():
            return
        try:
            loop = asyncio.get_running_loop()
            transport, protocol = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol,
                remote_addr=self.addr,
            )
            self._udp_sock = transport
            self._udp_protocol = protocol
        except Exception as e:
            logger.debug(f"Failed to create StatsD UDP socket: {e}")
            self._udp_sock = None

    async def _ensure_tcp_socket(self) -> None:
        if self._tcp_writer is not None and not self._tcp_writer.is_closing():
            return
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=2.0
            )
            self._tcp_writer = writer
        except Exception as e:
            logger.debug(f"Failed to connect to StatsD TCP: {e}")
            self._tcp_writer = None

    async def send(self, msg: str) -> None:
        async with self._lock:
            if self.protocol == "udp":
                await self._ensure_udp_socket()
                if self._udp_sock is None:
                    return
                try:
                    self._udp_sock.sendto(msg.encode("utf-8"))
                except Exception as e:
                    logger.debug(f"StatsD UDP send exception: {e}")
                    if self._udp_sock:
                        with contextlib.suppress(Exception):
                            self._udp_sock.close()
                        self._udp_sock = None
            elif self.protocol == "tcp":
                await self._ensure_tcp_socket()
                if self._tcp_writer is None:
                    return
                try:
                    self._tcp_writer.write(msg.encode("utf-8"))
                    await self._tcp_writer.drain()
                except Exception as e:
                    logger.debug(f"StatsD TCP send exception: {e}")
                    if self._tcp_writer:
                        with contextlib.suppress(Exception):
                            self._tcp_writer.close()
                        self._tcp_writer = None

    async def close(self) -> None:
        async with self._lock:
            if self._udp_sock is not None:
                with contextlib.suppress(Exception):
                    self._udp_sock.close()
                self._udp_sock = None
            if self._tcp_writer is not None:
                with contextlib.suppress(Exception):
                    self._tcp_writer.close()
                    await self._tcp_writer.wait_closed()
                self._tcp_writer = None
