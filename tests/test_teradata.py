"""Unit and pytester tests for clientless Teradata Vantage service fixtures."""

from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

import pytest_databases.docker.teradata as teradata_mod
from pytest_databases.docker.teradata import (
    DEFAULT_TERADATA_PASSWORD,
    DEFAULT_TERADATA_STARTUP_TIMEOUT,
    DEFAULT_TERADATA_USER,
    TERADATA_PORT,
    ExternalTeradataService,
    TeradataService,
    _is_teradata_ready,
    provide_external_teradata_service,
    provide_teradata_service,
    teradata_database,
    teradata_encryptdata,
    teradata_external_host,
    teradata_external_port,
    teradata_image,
    teradata_logdata,
    teradata_logmech,
    teradata_password,
    teradata_port,
    teradata_startup_timeout,
    teradata_tmode,
    teradata_user,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases.types import XdistIsolationLevel


def _unwrap_fixture(fixture_func: Any) -> Any:
    """Return the underlying callable wrapped by a ``@pytest.fixture`` decorator."""
    return getattr(fixture_func, "__wrapped__", fixture_func)


def test_plugin_imports_without_teradata_clients(pytester: pytest.Pytester) -> None:
    """Verify ``pytest_databases.docker.teradata`` imports cleanly without Teradata drivers installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if (
                name == "teradatasql"
                or name.startswith("teradatasql.")
                or name == "adbc_driver_manager"
                or name.startswith("adbc_driver_manager.")
            ):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.teradata
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_teradata_all_fixtures_inprocess(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify all default Teradata fixtures resolve and delegate through public providers."""
    monkeypatch.setenv("TERADATA_IMAGE", "example/teradata:20.00")
    monkeypatch.setenv("TERADATA_EXTERNAL_HOST", "td-vm.internal")
    monkeypatch.delenv("TERADATA_PORT", raising=False)
    monkeypatch.delenv("TERADATA_EXTERNAL_PORT", raising=False)
    monkeypatch.delenv("TERADATA_USER", raising=False)
    monkeypatch.delenv("TERADATA_PASSWORD", raising=False)
    monkeypatch.delenv("TERADATA_DATABASE", raising=False)
    monkeypatch.delenv("TERADATA_LOGMECH", raising=False)
    monkeypatch.delenv("TERADATA_LOGDATA", raising=False)
    monkeypatch.delenv("TERADATA_SSLMODE", raising=False)
    monkeypatch.delenv("TERADATA_ENCRYPTDATA", raising=False)
    monkeypatch.delenv("TERADATA_TMODE", raising=False)
    monkeypatch.delenv("TERADATA_STARTUP_TIMEOUT", raising=False)

    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest

    pytest_plugins = ["pytest_databases.docker.teradata"]

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_container_svc = MagicMock()
        mock_external_svc = MagicMock()

        @contextmanager
        def fake_container_provider(*args, **kwargs):
            yield mock_container_svc

        @contextmanager
        def fake_external_provider(*args, **kwargs):
            yield mock_external_svc

        assert request.getfixturevalue("xdist_teradata_isolation_level") == "server"
        assert request.getfixturevalue("teradata_image") == "example/teradata:20.00"
        assert request.getfixturevalue("teradata_external_host") == "td-vm.internal"
        assert request.getfixturevalue("teradata_external_port") is None
        assert request.getfixturevalue("teradata_port") is None
        assert request.getfixturevalue("teradata_user") == "dbc"
        assert request.getfixturevalue("teradata_password") == "dbc"
        assert request.getfixturevalue("teradata_database") is None
        assert request.getfixturevalue("teradata_logmech") is None
        assert request.getfixturevalue("teradata_logdata") is None
        assert request.getfixturevalue("teradata_sslmode") is None
        assert request.getfixturevalue("teradata_encryptdata") is None
        assert request.getfixturevalue("teradata_tmode") is None
        assert request.getfixturevalue("teradata_startup_timeout") == 300.0
        assert request.getfixturevalue("teradata_service_environment") == {}

        with (
            patch("pytest_databases.docker.teradata.provide_teradata_service", side_effect=fake_container_provider),
            patch("pytest_databases.docker.teradata.provide_external_teradata_service", side_effect=fake_external_provider),
        ):
            assert request.getfixturevalue("teradata_service") is mock_container_svc
            assert request.getfixturevalue("teradata_external_service") is mock_external_svc
    """)

    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("fixture_name", "cleared_vars"),
    [
        pytest.param("teradata_service", ("TERADATA_IMAGE", "TERADATA_TEST_IMAGE"), id="container-service"),
        pytest.param("teradata_external_service", ("TERADATA_EXTERNAL_HOST", "TERADATA_HOST"), id="external-service"),
    ],
)
def test_teradata_services_skip_when_unconfigured(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    cleared_vars: tuple[str, ...],
) -> None:
    """Verify both Teradata service fixtures skip cleanly when neither image nor host is configured."""
    for env_var in cleared_vars:
        monkeypatch.delenv(env_var, raising=False)

    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.teradata"]

    def test_skipped({fixture_name}) -> None:
        pytest.fail("Fixture should have skipped when configuration env vars are unset")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-rs")
    result.assert_outcomes(skipped=1)


@pytest.mark.parametrize(
    ("service_factory", "optional_kwargs", "expected_optional"),
    [
        pytest.param(
            lambda **kwargs: TeradataService(container=MagicMock(), host="127.0.0.1", port=1025, **kwargs),
            {},
            {},
            id="container-defaults",
        ),
        pytest.param(
            lambda **kwargs: TeradataService(container=MagicMock(), host="127.0.0.1", port=31025, **kwargs),
            {
                "database": "analytics",
                "logmech": "TD2",
                "logdata": "token",
                "sslmode": "REQUIRE",
                "encryptdata": "true",
                "tmode": "ANSI",
            },
            {
                "database": "analytics",
                "logmech": "TD2",
                "logdata": "token",
                "sslmode": "REQUIRE",
                "encryptdata": "true",
                "tmode": "ANSI",
            },
            id="container-full-options",
        ),
        pytest.param(
            lambda **kwargs: ExternalTeradataService(host="td-vm.local", port=1025, **kwargs),
            {},
            {},
            id="external-defaults",
        ),
        pytest.param(
            lambda **kwargs: ExternalTeradataService(host="td-vm.local", port=2025, **kwargs),
            {
                "database": "warehouse",
                "logmech": "LDAP",
                "logdata": "mech=ldap",
                "sslmode": "VERIFY-FULL",
                "encryptdata": "true",
                "tmode": "TERA",
            },
            {
                "database": "warehouse",
                "logmech": "LDAP",
                "logdata": "mech=ldap",
                "sslmode": "VERIFY-FULL",
                "encryptdata": "true",
                "tmode": "TERA",
            },
            id="external-full-options",
        ),
    ],
)
def test_teradata_service_connection_config(
    service_factory: Any,
    optional_kwargs: dict[str, Any],
    expected_optional: dict[str, Any],
) -> None:
    """Verify ``dbs_port`` and ``connection_config`` include base credentials and only set optional options."""
    service = service_factory(user="alice", password="secret", **optional_kwargs)
    assert service.dbs_port == str(service.port)
    assert service.connection_config == {
        "host": service.host,
        "dbs_port": str(service.port),
        "user": "alice",
        "password": "secret",
        **expected_optional,
    }


@pytest.mark.parametrize(
    ("env_updates", "fixture_func", "expected"),
    [
        pytest.param({}, teradata_image, None, id="image-unset"),
        pytest.param({"TERADATA_TEST_IMAGE": "byo/td:17"}, teradata_image, "byo/td:17", id="image-sqlspec-fallback"),
        pytest.param(
            {"TERADATA_IMAGE": "byo/td:20", "TERADATA_TEST_IMAGE": "byo/td:17"},
            teradata_image,
            "byo/td:20",
            id="image-primary-wins",
        ),
        pytest.param({}, teradata_external_host, None, id="external-host-unset"),
        pytest.param({"TERADATA_HOST": "10.0.0.5"}, teradata_external_host, "10.0.0.5", id="external-host-fallback"),
        pytest.param(
            {"TERADATA_EXTERNAL_HOST": "10.0.0.9", "TERADATA_HOST": "10.0.0.5"},
            teradata_external_host,
            "10.0.0.9",
            id="external-host-primary-wins",
        ),
        pytest.param({}, teradata_external_port, None, id="external-port-unset"),
        pytest.param({"TERADATA_PORT": "11025"}, teradata_external_port, 11025, id="external-port-fallback"),
        pytest.param(
            {"TERADATA_EXTERNAL_PORT": "21025", "TERADATA_PORT": "11025"},
            teradata_external_port,
            21025,
            id="external-port-primary-wins",
        ),
        pytest.param({"TERADATA_PORT": "31025"}, teradata_port, 31025, id="container-port"),
        pytest.param({"TERADATA_USER": "etl_user"}, teradata_user, "etl_user", id="user"),
        pytest.param({"TERADATA_PASSWORD": "etl_password"}, teradata_password, "etl_password", id="password"),
        pytest.param({"TERADATA_DATABASE": "sales"}, teradata_database, "sales", id="database"),
        pytest.param({"TERADATA_LOGMECH": "LDAP"}, teradata_logmech, "LDAP", id="logmech"),
        pytest.param({"TERADATA_LOGDATA": "k=v"}, teradata_logdata, "k=v", id="logdata"),
        pytest.param({"TERADATA_ENCRYPTDATA": "true"}, teradata_encryptdata, "true", id="encryptdata"),
        pytest.param({"TERADATA_TMODE": "ANSI"}, teradata_tmode, "ANSI", id="tmode"),
        pytest.param({}, teradata_startup_timeout, DEFAULT_TERADATA_STARTUP_TIMEOUT, id="startup-timeout-default"),
        pytest.param(
            {"TERADATA_STARTUP_TIMEOUT": "120.5"}, teradata_startup_timeout, 120.5, id="startup-timeout-custom"
        ),
    ],
)
def test_teradata_env_fixture_resolution(
    monkeypatch: pytest.MonkeyPatch,
    env_updates: dict[str, str],
    fixture_func: Any,
    expected: Any,
) -> None:
    """Verify environment variable precedence and defaults across Teradata fixtures."""
    for var in (
        "TERADATA_IMAGE",
        "TERADATA_TEST_IMAGE",
        "TERADATA_EXTERNAL_HOST",
        "TERADATA_HOST",
        "TERADATA_EXTERNAL_PORT",
        "TERADATA_PORT",
        "TERADATA_USER",
        "TERADATA_PASSWORD",
        "TERADATA_DATABASE",
        "TERADATA_LOGMECH",
        "TERADATA_LOGDATA",
        "TERADATA_SSLMODE",
        "TERADATA_ENCRYPTDATA",
        "TERADATA_TMODE",
        "TERADATA_STARTUP_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    for key, value in env_updates.items():
        monkeypatch.setenv(key, value)

    assert _unwrap_fixture(fixture_func)() == expected


@pytest.mark.parametrize(
    "raw_timeout",
    [
        pytest.param("not-a-number", id="non-numeric"),
        pytest.param("0", id="zero"),
        pytest.param("-5", id="negative"),
    ],
)
def test_teradata_startup_timeout_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_timeout: str,
) -> None:
    """Verify invalid ``TERADATA_STARTUP_TIMEOUT`` values raise ValueError."""
    monkeypatch.setenv("TERADATA_STARTUP_TIMEOUT", raw_timeout)
    with pytest.raises(ValueError, match="Invalid TERADATA_STARTUP_TIMEOUT"):
        _unwrap_fixture(teradata_startup_timeout)()


@pytest.mark.parametrize(
    ("worker_num", "isolation", "expected_name", "expected_transient"),
    [
        pytest.param(None, "server", "teradata", True, id="server-no-xdist"),
        pytest.param(1, "server", "teradata_1", True, id="server-gw1"),
        pytest.param(1, "database", "teradata", False, id="database-gw1"),
    ],
)
def test_provide_teradata_service_xdist_and_forwarding(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation: XdistIsolationLevel,
    expected_name: str,
    expected_transient: bool,
) -> None:
    """Verify ``provide_teradata_service`` container naming, transient behavior, and parameter forwarding."""
    monkeypatch.setattr(teradata_mod, "get_xdist_worker_num", lambda: worker_num)

    fake_container = MagicMock()
    started = ServiceContainer(container=fake_container, host="127.0.0.1", port=41025)
    container_service = MagicMock()
    custom_check = MagicMock(return_value=True)

    @contextmanager
    def fake_run(**_kwargs: Any) -> Generator[ServiceContainer, None, None]:
        yield started

    container_service.run.side_effect = fake_run

    with provide_teradata_service(
        container_service,
        "byo/teradata:20.00",
        xdist_teradata_isolate=isolation,
        user="admin",
        password="pw",
        database="analytics",
        logmech="LDAP",
        logdata="secret",
        sslmode="REQUIRE",
        encryptdata="true",
        tmode="TERA",
        host_port=41025,
        env={"ACCEPT_EULA": "Y"},
        command=["--start"],
        shm_size="2g",
        mem_limit="4g",
        volumes={"/host": {"bind": "/container", "mode": "ro"}},
        platform="linux/amd64",
        wait_for_health=True,
        check=custom_check,
        timeout=180.5,
        pause=2.5,
    ) as svc:
        assert isinstance(svc, TeradataService)
        assert svc.container is fake_container
        assert svc.host == "127.0.0.1"
        assert svc.port == 41025
        assert svc.dbs_port == "41025"
        assert svc.connection_config == {
            "host": "127.0.0.1",
            "dbs_port": "41025",
            "user": "admin",
            "password": "pw",
            "database": "analytics",
            "logmech": "LDAP",
            "logdata": "secret",
            "sslmode": "REQUIRE",
            "encryptdata": "true",
            "tmode": "TERA",
        }

    kwargs = container_service.run.call_args.kwargs
    assert kwargs["image"] == "byo/teradata:20.00"
    assert kwargs["container_port"] == TERADATA_PORT
    assert kwargs["name"] == expected_name
    assert kwargs["transient"] is expected_transient
    assert kwargs["env"] == {"ACCEPT_EULA": "Y"}
    assert kwargs["command"] == ["--start"]
    assert kwargs["host_port"] == 41025
    assert kwargs["shm_size"] == "2g"
    assert kwargs["mem_limit"] == "4g"
    assert kwargs["volumes"] == {"/host": {"bind": "/container", "mode": "ro"}}
    assert kwargs["platform"] == "linux/amd64"
    assert kwargs["wait_for_health"] is True
    assert kwargs["check"] is custom_check
    assert kwargs["timeout"] == 181
    assert kwargs["pause"] == pytest.approx(2.5)


def test_is_teradata_ready_probes_tcp_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default readiness check calls ``tcp_port_open`` on the started host and port."""
    calls: list[tuple[str, int, float]] = []

    def fake_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
        calls.append((host, port, timeout))
        return True

    monkeypatch.setattr(teradata_mod, "tcp_port_open", fake_tcp)
    assert _is_teradata_ready(SimpleNamespace(host="127.0.0.1", port=31025)) is True  # type: ignore[arg-type]
    assert calls == [("127.0.0.1", 31025, 2.0)]


@pytest.mark.parametrize(
    ("kwargs", "error_pattern"),
    [
        pytest.param({"image": "   "}, "image must be a non-empty string", id="empty-image"),
        pytest.param({"user": "   "}, "user must be a non-empty string", id="empty-user"),
        pytest.param({"xdist_teradata_isolate": "cluster"}, "Unsupported Teradata isolation level", id="bad-isolation"),
        pytest.param({"timeout": 0}, "timeout must be positive", id="zero-timeout"),
        pytest.param({"pause": 0}, "pause must be positive", id="zero-pause"),
    ],
)
def test_provide_teradata_service_validation_errors(kwargs: dict[str, Any], error_pattern: str) -> None:
    """Verify invalid arguments fail fast before invoking ``ContainerService.run``."""
    container_service = MagicMock()
    params: dict[str, Any] = {"image": "byo/td:20", **kwargs}
    with pytest.raises(ValueError, match=error_pattern), provide_teradata_service(container_service, **params):
        pass
    container_service.run.assert_not_called()


def test_provide_external_teradata_service_polls_and_yields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``provide_external_teradata_service`` retries TCP readiness and yields normalized metadata."""
    attempts = 0
    sleeps: list[float] = []

    def fake_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
        nonlocal attempts
        attempts += 1
        assert host == "td-vm.example"
        assert port == 2025
        assert timeout == pytest.approx(0.05)
        return attempts >= 2

    monkeypatch.setattr(teradata_mod, "tcp_port_open", fake_tcp)
    monkeypatch.setattr(teradata_mod.time, "sleep", sleeps.append)

    with provide_external_teradata_service(
        "  td-vm.example  ",
        port=2025,
        user=DEFAULT_TERADATA_USER,
        password=DEFAULT_TERADATA_PASSWORD,
        database="demo",
        tmode="TERA",
        timeout=5.0,
        pause=0.05,
    ) as svc:
        assert isinstance(svc, ExternalTeradataService)
        assert svc.host == "td-vm.example"
        assert svc.port == 2025
        assert svc.dbs_port == "2025"
        assert svc.connection_config == {
            "host": "td-vm.example",
            "dbs_port": "2025",
            "user": "dbc",
            "password": "dbc",
            "database": "demo",
            "tmode": "TERA",
        }

    assert attempts == 2
    assert sleeps == [pytest.approx(0.05, abs=0.05)]


def test_provide_external_teradata_service_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``provide_external_teradata_service`` raises ``TimeoutError`` when timeout expires."""
    monotonic_values = iter([0.0, 0.0, 1.5])
    monkeypatch.setattr(teradata_mod.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(teradata_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(teradata_mod, "tcp_port_open", lambda *_args, **_kwargs: False)

    with (
        pytest.raises(TimeoutError, match=r"td-vm\.example:1025"),
        provide_external_teradata_service("td-vm.example", timeout=1.0, pause=0.25),
    ):
        pass


def test_provide_external_teradata_service_supports_custom_check() -> None:
    """Verify ``provide_external_teradata_service`` accepts a custom readiness predicate."""
    custom_calls: list[tuple[str, int]] = []

    def _custom_check(host: str, port: int) -> bool:
        custom_calls.append((host, port))
        return True

    with provide_external_teradata_service(
        "td-vm.example",
        check=_custom_check,
        timeout=1.0,
        pause=0.1,
    ) as svc:
        assert svc.host == "td-vm.example"
        assert svc.port == TERADATA_PORT
    assert custom_calls == [("td-vm.example", TERADATA_PORT)]


@pytest.mark.parametrize(
    ("host", "kwargs", "error_pattern"),
    [
        pytest.param("   ", {}, "host must be a non-empty string", id="empty-host"),
        pytest.param("td-vm.example", {"port": 0}, "between 1 and 65535", id="port-too-low"),
        pytest.param("td-vm.example", {"port": 70000}, "between 1 and 65535", id="port-too-high"),
        pytest.param("td-vm.example", {"user": ""}, "user must be a non-empty string", id="empty-user"),
        pytest.param("td-vm.example", {"timeout": -1.0}, "timeout must be positive", id="negative-timeout"),
        pytest.param("td-vm.example", {"pause": 0.0}, "pause must be positive", id="zero-pause"),
    ],
)
def test_provide_external_teradata_service_validation_errors(
    host: str,
    kwargs: dict[str, Any],
    error_pattern: str,
) -> None:
    """Verify ``provide_external_teradata_service`` validates parameters before probing."""
    with pytest.raises(ValueError, match=error_pattern), provide_external_teradata_service(host, **kwargs):
        pass


def test_teradata_service_live(pytester: pytest.Pytester) -> None:
    """Verify BYO ``teradata_service`` yields reachable metadata when configured."""
    if not (os.getenv("TERADATA_IMAGE") or os.getenv("TERADATA_TEST_IMAGE")):
        pytest.skip("Set TERADATA_IMAGE or TERADATA_TEST_IMAGE to run live Teradata container test.")

    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.teradata"]

    def test_live(teradata_service) -> None:
        assert teradata_service.port > 0
        assert teradata_service.dbs_port == str(teradata_service.port)
        assert teradata_service.connection_config["host"] == teradata_service.host
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_teradata_external_service_live(pytester: pytest.Pytester) -> None:
    """Verify ``teradata_external_service`` yields reachable metadata when configured."""
    if not (os.getenv("TERADATA_EXTERNAL_HOST") or os.getenv("TERADATA_HOST")):
        pytest.skip("Set TERADATA_EXTERNAL_HOST or TERADATA_HOST to run live external Teradata test.")

    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.teradata"]

    def test_live(teradata_external_service) -> None:
        assert teradata_external_service.port > 0
        assert teradata_external_service.dbs_port == str(teradata_external_service.port)
        assert teradata_external_service.connection_config["host"] == teradata_external_service.host
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)
