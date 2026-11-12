"""Tests for Hardcharger container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import NotFound

from pytest_databases.docker.hardcharger import (
    HARDCHARGER_PORT,
    HardchargerService,
    exec_hardcharger,
    provide_hardcharger_service,
)

if TYPE_CHECKING:
    from pytest import Pytester

    from pytest_databases.types import XdistIsolationLevel


def test_plugin_imports_without_adbc_driver_hardcharger(pytester: Pytester) -> None:
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "adbc_driver_hardcharger" or name.startswith("adbc_driver_hardcharger."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.hardcharger
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_hardcharger_service_properties_and_exec() -> None:
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"answer\n1\n")
    service = HardchargerService(
        host="127.0.0.1",
        port=41337,
        container=container,
        username="hardcharger_username",
        password="hardcharger_password",
    )
    assert service.uri == "hardcharger://127.0.0.1:41337?tls=false"
    assert service.connection_kwargs == {
        "username": "hardcharger_username",
        "password": "hardcharger_password",
    }
    code, out = exec_hardcharger(
        container=container,
        sql="SELECT 1 AS answer",
        user="hardcharger_username",
        password="hardcharger_password",
    )
    assert code == 0
    assert out == b"answer\n1\n"
    command = container.exec_run.call_args.args[0]
    assert command[0] == "hardcharger"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == str(HARDCHARGER_PORT)
    assert command[command.index("--username") + 1] == "hardcharger_username"
    assert command[command.index("--command") + 1] == "SELECT 1 AS answer"
    assert "--no-tls" in command
    assert "hardcharger_password" not in command
    assert container.exec_run.call_args.kwargs["environment"] == {"HARDCHARGER_PASSWORD": "hardcharger_password"}


def test_exec_hardcharger_reports_a_command_that_could_not_start() -> None:
    container = MagicMock()
    container.exec_run.side_effect = NotFound("No such container: gone")
    code, out = exec_hardcharger(container=container, sql="SELECT 1", user="u", password="p")
    assert code == -1
    assert b"No such container: gone" in out

    container.exec_run.side_effect = None
    container.exec_run.return_value = MagicMock(exit_code=None, output=b"")
    code, out = exec_hardcharger(container=container, sql="SELECT 1", user="u", password="p")
    assert code == -1
    assert out == b""


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name"),
    [
        pytest.param(None, "database", "hardcharger", id="no-xdist"),
        pytest.param(0, "database", "hardcharger_0", id="database-gw0"),
        pytest.param(3, "database", "hardcharger_3", id="database-gw3"),
        pytest.param(3, "server", "hardcharger_3", id="server-gw3"),
    ],
)
def test_provide_hardcharger_service_container_per_worker(
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    expected_name: str,
) -> None:
    container = MagicMock()
    docker_service = MagicMock()
    docker_service.run.return_value.__enter__.return_value = MagicMock(
        host="127.0.0.1",
        port=41337,
        container=container,
    )
    with (
        patch("pytest_databases.docker.hardcharger.get_xdist_worker_num", return_value=worker_num),
        provide_hardcharger_service(
            docker_service=docker_service,
            isolation_level=isolation_level,
            image="ghcr.io/gizmodata/hardcharger:latest",
            username="u",
            password="p",
        ) as svc,
    ):
        assert svc.container is container
        assert svc.port == 41337
        assert svc.username == "u"
        assert svc.password == "p"
    run_kwargs = docker_service.run.call_args.kwargs
    assert run_kwargs["name"] == expected_name
    assert run_kwargs["image"] == "ghcr.io/gizmodata/hardcharger:latest"
    assert run_kwargs["container_port"] == HARDCHARGER_PORT
    assert run_kwargs["env"] == {"HARDCHARGER_ADMIN_USERNAME": "u", "HARDCHARGER_ADMIN_PASSWORD": "p"}
    assert run_kwargs["transient"] is (isolation_level == "server")


@pytest.mark.parametrize(
    ("exit_code", "output", "port_open", "expected"),
    [
        pytest.param(0, b"probe\n4242\n", True, True, id="exact-value"),
        pytest.param(0, b"probe\r\n4242\r\n", True, True, id="crlf"),
        pytest.param(0, b"probe\n4242\n", False, False, id="published-port-closed"),
        pytest.param(0, b"Connected to 127.0.0.1:31337\n", True, False, id="banner-only"),
        pytest.param(0, b"probe\n42420\n", True, False, id="partial-value"),
        pytest.param(1, b"probe\n4242\n", True, False, id="non-zero-exit"),
    ],
)
def test_provide_hardcharger_service_readiness_matches_exact_value(
    exit_code: int, output: bytes, port_open: bool, expected: bool
) -> None:
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=exit_code, output=output)
    docker_service = MagicMock()
    docker_service.run.return_value.__enter__.return_value = MagicMock(
        host="127.0.0.1",
        port=41337,
        container=container,
    )
    with (
        patch("pytest_databases.docker.hardcharger.tcp_port_open", return_value=port_open) as tcp_port_open,
        provide_hardcharger_service(
            docker_service=docker_service,
            isolation_level="database",
            image="ghcr.io/gizmodata/hardcharger:latest",
            username="u",
            password="p",
        ) as svc,
    ):
        assert docker_service.run.call_args.kwargs["check"](svc) is expected
    command = container.exec_run.call_args.args[0]
    assert command[command.index("--command") + 1] == "SELECT 4242 AS probe"
    if exit_code == 0 and b"4242" in output.split():
        tcp_port_open.assert_called_once_with(host="127.0.0.1", port=41337)
    else:
        tcp_port_open.assert_not_called()


HARDCHARGER_TEST_HELPERS = """
import json

