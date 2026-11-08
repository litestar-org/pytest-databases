"""Tests for Redpanda container service fixtures and stdlib Kafka metadata probes."""

from __future__ import annotations

import contextlib
import struct
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, Mock

import pytest

from pytest_databases.docker import redpanda
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest import MonkeyPatch


REDPANDA_TEST_HELPERS = r"""
def rpk(service, *args):
    result = service.container.exec_run([
        "rpk",
        *args,
        "-X",
        "brokers=127.0.0.1:9092",
    ])
    output = result.output if isinstance(result.output, bytes) else str(result.output).encode()
    assert result.exit_code == 0, output.decode(errors="replace")
    return output


def round_trip(service, suffix):
    topic = f"{service.topic_prefix}smoke_{suffix}"
    rpk(service, "topic", "create", topic, "--partitions", "1", "--replicas", "1")
    try:
        produced = service.container.exec_run([
            "sh",
            "-c",
            f"printf 'test-value\\n' | rpk topic produce {topic} --key test-key "
            "-X brokers=127.0.0.1:9092",
        ])
        assert produced.exit_code == 0, produced.output
        consumed = rpk(
            service,
            "topic",
            "consume",
            topic,
            "--num",
            "1",
            "--offset",
            "start",
            "--format",
            "%k|%v",
        )
        assert consumed.strip() == b"test-key|test-value"
    finally:
        rpk(service, "topic", "delete", topic)
"""


def test_plugin_imports_without_kafka_clients(pytester: pytest.Pytester) -> None:
    """Ensure the Redpanda module imports cleanly when Kafka client packages are absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith(("confluent_kafka", "kafka")):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.redpanda")
            assert module.DEFAULT_REDPANDA_IMAGE
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_public_contract_and_environment_overrides(monkeypatch: MonkeyPatch) -> None:
    """Verify RedpandaService attributes and environment variable resolution helpers."""
    service = redpanda.RedpandaService(
        container=Mock(),
        host="127.0.0.1",
        port=19092,
        bootstrap_servers="127.0.0.1:19092",
        topic_prefix="pytest_databases_",
    )
    assert service.bootstrap_servers == f"{service.host}:{service.port}"
    assert service.topic_prefix == "pytest_databases_"

    monkeypatch.delenv("REDPANDA_IMAGE", raising=False)
    monkeypatch.delenv("REDPANDA_PORT", raising=False)
    assert unwrap_fixture(redpanda.redpanda_image)() == redpanda.DEFAULT_REDPANDA_IMAGE
    assert unwrap_fixture(redpanda.redpanda_port)() is None
    monkeypatch.setenv("REDPANDA_IMAGE", "example.test/redpanda:v1")
    monkeypatch.setenv("REDPANDA_PORT", "29092")
    assert unwrap_fixture(redpanda.redpanda_image)() == "example.test/redpanda:v1"
    assert unwrap_fixture(redpanda.redpanda_port)() == 29092


def test_start_command_advertises_mapped_port() -> None:
    """Verify the Redpanda startup command configures internal and external Kafka listeners."""
    command = redpanda._redpanda_command(29092, advertised_host="10.0.0.5")
    assert command.startswith("redpanda start --mode dev-container")
    assert "external://0.0.0.0:19092" in command
    assert "external://10.0.0.5:29092" in command


@pytest.mark.parametrize(("redpanda_port", "expected_host_port"), [(None, None), (29092, 29092)])
def test_runtime_allocates_port_and_listener_follows_mapping(
    redpanda_port: int | None, expected_host_port: int | None
) -> None:
    """Verify the broker waits for start arguments built from the port the runtime actually mapped."""
    captured: dict[str, Any] = {}
    container = MagicMock()
    container.exec_run.return_value = Mock(exit_code=0, output=b"")
    mapped = ServiceContainer(container=container, host="10.0.0.5", port=41234)

    @contextlib.contextmanager
    def fake_run(**kwargs: Any) -> Generator[ServiceContainer, None, None]:
        captured.update(kwargs)
        yield mapped

    container_service = MagicMock()
    container_service.run.side_effect = fake_run

    def fake_brokers(host: str, port: int, **_kwargs: Any) -> list[tuple[str, int]]:
        return [(host, port)]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(redpanda, "fetch_kafka_brokers", fake_brokers)
        with redpanda.provide_redpanda_service(
            container_service=container_service,
            redpanda_image=redpanda.DEFAULT_REDPANDA_IMAGE,
            redpanda_port=redpanda_port,
            xdist_redpanda_isolation_level="database",
        ) as service:
            assert captured["host_port"] == expected_host_port
            assert "command" not in captured
            entrypoint = captured["entrypoint"]
            assert entrypoint[:2] == ["/bin/sh", "-c"]
            assert "exec /entrypoint.sh" in entrypoint[2]
            assert captured["check"](mapped) is True
            assert captured["check"](mapped) is True
            assert service.bootstrap_servers == "10.0.0.5:41234"
    container_service.resolve_service_host.assert_not_called()

    write_commands = [call.args[0][2] for call in container.exec_run.call_args_list if "external://" in call.args[0][2]]
    assert len(write_commands) == 1
    assert "external://10.0.0.5:41234" in write_commands[0]
    assert write_commands[0].startswith("[ -f /var/lib/redpanda/pytest-databases-start ] ||")


def test_start_arguments_write_failure_raises() -> None:
    """Verify a failed write of the start arguments surfaces the container output."""
    container = MagicMock()
    container.exec_run.return_value = Mock(exit_code=1, output=b"read-only file system")
    service = ServiceContainer(container=container, host="127.0.0.1", port=41234)
    with pytest.raises(RuntimeError, match="read-only file system"):
        redpanda._write_start_arguments(service)


def test_fetch_kafka_brokers_parses_v0_metadata_response(monkeypatch: MonkeyPatch) -> None:
    """Verify fetch_kafka_brokers decodes broker host and port from a Kafka MetadataResponse v0 frame."""
    host_bytes = b"127.0.0.1"
    body = struct.pack(
        f">iiih{len(host_bytes)}si",
        1,
        1,
        0,
        len(host_bytes),
        host_bytes,
        19092,
    )
    wire = struct.pack(">i", len(body)) + body

    fake_sock = MagicMock()
    cursor = 0

    def recv_bytes(count: int) -> bytes:
        nonlocal cursor
        chunk = wire[cursor : cursor + count]
        cursor += len(chunk)
        return chunk

    fake_sock.recv.side_effect = recv_bytes
    fake_sock.__enter__.return_value = fake_sock
    fake_sock.__exit__.return_value = False

    monkeypatch.setattr(redpanda.socket, "create_connection", lambda *_args, **_kwargs: fake_sock)

    brokers = redpanda.fetch_kafka_brokers("127.0.0.1", 19092)
    assert brokers == [("127.0.0.1", 19092)]
    fake_sock.sendall.assert_called_once()


def test_default_service_is_clientless(pytester: pytest.Pytester) -> None:
    """Verify redpanda_service starts and executes a clientless rpk produce/consume round-trip."""
    pytester.makepyfile(f"""
