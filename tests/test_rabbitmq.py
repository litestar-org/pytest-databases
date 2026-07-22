from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

    from pytest_databases.docker.rabbitmq import RabbitMQService

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


def _run_rabbitmqadmin(service: RabbitMQService, *args: str) -> str:
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
    output = result.output if isinstance(result.output, bytes) else b"".join(result.output)
    assert result.exit_code == 0, output.decode(errors="replace")
    return output.decode(errors="replace")


def _assert_round_trip(service: RabbitMQService, queue: str) -> None:
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


def test_rabbitmq_service_is_clientless_and_ready(rabbitmq_service: RabbitMQService) -> None:
    assert rabbitmq_service.host == "127.0.0.1"
    assert rabbitmq_service.port > 0
    assert rabbitmq_service.amqp_url.startswith("amqp://pytest-databases:")
    _assert_round_trip(rabbitmq_service, "clientless-smoke")


def test_rabbitmq_xdist_vhost_isolation(pytester: pytest.Pytester) -> None:
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