from pytest_databases.docker.hardcharger import exec_hardcharger
from pytest_databases.helpers import http_request


def run_hardcharger(service, sql):
    exit_code, output = exec_hardcharger(
        container=service.container,
        sql=sql,
        user=service.username,
        password=service.password,
    )
    decoded = output.decode(errors="replace").strip()
    assert exit_code == 0, decoded
    return decoded.splitlines()


def chargewire_post(service, path, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    status, payload = http_request(
        url=f"http://{service.host}:{service.port}/chargewire/v1{path}",
        method="POST",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    return status, json.loads(payload)


def chargewire_sign_in(service, password):
    return chargewire_post(
        service,
        "/auth/token",
        {"grant_type": "password", "username": service.username, "password": password},
    )
"""


def test_service_fixture(pytester: Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.hardcharger import HardchargerService

pytest_plugins = ["pytest_databases.docker.hardcharger"]

{HARDCHARGER_TEST_HELPERS}

def test(hardcharger_service: HardchargerService) -> None:
    assert run_hardcharger(hardcharger_service, "SELECT 4242 AS answer") == ["answer", "4242"]
    assert hardcharger_service.uri == f"hardcharger://{{hardcharger_service.host}}:{{hardcharger_service.port}}?tls=false"
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_service_ddl_dml(pytester: Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.hardcharger import HardchargerService

pytest_plugins = ["pytest_databases.docker.hardcharger"]

{HARDCHARGER_TEST_HELPERS}

def test(hardcharger_service: HardchargerService) -> None:
    \"\"\"Verify tables created by one client invocation are visible to the next.\"\"\"
    run_hardcharger(
        hardcharger_service,
        "CREATE OR REPLACE TABLE test_table (id INTEGER, name VARCHAR); INSERT INTO test_table VALUES (1, 'test');",
    )
    assert run_hardcharger(hardcharger_service, "SELECT id, name FROM test_table") == ["id,name", "1,test"]
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_service_published_port_speaks_chargewire(pytester: Pytester) -> None:
    """The host and port the fixture reports accept the fixture's credentials, and only those."""
    pytester.makepyfile(f"""
from pytest_databases.docker.hardcharger import HardchargerService

pytest_plugins = ["pytest_databases.docker.hardcharger"]

{HARDCHARGER_TEST_HELPERS}

def test_sign_in_and_query(hardcharger_service: HardchargerService) -> None:
    status, token = chargewire_sign_in(hardcharger_service, hardcharger_service.password)
    assert status == 200, token
    status, session = chargewire_post(hardcharger_service, "/sessions", {{}}, token["access_token"])
    assert status == 201, session
    status, statement = chargewire_post(
        hardcharger_service,
        f"/sessions/{{session['session_id']}}/statements",
        {{"sql": "SELECT 4242 AS probe"}},
        token["access_token"],
    )
    assert status == 201, statement
    assert statement["state"] == "succeeded"
    assert [partition["rows"] for partition in statement["result"]["partitions"]] == [1]


def test_wrong_password_is_refused(hardcharger_service: HardchargerService) -> None:
    status, error = chargewire_sign_in(hardcharger_service, hardcharger_service.password + "-wrong")
    assert status == 401, error
    assert "invalid_credentials" in str(error)
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    "isolation_override",
    [
        pytest.param("", id="default-isolation"),
        pytest.param(
            """
@pytest.fixture(scope="session")
def xdist_hardcharger_isolation_level():
    return "server"
""",
            id="server-isolation",
        ),
    ],
)
def test_xdist_container_per_worker(pytester: Pytester, isolation_override: str) -> None:
    """Each xdist worker gets its own container, whatever the isolation level."""
    pytester.makepyfile(f"""
import os

import pytest
from pytest_databases.docker.hardcharger import HardchargerService

pytest_plugins = ["pytest_databases.docker.hardcharger"]

{isolation_override}
{HARDCHARGER_TEST_HELPERS}

def assert_worker_container(service: HardchargerService) -> None:
    worker_num = int(os.environ["PYTEST_XDIST_WORKER"].removeprefix("gw"))
    assert f"hardcharger_{{worker_num}}_" in service.container.name
    assert run_hardcharger(service, "SELECT 4242 AS answer") == ["answer", "4242"]


def test_one(hardcharger_service: HardchargerService) -> None:
    assert_worker_container(hardcharger_service)


def test_two(hardcharger_service: HardchargerService) -> None:
    assert_worker_container(hardcharger_service)
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_custom_credentials(pytester: Pytester) -> None:
    """Overriding the user name and password fixtures changes the administrator the server starts with."""
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.hardcharger import HardchargerService

pytest_plugins = ["pytest_databases.docker.hardcharger"]

{HARDCHARGER_TEST_HELPERS}

@pytest.fixture(scope="session")
def hardcharger_username():
    return "custom_admin"


@pytest.fixture(scope="session")
def hardcharger_password():
    return "custom-password"


def test(hardcharger_service: HardchargerService) -> None:
    assert hardcharger_service.username == "custom_admin"
    assert hardcharger_service.password == "custom-password"
    assert hardcharger_service.connection_kwargs == {{"username": "custom_admin", "password": "custom-password"}}
    status, token = chargewire_sign_in(hardcharger_service, "custom-password")
    assert status == 200, token
    status, error = chargewire_sign_in(hardcharger_service, "hardcharger_password")
    assert status == 401, error
    assert "invalid_credentials" in str(error)
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_hardcharger_all_fixtures_inprocess(pytester: Pytester) -> None:
    """Verify Hardcharger config and service fixtures execute in-process with mocked provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest

    pytest_plugins = ["pytest_databases.docker.hardcharger"]

    @pytest.fixture(scope="session")
    def docker_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_svc = MagicMock()

        @contextmanager
        def fake_svc(*args, **kwargs):
            yield mock_svc

        with patch(
            "pytest_databases.docker.hardcharger.provide_hardcharger_service", side_effect=fake_svc
        ) as provide:
            assert request.getfixturevalue("xdist_hardcharger_isolation_level") == "database"
            assert request.getfixturevalue("hardcharger_image") == "ghcr.io/gizmodata/hardcharger:latest"
            assert request.getfixturevalue("hardcharger_username") == "hardcharger_username"
            assert request.getfixturevalue("hardcharger_password") == "hardcharger_password"
            assert request.getfixturevalue("hardcharger_service") is mock_svc
        assert provide.call_args.kwargs["isolation_level"] == "database"
        assert provide.call_args.kwargs["image"] == "ghcr.io/gizmodata/hardcharger:latest"
        assert provide.call_args.kwargs["username"] == "hardcharger_username"
        assert provide.call_args.kwargs["password"] == "hardcharger_password"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
