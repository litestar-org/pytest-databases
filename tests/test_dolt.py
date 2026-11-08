"""Tests for Dolt SQL container service fixtures."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, NotFound

from pytest_databases.docker.dolt import provide_dolt_service
from pytest_databases.types import ServiceContainer
from tests.conftest import assert_legacy_platform_handling


@pytest.mark.parametrize("mode", ["default", "override", "legacy"])
def test_dolt_platform_and_legacy_platform_fixture(pytester: pytest.Pytester, mode: str) -> None:
    """Verify dolt_platform defaults to native, honors a legacy platform override, and the bare shim warns once."""
    assert_legacy_platform_handling(pytester, "pytest_databases.docker.dolt", "dolt_platform", None, mode)


def _start_dolt(mock_docker: MagicMock) -> None:
    with provide_dolt_service(
        docker_service=mock_docker,
        image="dolthub/dolt-sql-server:latest",
        name="dolt",
        isolation_level="database",
        platform=None,
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.port == 33306


def _mock_dolt_docker(exec_side_effect: list[object]) -> tuple[MagicMock, MagicMock]:
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.side_effect = exec_side_effect
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=33306,
        container=mock_container,
    )
    return mock_docker, mock_container


def test_dolt_setup_passes_platform_and_retries_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the native platform is forwarded and a 409 during setup is retried until the SQL succeeds."""
    monkeypatch.setattr("pytest_databases.docker.dolt.time.sleep", lambda _seconds: None)
    mock_docker, mock_container = _mock_dolt_docker([
        APIError("conflict", response=MagicMock(status_code=409)),
        MagicMock(exit_code=0, output=b""),
    ])

    _start_dolt(mock_docker)

    assert mock_docker.run.call_args.kwargs["platform"] is None
    assert mock_container.exec_run.call_count == 2


def test_dolt_setup_fails_fast_when_container_disappears(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a container removed after startup raises immediately instead of retrying a dead handle."""
    monkeypatch.setattr("pytest_databases.docker.dolt.time.sleep", lambda _seconds: None)
    mock_docker, mock_container = _mock_dolt_docker([NotFound("gone")])

    with pytest.raises(RuntimeError, match="disappeared after startup"):
        _start_dolt(mock_docker)

    assert mock_container.exec_run.call_count == 1


@pytest.mark.parametrize(
    "service_fixture",
    [
        "dolt_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify dolt_service starts and executes SQL queries."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.dolt"]

    def run_dolt(service, sql):
        result = service.container.exec_run([
            "dolt",
            "--use-db",
            service.db,
            "sql",
            "-q",
            sql,
            "-r",
            "csv",
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().splitlines()[-1].strip()

    def test({service_fixture}):
        assert run_dolt({service_fixture}, "select 1 as is_available") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify dolt_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.dolt"]

    def run_dolt(service, sql):
        result = service.container.exec_run([
            "dolt",
            "--use-db",
            service.db,
            "sql",
            "-q",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(dolt_service):
        run_dolt(dolt_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(dolt_service):
        run_dolt(dolt_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify dolt_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.dolt"]

    @pytest.fixture(scope="session")
    def xdist_dolt_isolation_level():
        return "server"

    def run_dolt(service, sql):
        result = service.container.exec_run([
            "dolt",
            "--use-db",
            service.db,
            "sql",
            "-q",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(dolt_service):
        run_dolt(dolt_service, "CREATE DATABASE db_test")

    def test_2(dolt_service):
        run_dolt(dolt_service, "CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        (1, "database", "dolt", "pytest_databases_1"),
        (2, "server", "dolt_2", "pytest_databases"),
    ],
)
def test_provide_dolt_service_xdist_and_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int,
    isolation_level: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_dolt_service xdist modes, readiness check, and setup retry failure."""
    monkeypatch.setattr("pytest_databases.docker.dolt.time.sleep", lambda _s: None)
    monkeypatch.setattr("pytest_databases.docker.dolt.get_xdist_worker_num", lambda: worker_num)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    svc_container = ServiceContainer(host="127.0.0.1", port=33306, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    with provide_dolt_service(
        docker_service=mock_docker,
        image="dolthub/dolt-sql-server:latest",
        name="dolt",
        isolation_level=isolation_level,  # type: ignore[arg-type]
        platform=None,
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.db == expected_db

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True

    resp_500 = MagicMock(status_code=500)
    mock_container.exec_run.side_effect = APIError("fatal", response=resp_500)
    with (
        pytest.raises(APIError),
        provide_dolt_service(
            docker_service=mock_docker,
            image="dolthub/dolt-sql-server:latest",
            name="dolt",
            isolation_level="database",
            platform=None,
            user="app",
            password="secret",
            root_password="secret",
            database="db",
        ),
    ):
        pass

    mock_container.exec_run.side_effect = None
    mock_container.exec_run.return_value = MagicMock(exit_code=1, output=b"booting")
    with (
        pytest.raises(RuntimeError, match="Dolt setup SQL failed after 5 attempts"),
        provide_dolt_service(
            docker_service=mock_docker,
            image="dolthub/dolt-sql-server:latest",
            name="dolt",
            isolation_level="database",
            platform=None,
            user="app",
            password="secret",
            root_password="secret",
            database="db",
        ),
    ):
        pass


def test_dolt_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Exercise all Dolt session fixtures in-process with a mocked provide_dolt_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import dolt as dolt_mod
    from pytest_databases.docker.dolt import DoltService

    pytest_plugins = ["pytest_databases.docker.dolt"]

    @pytest.fixture(scope="session")
    def docker_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(**kwargs):
        yield DoltService(
            host="127.0.0.1",
            port=3306,
            container=MagicMock(),
            db=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
        )

    def test_all(request):
        with patch.object(dolt_mod, "provide_dolt_service", _fake_provide):
            for name in dolt_mod.__all__:
                if name in {"DoltService", "provide_dolt_service", "platform"}:
                    continue
                val = request.getfixturevalue(name)
                if name != "dolt_platform":
                    assert val is not None
            with pytest.deprecated_call():
                assert request.getfixturevalue("platform") == "linux/x86_64"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
