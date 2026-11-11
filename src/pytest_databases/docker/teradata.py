"""Clientless Teradata Vantage container and external endpoint service fixtures."""

from __future__ import annotations

import math
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import env_port, get_xdist_worker_num, tcp_port_open
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping

    from pytest_databases._service import ContainerService

__all__ = (
    "DEFAULT_TERADATA_PASSWORD",
    "DEFAULT_TERADATA_STARTUP_TIMEOUT",
    "DEFAULT_TERADATA_USER",
    "TERADATA_PORT",
    "ExternalTeradataService",
    "TeradataService",
    "provide_external_teradata_service",
    "provide_teradata_service",
    "teradata_database",
    "teradata_encryptdata",
    "teradata_external_host",
    "teradata_external_port",
    "teradata_external_service",
    "teradata_image",
    "teradata_logdata",
    "teradata_logmech",
    "teradata_password",
    "teradata_port",
    "teradata_service",
    "teradata_service_environment",
    "teradata_sslmode",
    "teradata_startup_timeout",
    "teradata_tmode",
    "teradata_user",
    "xdist_teradata_isolation_level",
)

TERADATA_PORT = 1025
DEFAULT_TERADATA_USER = "dbc"
DEFAULT_TERADATA_PASSWORD = "dbc"
DEFAULT_TERADATA_STARTUP_TIMEOUT = 300.0


@dataclass
class TeradataService(ServiceContainer):
    """Connection metadata for a BYO Teradata Vantage container service."""

    user: str
    password: str
    database: str | None = None
    logmech: str | None = None
    logdata: str | None = None
    sslmode: str | None = None
    encryptdata: str | None = None
    tmode: str | None = None

    @property
    def dbs_port(self) -> str:
        """Port number formatted as a string for ``teradatasql.connect``."""
        return str(self.port)

    @property
    def connection_config(self) -> dict[str, Any]:
        """Dictionary of connection parameters compatible with ``teradatasql.connect`` and ``sqlspec``."""
        return _build_connection_config(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            logmech=self.logmech,
            logdata=self.logdata,
            sslmode=self.sslmode,
            encryptdata=self.encryptdata,
            tmode=self.tmode,
        )


@dataclass
class ExternalTeradataService:
    """Connection metadata for an external Teradata Vantage VM or cloud endpoint."""

    host: str
    port: int = TERADATA_PORT
    user: str = DEFAULT_TERADATA_USER
    password: str = DEFAULT_TERADATA_PASSWORD
    database: str | None = None
    logmech: str | None = None
    logdata: str | None = None
    sslmode: str | None = None
    encryptdata: str | None = None
    tmode: str | None = None

    @property
    def dbs_port(self) -> str:
        """Port number formatted as a string for ``teradatasql.connect``."""
        return str(self.port)

    @property
    def connection_config(self) -> dict[str, Any]:
        """Dictionary of connection parameters compatible with ``teradatasql.connect`` and ``sqlspec``."""
        return _build_connection_config(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            logmech=self.logmech,
            logdata=self.logdata,
            sslmode=self.sslmode,
            encryptdata=self.encryptdata,
            tmode=self.tmode,
        )


