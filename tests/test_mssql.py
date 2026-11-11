"""Tests for Microsoft SQL Server container service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError

from pytest_databases.docker import mssql
from pytest_databases.docker.mssql import (
    MSSQLService,
    _prepare_database,
    exec_sqlcmd,
    mssql_2022_image,
    mssql_2025_image,
    mssql_service,
    provide_mssql_service,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import PLATFORM_PROCESSOR, unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest_databases.types import XdistIsolationLevel


def test_plugin_imports_without_pymssql(pytester: pytest.Pytester) -> None:
    """Verify mssql plugin imports cleanly without pymssql installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pymssql":
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.mssql
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_mssql_sqlcmd_fallback_and_images() -> None:
    """Verify exec_sqlcmd falls back across sqlcmd binary locations and image fixtures exist."""
    assert unwrap_fixture(mssql_2022_image)() == "mcr.microsoft.com/mssql/server:2022-latest"
    assert unwrap_fixture(mssql_2025_image)() == "mcr.microsoft.com/mssql/server:2025-latest"

    mock_container = MagicMock()
    mock_container.exec_run.side_effect = [
        MagicMock(exit_code=127, output=b"executable file not found"),
        MagicMock(exit_code=0, output=b"1\n"),
    ]
    exit_code, output = exec_sqlcmd(mock_container, "SELECT 1")
    assert exit_code == 0
    assert output == b"1\n"
    assert mock_container.exec_run.call_count == 2
    first_call = mock_container.exec_run.call_args_list[0]
    first_cmd = first_call.args[0]
    second_cmd = mock_container.exec_run.call_args_list[1].args[0]
    assert first_cmd[0] == "/opt/mssql-tools18/bin/sqlcmd"
    assert second_cmd[0] == "/opt/mssql-tools/bin/sqlcmd"
    assert "-P" not in first_cmd
    assert first_call.kwargs["environment"] == {"SQLCMDPASSWORD": mssql.MSSQL_PASSWORD}


@pytest.mark.parametrize(
    ("image", "expected_name"),
    [
        ("mcr.microsoft.com/mssql/server:2022-latest", "mssql-2022"),
        ("mcr.microsoft.com/mssql/server:2019-latest", "mssql"),
    ],
)
def test_mssql_service_reuses_2022_container_for_default_image(
    monkeypatch: pytest.MonkeyPatch,
    image: str,
    expected_name: str,
) -> None:
    """Verify mssql_service shares the mssql_2022_service container only when it runs the 2022 image."""
    captured: dict[str, object] = {}

    @contextmanager
    def fake_provide(**kwargs: object) -> Generator[str, None, None]:
        captured.update(kwargs)
        yield "service"

    monkeypatch.setattr(mssql, "provide_mssql_service", fake_provide)
    fixture_gen = unwrap_fixture(mssql_service)(
        MagicMock(),
        "database",
        image,
        "mcr.microsoft.com/mssql/server:2022-latest",
        "sa",
        "secret",
        "db",
        None,
    )

    assert next(fixture_gen) == "service"
    assert captured["name"] == expected_name
    assert captured["image"] == image


