"""Tests for MariaDB container service fixtures."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, NotFound

from pytest_databases._service import ContainerService
from pytest_databases.docker import mariadb as mariadb_mod
from pytest_databases.docker.mariadb import exec_mariadb, provide_mariadb_service
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest_databases.types import XdistIsolationLevel


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
    ("worker_num", "isolation_level", "database", "expected_name", "expected_db"),
    [
        (None, "database", "custom_db", "mariadb-11.8", "custom_db"),
        (1, "database", "custom_db", "mariadb-11.8", "custom_db_1"),
        (2, "server", "custom_db", "mariadb-11.8_2", "custom_db"),
    ],
)
def test_provide_mariadb_service_xdist_and_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    database: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_mariadb_service honors custom database names, xdist modes, host-port gating, and retries."""
    monkeypatch.setattr("pytest_databases.docker.mariadb.time.sleep", lambda _s: None)
    monkeypatch.setattr("pytest_databases.docker.mariadb.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.mariadb.tcp_port_open", lambda _h, _p: True)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    svc_container = ServiceContainer(host="127.0.0.1", port=33306, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    with provide_mariadb_service(
        docker_service=mock_docker,
        image="mariadb:11.8",
        name="mariadb-11.8",
        isolation_level=isolation_level,
        user="app",
        password="secret",
        root_password="secret",
        database=database,
    ) as service:
        assert service.db == expected_db

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True
    monkeypatch.setattr("pytest_databases.docker.mariadb.tcp_port_open", lambda _h, _p: False)
    assert check(svc_container) is False
    monkeypatch.setattr("pytest_databases.docker.mariadb.tcp_port_open", lambda _h, _p: True)
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
            database=database,
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
            database=database,
        ),
    ):
        pass


def test_mariadb_command_env_init_sql_and_exec_sql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify command merging, env overrides, host_port, init_sql, and MariaDBService.exec_sql."""
    monkeypatch.setattr(mariadb_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(mariadb_mod.run_container_init_once.__globals__["tempfile"], "tempdir", str(tmp_path))

    sql_file = tmp_path / "seed.sql"
    sql_file.write_text("SET GLOBAL userstat = 1;", encoding="utf-8")

    executed: list[tuple[list[str], dict[str, str] | None]] = []
    mock_container = MagicMock()
    mock_container.id = "mariadbcid1234"

    def _record_exec(cmd: list[str], environment: dict[str, str] | None = None) -> MagicMock:
        executed.append((cmd, environment))
        return MagicMock(exit_code=0, output=b"1\n")

    mock_container.exec_run.side_effect = _record_exec
    mock_docker = MagicMock()
    mock_docker.temp_dir = tmp_path
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=43307,
        container=mock_container,
    )

    with provide_mariadb_service(
        docker_service=mock_docker,
        image="mariadb:11.8",
        name="mariadb-11.8",
        isolation_level="database",
        user="app",
        password="secret",
        root_password="rootpw",
        database="maria-metrics",
        host_port=43307,
        command=["--userstat=1"],
        env={"TZ": "UTC"},
        init_sql=[sql_file, "CREATE TABLE t (id INT);"],
    ) as svc:
        assert svc.db == "maria-metrics"
        code, out = svc.exec_sql("SELECT 1")
        assert (code, out) == (0, b"1\n")
        assert executed[-1][1] == {"MYSQL_PWD": "secret"}

    run_kwargs = mock_docker.run.call_args.kwargs
    assert run_kwargs["command"] == ["--performance-schema=ON", "--userstat=1"]
    assert run_kwargs["host_port"] == 43307
    assert run_kwargs["env"]["MARIADB_DATABASE"] == "maria-metrics"
    assert any("`maria-metrics`" in cmd[-1] for cmd, _ in executed)
    assert any("SET GLOBAL userstat = 1;" in cmd[-1] for cmd, _ in executed)

    mock_container.exec_run.side_effect = APIError("daemon down")
    assert exec_mariadb(mock_container, "SELECT 1")[0] == -1


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
                if name in {"MariaDBService", "exec_mariadb", "provide_mariadb_service"}:
                    continue
                val = request.getfixturevalue(name)
                if name == "mariadb_port":
                    assert val is None
                else:
                    assert val is not None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_provide_mariadb_service_serializes_concurrent_grants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify concurrent provide_mariadb_service calls serialize GRANT/FLUSH behind ContainerService.temp_dir."""
    monkeypatch.setattr(mariadb_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(mariadb_mod, "tcp_port_open", lambda _h, _p: True)

    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
    docker_service = ContainerService(cast("Any", MagicMock()), tmp_path, mock_session, owner_id="mariadb01")

    state_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0
    mock_container = MagicMock()
    mock_container.id = "mariadbcid_xdist"

    def _exec_run(cmd: list[str], environment: dict[str, str] | None = None) -> MagicMock:
        nonlocal active_calls, max_active_calls
        _ = environment
        if "GRANT ALL PRIVILEGES" in cmd[-1]:
            with state_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                time.sleep(0.03)
            finally:
                with state_lock:
                    active_calls -= 1
        return MagicMock(exit_code=0, output=b"1\n")

    mock_container.exec_run.side_effect = _exec_run

    @contextmanager
    def _fake_run(**_kwargs: object) -> Generator[ServiceContainer, None, None]:
        yield ServiceContainer(host="127.0.0.1", port=3306, container=mock_container)

    monkeypatch.setattr(docker_service, "run", _fake_run)

    def _worker(db_name: str) -> None:
        with provide_mariadb_service(
            docker_service=docker_service,
            image="mariadb:11.8",
            name="mariadb-11.8",
            isolation_level="database",
            user="app",
            password="secret",
            root_password="root",
            database=db_name,
        ):
            pass

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_worker, f"test_db_{idx}") for idx in range(3)]
        for future in futures:
            future.result()

    assert max_active_calls == 1
    assert (tmp_path / "mariadbcid_xdist_db_init.lock").is_file()


