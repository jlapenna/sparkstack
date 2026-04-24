from pathlib import Path

import pytest

from tests.e2e.context import E2EContext


def pytest_addoption(parser):
    parser.addoption("--stack", action="store", default="current", help="Stack to test")
    parser.addoption("--soak", type=int, default=15, help="Soak time in minutes")


@pytest.fixture(scope="session")
def ctx(request):
    stack = request.config.getoption("--stack")
    soak = request.config.getoption("--soak")

    import shutil

    root_dir = Path(__file__).parent.parent.absolute()
    if stack == "current":
        stack_dir = root_dir / "current"
    else:
        stack_dir = root_dir / "spark-stack-registry" / "stacks" / stack

    oc_bin = Path(shutil.which("openclaw") or Path.home() / "bin" / "openclaw")
    gateway_url = "http://localhost:4000/v1"
    telemetry_url = "http://localhost:9090/api/v1/targets"

    return E2EContext(
        root_dir=root_dir,
        stack_dir=stack_dir,
        oc_bin=oc_bin,
        gateway_url=gateway_url,
        telemetry_url=telemetry_url,
        soak_minutes=soak,
    )
