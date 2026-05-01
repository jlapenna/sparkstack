import shutil
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tests.e2e.context import E2EContext
from tests.e2e.session_cleanup import wipe_all_sessions

# Automatically load environment variables from the project root .env file
load_dotenv(Path(__file__).parent.parent / ".env")


def pytest_addoption(parser):
    parser.addoption("--stack", action="store", default="current", help="Stack to test")
    parser.addoption("--soak", type=int, default=15, help="Soak time in minutes")


@pytest.fixture(scope="session", autouse=True)
def _cleanup_verifier_sessions():
    """Wipe verifier session store before and after the E2E suite."""
    wipe_all_sessions("pre-suite")

    yield

    wipe_all_sessions("post-suite")


@pytest.fixture(scope="session")
def ctx(request):
    stack = request.config.getoption("--stack")
    soak = request.config.getoption("--soak")

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

def pytest_sessionstart(session):
    session.backends_failed = False

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed and "wait_for_backends" in item.name:
        item.session.backends_failed = True

def pytest_runtest_setup(item):
    if getattr(item.session, "backends_failed", False) and "wait_for_backends" not in item.name:
        pytest.skip("Pre-condition failed: Backends did not load.")