@contextmanager
def provide_teradata_service(
    container_service: ContainerService,
    image: str,
    *,
    name: str = "teradata",
    xdist_teradata_isolate: XdistIsolationLevel = "server",
    user: str = DEFAULT_TERADATA_USER,
    password: str = DEFAULT_TERADATA_PASSWORD,
    database: str | None = None,
    logmech: str | None = None,
    logdata: str | None = None,
    sslmode: str | None = None,
    encryptdata: str | None = None,
    tmode: str | None = None,
    host_port: int | None = None,
    env: Mapping[str, str] | None = None,
    command: str | list[str] | None = None,
    shm_size: int | str | None = None,
    mem_limit: str | None = None,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
    platform: str | None = None,
    wait_for_health: bool = False,
    check: Callable[[ServiceContainer], bool] | None = None,
    timeout: float = DEFAULT_TERADATA_STARTUP_TIMEOUT,
    pause: float = 2.0,
) -> Generator[TeradataService, None, None]:
    """Start a user-supplied Teradata container and yield its connection metadata.

    Args:
        container_service: Container runtime manager.
        image: User-supplied Teradata container image reference.
        name: Base container name.
        xdist_teradata_isolate: Isolation mode across xdist workers (``"server"`` or ``"database"``).
        user: Teradata user name.
        password: Password for ``user``.
        database: Optional default database name.
        logmech: Optional logon mechanism (for example ``TD2`` or ``LDAP``).
        logdata: Optional logon data payload.
        sslmode: Optional TLS mode.
        encryptdata: Optional encryption setting.
        tmode: Optional transaction mode (for example ``TERA`` or ``ANSI``).
        host_port: Optional host port to bind container port 1025.
        env: Optional container environment variables.
        command: Optional container command override.
        shm_size: Optional container ``/dev/shm`` size.
        mem_limit: Optional container memory limit.
        volumes: Optional container volume mounts.
        platform: Optional container target platform.
        wait_for_health: Whether to wait for the container's Docker healthcheck before probing port 1025.
        check: Optional custom readiness predicate receiving the started :class:`ServiceContainer`.
        timeout: Maximum startup wait duration in seconds.
        pause: Delay between readiness checks in seconds.

    Yields:
        A running :class:`TeradataService`.
    """
    if not image.strip():
        msg = "Teradata container image must be a non-empty string"
        raise ValueError(msg)
    if not user.strip():
        msg = "Teradata user must be a non-empty string"
        raise ValueError(msg)
    if xdist_teradata_isolate not in {"database", "server"}:
        msg = f"Unsupported Teradata isolation level: {xdist_teradata_isolate}"
        raise ValueError(msg)
    if timeout <= 0:
        msg = "timeout must be positive"
        raise ValueError(msg)
    if pause <= 0:
        msg = "pause must be positive"
        raise ValueError(msg)

    worker_num = get_xdist_worker_num()
    if xdist_teradata_isolate == "server":
        container_name = f"{name}_{worker_num}" if worker_num is not None else name
        transient = True
    else:
        container_name = name
        transient = False

    container_env = dict(env) if env else {}
    readiness_check = check or _is_teradata_ready

    with container_service.run(
        image=image,
        container_port=TERADATA_PORT,
        name=container_name,
        command=command,
        env=container_env,
        host_port=host_port,
        shm_size=shm_size,
        mem_limit=mem_limit,
        volumes=volumes,
        platform=platform,
        wait_for_health=wait_for_health,
        check=readiness_check,
        timeout=math.ceil(timeout),
        pause=pause,
        transient=transient,
    ) as service:
        yield TeradataService(
            container=service.container,
            host=service.host,
            port=service.port,
            user=user,
            password=password,
            database=database,
            logmech=logmech,
            logdata=logdata,
            sslmode=sslmode,
            encryptdata=encryptdata,
            tmode=tmode,
        )


@contextmanager
def provide_external_teradata_service(
    host: str,
    *,
    port: int = TERADATA_PORT,
    user: str = DEFAULT_TERADATA_USER,
    password: str = DEFAULT_TERADATA_PASSWORD,
    database: str | None = None,
    logmech: str | None = None,
    logdata: str | None = None,
    sslmode: str | None = None,
    encryptdata: str | None = None,
    tmode: str | None = None,
    check: Callable[[str, int], bool] | None = None,
    timeout: float = DEFAULT_TERADATA_STARTUP_TIMEOUT,
    pause: float = 2.0,
) -> Generator[ExternalTeradataService, None, None]:
    """Wait for an external Teradata Vantage endpoint and yield its connection metadata.

    Args:
        host: Hostname or IP address of the external Teradata instance.
        port: TCP port exposed by the Teradata gateway.
        user: Teradata user name.
        password: Password for ``user``.
        database: Optional default database name.
        logmech: Optional logon mechanism.
        logdata: Optional logon data payload.
        sslmode: Optional TLS mode.
        encryptdata: Optional encryption setting.
        tmode: Optional transaction mode.
        check: Optional readiness predicate receiving ``(host, port)``.
        timeout: Maximum readiness wait duration in seconds.
        pause: Delay between readiness probes in seconds.

    Yields:
        An :class:`ExternalTeradataService` bound to the reachable endpoint.
    """
    normalized_host = host.strip()
    if not normalized_host:
        msg = "Teradata external host must be a non-empty string"
        raise ValueError(msg)
    if port < 1 or port > 65535:
        msg = f"Teradata port must be between 1 and 65535, got {port}"
        raise ValueError(msg)
    if not user.strip():
        msg = "Teradata user must be a non-empty string"
        raise ValueError(msg)
    if timeout <= 0:
        msg = "timeout must be positive"
        raise ValueError(msg)
    if pause <= 0:
        msg = "pause must be positive"
        raise ValueError(msg)

    _wait_for_teradata_port(normalized_host, port, timeout=timeout, pause=pause, check=check)
    yield ExternalTeradataService(
        host=normalized_host,
        port=port,
        user=user,
        password=password,
        database=database,
        logmech=logmech,
        logdata=logdata,
        sslmode=sslmode,
        encryptdata=encryptdata,
        tmode=tmode,
    )