from pytest_databases.docker.redpanda import RedpandaService, fetch_kafka_brokers

pytest_plugins = ["pytest_databases.docker.redpanda"]

{REDPANDA_TEST_HELPERS}


def test_round_trip(redpanda_service: RedpandaService):
    endpoint = (redpanda_service.host, redpanda_service.port)
    assert endpoint in fetch_kafka_brokers(*endpoint)
    assert redpanda_service.bootstrap_servers == f"{{redpanda_service.host}}:{{redpanda_service.port}}"
    assert redpanda_service.topic_prefix == "pytest_databases_"
    round_trip(redpanda_service, "default")
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("isolation_level", ["database", "server"])
def test_xdist_isolation_is_clientless(pytester: pytest.Pytester, isolation_level: str) -> None:
    """Verify database and server xdist isolation modes for redpanda_service."""
    pytester.makepyfile(f"""
import pytest

from pytest_databases.docker.redpanda import RedpandaService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = ["pytest_databases.docker.redpanda"]


@pytest.fixture(scope="session")
def xdist_redpanda_isolation_level():
    return "{isolation_level}"


{REDPANDA_TEST_HELPERS}


def assert_round_trip(service: RedpandaService):
    worker = get_xdist_worker_num()
    if "{isolation_level}" == "database":
        assert service.topic_prefix == f"pytest_databases_{{worker}}_"
    else:
        assert service.topic_prefix == ""
    round_trip(service, f"worker_{{worker}}")


def test_one(redpanda_service: RedpandaService):
    assert_round_trip(redpanda_service)


def test_two(redpanda_service: RedpandaService):
    assert_round_trip(redpanda_service)
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


def test_fetch_kafka_brokers_and_recv_exact_error_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify fetch_kafka_brokers validation and _recv_exact EOF handling."""
    mock_sock = MagicMock()
    mock_sock.recv.return_value = b""
    with pytest.raises(OSError, match="Unexpected EOF"):
        redpanda._recv_exact(mock_sock, 4)

    def make_conn(payloads: list[bytes]) -> Any:
        @contextlib.contextmanager
        def _conn(*_a: Any, **_kw: Any) -> Any:
            s = MagicMock()
            s.recv.side_effect = payloads
            yield s

        return _conn

    monkeypatch.setattr(
        "pytest_databases.docker.redpanda.socket.create_connection",
        make_conn([struct.pack(">i", 0)]),
    )
    with pytest.raises(ValueError, match="Invalid Kafka metadata response size"):
        redpanda.fetch_kafka_brokers("127.0.0.1", 9092)

    monkeypatch.setattr(
        "pytest_databases.docker.redpanda.socket.create_connection",
        make_conn([struct.pack(">i", 4), b"1234"]),
    )
    with pytest.raises(ValueError, match="Truncated Kafka metadata response header"):
        redpanda.fetch_kafka_brokers("127.0.0.1", 9092)

    monkeypatch.setattr(
        "pytest_databases.docker.redpanda.socket.create_connection",
        make_conn([struct.pack(">i", 8), struct.pack(">ii", 999, 0)]),
    )
    assert redpanda.fetch_kafka_brokers("127.0.0.1", 9092) == []

    monkeypatch.setattr(
        "pytest_databases.docker.redpanda.socket.create_connection",
        make_conn([struct.pack(">i", 10), struct.pack(">ii", 7, 1) + b"12"]),
    )
    assert redpanda.fetch_kafka_brokers("127.0.0.1", 9092) == []

    monkeypatch.setattr(
        "pytest_databases.docker.redpanda.socket.create_connection",
        make_conn([struct.pack(">i", 14), struct.pack(">iihi", 7, 1, 10, 0)]),
    )
    assert redpanda.fetch_kafka_brokers("127.0.0.1", 9092) == []


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_prefix"),
    [
        (1, "database", "redpanda", "pytest_databases_1_"),
        (1, "server", "redpanda_1", ""),
    ],
)
def test_provide_redpanda_service_xdist_and_readiness_errors(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int,
    isolation_level: str,
    expected_name: str,
    expected_prefix: str,
) -> None:
    """Verify provide_redpanda_service xdist modes and check failure branches."""
    monkeypatch.setattr("pytest_databases.docker.redpanda.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.redpanda._write_start_arguments", lambda _: None)

    broker_calls = 0

    def fake_brokers(host: str, port: int) -> list[tuple[str, int]]:
        nonlocal broker_calls
        broker_calls += 1
        if broker_calls == 1:
            msg = "not listening"
            raise OSError(msg)
        if broker_calls == 2:
            return [("other", 1234)]
        return [(host, port)]

    monkeypatch.setattr("pytest_databases.docker.redpanda.fetch_kafka_brokers", fake_brokers)
    container = MagicMock()
    container.exec_run.side_effect = [
        MagicMock(exit_code=1, output=b"starting"),
        MagicMock(exit_code=0, output=b"healthy"),
        MagicMock(exit_code=0, output=b"healthy"),
        MagicMock(exit_code=0, output=b"healthy"),
    ]
    cs = MagicMock()
    captured_name: list[str] = []

    @contextlib.contextmanager
    def fake_run(**kwargs: Any) -> Any:
        captured_name.append(kwargs["name"])
        svc = ServiceContainer(host="127.0.0.1", port=19092, container=container)
        check = kwargs["check"]
        assert check(svc) is False
        assert check(svc) is False
        assert check(svc) is False
        assert check(svc) is True
        yield svc

    cs.run.side_effect = fake_run

    with redpanda.provide_redpanda_service(
        container_service=cs,
        redpanda_image="redpanda:latest",
        redpanda_port=None,
        xdist_redpanda_isolation_level=isolation_level,  # type: ignore[arg-type]
    ) as service:
        assert service.topic_prefix == expected_prefix
        assert captured_name == [expected_name]


def test_redpanda_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all Redpanda fixtures execute in-process with mocked container_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    import pytest
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.redpanda"]

    @pytest.fixture(scope="session")
    def container_service():
        mock_cs = MagicMock()
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=19092, container=MagicMock())
        mock_cs.run.side_effect = _run
        return mock_cs

    def test_fixtures(
        redpanda_image,
        redpanda_port,
        xdist_redpanda_isolation_level,
        redpanda_service,
    ):
        assert "redpanda" in redpanda_image
        assert redpanda_port is None
        assert xdist_redpanda_isolation_level == "database"
        assert redpanda_service.port == 19092
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
