"""Tests for Doltgres container service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, NotFound

from pytest_databases.docker.doltgres import (
    DOLTGRES_DATABASE,
    DOLTGRES_IMAGE,
    DOLTGRES_PASSWORD,
    DOLTGRES_ROOT_USER,
    DOLTGRES_USER,
    DoltgresService,
    _ensure_doltgres_database,
    _ensure_doltgres_user,
    _prepare_doltgres_database,
    exec_doltgres_psql,
    provide_doltgres_service,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator


def test_plugin_imports_without_psycopg(pytester: pytest.Pytester) -> None:
    """Verify pytest_databases.docker.doltgres imports without psycopg installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "psycopg" or name.startswith("psycopg."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.doltgres
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_doltgres_unit_helpers_and_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify DoltgresService, exec_doltgres_psql, user/db provisioning, and retry exhaustion."""
    monkeypatch.setattr("pytest_databases.docker.doltgres.time.sleep", lambda _s: None)
    container = MagicMock()
    service = DoltgresService(
        host="127.0.0.1",
        port=5432,
        container=container,
        database="mydb",
        user="doltgres",
        password="secret",
    )
    assert service.db == "mydb"

    container.exec_run.side_effect = APIError("boom")
    code, out = exec_doltgres_psql(container, "SELECT 1", password="secret")
    assert code == -1
    assert b"boom" in out

    container.exec_run.side_effect = None
    assert _ensure_doltgres_user(container, user=DOLTGRES_ROOT_USER, password="p", root_password="p") == (True, b"")

    container.exec_run.side_effect = [
        MagicMock(exit_code=1, output=b"fatal"),
    ]
    ok, err = _ensure_doltgres_user(container, user="app", password="p", root_password="p")
    assert ok is False
    assert err == b"fatal"

    container.exec_run.side_effect = [
        MagicMock(exit_code=1, output=b"already exists"),
        MagicMock(exit_code=1, output=b"alter failed"),
    ]
    ok, err = _ensure_doltgres_user(container, user="app", password="p", root_password="p")
    assert ok is False
    assert err == b"alter failed"

    container.exec_run.side_effect = [
        MagicMock(exit_code=1, output=b"db create failed"),
    ]
    ok, err = _ensure_doltgres_database(container, database="db", user="app", root_password="p")
    assert ok is False
    assert err == b"db create failed"

    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b""),
        MagicMock(exit_code=1, output=b"grant failed"),
    ]
    ok, err = _ensure_doltgres_database(container, database="db", user="app", root_password="p")
    assert ok is False
    assert err == b"grant failed"

    container.exec_run.side_effect = None
    container.exec_run.return_value = MagicMock(exit_code=1, output=b"not ready")
    with pytest.raises(RuntimeError, match="after 10 attempts"):
        _prepare_doltgres_database(
            container,
            container_name="doltgres",
            database="db",
            user="app",
            password="p",
            root_password="p",
        )


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        (None, "database", "doltgres", DOLTGRES_DATABASE),
        (1, "database", "doltgres", f"{DOLTGRES_DATABASE}_1"),
        (2, "server", "doltgres_2", DOLTGRES_DATABASE),
    ],
)
def test_provide_doltgres_service_modes_and_check(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_doltgres_service check callback and xdist isolation modes."""
    monkeypatch.setattr("pytest_databases.docker.doltgres.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.doltgres.tcp_port_open", lambda _h, _p: True)

    docker_service = MagicMock()
    container = MagicMock()

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        assert kwargs["name"] == expected_name
        check = kwargs["check"]
        assert callable(check)
        sc = ServiceContainer(host="127.0.0.1", port=15432, container=container)

        container.exec_run.side_effect = NotFound("missing")
        assert check(sc) is False

        container.exec_run.side_effect = [MagicMock(exit_code=1, output=b"")]
        assert check(sc) is False

        container.exec_run.side_effect = [
            MagicMock(exit_code=0, output=b""),
            MagicMock(exit_code=0, output=b"1\n"),
            MagicMock(exit_code=0, output=b""),
            MagicMock(exit_code=0, output=b""),
            MagicMock(exit_code=0, output=b""),
            MagicMock(exit_code=0, output=b""),
            MagicMock(exit_code=0, output=b"1\n"),
        ]
        assert check(sc) is True
        yield sc

    docker_service.run.side_effect = fake_run

    with provide_doltgres_service(
        docker_service,
        image=DOLTGRES_IMAGE,
        name="doltgres",
        isolation_level=isolation_level,  # type: ignore[arg-type]
        user=DOLTGRES_USER,
        password=DOLTGRES_PASSWORD,
        root_password=DOLTGRES_PASSWORD,
        database=DOLTGRES_DATABASE,
        port=15432,
    ) as service:
        assert service.database == expected_db
        assert service.user == DOLTGRES_USER
        assert service.port == 15432


def test_doltgres_fixtures_inprocess(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise all doltgres session fixtures in-process with a mocked provide_doltgres_service."""
    monkeypatch.setenv("DOLTGRES_PORT", "25432")
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker.doltgres import DoltgresService

    pytest_plugins = ["pytest_databases.docker.doltgres"]

    @pytest.fixture(scope="session")
    def docker_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(*args, **kwargs):
        yield DoltgresService(
            host="127.0.0.1",
            port=kwargs["port"] or 5432,
            container=MagicMock(),
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
        )

    def test_fixtures(
        request,
        xdist_doltgres_isolation_level,
        doltgres_image,
        doltgres_user,
        doltgres_password,
        doltgres_root_password,
        doltgres_database,
        doltgres_port,
    ):
        assert xdist_doltgres_isolation_level == "database"
        assert "doltgresql" in doltgres_image
        assert doltgres_user == "doltgres"
        assert doltgres_password == "super-secret"
        assert doltgres_root_password == "super-secret"
        assert doltgres_database == "pytest_databases"
        assert doltgres_port == 25432
        with patch("pytest_databases.docker.doltgres.provide_doltgres_service", _fake_provide):
            svc = request.getfixturevalue("doltgres_service")
            assert svc.port == 25432
            assert svc.db == "pytest_databases"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_service_fixture(pytester: pytest.Pytester) -> None:
    """Verify doltgres_service starts a live Doltgres container and executes SQL queries."""
    pytester.makepyfile("""
    from pytest_databases.docker.doltgres import DoltgresService, exec_doltgres_psql

    pytest_plugins = ["pytest_databases.docker.doltgres"]

    def test(doltgres_service: DoltgresService) -> None:
        code, output = exec_doltgres_psql(
            doltgres_service.container,
            "SELECT 1",
            user=doltgres_service.user,
            password=doltgres_service.password,
            database=doltgres_service.database,
        )
        assert code == 0, output.decode(errors="replace")
        assert output.decode().strip() == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify doltgres_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    from pytest_databases.docker.doltgres import DoltgresService, exec_doltgres_psql

    pytest_plugins = ["pytest_databases.docker.doltgres"]

    def run_sql(service: DoltgresService, sql: str) -> None:
        code, output = exec_doltgres_psql(
            service.container,
            sql,
            user=service.user,
            password=service.password,
            database=service.database,
        )
        assert code == 0, output.decode(errors="replace")

    def test_1(doltgres_service: DoltgresService) -> None:
        run_sql(doltgres_service, "CREATE TABLE simple_table (id INT PRIMARY KEY, val INT)")

    def test_2(doltgres_service: DoltgresService) -> None:
        run_sql(doltgres_service, "CREATE TABLE simple_table (id INT PRIMARY KEY, val INT)")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify doltgres_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest
    from pytest_databases.docker.doltgres import DoltgresService, exec_doltgres_psql

    pytest_plugins = ["pytest_databases.docker.doltgres"]

    @pytest.fixture(scope="session")
    def xdist_doltgres_isolation_level():
        return "server"

    def run_sql(service: DoltgresService, sql: str) -> None:
        code, output = exec_doltgres_psql(
            service.container,
            sql,
            user=service.user,
            password=service.password,
            database=service.database,
        )
        assert code == 0, output.decode(errors="replace")

    def test_1(doltgres_service: DoltgresService) -> None:
        run_sql(doltgres_service, "CREATE DATABASE db_test")

    def test_2(doltgres_service: DoltgresService) -> None:
        run_sql(doltgres_service, "CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