@pytest.fixture(scope="session")
def teradata_image() -> str | None:
    """BYO Teradata container image from ``TERADATA_IMAGE`` or ``TERADATA_TEST_IMAGE``."""
    return os.getenv("TERADATA_IMAGE") or os.getenv("TERADATA_TEST_IMAGE") or None


@pytest.fixture(scope="session")
def teradata_external_host() -> str | None:
    """External Teradata host from ``TERADATA_EXTERNAL_HOST`` or ``TERADATA_HOST``."""
    return os.getenv("TERADATA_EXTERNAL_HOST") or os.getenv("TERADATA_HOST") or None


@pytest.fixture(scope="session")
def teradata_external_port() -> int | None:
    """External Teradata port from ``TERADATA_EXTERNAL_PORT`` or ``TERADATA_PORT``."""
    return env_port("TERADATA_EXTERNAL_PORT") or env_port("TERADATA_PORT")


@pytest.fixture(scope="session")
def teradata_port() -> int | None:
    """Optional fixed host port for ``teradata_service`` from ``TERADATA_PORT``."""
    return env_port("TERADATA_PORT")


@pytest.fixture(scope="session")
def teradata_user() -> str:
    """Teradata username from ``TERADATA_USER`` (default ``dbc``)."""
    return os.getenv("TERADATA_USER") or DEFAULT_TERADATA_USER


@pytest.fixture(scope="session")
def teradata_password() -> str:
    """Teradata password from ``TERADATA_PASSWORD`` (default ``dbc``)."""
    return os.getenv("TERADATA_PASSWORD") or DEFAULT_TERADATA_PASSWORD


@pytest.fixture(scope="session")
def teradata_database() -> str | None:
    """Optional default Teradata database from ``TERADATA_DATABASE``."""
    return os.getenv("TERADATA_DATABASE") or None


@pytest.fixture(scope="session")
def teradata_logmech() -> str | None:
    """Optional Teradata logon mechanism from ``TERADATA_LOGMECH``."""
    return os.getenv("TERADATA_LOGMECH") or None


@pytest.fixture(scope="session")
def teradata_logdata() -> str | None:
    """Optional Teradata logon data from ``TERADATA_LOGDATA``."""
    return os.getenv("TERADATA_LOGDATA") or None


@pytest.fixture(scope="session")
def teradata_sslmode() -> str | None:
    """Optional Teradata SSL mode from ``TERADATA_SSLMODE``."""
    return os.getenv("TERADATA_SSLMODE") or None


@pytest.fixture(scope="session")
def teradata_encryptdata() -> str | None:
    """Optional Teradata encryption setting from ``TERADATA_ENCRYPTDATA``."""
    return os.getenv("TERADATA_ENCRYPTDATA") or None


@pytest.fixture(scope="session")
def teradata_tmode() -> str | None:
    """Optional Teradata transaction mode from ``TERADATA_TMODE``."""
    return os.getenv("TERADATA_TMODE") or None


@pytest.fixture(scope="session")
def teradata_startup_timeout() -> float:
    """Startup timeout in seconds from ``TERADATA_STARTUP_TIMEOUT`` (default ``300.0``)."""
    raw = os.getenv("TERADATA_STARTUP_TIMEOUT")
    if not raw:
        return DEFAULT_TERADATA_STARTUP_TIMEOUT
    try:
        value = float(raw)
    except ValueError as exc:
        msg = f"Invalid TERADATA_STARTUP_TIMEOUT={raw!r}: expected a positive number"
        raise ValueError(msg) from exc
    if value <= 0:
        msg = f"Invalid TERADATA_STARTUP_TIMEOUT={raw!r}: must be positive"
        raise ValueError(msg)
    return value


@pytest.fixture(scope="session")
def teradata_service_environment() -> dict[str, str]:
    """Environment variables passed to the Teradata container started by ``teradata_service``."""
    return {}


@pytest.fixture(scope="session")
def xdist_teradata_isolation_level() -> XdistIsolationLevel:
    """Xdist isolation level for ``teradata_service`` (default ``"server"``)."""
    return "server"


