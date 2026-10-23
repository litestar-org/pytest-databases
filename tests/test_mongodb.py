"""Tests for MongoDB container service fixtures."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.mongodb import (
    MongoDBService,
    mongodb_connection,
    mongodb_database,
)
from tests.conftest import run_recording_deprecations, unwrap_fixture


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


@pytest.mark.parametrize(
    ("fixture_def", "fixture_name", "expects_database"),
    [
        (mongodb_connection, "mongodb_connection", False),
        (mongodb_database, "mongodb_database", True),
    ],
)
def test_mongodb_deprecated_fixtures_warn_once_and_close_client(
    fixture_def: object,
    fixture_name: str,
    expects_database: bool,
) -> None:
    """Verify each deprecated MongoDB fixture warns once, opens its own client, and closes it."""
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
        pytest.warns(DeprecationWarning, match=fixture_name) as record,
    ):
        fixture_gen = unwrap_fixture(fixture_def)(service)
        assert next(fixture_gen) is (mock_db if expects_database else mock_client)
        with pytest.raises(StopIteration):
            next(fixture_gen)

    assert len(record) == 1
    assert record[0].filename == __file__
    mock_import.assert_called_once_with("pymongo")
    mock_pymongo.MongoClient.assert_called_once_with(
        host="127.0.0.1",
        port=27017,
        username="mongo_user",
        password="mongo_password",
    )
    mock_client.close.assert_called_once_with()
    if expects_database:
        mock_client.__getitem__.assert_called_once_with("pytest_db")


_FAKE_SERVICES = {
    "mongodb": """
from pytest_databases.docker.mongodb import MongoDBService

sys.modules["pymongo"] = MagicMock()

@pytest.fixture(scope="session")
def mongodb_service():
    return MongoDBService(
        container=MagicMock(), host="127.0.0.1", port=27017, username="u", password="p", database="d"
    )
""",
    "oracle": """
from pytest_databases.docker.oracle import OracleService

sys.modules["oracledb"] = MagicMock()

def _oracle():
    return OracleService(
        container=MagicMock(),
        host="127.0.0.1",
        port=1521,
        user="app",
        password="p",
        system_password="p",
        service_name="FREEPDB1",
    )

@pytest.fixture(scope="session")
def oracle_18c_service():
    return _oracle()

@pytest.fixture(scope="session")
def oracle_23ai_service():
    return _oracle()
""",
    "cockroachdb": """
from pytest_databases.docker.cockroachdb import CockroachDBService

sys.modules["psycopg"] = MagicMock()

@pytest.fixture(scope="session")
def cockroachdb_service():
    return CockroachDBService(container=MagicMock(), host="127.0.0.1", port=26257, database="d")
""",
    "spanner": """
from pytest_databases.docker.spanner import SpannerService

for name in ("google.cloud.spanner", "google.auth.credentials", "google.api_core.client_options"):
    sys.modules[name] = MagicMock()

@pytest.fixture(scope="session")
def spanner_service():
    return SpannerService(
        container=MagicMock(), host="127.0.0.1", port=9010, project="p", database_name="d", instance_name="i"
    )
""",
}


@pytest.mark.parametrize(
    ("provider", "fixture_name"),
    [
        ("mongodb", "mongodb_connection"),
        ("mongodb", "mongodb_database"),
        ("oracle", "oracle_18c_connection"),
        ("oracle", "oracle_23ai_connection"),
        ("oracle", "oracle_startup_connection"),
        ("cockroachdb", "cockroachdb_connection"),
        ("spanner", "spanner_connection"),
    ],
)
def test_deprecated_v019_fixtures_emit_exactly_one_warning(
    pytester: pytest.Pytester,
    provider: str,
    fixture_name: str,
) -> None:
    """Verify requesting a deprecated v0.19.0 fixture records exactly one DeprecationWarning naming it."""
    recorded = run_recording_deprecations(
        pytester,
        f"""
import sys
from unittest.mock import MagicMock

import pytest

pytest_plugins = ["pytest_databases.docker.{provider}"]
{_FAKE_SERVICES[provider]}

def test_fixture({fixture_name}):
    assert {fixture_name} is not None
""",
    )

    assert len(recorded) == 1, recorded
    assert f"'{fixture_name}'" in recorded[0]
    assert "v1.0.0" in recorded[0]


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
