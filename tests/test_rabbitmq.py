"""Tests for RabbitMQ AMQP broker container service fixtures."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, call

import pytest
from docker.errors import APIError

from pytest_databases.docker import rabbitmq
from pytest_databases.docker.rabbitmq import RabbitMQService
from pytest_databases.types import ServiceContainer, XdistIsolationLevel
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator


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


def test_rabbitmq_service_urls_escape_credentials() -> None:
    """Verify RabbitMQService.amqp_url escapes credentials and the virtual host, and management_url uses its port."""
    service = RabbitMQService(
        container=MagicMock(),
        host="127.0.0.1",
        port=5672,
        username="user/name",
        password="p@ss:word",
        vhost="/custom",
        management_port=35672,
    )
    assert service.amqp_url == "amqp://user%2Fname:p%40ss%3Aword@127.0.0.1:5672/%2Fcustom"
    assert service.management_url == "http://127.0.0.1:35672"


def test_rabbitmq_responsive_runs_both_diagnostics() -> None:
    """Verify readiness requires both the running check and the AMQP listener check to pass."""
    container = MagicMock()
    container.exec_run.side_effect = [MagicMock(exit_code=0, output=b"ok"), MagicMock(exit_code=69, output=b"")]
    assert rabbitmq._rabbitmq_responsive(ServiceContainer(container=container, host="127.0.0.1", port=5672)) is False
    assert container.exec_run.call_args_list == [
        call(["rabbitmq-diagnostics", "-q", "check_running"]),
        call(["rabbitmq-diagnostics", "-q", "check_port_listener", "5672"]),
    ]


@pytest.mark.parametrize(
    ("existing_vhosts", "expect_add"),
    [(b"/\n", True), (b"/\npytest_databases_0\n", False)],
)
def test_ensure_vhost_creates_missing_vhost_and_grants_permissions(existing_vhosts: bytes, expect_add: bool) -> None:
    """Verify the exact rabbitmqctl commands that create the worker virtual host and grant the test user access."""
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=existing_vhosts),
        *[container.exec_run.return_value] * 2,
    ]
    rabbitmq._ensure_vhost(container, username="pytest-databases", vhost="pytest_databases_0")

    expected = [call(["rabbitmqctl", "-q", "list_vhosts", "name", "--no-table-headers"])]
    if expect_add:
        expected.append(call(["rabbitmqctl", "-q", "add_vhost", "pytest_databases_0"]))
    expected.append(
        call(["rabbitmqctl", "-q", "set_permissions", "-p", "pytest_databases_0", "pytest-databases", ".*", ".*", ".*"])
    )
    assert container.exec_run.call_args_list == expected


def test_ensure_vhost_surfaces_rabbitmqctl_errors() -> None:
    """Verify a failing rabbitmqctl command raises with its output."""
    container = MagicMock()
    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b"/\n"),
        MagicMock(exit_code=2, output=b"vhost_limit_exceeded"),
    ]
    with pytest.raises(RuntimeError, match="vhost_limit_exceeded"):
        rabbitmq._ensure_vhost(container, username="pytest-databases", vhost="pytest_databases_0")


@pytest.mark.parametrize(
    ("worker", "isolation_level", "expected_name", "expected_transient"),
    [
        (None, "server", "rabbitmq", False),
        ("gw0", "database", "rabbitmq", False),
        ("gw0", "server", "rabbitmq_0", True),
        ("gw3", "server", "rabbitmq_3", True),
    ],
)
def test_rabbitmq_container_naming_and_environment(
    monkeypatch: pytest.MonkeyPatch,
    worker: str | None,
    isolation_level: XdistIsolationLevel,
    expected_name: str,
    expected_transient: bool,
) -> None:
    """Verify container naming, the transient rule, and that no fixed Erlang cookie is configured."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    if worker is not None:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    captured: dict[str, Any] = {}
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"pytest_databases\n")

    @contextlib.contextmanager
    def fake_run(*_args: Any, **kwargs: Any) -> Generator[ServiceContainer, None, None]:
        captured.update(kwargs)
        yield ServiceContainer(container=container, host="127.0.0.1", port=35672)

    container_service = MagicMock()
    container_service.run.side_effect = fake_run
    container_service.resolve_port.return_value = 45672
    with rabbitmq.provide_rabbitmq_service(
        container_service, "rabbitmq:4.3-management", "user", "secret", "pytest_databases", isolation_level
    ) as service:
        assert service.management_port == 45672
    assert captured["name"] == expected_name
    assert captured["transient"] is expected_transient
    assert "RABBITMQ_ERLANG_COOKIE" not in captured["env"]


def test_rabbitmq_service_is_clientless_and_ready(pytester: pytest.Pytester) -> None:
    """Verify rabbitmq_service starts and executes a clientless rabbitmqadmin round-trip."""
    pytester.makepyfile(f"""
from pytest_databases.docker.rabbitmq import RabbitMQService

pytest_plugins = ["pytest_databases.docker.rabbitmq"]

{RABBITMQ_TEST_HELPERS}

def test_round_trip(rabbitmq_service: RabbitMQService) -> None:
    assert rabbitmq_service.port > 0
    assert rabbitmq_service.management_port > 0
    assert rabbitmq_service.amqp_url.startswith("amqp://pytest-databases:")
    assert_round_trip(rabbitmq_service, "clientless-smoke")
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


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


def test_rabbitmq_helpers_and_all_fixtures_inprocess(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify RabbitMQ error branches and in-process fixture execution."""
    container = MagicMock()
    container.exec_run.side_effect = APIError("exec failed")
    assert rabbitmq._rabbitmq_responsive(ServiceContainer(host="127.0.0.1", port=5672, container=container)) is False

    container.exec_run.side_effect = [MagicMock(exit_code=1, output=b"list failed")]
    with pytest.raises(RuntimeError, match="list failed"):
        rabbitmq._ensure_vhost(container, username="u", vhost="vh")

    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b"vh\n"),
        MagicMock(exit_code=1, output=b"perm failed"),
    ]
    with pytest.raises(RuntimeError, match="perm failed"):
        rabbitmq._ensure_vhost(container, username="u", vhost="vh")

    monkeypatch.setattr("pytest_databases.docker.rabbitmq.get_xdist_worker_num", lambda: 4)
    assert unwrap_fixture(rabbitmq.rabbitmq_vhost)("database") == "pytest_databases_4"

    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    import pytest
    import pytest_databases.docker.rabbitmq as rmq_mod
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.rabbitmq"]

    @pytest.fixture(autouse=True, scope="session")
    def mock_vhost():
        orig = rmq_mod._ensure_vhost
        rmq_mod._ensure_vhost = lambda *a, **kw: None
        yield
        rmq_mod._ensure_vhost = orig

    @pytest.fixture(scope="session")
    def container_service():
        mock_cs = MagicMock()
        mock_cs.resolve_port.return_value = 15672
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=5672, container=MagicMock())
        mock_cs.run.side_effect = _run
        return mock_cs

    def test_fixtures(
        xdist_rabbitmq_isolation_level,
        rabbitmq_image,
        rabbitmq_username,
        rabbitmq_password,
        rabbitmq_vhost,
        rabbitmq_service,
    ):
        assert xdist_rabbitmq_isolation_level == "database"
        assert "rabbitmq" in rabbitmq_image
        assert rabbitmq_username == "pytest-databases"
        assert rabbitmq_password == "pytest-databases-secret"
        assert rabbitmq_vhost == "pytest_databases_4"
        assert rabbitmq_service.port == 5672
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