@pytest.fixture(scope="session")
def teradata_service(
    request: pytest.FixtureRequest,
    teradata_image: str | None,
    xdist_teradata_isolation_level: XdistIsolationLevel,
    teradata_user: str,
    teradata_password: str,
    teradata_database: str | None,
    teradata_logmech: str | None,
    teradata_logdata: str | None,
    teradata_sslmode: str | None,
    teradata_encryptdata: str | None,
    teradata_tmode: str | None,
    teradata_port: int | None,
    teradata_startup_timeout: float,
    teradata_service_environment: dict[str, str],
) -> Generator[TeradataService, None, None]:
    """Session-scoped BYO Teradata Vantage container service fixture.

    Skips automatically when neither ``TERADATA_IMAGE`` nor ``TERADATA_TEST_IMAGE`` is set.

    Yields:
        A running :class:`TeradataService`.
    """
    if not teradata_image:
        pytest.skip("Set TERADATA_IMAGE or TERADATA_TEST_IMAGE to enable teradata_service.")
    container_service: ContainerService = request.getfixturevalue("container_service")
    with provide_teradata_service(
        container_service,
        teradata_image,
        xdist_teradata_isolate=xdist_teradata_isolation_level,
        user=teradata_user,
        password=teradata_password,
        database=teradata_database,
        logmech=teradata_logmech,
        logdata=teradata_logdata,
        sslmode=teradata_sslmode,
        encryptdata=teradata_encryptdata,
        tmode=teradata_tmode,
        host_port=teradata_port,
        env=teradata_service_environment,
        timeout=teradata_startup_timeout,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def teradata_external_service(
    teradata_external_host: str | None,
    teradata_external_port: int | None,
    teradata_user: str,
    teradata_password: str,
    teradata_database: str | None,
    teradata_logmech: str | None,
    teradata_logdata: str | None,
    teradata_sslmode: str | None,
    teradata_encryptdata: str | None,
    teradata_tmode: str | None,
    teradata_startup_timeout: float,
) -> Generator[ExternalTeradataService, None, None]:
    """Session-scoped external Teradata Vantage endpoint fixture.

    Skips automatically when neither ``TERADATA_EXTERNAL_HOST`` nor ``TERADATA_HOST`` is set.

    Yields:
        An :class:`ExternalTeradataService` bound to the configured endpoint.
    """
    if not teradata_external_host:
        pytest.skip("Set TERADATA_EXTERNAL_HOST or TERADATA_HOST to enable teradata_external_service.")
    port = teradata_external_port if teradata_external_port is not None else TERADATA_PORT
    with provide_external_teradata_service(
        teradata_external_host,
        port=port,
        user=teradata_user,
        password=teradata_password,
        database=teradata_database,
        logmech=teradata_logmech,
        logdata=teradata_logdata,
        sslmode=teradata_sslmode,
        encryptdata=teradata_encryptdata,
        tmode=teradata_tmode,
        timeout=teradata_startup_timeout,
    ) as service:
        yield service


def _build_connection_config(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str | None,
    logmech: str | None,
    logdata: str | None,
    sslmode: str | None,
    encryptdata: str | None,
    tmode: str | None,
) -> dict[str, Any]:
    """Build a dictionary of Teradata connection parameters, omitting unset optional values."""
    config: dict[str, Any] = {
        "host": host,
        "dbs_port": str(port),
        "user": user,
        "password": password,
    }
    optional_fields = {
        "database": database,
        "logmech": logmech,
        "logdata": logdata,
        "sslmode": sslmode,
        "encryptdata": encryptdata,
        "tmode": tmode,
    }
    config.update({key: value for key, value in optional_fields.items() if value is not None})
    return config


def _is_teradata_ready(service: ServiceContainer) -> bool:
    """Return whether Teradata Gateway port 1025 accepts TCP connections."""
    return tcp_port_open(service.host, service.port, timeout=2.0)


def _wait_for_teradata_port(
    host: str,
    port: int,
    *,
    timeout: float,
    pause: float,
    check: Callable[[str, int], bool] | None = None,
) -> None:
    """Poll Teradata TCP port readiness until reachable or ``timeout`` expires."""
    probe = check or (lambda target_host, target_port: tcp_port_open(target_host, target_port, timeout=min(pause, 2.0)))
    deadline = time.monotonic() + timeout
    while True:
        if probe(host, port):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            msg = f"Teradata service at {host}:{port} did not become ready within {timeout}s"
            raise TimeoutError(msg)
        time.sleep(min(pause, remaining))
