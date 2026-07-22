from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_plugin_imports_without_aws_clients(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"awscli", "boto3", "botocore", "localstack_client"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.localstack
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_sqs_lifecycle_uses_the_container_cli(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import json

    from pytest_databases.docker.localstack import LocalStackService

    pytest_plugins = ["pytest_databases.docker.localstack"]

    def test(localstack_service: LocalStackService) -> None:
        assert localstack_service.endpoint_url == f"http://{localstack_service.host}:{localstack_service.port}"
        assert localstack_service.region == "us-east-1"
        assert localstack_service.access_key == "test"
        assert localstack_service.secret_key == "test"
        assert localstack_service.services is None
        assert localstack_service.resource_prefix.startswith("pytest-databases-")

        queue_name = f"{localstack_service.resource_prefix}sqs-lifecycle"
        created = json.loads(localstack_service.exec_aws_cli(
            "sqs", "create-queue", "--queue-name", queue_name, "--output", "json"
        ))
        queue_url = created["QueueUrl"]
        sent = json.loads(localstack_service.exec_aws_cli(
            "sqs", "send-message", "--queue-url", queue_url,
            "--message-body", "clientless", "--output", "json"
        ))
        assert sent["MessageId"]

        received = json.loads(localstack_service.exec_aws_cli(
            "sqs", "receive-message", "--queue-url", queue_url,
            "--wait-time-seconds", "1", "--max-number-of-messages", "1", "--output", "json"
        ))
        message = received["Messages"][0]
        assert message["Body"] == "clientless"
        localstack_service.exec_aws_cli(
            "sqs", "delete-message", "--queue-url", queue_url,
            "--receipt-handle", message["ReceiptHandle"]
        )
        localstack_service.exec_aws_cli("sqs", "delete-queue", "--queue-url", queue_url)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_fixture_overrides_are_visible(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest

    pytest_plugins = ["pytest_databases.docker.localstack"]

    @pytest.fixture(scope="session")
    def localstack_region():
        return "eu-west-1"

    @pytest.fixture(scope="session")
    def localstack_access_key():
        return "override-access"

    @pytest.fixture(scope="session")
    def localstack_secret_key():
        return "override-secret"

    @pytest.fixture(scope="session")
    def localstack_services():
        return ("s3",)

    @pytest.fixture(scope="session")
    def localstack_resource_prefix():
        return "custom-prefix-"

    def test(localstack_service) -> None:
        assert localstack_service.region == "eu-west-1"
        assert localstack_service.access_key == "override-access"
        assert localstack_service.secret_key == "override-secret"
        assert localstack_service.services == ("s3",)
        assert localstack_service.resource_prefix == "custom-prefix-"
        environment = localstack_service.container.attrs["Config"]["Env"]
        assert "SERVICES=s3" in environment
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_database_isolation(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALSTACK_TEST_STATE", str(tmp_path))
    pytester.makepyfile("""
    import os
    from pathlib import Path

    pytest_plugins = ["pytest_databases.docker.localstack"]

    def record(localstack_service) -> None:
        worker = os.environ["PYTEST_XDIST_WORKER"]
        value = f"{localstack_service.container.id}|{localstack_service.resource_prefix}"
        Path(os.environ["LOCALSTACK_TEST_STATE"], f"{worker}.txt").write_text(value, encoding="utf-8")

    def test_one(localstack_service) -> None:
        record(localstack_service)

    def test_two(localstack_service) -> None:
        record(localstack_service)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)
    records = [path.read_text(encoding="utf-8").split("|") for path in sorted(tmp_path.glob("gw*.txt"))]
    assert len(records) == 2
    assert len({container_id for container_id, _ in records}) == 1
    assert len({prefix for _, prefix in records}) == 2


def test_xdist_server_isolation(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALSTACK_TEST_STATE", str(tmp_path))
    pytester.makepyfile("""
    import os
    from pathlib import Path

    import pytest

    pytest_plugins = ["pytest_databases.docker.localstack"]

    @pytest.fixture(scope="session")
    def xdist_localstack_isolation_level():
        return "server"

    def record(localstack_service) -> None:
        worker = os.environ["PYTEST_XDIST_WORKER"]
        Path(os.environ["LOCALSTACK_TEST_STATE"], f"{worker}.txt").write_text(
            localstack_service.container.id, encoding="utf-8"
        )

    def test_one(localstack_service) -> None:
        record(localstack_service)

    def test_two(localstack_service) -> None:
        record(localstack_service)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)
    container_ids = {path.read_text(encoding="utf-8") for path in tmp_path.glob("gw*.txt")}
    assert len(container_ids) == 2
