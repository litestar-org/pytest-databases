"""Tests for YugabyteDB distributed SQL service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import APIError

from pytest_databases.docker.yugabyte import (
    YUGABYTE_DATABASE,
    YUGABYTE_PASSWORD,
    YUGABYTE_USER,
    _ensure_yugabyte_database,
    _exec_ysqlsh,
    _make_ysqlsh_command,
    _prepare_yugabyte_database,
    _validate_mapped_endpoint,
    is_transient_yugabyte_error,
    provide_yugabyte_service,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator


def test_provide_yugabyte_service_validates_without_sidecar_containers() -> None:
    """Verify provide_yugabyte_service uses service.container directly without spawning sidecar containers."""
    docker_service = MagicMock()
    dummy_container = MagicMock()
    dummy_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        check = kwargs["check"]
        assert callable(check)
        service_container = ServiceContainer(host="127.0.0.1", port=5433, container=dummy_container)
        assert check(service_container) is True
        yield service_container

    docker_service.run.side_effect = fake_run

    with (
        patch("pytest_databases.docker.yugabyte.socket.create_connection") as mock_connect,
        provide_yugabyte_service(
            docker_service,
            isolation_level="database",
            image="software.yugabyte.com/yugabytedb/yugabyte:latest",
            user=YUGABYTE_USER,
            password=YUGABYTE_PASSWORD,
            database=YUGABYTE_DATABASE,
        ) as service,
    ):
        assert service.host == "127.0.0.1"
        assert service.port == 5433
        assert service.database == YUGABYTE_DATABASE
        assert service.user == YUGABYTE_USER
        assert service.password == YUGABYTE_PASSWORD
        mock_connect.assert_called_once_with(("127.0.0.1", 5433), timeout=2.0)
        docker_service._client.containers.run.assert_not_called()


def test_service_fixture(pytester: pytest.Pytester) -> None:
    """Verify yugabyte_service provisions custom credentials and executes SQL."""
    pytester.makepyfile("""
    import shlex
    import pytest

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(scope="session")
    def yugabyte_user():
        return "custom_yugabyte_user"

    @pytest.fixture(scope="session")
    def yugabyte_password():
        return "custom-yugabyte-password"

    @pytest.fixture(scope="session")
    def yugabyte_database():
        return "custom_yugabyte_database"

    def run_ysqlsh(yugabyte_service, sql, database=None):
        database = database or yugabyte_service.database
        command = " ".join([
            "bin/ysqlsh",
            "-h $(hostname)",
            f"-U {shlex.quote(yugabyte_service.user)}",
            f"-d {shlex.quote(database)}",
            "-tAc",
            shlex.quote(sql),
        ])
        result = yugabyte_service.container.exec_run(["sh", "-c", command])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().strip()

    def test(yugabyte_service) -> None:
        assert yugabyte_service.user == "custom_yugabyte_user"
        assert yugabyte_service.password == "custom-yugabyte-password"
        assert yugabyte_service.database == "custom_yugabyte_database"
        assert run_ysqlsh(yugabyte_service, "SELECT 1") == "1"
        run_ysqlsh(yugabyte_service, "CREATE TABLE IF NOT EXISTS simple_table AS SELECT 1")
        assert run_ysqlsh(yugabyte_service, "SELECT * FROM simple_table") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify database-isolated yugabyte_service isolates xdist workers in separate databases."""
    pytester.makepyfile("""
    import shlex
    import time
    import pytest
    from pytest_databases.docker.yugabyte import is_transient_yugabyte_error

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    def run_ysqlsh(yugabyte_service, sql):
        command = " ".join([
            "bin/ysqlsh",
            "-h $(hostname)",
            f"-U {shlex.quote(yugabyte_service.user)}",
            f"-d {shlex.quote(yugabyte_service.database)}",
            "-c",
            shlex.quote(sql),
        ])
        for attempt in range(10):
            result = yugabyte_service.container.exec_run(["sh", "-c", command])
            output = result.output.decode(errors="replace")
            if result.exit_code == 0:
                return
            if is_transient_yugabyte_error(output) and attempt < 9:
                time.sleep(0.3 * (attempt + 1))
                continue
            assert result.exit_code == 0, output

    def test_one(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE TABLE foo AS SELECT 1")

    def test_two(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE TABLE foo AS SELECT 1")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify server-isolated yugabyte_service starts separate containers per xdist worker."""
    pytester.makepyfile("""
    import shlex
    import time
    import pytest
    from pytest_databases.docker.yugabyte import is_transient_yugabyte_error

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(scope="session")
    def xdist_yugabyte_isolation_level():
        return "server"

    def run_ysqlsh(yugabyte_service, sql, database="yugabyte"):
        command = " ".join([
            "bin/ysqlsh",
            "-h $(hostname)",
            f"-U {shlex.quote(yugabyte_service.user)}",
            f"-d {shlex.quote(database)}",
            "-c",
            shlex.quote(sql),
        ])
        for attempt in range(10):
            result = yugabyte_service.container.exec_run(["sh", "-c", command])
            output = result.output.decode(errors="replace")
            if result.exit_code == 0:
                return
            if is_transient_yugabyte_error(output) and attempt < 9:
                time.sleep(0.3 * (attempt + 1))
                continue
            assert result.exit_code == 0, output

    def test_one(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE DATABASE foo")

    def test_two(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE DATABASE foo")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        (2, "database", "yugabyte", "pytest_databases_2"),
        (2, "server", "yugabyte_2", "pytest_databases"),
    ],
)
def test_provide_yugabyte_service_xdist_and_endpoint_retry(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int,
    isolation_level: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_yugabyte_service xdist modes and mapped endpoint retry/failure."""
    monkeypatch.setattr("pytest_databases.docker.yugabyte.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.yugabyte.time.sleep", lambda _: None)
    monkeypatch.setattr("pytest_databases.docker.yugabyte._prepare_yugabyte_database", lambda *_a, **_kw: None)

    calls = 0

    def fake_validate(*_args: Any, **_kwargs: Any) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return 1, b"not ready"
        return 0, b"1\n"

    monkeypatch.setattr("pytest_databases.docker.yugabyte._validate_mapped_endpoint", fake_validate)
    docker_service = MagicMock()
    captured_name: list[str] = []

    @contextmanager
    def fake_run(**kwargs: Any) -> Generator[ServiceContainer, None, None]:
        captured_name.append(kwargs["name"])
        yield ServiceContainer(host="127.0.0.1", port=5433, container=MagicMock())

    docker_service.run.side_effect = fake_run

    with provide_yugabyte_service(
        docker_service,
        isolation_level=isolation_level,  # type: ignore[arg-type]
        image="yugabyte:latest",
        user=YUGABYTE_USER,
        password=YUGABYTE_PASSWORD,
        database=YUGABYTE_DATABASE,
    ) as svc:
        assert svc.database == expected_db
        assert captured_name == [expected_name]

    monkeypatch.setattr(
        "pytest_databases.docker.yugabyte._validate_mapped_endpoint",
        lambda *_a, **_kw: (1, b"connection refused"),
    )
    with (
        pytest.raises(RuntimeError, match=r"mapped endpoint 127\.0\.0\.1:5433 was not ready"),
        provide_yugabyte_service(
            docker_service,
            isolation_level="database",
            image="yugabyte:latest",
            user=YUGABYTE_USER,
            password=YUGABYTE_PASSWORD,
            database=YUGABYTE_DATABASE,
        ),
    ):
        pass


def test_yugabyte_helpers_and_error_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Yugabyte helper branches including transient error detection and retry exhaustion."""
    assert "-p 5433" in _make_ysqlsh_command("SELECT 1", port=5433)
    assert is_transient_yugabyte_error(b"ERROR: Restart read required") is True
    assert is_transient_yugabyte_error("ERROR: Catalog Version Mismatch") is True
    assert is_transient_yugabyte_error("ERROR: syntax error") is False

    container = MagicMock()
    container.exec_run.side_effect = APIError("daemon error")
    assert _exec_ysqlsh(container, "SELECT 1")[0] == -1

    container.exec_run.side_effect = [MagicMock(exit_code=1, output=b"exists err")]
    assert _ensure_yugabyte_database(container, "db", "usr") == (False, b"exists err")

    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b""),
        MagicMock(exit_code=1, output=b"create err"),
    ]
    assert _ensure_yugabyte_database(container, "db", "usr") == (False, b"create err")

    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b"1"),
        MagicMock(exit_code=1, output=b"grant err"),
    ]
    assert _ensure_yugabyte_database(container, "db", "usr") == (False, b"grant err")

    monkeypatch.setattr("pytest_databases.docker.yugabyte.time.sleep", lambda _: None)
    container.exec_run.side_effect = None
    container.exec_run.return_value = MagicMock(exit_code=1, output=b"role err")
    with pytest.raises(RuntimeError, match="could not reach database"):
        _prepare_yugabyte_database(container, "yugabyte", "db", "usr", "pwd")

    monkeypatch.setattr(
        "pytest_databases.docker.yugabyte.socket.create_connection",
        MagicMock(side_effect=OSError("refused")),
    )
    svc = ServiceContainer(host="127.0.0.1", port=5433, container=container)
    assert _validate_mapped_endpoint(svc, "db", "usr", "pwd")[0] == 1


def test_yugabyte_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all Yugabyte fixtures execute in-process with mocked docker_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    import pytest
    import pytest_databases.docker.yugabyte as yb_mod
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(autouse=True, scope="session")
    def mock_yb():
        orig_prep = yb_mod._prepare_yugabyte_database
        orig_val = yb_mod._validate_mapped_endpoint
        yb_mod._prepare_yugabyte_database = lambda *a, **kw: None
        yb_mod._validate_mapped_endpoint = lambda *a, **kw: (0, b"1")
        yield
        yb_mod._prepare_yugabyte_database = orig_prep
        yb_mod._validate_mapped_endpoint = orig_val

    @pytest.fixture(scope="session")
    def docker_service():
        mock_ds = MagicMock()
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=5433, container=MagicMock())
        mock_ds.run.side_effect = _run
        return mock_ds

    def test_fixtures(
        xdist_yugabyte_isolation_level,
        yugabyte_image,
        yugabyte_user,
        yugabyte_password,
        yugabyte_database,
        yugabyte_service,
    ):
        assert xdist_yugabyte_isolation_level == "database"
        assert "yugabyte" in yugabyte_image
        assert yugabyte_user == "yugabyte"
        assert yugabyte_password == "yugabyte"
        assert yugabyte_database == "pytest_databases"
        assert yugabyte_service.port == 5433
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
