"""Tests for MongoDB container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import APIError

from pytest_databases.docker import mongodb as mongodb_mod
from pytest_databases.docker.mongodb import (
    MongoDBService,
    exec_mongosh,
    mongodb_connection,
    mongodb_database,
    provide_mongodb_service,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import run_recording_deprecations, unwrap_fixture

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_databases.types import XdistIsolationLevel


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
def oracle_26ai_service():
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
        ("oracle", "oracle_23ai_image"),
        ("oracle", "oracle_23ai_service"),
        ("oracle", "oracle_23ai_service_name"),
        ("oracle", "oracle_26ai_connection"),
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


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        (None, "database", "mongodb", "pytest_db"),
        (1, "database", "mongodb", "pytest_db_1"),
        (2, "server", "mongodb_2", "pytest_db"),
    ],
)
def test_provide_mongodb_service_and_exec_mongosh(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_mongodb_service xdist modes, readiness check, and exec_mongosh error handling."""
    monkeypatch.setattr("pytest_databases.docker.mongodb.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr(mongodb_mod, "tcp_port_open", lambda *_args, **_kwargs: True)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    svc_container = ServiceContainer(host="127.0.0.1", port=27017, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    with provide_mongodb_service(
        docker_service=mock_docker,
        image="mongo:latest",
        name="mongodb",
        isolation_level=isolation_level,
    ) as service:
        assert service.database == expected_db

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True
    monkeypatch.setattr(mongodb_mod, "tcp_port_open", lambda *_args, **_kwargs: False)
    assert check(svc_container) is False

    code, _ = exec_mongosh(mock_container, "db.runCommand({ping: 1})", user="u", password="p", database="mydb")
    assert code == 0
    unauth_code, _ = exec_mongosh(mock_container, "db.runCommand({ping: 1})", database="mydb")
    assert unauth_code == 0
    unauth_args = mock_container.exec_run.call_args.args[0]
    assert "-u" not in unauth_args and "--authenticationDatabase" not in unauth_args

    with pytest.raises(ValueError, match="both 'user' and 'password'"):
        exec_mongosh(mock_container, "db.runCommand({ping: 1})", user="u")

    mock_container.exec_run.side_effect = APIError("boom")
    code_err, out_err = exec_mongosh(mock_container, "db.runCommand({ping: 1})", user="u", password="p")
    assert code_err == -1
    assert b"boom" in out_err


def test_mongodb_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Exercise all MongoDB session fixtures in-process with a mocked provide_mongodb_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import mongodb as mongo_mod
    from pytest_databases.docker.mongodb import MongoDBService

    pytest_plugins = ["pytest_databases.docker.mongodb"]

    @pytest.fixture(scope="session")
    def docker_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(*args, **kwargs):
        yield MongoDBService(
            host="127.0.0.1",
            port=27017,
            container=MagicMock(),
            username="u",
            password="p",
            database="default_db",
        )

    def test_all(request):
        with patch.object(mongo_mod, "provide_mongodb_service", _fake_provide):
            for name in (
                "xdist_mongodb_isolation_level",
                "mongodb_image",
                "mongodb_username",
                "mongodb_password",
                "mongodb_database_name",
                "mongodb_service",
            ):
                assert request.getfixturevalue(name) is not None
            assert request.getfixturevalue("mongodb_port") is None
            assert request.getfixturevalue("mongodb_replica_set") is None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("host", "username", "password", "database", "replica_set", "expected_uri"),
    [
        (
            "127.0.0.1",
            "admin@org",
            "p:a/s#s",
            "app_db",
            None,
            "mongodb://admin%40org:p%3Aa%2Fs%23s@127.0.0.1:27017/app_db?authSource=admin",
        ),
        (
            "127.0.0.1",
            None,
            None,
            "open_db",
            None,
            "mongodb://127.0.0.1:27017/open_db",
        ),
        (
            "::1",
            "mongo_user",
            "mongo_password",
            "rs_db",
            "rs0",
            "mongodb://mongo_user:mongo_password@[::1]:27017/rs_db?authSource=admin&replicaSet=rs0&directConnection=true",
        ),
    ],
)
def test_mongodb_service_uri_formatting(
    host: str,
    username: str | None,
    password: str | None,
    database: str,
    replica_set: str | None,
    expected_uri: str,
) -> None:
    """Verify MongoDBService.uri encodes credentials, IPv6 brackets, unauthenticated mode, and replicaSet params."""
    svc = MongoDBService(
        host=host,
        port=27017,
        container=MagicMock(),
        username=username,
        password=password,
        database=database,
        replica_set=replica_set,
    )
    assert svc.uri == expected_uri