@pytest.fixture(scope="module")
def mssql_test_helpers() -> str:
    """Return shared SQL Server sqlcmd test helper code.

    Returns:
        Helper Python source code string.
    """
    return """
    def run_mssql(service, sql, database=None):
        prefix = "" if sql.lstrip().upper().startswith(("ALTER", "CREATE", "DROP")) else "SET NOCOUNT ON; "
        result = service.container.exec_run([
            "/opt/mssql-tools18/bin/sqlcmd",
            "-C",
            "-b",
            "-S",
            "localhost,1433",
            "-U",
            service.user,
            "-P",
            service.password,
            "-d",
            database or service.database,
            "-h",
            "-1",
            "-W",
            "-Q",
            f"{prefix}{sql}",
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return [line.strip() for line in result.output.decode().splitlines() if line.strip()]
    """


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="SQL Server container image is not supported on ARM")
@pytest.mark.parametrize("service_fixture", ["mssql_service", "mssql_2022_service", "mssql_2025_service"])
def test_service_fixture(pytester: pytest.Pytester, mssql_test_helpers: str, service_fixture: str) -> None:
    """Verify each SQL Server service fixture starts and executes T-SQL queries with custom credentials."""
    pytester.makepyfile(f"""
    import pytest

    pytest_plugins = ["pytest_databases.docker.mssql"]

    @pytest.fixture(scope="session")
    def mssql_user():
        return "custom_mssql_user"

    @pytest.fixture(scope="session")
    def mssql_password():
        return "Custom-secret1"

    @pytest.fixture(scope="session")
    def mssql_database():
        return "custom_mssql_database"

    {mssql_test_helpers}

    def test({service_fixture}):
        service = {service_fixture}
        assert service.user == "custom_mssql_user"
        assert service.password == "Custom-secret1"
        assert service.database == "custom_mssql_database"
        assert run_mssql(service, "SELECT 1 AS is_available") == ["1"]
        run_mssql(service, "CREATE TABLE simple_table (the_value int)")
        run_mssql(service, "INSERT INTO simple_table VALUES (1)")
        assert run_mssql(service, "SELECT the_value FROM simple_table") == ["1"]
        run_mssql(service, "DROP TABLE simple_table")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="SQL Server container image is not supported on ARM")
def test_xdist_isolate_database(pytester: pytest.Pytester, mssql_test_helpers: str) -> None:
    """Verify mssql_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mssql"]

    {mssql_test_helpers}

    def test_1(mssql_service):
        run_mssql(mssql_service, "CREATE TABLE simple_table (the_value int)")

    def test_2(mssql_service):
        run_mssql(mssql_service, "CREATE TABLE simple_table (the_value int)")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="SQL Server container image is not supported on ARM")
