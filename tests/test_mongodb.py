"""Tests for MongoDB container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.mongodb import (
    MongoDBService,
    mongodb_connection,
    mongodb_database,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def test_plugin_imports_without_pymongo(pytester: pytest.Pytester) -> None:
    """Verify mongodb plugin imports cleanly without pymongo installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pymongo" or name.startswith("pymongo."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.mongodb
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_mongodb_deprecated_connection_and_database_shims() -> None:
    """Verify mongodb_connection and mongodb_database emit DeprecationWarning and lazily load pymongo."""
    mock_pymongo = MagicMock()
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_pymongo.MongoClient.return_value = mock_client
    service = MongoDBService(
        host="127.0.0.1",
        port=27017,
        container=MagicMock(),
        username="mongo_user",
        password="mongo_password",
        database="pytest_db",
    )

    with (
        patch("importlib.import_module", return_value=mock_pymongo) as mock_import,
        pytest.deprecated_call(match="mongodb_connection"),
    ):
        conn_gen = _unwrap_fixture(mongodb_connection)(service)
        client = next(conn_gen)
        assert client is mock_client
        with pytest.raises(StopIteration):
            next(conn_gen)

    mock_import.assert_called_once_with("pymongo")
    mock_client.close.assert_called_once_with()

    with pytest.deprecated_call(match="mongodb_database"):
        db_gen = _unwrap_fixture(mongodb_database)(mock_client, service)
        db = next(db_gen)
        assert db is mock_db
        with pytest.raises(StopIteration):
            next(db_gen)


@pytest.fixture(scope="module")
def mongodb_test_helpers() -> str:
    """Return shared mongosh test helper code.

    Returns:
        Helper Python source code string.
    """
    return """
    def run_mongosh(service, eval_script, database=None):
        cmd = [
            "mongosh",
            "--quiet",
            "--host",
            "localhost",
            "--port",
            "27017",
            "-u",
            service.username,
            "-p",
            service.password,
            "--authenticationDatabase",
            "admin",
        ]
        if database is not None:
            cmd.append(database)
        cmd.extend(["--eval", eval_script])
        result = service.container.exec_run(cmd)
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return [line.strip() for line in result.output.decode().splitlines() if line.strip()]
    """


def test_service_fixture(pytester: pytest.Pytester, mongodb_test_helpers: str) -> None:
    """Verify mongodb_service starts and executes commands via mongosh."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mongodb"]

    {mongodb_test_helpers}

    def test(mongodb_service):
        output = run_mongosh(mongodb_service, "print(db.adminCommand('ping').ok)")
        assert output[-1] == "1"

        insert_script = (
            "db.getSiblingDB('" + mongodb_service.database + "').test_collection.insertOne({{a: 1}}); "
            "printjson(db.getSiblingDB('" + mongodb_service.database + "').test_collection.findOne({{a: 1}}))"
        )
        result = run_mongosh(mongodb_service, insert_script)
        joined = "".join(result)
        assert "a: 1" in joined
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester, mongodb_test_helpers: str) -> None:
    """Verify mongodb_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mongodb"]

    {mongodb_test_helpers}

    def test_1(mongodb_service):
        run_mongosh(
            mongodb_service,
            "db.test_collection.insertOne({{key: 'value1'}})",
            database=mongodb_service.database,
        )
        result = run_mongosh(
            mongodb_service,
            "printjson(db.test_collection.findOne({{key: 'value1'}}))",
            database=mongodb_service.database,
        )
        joined = "".join(result)
        assert "value1" in joined

    def test_2(mongodb_service):
        run_mongosh(
            mongodb_service,
            "db.test_collection.insertOne({{key: 'value2'}})",
            database=mongodb_service.database,
        )
        result = run_mongosh(
            mongodb_service,
            "printjson(db.test_collection.findOne({{key: 'value2'}}))",
            database=mongodb_service.database,
        )
        joined = "".join(result)
        assert "value2" in joined
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester, mongodb_test_helpers: str) -> None:
    """Verify mongodb_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile(f"""
    import pytest

    pytest_plugins = ["pytest_databases.docker.mongodb"]

    @pytest.fixture(scope="session")
    def xdist_mongodb_isolation_level():
        return "server"

    {mongodb_test_helpers}

    def test_1(mongodb_service):
        run_mongosh(
            mongodb_service,
            "db.collection_one.insertOne({{key: 'server1'}})",
            database=mongodb_service.database,
        )
        result = run_mongosh(
            mongodb_service,
            "print(db.collection_one.countDocuments({{}}))",
            database=mongodb_service.database,
        )
        assert result[-1] == "1"

    def test_2(mongodb_service):
        run_mongosh(
            mongodb_service,
            "db.collection_two.insertOne({{key: 'server2'}})",
            database=mongodb_service.database,
        )
        result = run_mongosh(
            mongodb_service,
            "print(db.collection_two.countDocuments({{}}))",
            database=mongodb_service.database,
        )
        assert result[-1] == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


def _unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__
