import asyncio
import pytest

from core.statsd import StatsdClient


@pytest.mark.asyncio
async def test_statsd_udp():
    """Test that the StatsdClient can successfully send UDP packets."""
    loop = asyncio.get_running_loop()
    received = []

    class DummyProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data, addr):
            received.append(data.decode("utf-8"))

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DummyProtocol(),
        local_addr=("127.0.0.1", 0),
    )

    host, port = transport.get_extra_info("sockname")

    client = StatsdClient(host=host, port=port, protocol="udp")
    await client.send("test_metric:1|c")

    # Give the UDP packet a moment to arrive
    await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0] == "test_metric:1|c"

    transport.close()


@pytest.mark.asyncio
async def test_statsd_tcp():
    """Test that the StatsdClient can successfully send TCP packets."""
    received = []

    async def handle_client(reader, writer):
        data = await reader.read(100)
        received.append(data.decode("utf-8"))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()

    async with server:
        client = StatsdClient(host=host, port=port, protocol="tcp")
        await client.send("test_metric:2|c")
        
        # Give TCP a moment to transfer
        await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0] == "test_metric:2|c"