def test_xdist_isolate_server(pytester: pytest.Pytester, mssql_test_helpers: str) -> None:
    """Verify mssql_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile(f"""
    import pytest

    pytest_plugins = ["pytest_databases.docker.mssql"]

    @pytest.fixture(scope="session")
    def xdist_mssql_isolation_level():
        return "server"

    {mssql_test_helpers}

    def test_1(mssql_service):
        run_mssql(mssql_service, "CREATE DATABASE db_test", database="master")

    def test_2(mssql_service):
        run_mssql(mssql_service, "CREATE DATABASE db_test", database="master")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "user", "expected_name", "expected_db"),
    [
        (None, "database", "sa", "mssql", "db"),
        (1, "database", "custom_user", "mssql", "db_1"),
        (2, "server", "sa", "mssql_2", "db"),
    ],
)
def test_provide_mssql_service_and_prepare_database_branches(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    user: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_mssql_service xdist modes, custom user creation, and retry exhaustion."""
    monkeypatch.setattr("pytest_databases.docker.mssql.time.sleep", lambda _s: None)
    monkeypatch.setattr("pytest_databases.docker.mssql.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.mssql.tcp_port_open", lambda _h, _p: True)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    svc_container = ServiceContainer(host="127.0.0.1", port=1433, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    with provide_mssql_service(
        docker_service=mock_docker,
        xdist_mssql_isolation_level=isolation_level,
        image="mcr.microsoft.com/mssql/server:2022-latest",
        name="mssql",
        mssql_user=user,
        mssql_password="Secret-password1",
        mssql_database="db",
    ) as service:
        assert isinstance(service, MSSQLService)
        assert service.database == expected_db

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True
    monkeypatch.setattr("pytest_databases.docker.mssql.tcp_port_open", lambda _h, _p: False)
    assert check(svc_container) is False
    monkeypatch.setattr("pytest_databases.docker.mssql.tcp_port_open", lambda _h, _p: True)
    mock_container.exec_run.side_effect = APIError("boom")
    assert check(svc_container) is False

    mock_container.exec_run.side_effect = None
    mock_container.exec_run.return_value = MagicMock(exit_code=1, output=b"not ready")
    with pytest.raises(RuntimeError, match="could not be prepared"):
        _prepare_database(
            mock_container,
            database="db",
            user="sa",
            password="Secret-password1",
        )

    mock_container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b""),
        MagicMock(exit_code=1, output=b"login err"),
    ] * 15
    with pytest.raises(RuntimeError, match="could not be prepared"):
        _prepare_database(
            mock_container,
            database="db",
            user="custom_user",
            password="Secret-password1",
        )


def test_mssql_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Exercise all MSSQL session fixtures in-process with a mocked provide_mssql_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import mssql as mssql_mod
    from pytest_databases.docker.mssql import MSSQLService

    pytest_plugins = ["pytest_databases.docker.mssql"]

    @pytest.fixture(scope="session")
    def docker_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(**kwargs):
        yield MSSQLService(
            host="127.0.0.1",
            port=1433,
            container=MagicMock(),
            database=kwargs["mssql_database"],
            user=kwargs["mssql_user"],
            password=kwargs["mssql_password"],
        )

    def test_all(request):
        with patch.object(mssql_mod, "provide_mssql_service", _fake_provide):
            for name in mssql_mod.__all__:
                if name.isupper() or name in {"MSSQLService", "provide_mssql_service", "exec_sqlcmd"}:
                    continue
                val = request.getfixturevalue(name)
                if name == "mssql_port":
                    assert val is None
                else:
                    assert val is not None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_exec_sqlcmd_go_batches_sql_file_and_mssql_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify multi-batch GO staging, sql_file upload/cleanup, empty password handling, and service options."""
    monkeypatch.setattr(mssql, "get_xdist_worker_num", lambda: None)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(mssql.tempfile, "tempdir", str(tmp_path))

    mock_container = MagicMock()
    mock_container.id = "mssqlcid123456"
    mock_container.put_archive.return_value = True
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")

    script = tmp_path / "batches.sql"
    script.write_text("CREATE VIEW v AS SELECT 1 AS c;\nGO\nSELECT c FROM v;\n", encoding="utf-8")

    code, out = exec_sqlcmd(mock_container, sql_file=script, database="appdb", password="", query_timeout=15)
    assert (code, out) == (0, b"1\n")
    mock_container.put_archive.assert_called_once()
    sqlcmd_call = mock_container.exec_run.call_args_list[0]
    cleanup_call = mock_container.exec_run.call_args_list[1]
    assert "-P" in sqlcmd_call.args[0]
    assert "-t" in sqlcmd_call.args[0] and "15" in sqlcmd_call.args[0]
    assert "-i" in sqlcmd_call.args[0]
    assert sqlcmd_call.kwargs["environment"] is None
    assert cleanup_call.args[0][:2] == ["rm", "-f"]

    mock_docker = MagicMock()
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=21433,
        container=mock_container,
    )
    with provide_mssql_service(
        docker_service=mock_docker,
        xdist_mssql_isolation_level="database",
        image="mcr.microsoft.com/mssql/server:2022-latest",
        name="mssql-2022",
        mssql_user="sa",
        mssql_password="Secret-password1",
        mssql_database="telemetry",
        host_port=21433,
        env={"MSSQL_AGENT_ENABLED": "true", "MSSQL_PID": "Standard"},
        mem_limit="4g",
        shm_size="512m",
        init_sql="ALTER DATABASE [telemetry] SET QUERY_STORE = ON;\nGO\nSELECT 1;",
    ) as svc:
        assert svc.port == 21433
        assert svc.exec_sql("SELECT 1") == (0, b"1\n")

    run_kwargs = mock_docker.run.call_args.kwargs
    assert run_kwargs["env"]["MSSQL_AGENT_ENABLED"] == "true"
    assert run_kwargs["env"]["MSSQL_PID"] == "Standard"
    assert run_kwargs["mem_limit"] == "4g"
    assert run_kwargs["shm_size"] == "512m"

    with pytest.raises(ValueError, match="exactly one"):
        exec_sqlcmd(mock_container)
    with pytest.raises(ValueError, match="exactly one"):
        exec_sqlcmd(mock_container, "SELECT 1", sql_file=script)
    with pytest.raises(ValueError, match="query_timeout"):
        exec_sqlcmd(mock_container, "SELECT 1", query_timeout=-1)
