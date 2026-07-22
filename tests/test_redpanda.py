from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from pytest_databases.docker import redpanda

if TYPE_CHECKING:
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
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith(("confluent_kafka", "kafka")):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.redpanda  # noqa: F401
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_public_contract_and_environment_overrides(monkeypatch: MonkeyPatch) -> None:
    service = redpanda.RedpandaService(
        container=Mock(),
        host="127.0.0.1",
        port=19092,
        bootstrap_servers="127.0.0.1:19092",
        topic_prefix="pytest_databases_",
    )
    assert service.bootstrap_servers == f"{service.host}:{service.port}"
    assert service.topic_prefix == "pytest_databases_"

    assert redpanda.redpanda_image.__wrapped__() == redpanda.DEFAULT_REDPANDA_IMAGE  # type: ignore[attr-defined]
    assert redpanda.redpanda_port.__wrapped__() is None  # type: ignore[attr-defined]
    monkeypatch.setenv("REDPANDA_IMAGE", "example.test/redpanda:v1")
    monkeypatch.setenv("REDPANDA_PORT", "29092")
    assert redpanda.redpanda_image.__wrapped__() == "example.test/redpanda:v1"  # type: ignore[attr-defined]
    assert redpanda.redpanda_port.__wrapped__() == 29092  # type: ignore[attr-defined]


def test_start_command_waits_for_the_mapped_port() -> None:
    command = redpanda._redpanda_command()
    assert command[0] == "-c"
    assert redpanda.REDPANDA_PORT_FILE in command[1]
    assert "external://0.0.0.0:19092" in command[1]
    assert "external://127.0.0.1:${advertised_port}" in command[1]


def test_default_service_is_clientless(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.redpanda import RedpandaService

pytest_plugins = ["pytest_databases.docker.redpanda"]

{REDPANDA_TEST_HELPERS}


def test_round_trip(redpanda_service: RedpandaService):
    assert redpanda_service.host == "127.0.0.1"
    assert redpanda_service.bootstrap_servers == f"{{redpanda_service.host}}:{{redpanda_service.port}}"
    assert redpanda_service.topic_prefix == "pytest_databases_"
    round_trip(redpanda_service, "default")
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("isolation_level", ["database", "server"])
def test_xdist_isolation_is_clientless(pytester: pytest.Pytester, isolation_level: str) -> None:
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