@pytest.mark.parametrize("failure_mode", ["grant_error", "retry_exhaustion"])
def test_provide_mariadb_service_releases_lock_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    """Verify failed provisioning releases the MariaDB xdist init lock so peer workers can proceed."""
    monkeypatch.setattr(mariadb_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(mariadb_mod, "tcp_port_open", lambda _h, _p: True)
    monkeypatch.setattr(mariadb_mod.time, "sleep", lambda _s: None)

    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
    docker_service = ContainerService(cast("Any", MagicMock()), tmp_path, mock_session, owner_id="mariadb02")
    mock_container = MagicMock()
    mock_container.id = "mariadbcid_fail"

    def _failing_exec(cmd: list[str], environment: dict[str, str] | None = None) -> MagicMock:
        _ = environment
        if failure_mode == "grant_error" and "GRANT ALL PRIVILEGES" in cmd[-1]:
            return MagicMock(exit_code=1, output=b"ERROR 1396")
        if failure_mode == "retry_exhaustion" and cmd[-1] == "SELECT 1":
            return MagicMock(exit_code=1, output=b"ERROR 1045")
        return MagicMock(exit_code=0, output=b"1\n")

    @contextmanager
    def _fake_run(**_kwargs: object) -> Generator[ServiceContainer, None, None]:
        yield ServiceContainer(host="127.0.0.1", port=3306, container=mock_container)

    monkeypatch.setattr(docker_service, "run", _fake_run)
    mock_container.exec_run.side_effect = _failing_exec

    with (
        pytest.raises(RuntimeError, match="after 15 attempts"),
        provide_mariadb_service(
            docker_service=docker_service,
            image="mariadb:11.8",
            name="mariadb-11.8",
            isolation_level="database",
            user="app",
            password="secret",
            root_password="root",
            database="test_db_0",
        ),
    ):
        pass

    mock_container.exec_run.side_effect = None
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    with provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.8",
        name="mariadb-11.8",
        isolation_level="database",
        user="app",
        password="secret",
        root_password="root",
        database="test_db_1",
    ) as service:
        assert service.db == "test_db_1"
