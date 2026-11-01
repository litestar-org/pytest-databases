"""Tests for RabbitMQ AMQP broker container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from pytest_databases.docker import rabbitmq
from pytest_databases.docker.rabbitmq import RabbitMQService
from pytest_databases.helpers import exec_output_to_bytes
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    import pytest

pytest_plugins = ["pytest_databases.docker.rabbitmq"]


RABBITMQ_TEST_HELPERS = """
def run_rabbitmqadmin(service, *args):
    result = service.container.exec_run([
        "rabbitmqadmin",
        "--username", service.username,
        "--password", service.password,
        "--vhost", service.vhost,
        "--non-interactive",
        *args,
    ])
    output = result.output if isinstance(result.output, bytes) else b"".join(result.output)
    assert result.exit_code == 0, output.decode(errors="replace")
    return output.decode(errors="replace")


def assert_round_trip(service, queue):
    run_rabbitmqadmin(service, "declare", "queue", "--name", queue, "--durable", "true")
    run_rabbitmqadmin(
        service,
        "publish", "message",
        "--routing-key", queue,
        "--payload", "pytest-databases-message",
    )
    output = run_rabbitmqadmin(service, "get", "messages", "--queue", queue)
    assert "pytest-databases-message" in output
"""


def test_plugin_imports_without_amqp_clients(pytester: pytest.Pytester) -> None:
    """Ensure the RabbitMQ module imports cleanly when AMQP client packages are absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"aio_pika", "amqp", "kombu", "pika"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.rabbitmq")
            assert module.RabbitMQService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_rabbitmq_unit_helpers() -> None:
    """Verify RabbitMQService.amqp_url escaping, management_url, _rabbitmq_responsive, and _ensure_vhost."""
    container = MagicMock()
    service = RabbitMQService(
        container=container,
        host="127.0.0.1",
        port=5672,
        username="user/name",
        password="p@ss:word",
        vhost="/custom",
        management_port=35672,
    )
    assert service.amqp_url == "amqp://user%2Fname:p%40ss%3Aword@127.0.0.1:5672/%2Fcustom"
    assert service.management_port == 35672
    assert service.management_url == "http://127.0.0.1:35672"

    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b"ok"),
        MagicMock(exit_code=0, output=b"ok"),
    ]
    assert rabbitmq._rabbitmq_responsive(ServiceContainer(container=container, host="127.0.0.1", port=5672)) is True

    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b"/\n"),
        MagicMock(exit_code=0, output=b""),
        MagicMock(exit_code=0, output=b""),
    ]
    rabbitmq._ensure_vhost(container, username="pytest-databases", vhost="pytest_databases_0")
    assert container.exec_run.call_count == 5


def test_rabbitmq_service_is_clientless_and_ready(rabbitmq_service: RabbitMQService) -> None:
    """Verify rabbitmq_service starts and executes a clientless rabbitmqadmin round-trip."""
    assert rabbitmq_service.host == "127.0.0.1"
    assert rabbitmq_service.port > 0
    assert rabbitmq_service.management_port > 0
    assert rabbitmq_service.amqp_url.startswith("amqp://pytest-databases:")
    _assert_round_trip(rabbitmq_service, "clientless-smoke")


def test_rabbitmq_xdist_vhost_isolation(pytester: pytest.Pytester) -> None:
    """Verify database xdist isolation uses separate virtual hosts per worker."""
    pytester.makepyfile(f"""
from pytest_databases.docker.rabbitmq import RabbitMQService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = ["pytest_databases.docker.rabbitmq"]

{RABBITMQ_TEST_HELPERS}

def check_isolation(service):
    assert service.vhost == f"pytest_databases_{{get_xdist_worker_num()}}"
    assert_round_trip(service, "same-queue")

def test_one(rabbitmq_service: RabbitMQService) -> None:
    check_isolation(rabbitmq_service)

def test_two(rabbitmq_service: RabbitMQService) -> None:
    check_isolation(rabbitmq_service)
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_rabbitmq_xdist_server_isolation(pytester: pytest.Pytester) -> None:
    """Verify server xdist isolation launches separate RabbitMQ containers per worker."""
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.rabbitmq import RabbitMQService

pytest_plugins = ["pytest_databases.docker.rabbitmq"]

{RABBITMQ_TEST_HELPERS}

@pytest.fixture(scope="session")
def xdist_rabbitmq_isolation_level():
    return "server"

def check_isolation(service):
    assert service.vhost == "pytest_databases"
    assert_round_trip(service, "same-queue")

def test_one(rabbitmq_service: RabbitMQService) -> None:
    check_isolation(rabbitmq_service)

def test_two(rabbitmq_service: RabbitMQService) -> None:
    check_isolation(rabbitmq_service)
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def _run_rabbitmqadmin(service: RabbitMQService, *args: str) -> str:
    """Execute rabbitmqadmin inside the RabbitMQ container.

    Returns:
        Decoded rabbitmqadmin stdout/stderr.
    """
    result = service.container.exec_run([
        "rabbitmqadmin",
        "--username",
        service.username,
        "--password",
        service.password,
        "--vhost",
        service.vhost,
        "--non-interactive",
        *args,
    ])
    output = exec_output_to_bytes(result.output)
    assert result.exit_code == 0, output.decode(errors="replace")
    return output.decode(errors="replace")


def _assert_round_trip(service: RabbitMQService, queue: str) -> None:
    """Verify declaring a queue, publishing a message, and fetching it via rabbitmqadmin."""
    _run_rabbitmqadmin(service, "declare", "queue", "--name", queue, "--durable", "true")
    _run_rabbitmqadmin(
        service,
        "publish",
        "message",
        "--routing-key",
        queue,
        "--payload",
        "pytest-databases-message",
    )
    assert "pytest-databases-message" in _run_rabbitmqadmin(service, "get", "messages", "--queue", queue)
