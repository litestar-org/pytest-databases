"""Tests for MySQL container service fixtures."""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, NotFound

from pytest_databases.docker import mysql as mysql_mod
from pytest_databases.docker.mysql import exec_mysql, provide_mysql_service
from pytest_databases.types import ServiceContainer
from tests.conftest import assert_legacy_platform_handling, unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest_databases.types import XdistIsolationLevel


def test_mysql_performance_schema_and_native_platform() -> None:
    """Verify provide_mysql_service enables performance_schema and forwards a native (None) platform."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=33306,
        container=mock_container,
    )

    with provide_mysql_service(
        docker_service=mock_docker,
        image="mysql:9.7",
        name="mysql-9.7",
        isolation_level="database",
        platform=None,
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.port == 33306

    assert mock_docker.run.call_args.kwargs["command"] == "--performance-schema=ON"
    assert mock_docker.run.call_args.kwargs["platform"] is None


def _user_platform() -> str:
    return "linux/arm64"


@pytest.mark.parametrize(
    ("platform_func", "expected_platform", "expected_warnings"),
    [
        (_user_platform, "linux/arm64", 1),
        (mysql_mod.platform, None, 0),
    ],
)
def test_mysql_8_services_honor_legacy_platform_override(
    monkeypatch: pytest.MonkeyPatch,
    platform_func: object,
    expected_platform: str | None,
    expected_warnings: int,
) -> None:
    """Verify MySQL 8+ services run natively unless a user-defined ``platform`` override is visible."""
    captured: dict[str, object] = {}

    @contextmanager
    def fake_provide(**kwargs: object) -> Generator[str, None, None]:
        captured.update(kwargs)
        yield "service"

    monkeypatch.setattr(mysql_mod, "provide_mysql_service", fake_provide)
    request = MagicMock()
    request._fixturemanager.getfixturedefs.return_value = [SimpleNamespace(func=platform_func)]
    request.getfixturevalue.return_value = "linux/arm64"

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        fixture_gen = unwrap_fixture(mysql_mod.mysql_8_service)(
            request, MagicMock(), "database", "app", "pw", "pw", "db", None
        )
        assert next(fixture_gen) == "service"

    deprecations = [w for w in record if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == expected_warnings
    if expected_warnings:
        assert "multi-arch" in str(deprecations[0].message)
    assert captured["platform"] == expected_platform


@pytest.mark.parametrize("mode", ["default", "override", "legacy"])
def test_mysql_platform_and_legacy_platform_fixture(pytester: pytest.Pytester, mode: str) -> None:
    """Verify mysql_platform defaults to x86_64, honors a legacy platform override, and the bare shim warns once."""
    assert_legacy_platform_handling(pytester, "pytest_databases.docker.mysql", "mysql_platform", "linux/x86_64", mode)


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mysql_8_service",
        "mysql_56_service",
        "mysql_57_service",
        "mysql_97_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify mysql_service starts and executes SQL queries."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mysql"]

    def run_mysql(service, sql):
        result = service.container.exec_run(
            [
                "mysql",
                f"--user={{service.user}}",
                "-D",
                service.db,
                "--batch",
                "--skip-column-names",
                "-e",
                sql,
            ],
            environment={{"MYSQL_PWD": service.password}},
        )
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().strip()

    def test({service_fixture}):
        assert run_mysql({service_fixture}, "select 1 as is_available") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify mysql_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.mysql"]

    def run_mysql(service, sql):
        result = service.container.exec_run(
            [
                "mysql",
                f"--user={service.user}",
                "-D",
                service.db,
                "-e",
                sql,
            ],
            environment={"MYSQL_PWD": service.password},
        )
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify mysql_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.mysql"]

    @pytest.fixture(scope="session")
    def xdist_mysql_isolation_level():
        return "server"

    def run_mysql(service, sql):
        result = service.container.exec_run(
            [
                "mysql",
                f"--user={service.user}",
                "-D",
                service.db,
                "-e",
                sql,
            ],
            environment={"MYSQL_PWD": service.password},
        )
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE DATABASE db_test")

    def test_2(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "database", "expected_name", "expected_db"),
    [
        (None, "database", "custom_db", "mysql-8", "custom_db"),
        (1, "database", "custom_db", "mysql-8", "custom_db_1"),
        (2, "server", "custom_db", "mysql-8_2", "custom_db"),
    ],
)
def test_provide_mysql_service_xdist_and_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    database: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_mysql_service honors custom database names, xdist modes, host-port gating, and retries."""
    monkeypatch.setattr("pytest_databases.docker.mysql.time.sleep", lambda _s: None)
    monkeypatch.setattr("pytest_databases.docker.mysql.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.mysql.tcp_port_open", lambda _h, _p: True)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    svc_container = ServiceContainer(host="127.0.0.1", port=33306, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    with provide_mysql_service(
        docker_service=mock_docker,
        image="mysql:8",
        name="mysql-8",
        isolation_level=isolation_level,
        platform=None,
        user="app",
        password="secret",
        root_password="secret",
        database=database,
    ) as service:
        assert service.db == expected_db

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True
    monkeypatch.setattr("pytest_databases.docker.mysql.tcp_port_open", lambda _h, _p: False)
    assert check(svc_container) is False
    monkeypatch.setattr("pytest_databases.docker.mysql.tcp_port_open", lambda _h, _p: True)
    mock_container.exec_run.side_effect = APIError("not ready")
    assert check(svc_container) is False

    mock_container.exec_run.side_effect = [APIError("transient"), MagicMock(exit_code=1, output=b"err")] * 10
    with (
        pytest.raises(RuntimeError, match="after 15 attempts"),
        provide_mysql_service(
            docker_service=mock_docker,
            image="mysql:8",
            name="mysql-8",
            isolation_level="database",
            platform=None,
            user="app",
            password="secret",
            root_password="secret",
            database=database,
        ),
    ):
        pass

    mock_container.exec_run.side_effect = NotFound("gone")
    with (
        pytest.raises(RuntimeError, match="after 15 attempts"),
        provide_mysql_service(
            docker_service=mock_docker,
            image="mysql:8",
            name="mysql-8",
            isolation_level="database",
            platform=None,
            user="app",
            password="secret",
            root_password="secret",
            database=database,
        ),
    ):
        pass


def test_mysql_command_env_init_sql_and_exec_sql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify command merging, env overrides, host_port, init_sql, and MySQLService.exec_sql."""
    monkeypatch.setattr(mysql_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(mysql_mod.run_container_init_once.__globals__["tempfile"], "tempdir", str(tmp_path))

    sql_file = tmp_path / "seed.sql"
    sql_file.write_text("SET GLOBAL slow_query_log = 1;", encoding="utf-8")

    executed: list[tuple[list[str], dict[str, str] | None]] = []
    mock_container = MagicMock()
    mock_container.id = "mysqlcid123456"

    def _record_exec(cmd: list[str], environment: dict[str, str] | None = None) -> MagicMock:
        executed.append((cmd, environment))
        return MagicMock(exit_code=0, output=b"1\n")

    mock_container.exec_run.side_effect = _record_exec
    mock_docker = MagicMock()
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=43306,
        container=mock_container,
    )

    with provide_mysql_service(
        docker_service=mock_docker,
        image="mysql:8.4",
        name="mysql-8.4",
        isolation_level="database",
        platform=None,
        user="app'user",
        password="secret",
        root_password="rootpw",
        database="my-app-db",
        host_port=43306,
        command=["--slow-query-log=1"],
        env={"TZ": "UTC"},
        init_sql=[sql_file, "CREATE TABLE t (id INT);"],
    ) as svc:
        assert svc.db == "my-app-db"
        code, out = svc.exec_sql("SELECT 1")
        assert (code, out) == (0, b"1\n")
        assert executed[-1][1] == {"MYSQL_PWD": "secret"}

    run_kwargs = mock_docker.run.call_args.kwargs
    assert run_kwargs["command"] == ["--performance-schema=ON", "--slow-query-log=1"]
    assert run_kwargs["host_port"] == 43306
    assert run_kwargs["env"]["TZ"] == "UTC"
    assert run_kwargs["env"]["MYSQL_DATABASE"] == "my-app-db"
    assert any("`my-app-db`" in cmd[-1] and "'app''user'" in cmd[-1] for cmd, _ in executed)
    assert any("SET GLOBAL slow_query_log = 1;" in cmd[-1] for cmd, _ in executed)

    with provide_mysql_service(
        docker_service=mock_docker,
        image="mysql:8.4",
        name="mysql-8.4",
        isolation_level="database",
        platform=None,
        user="root",
        password="rootpw",
        root_password="rootpw",
        database="my-app-db",
        command="--performance-schema=OFF --log-bin=mysql-bin",
    ):
        pass
    assert mock_docker.run.call_args.kwargs["command"] == ["--performance-schema=OFF", "--log-bin=mysql-bin"]
    assert "MYSQL_USER" not in mock_docker.run.call_args.kwargs["env"]

    with (
        pytest.raises(ValueError, match="Invalid MySQL database identifier"),
        provide_mysql_service(mock_docker, "mysql:8.4", "mysql", "database", None, "app", "pw", "pw", ""),
    ):
        pass
    with (
        pytest.raises(ValueError, match="user must be non-empty"),
        provide_mysql_service(mock_docker, "mysql:8.4", "mysql", "database", None, "", "pw", "pw", "db"),
    ):
        pass
    mock_container.exec_run.side_effect = APIError("daemon down")
    assert exec_mysql(mock_container, "SELECT 1")[0] == -1


def test_mysql_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Exercise all MySQL session fixtures in-process with a mocked provide_mysql_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import mysql as mysql_mod
    from pytest_databases.docker.mysql import MySQLService

    pytest_plugins = ["pytest_databases.docker.mysql"]

    @pytest.fixture(scope="session")
    def docker_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(**kwargs):
        yield MySQLService(
            host="127.0.0.1",
            port=3306,
            container=MagicMock(),
            db=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
        )

    def test_all(request):
        with patch.object(mysql_mod, "provide_mysql_service", _fake_provide):
            for name in mysql_mod.__all__:
                if name in {"MySQLService", "exec_mysql", "provide_mysql_service", "platform"}:
                    continue
                val = request.getfixturevalue(name)
                if name == "mysql_port":
                    assert val is None
                elif name != "mysql_platform":
                    assert val is not None
            with pytest.deprecated_call():
                assert request.getfixturevalue("platform") == "linux/x86_64"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
