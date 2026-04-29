import pytest

from manager.wait_for_backends import wait_for_backends_to_load
from tests.e2e.context import E2EContext


@pytest.mark.order(3)
@pytest.mark.asyncio
async def test_wait_for_backends(ctx: E2EContext):
    assert await wait_for_backends_to_load(ctx.stack_dir)
