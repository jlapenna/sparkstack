import shutil
from pathlib import Path

import pytest
from dotenv import load_dotenv

from sparkstack.core.utils import LockHeldError, ProcessLock
from tests.e2e.context import E2EContext
from tests.e2e.session_cleanup import wipe_all_sessions

# Automatically load environment variables from the project root .env file
load_dotenv(Path(__file__).parent.parent / ".env")

_test_lock = None


def pytest_configure(config):
    global _test_lock
    lockfile = Path(__file__).parent.parent / "tmp" / ".sparkstack-e2e.lock"
    lockfile.parent.mkdir(exist_ok=True)
    _test_lock = ProcessLock(str(lockfile))
    try:
        _test_lock.__enter__()
    except LockHeldError as exc:
        pytest.exit(f"LOCK CONTENTION: {exc}", returncode=1)


def pytest_unconfigure(config):
    global _test_lock
    if _test_lock:
        _test_lock.__exit__(None, None, None)


def pytest_addoption(parser):
    parser.addoption("--stack", action="store", default="current", help="Stack to test")
    parser.addoption("--soak", type=int, default=2, help="Soak time in minutes")
    parser.addoption(
        "--long-conversation-messages",
        type=int,
        default=4,
        help="Number of messages in long conversation test",
    )


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
    long_conversation_messages = request.config.getoption("--long-conversation-messages")

    root_dir = Path(__file__).parent.parent.absolute()
    if stack == "current":
        stack_dir = (root_dir / "current").resolve()
    else:
        stack_dir = root_dir / "sparkstack-registry" / "stacks" / stack

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
        long_conversation_messages=long_conversation_messages,
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
