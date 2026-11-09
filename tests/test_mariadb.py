"""Tests for MariaDB container service fixtures."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, NotFound

from pytest_databases.docker.mariadb import provide_mariadb_service
from pytest_databases.types import ServiceContainer


def test_mariadb_performance_schema_and_version_fixtures() -> None:
    """Verify provide_mariadb_service enables performance_schema."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=33306,
        container=mock_container,
    )

    with provide_mariadb_service(
        docker_service=mock_docker,
        image="mariadb:11.8",
        name="mariadb-11.8",
        isolation_level="database",
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.port == 33306

    assert mock_docker.run.call_args.kwargs["command"] == "--performance-schema=ON"


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mariadb_service",
        "mariadb_113_service",
        "mariadb_118_service",
        "mariadb_123_service",
        "mariadb_130_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify mariadb_service starts and executes SQL queries."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def run_mariadb(service, sql):
        result = service.container.exec_run([
            "mariadb",
            f"--user={{service.user}}",
            f"--password={{service.password}}",
            "-D",
            service.db,
            "--batch",
            "--skip-column-names",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().strip()

    def test({service_fixture}):
        assert run_mariadb({service_fixture}, "select 1 as is_available") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify mariadb_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def run_mariadb(service, sql):
        result = service.container.exec_run([
            "mariadb",
            f"--user={service.user}",
            f"--password={service.password}",
            "-D",
            service.db,
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify mariadb_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    @pytest.fixture(scope="session")
    def xdist_mariadb_isolation_level():
        return "server"

    def run_mariadb(service, sql):
        result = service.container.exec_run([
            "mariadb",
            f"--user={service.user}",
            f"--password={service.password}",
            "-D",
            service.db,
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE DATABASE db_test")

    def test_2(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        (1, "database", "mariadb-11.8", "pytest_databases_1"),
        (2, "server", "mariadb-11.8_2", "pytest_databases"),
    ],
)
def test_provide_mariadb_service_xdist_and_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int,
    isolation_level: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_mariadb_service xdist modes, readiness check, and setup retry failure."""
    monkeypatch.setattr("pytest_databases.docker.mariadb.time.sleep", lambda _s: None)
    monkeypatch.setattr("pytest_databases.docker.mariadb.get_xdist_worker_num", lambda: worker_num)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    svc_container = ServiceContainer(host="127.0.0.1", port=33306, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    with provide_mariadb_service(
        docker_service=mock_docker,
        image="mariadb:11.8",
        name="mariadb-11.8",
        isolation_level=isolation_level,  # type: ignore[arg-type]
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.db == expected_db

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True
    mock_container.exec_run.side_effect = APIError("not ready")
    assert check(svc_container) is False

    mock_container.exec_run.side_effect = [APIError("transient"), MagicMock(exit_code=1, output=b"err")] * 10
    with (
        pytest.raises(RuntimeError, match="after 15 attempts"),
        provide_mariadb_service(
            docker_service=mock_docker,
            image="mariadb:11.8",
            name="mariadb-11.8",
            isolation_level="database",
            user="app",
            password="secret",
            root_password="secret",
            database="db",
        ),
    ):
        pass

    mock_container.exec_run.side_effect = NotFound("gone")
    with (
        pytest.raises(RuntimeError, match="after 15 attempts"),
        provide_mariadb_service(
            docker_service=mock_docker,
            image="mariadb:11.8",
            name="mariadb-11.8",
            isolation_level="database",
            user="app",
            password="secret",
            root_password="secret",
            database="db",
        ),
    ):
        pass


def test_mariadb_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Exercise all MariaDB session fixtures in-process with a mocked provide_mariadb_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import mariadb as mariadb_mod
    from pytest_databases.docker.mariadb import MariaDBService

    pytest_plugins = ["pytest_databases.docker.mariadb"]

    @pytest.fixture(scope="session")
    def docker_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(**kwargs):
        yield MariaDBService(
            host="127.0.0.1",
            port=3306,
            container=MagicMock(),
            db=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
        )

    def test_all(request):
        with patch.object(mariadb_mod, "provide_mariadb_service", _fake_provide):
            for name in mariadb_mod.__all__:
                if name in {"MariaDBService", "provide_mariadb_service"}:
                    continue
                val = request.getfixturevalue(name)
                assert val is not None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