@pytest.mark.parametrize("authenticated", [True, False])
def test_provide_mongodb_service_replica_set_keyfile_init_js_and_profiling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    authenticated: bool,
) -> None:
    """Verify replica_set + keyfile bootstrap, custom flags, init_js once-per-db, and set_profiling_level."""
    monkeypatch.setattr(mongodb_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(mongodb_mod, "tcp_port_open", lambda *_args, **_kwargs: True)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(mongodb_mod.tempfile, "tempdir", str(tmp_path))

    evals: list[list[str]] = []
    mock_container = MagicMock()
    mock_container.id = f"mongocid_{authenticated}"

    def _exec(cmd: list[str]) -> MagicMock:
        evals.append(cmd)
        script = cmd[-1]
        if "isWritablePrimary" in script:
            return MagicMock(exit_code=0, output=b"true\n")
        return MagicMock(exit_code=0, output=b"ok\n1\n")

    mock_container.exec_run.side_effect = _exec
    mock_docker = MagicMock()
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=37017,
        container=mock_container,
    )

    js_file = tmp_path / "seed.js"
    js_file.write_text("db.metrics.insertOne({seeded: true});", encoding="utf-8")

    with provide_mongodb_service(
        docker_service=mock_docker,
        image="mongo:7",
        name="mongodb",
        isolation_level="database",
        username="admin_u" if authenticated else None,
        password="secret" if authenticated else "ignored",
        database="analytics",
        host_port=37017,
        replica_set="rs0",
        command=["--oplogSize", "64"],
        env={"CUSTOM_MONGO_ENV": "1"},
        init_js=[js_file, "db.metrics.createIndex({seeded: 1});"],
        profiling_level=2,
        slow_ms=25,
    ) as svc:
        assert svc.replica_set == "rs0"
        assert svc.port == 37017
        assert ("replicaSet=rs0&directConnection=true" in svc.uri) is True
        assert (svc.username is not None) is authenticated

    run_kwargs = mock_docker.run.call_args.kwargs
    assert run_kwargs["host_port"] == 37017
    assert run_kwargs["env"]["CUSTOM_MONGO_ENV"] == "1"
    if authenticated:
        assert run_kwargs["entrypoint"] == ["/bin/sh", "-c"]
        assert "--keyFile /data/configdb/ptdb-keyfile" in run_kwargs["command"][0]
        assert "--replSet rs0" in run_kwargs["command"][0]
        assert "--oplogSize 64" in run_kwargs["command"][0]
        assert "PTDB_MONGO_KEYFILE_SECRET" in run_kwargs["env"]
    else:
        assert "entrypoint" not in run_kwargs
        assert run_kwargs["command"] == ["mongod", "--replSet", "rs0", "--bind_ip_all", "--oplogSize", "64"]
        assert "MONGO_INITDB_ROOT_USERNAME" not in run_kwargs["env"]

    joined_scripts = "\n".join(cmd[-1] for cmd in evals)
    assert 'rs.initiate({"_id": "rs0", "members": [{"_id": 0, "host": "localhost:27017"}]})' in joined_scripts
    assert "db.metrics.insertOne({seeded: true});" in joined_scripts
    assert "db.setProfilingLevel(2, { slowms: 25 })" in joined_scripts


@pytest.mark.parametrize(
    ("kwargs", "pattern"),
    [
        ({"username": ""}, "non-empty or None"),
        ({"username": "u", "password": None}, "password must not be None"),
        ({"replica_set": "bad space;rm"}, "Invalid MongoDB replica_set"),
        ({"database": ""}, "database name must be non-empty"),
    ],
)
def test_provide_mongodb_service_validation_errors(kwargs: dict[str, Any], pattern: str) -> None:
    """Verify provide_mongodb_service rejects invalid credential, database, and replica_set inputs."""
    mock_docker = MagicMock()
    with (
        pytest.raises(ValueError, match=pattern),
        provide_mongodb_service(mock_docker, "mongo:latest", "mongodb", "database", **kwargs),
    ):
        pass
    mock_docker.run.assert_not_called()


@pytest.mark.parametrize(
    ("level", "slow_ms", "pattern"),
    [
        (3, None, "must be 0, 1, or 2"),
        (True, None, "must be 0, 1, or 2"),
        (1, -5, "slow_ms must be >= 0"),
    ],
)
def test_mongodb_set_profiling_level_validation(level: Any, slow_ms: int | None, pattern: str) -> None:
    """Verify MongoDBService.set_profiling_level rejects invalid levels and negative slow_ms values."""
    svc = MongoDBService(host="127.0.0.1", port=27017, container=MagicMock())
    with pytest.raises(ValueError, match=pattern):
        svc.set_profiling_level(level, slow_ms=slow_ms)
