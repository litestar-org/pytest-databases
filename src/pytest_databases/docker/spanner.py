"""Google Cloud Spanner emulator container fixtures and HTTP REST provisioning."""

from __future__ import annotations

import contextlib
import datetime as dt
import email.message
import http.client
import importlib
import io
import json
import logging
import os
import time
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num, send_http_request
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel

__all__ = [
    "SpannerService",
    "bootstrap_spanner_emulator",
    "configure_spanner_emulator_client_guards",
    "provide_spanner_service",
    "spanner_connection",
    "spanner_database_name",
    "spanner_image",
    "spanner_instance_name",
    "spanner_project",
    "spanner_service",
    "xdist_spanner_isolation_level",
]

_SPANNER_SESSION_MODULES = (
    "google.cloud.spanner_v1.database_sessions_manager",
    "google.cloud.spanner_v1._async.database_sessions_manager",
)
_SPANNER_LOGGER_NAMES = (
    "google.cloud.spanner_v1.database_sessions_manager",
    "database_sessions_manager",
)
_POLLING_ATTR = "_MAINTENANCE_THREAD_POLLING_INTERVAL"
_FAST_POLLING_INTERVAL = dt.timedelta(milliseconds=100)
_STREAM_GUARD_MARKER = "_pytest_databases_stream_guard"


@dataclass(init=False)
class SpannerService(ServiceContainer):
    """Container handle with gRPC and REST endpoints for Cloud Spanner emulator."""

    project: str
    database_name: str
    instance_name: str
    rest_port: int = 0

    def __init__(
        self,
        container: Container,
        host: str,
        port: int,
        project: str,
        database_name: str,
        instance_name: str,
        rest_port: int = 0,
        credentials: Any = None,
    ) -> None:
        """Initialize the service metadata.

        Args:
            container: Running emulator container.
            host: Host name the emulator is reachable on.
            port: Published emulator gRPC port.
            project: Emulator project ID.
            database_name: Database reserved for the current test process.
            instance_name: Emulator instance ID.
            rest_port: Published emulator REST port.
            credentials: Deprecated and ignored; credentials are built on access by :attr:`credentials`.
        """
        super().__init__(container=container, host=host, port=port)
        self.project = project
        self.database_name = database_name
        self.instance_name = instance_name
        self.rest_port = rest_port
        if credentials is not None:
            warnings.warn(
                "Passing 'credentials' to SpannerService is deprecated in v0.20.0 and will be removed in v1.0.0. "
                "The argument is ignored.",
                DeprecationWarning,
                stacklevel=2,
            )

    @property
    def endpoint(self) -> str:
        """GRPC endpoint for Cloud Spanner client connections."""
        return f"{self.host}:{self.port}"

    @property
    def emulator_host(self) -> str:
        """Host:port endpoint value formatted for ``SPANNER_EMULATOR_HOST``."""
        return f"{self.host}:{self.port}"

    @property
    def rest_endpoint(self) -> str:
        """HTTP REST endpoint for Cloud Spanner administration."""
        return f"{self.host}:{self.rest_port}"

    @property
    def credentials(self) -> Any:
        """Deprecated AnonymousCredentials for Cloud Spanner emulator."""
        warnings.warn(
            "SpannerService.credentials is deprecated in v0.20.0 and will be removed in v1.0.0. "
            "Instantiate 'google.auth.credentials.AnonymousCredentials()' directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        credentials_mod = importlib.import_module("google.auth.credentials")
        return credentials_mod.AnonymousCredentials()

    @property
    def client_options(self) -> Any:
        """Deprecated ClientOptions for Cloud Spanner emulator."""
        warnings.warn(
            "SpannerService.client_options is deprecated in v0.20.0 and will be removed in v1.0.0. "
            "Instantiate 'google.api_core.client_options.ClientOptions(api_endpoint=service.endpoint)' directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        options_mod = importlib.import_module("google.api_core.client_options")
        return options_mod.ClientOptions(api_endpoint=self.endpoint)


def bootstrap_spanner_emulator(
    host: str,
    rest_port: int,
    *,
    project: str,
    instance_name: str,
    database_name: str,
) -> None:
    """Create the Spanner emulator instance and database through the REST API.

    Args:
        host: Host where the emulator REST port is published.
        rest_port: Published host port of the emulator REST API (container port 9020).
        project: Google Cloud project identifier.
        instance_name: Spanner instance identifier.
        database_name: Spanner database identifier.
    """
    instance_url = f"http://{host}:{rest_port}/v1/projects/{project}/instances"
    instance_payload = {
        "instanceId": instance_name,
        "instance": {
            "config": f"projects/{project}/instanceConfigs/emulator-config",
            "displayName": "pytest-databases",
            "nodeCount": 1,
        },
    }
    database_url = f"http://{host}:{rest_port}/v1/projects/{project}/instances/{instance_name}/databases"
    database_payload = {
        "createStatement": f"CREATE DATABASE `{database_name}`",
    }
    _send_spanner_request_with_retry(instance_url, instance_payload)
    _send_spanner_request_with_retry(database_url, database_payload)


@contextlib.contextmanager
def configure_spanner_emulator_client_guards() -> Generator[None, None, None]:
    """Configure optional Google Cloud Spanner Python SDK defaults for local emulator sessions.

    Defaults ``SPANNER_DISABLE_BUILTIN_METRICS="true"`` while active when unset, lowers installed sync and async
    ``DatabaseSessionsManager._MAINTENANCE_THREAD_POLLING_INTERVAL`` to 100ms with ``finally`` restoration, clamps
    session-manager loggers to at least ``logging.WARNING``, and guards closed pytest capture streams against
    ``ValueError`` during background teardown.
    """
    had_metrics_env = "SPANNER_DISABLE_BUILTIN_METRICS" in os.environ
    if not had_metrics_env:
        os.environ["SPANNER_DISABLE_BUILTIN_METRICS"] = "true"
    saved_polling: list[tuple[Any, Any]] = []
    for mod_name in _SPANNER_SESSION_MODULES:
        with contextlib.suppress(ImportError):
            mod = importlib.import_module(mod_name)
            manager_cls = getattr(mod, "DatabaseSessionsManager", None)
            if manager_cls is not None and hasattr(manager_cls, _POLLING_ATTR):
                saved_polling.append((manager_cls, getattr(manager_cls, _POLLING_ATTR)))
                setattr(manager_cls, _POLLING_ATTR, _FAST_POLLING_INTERVAL)
    saved_levels: list[tuple[logging.Logger, int]] = []
    for logger_name in _SPANNER_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        saved_levels.append((logger, logger.level))
        if logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)
        _install_closed_stream_guard(logger)
    try:
        yield
    finally:
        for logger, prev_level in reversed(saved_levels):
            logger.setLevel(prev_level)
        for manager_cls, prev_interval in reversed(saved_polling):
            setattr(manager_cls, _POLLING_ATTR, prev_interval)
        if not had_metrics_env:
            os.environ.pop("SPANNER_DISABLE_BUILTIN_METRICS", None)


@contextlib.contextmanager
def provide_spanner_service(
    docker_service: DockerService,
    spanner_image: str,
    spanner_project: str,
    spanner_instance_name: str,
    spanner_database_name: str,
    isolation_level: XdistIsolationLevel = "database",
) -> Generator[SpannerService, None, None]:
    """Start and manage a Google Cloud Spanner emulator container.

    Args:
        docker_service: The container service manager.
        spanner_image: Container image for the emulator.
        spanner_project: Project identifier.
        spanner_instance_name: Instance identifier.
        spanner_database_name: Database identifier.
        isolation_level: Isolation level for xdist workers (database or server).

    Yields:
        A SpannerService handle with host and port bindings.
    """
    worker_num = get_xdist_worker_num()
    name = "spanner"
    effective_db = spanner_database_name
    if worker_num is not None:
        if isolation_level == "server":
            name = f"{name}_{worker_num}"
        else:
            effective_db = f"{spanner_database_name}_{worker_num}"

    with (
        configure_spanner_emulator_client_guards(),
        docker_service.run(
            image=spanner_image,
            name=name,
            container_port=9010,
            extra_ports={9020: None},
            wait_for_log="gRPC server listening at",
            transient=worker_num is not None and isolation_level == "server",
        ) as service,
    ):
        rest_port = docker_service.resolve_port(service.container, 9020)
        bootstrap_spanner_emulator(
            service.host,
            rest_port,
            project=spanner_project,
            instance_name=spanner_instance_name,
            database_name=effective_db,
        )
        yield SpannerService(
            host=service.host,
            port=service.port,
            container=service.container,
            project=spanner_project,
            instance_name=spanner_instance_name,
            database_name=effective_db,
            rest_port=rest_port,
        )


@pytest.fixture(scope="session")
def xdist_spanner_isolation_level() -> XdistIsolationLevel:
    """Determine Spanner xdist isolation mode (database or server)."""
    return "database"


@pytest.fixture(scope="session")
def spanner_project() -> str:
    """Project identifier for Cloud Spanner emulator."""
    return "emulator-test-project"


@pytest.fixture(scope="session")
def spanner_instance_name() -> str:
    """Instance identifier for Cloud Spanner emulator."""
    return "emulator-test-instance"


@pytest.fixture(scope="session")
def spanner_database_name() -> str:
    """Database identifier for Cloud Spanner emulator."""
    return "emulator-test-database"


@pytest.fixture(scope="session")
def spanner_image() -> str:
    """Container image for Cloud Spanner emulator."""
    return "gcr.io/cloud-spanner-emulator/emulator:latest"


@pytest.fixture(autouse=False, scope="session")
def spanner_service(
    docker_service: DockerService,
    xdist_spanner_isolation_level: XdistIsolationLevel,
    spanner_image: str,
    spanner_project: str,
    spanner_instance_name: str,
    spanner_database_name: str,
) -> Generator[SpannerService, None, None]:
    """Start and manage a Google Cloud Spanner emulator container.

    Yields:
        A SpannerService handle with host and port bindings.
    """
    with provide_spanner_service(
        docker_service=docker_service,
        spanner_image=spanner_image,
        spanner_project=spanner_project,
        spanner_instance_name=spanner_instance_name,
        spanner_database_name=spanner_database_name,
        isolation_level=xdist_spanner_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def spanner_connection(
    spanner_service: SpannerService,
) -> Generator[Any, None, None]:
    """Provide a deprecated Cloud Spanner client connected to the emulator.

    Yields:
        Active google.cloud.spanner.Client instance.
    """
    warnings.warn(
        "The 'spanner_connection' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'spanner_service' and instantiate your google.cloud.spanner.Client directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    spanner = importlib.import_module("google.cloud.spanner")
    credentials_mod = importlib.import_module("google.auth.credentials")
    options_mod = importlib.import_module("google.api_core.client_options")
    client = spanner.Client(
        project=spanner_service.project,
        credentials=credentials_mod.AnonymousCredentials(),
        client_options=options_mod.ClientOptions(api_endpoint=spanner_service.endpoint),
    )
    try:
        yield client
    finally:
        client.close()


def _send_spanner_request_with_retry(
    url: str,
    payload: dict[str, Any],
    max_attempts: int = 10,
) -> None:
    """Send a JSON POST request to the Spanner REST API with retries for container readiness.

    Args:
        url: Target REST URL.
        payload: Request payload dictionary.
        max_attempts: Maximum retry attempts before raising.

    Raises:
        HTTPError: If the server returns an unexpected HTTP error code other than 409.
        URLError: If the connection fails after max attempts.
    """
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(max_attempts):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            status, resp_headers, body = send_http_request(req, timeout=5.0)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException):
            if attempt == max_attempts - 1:
                raise
            time.sleep(0.5)
            continue
        if 200 <= status < 300 or status == 409:
            return
        if status >= 500 and attempt < max_attempts - 1:
            time.sleep(0.5)
            continue
        msg_headers = email.message.Message()
        for key, value in resp_headers.items():
            msg_headers[key] = value
        raise urllib.error.HTTPError(url, status, f"HTTP {status}", msg_headers, io.BytesIO(body))


def _has_closed_stream_handler(logger: logging.Logger) -> bool:
    current: logging.Logger | None = logger
    while current is not None:
        for handler in current.handlers:
            stream = getattr(handler, "stream", None)
            if stream is not None and getattr(stream, "closed", False):
                return True
        if not current.propagate:
            break
        current = current.parent
    return False


def _install_closed_stream_guard(logger: logging.Logger) -> None:
    orig_call_handlers: Any = logger.callHandlers
    if getattr(orig_call_handlers, _STREAM_GUARD_MARKER, False):
        return

    @wraps(orig_call_handlers)
    def guarded_call_handlers(record: logging.LogRecord) -> None:
        if _has_closed_stream_handler(logger):
            return
        try:
            orig_call_handlers(record)
        except ValueError as exc:
            if "closed file" in str(exc).lower() or _has_closed_stream_handler(logger):
                return
            raise

    setattr(guarded_call_handlers, _STREAM_GUARD_MARKER, True)
    logger.callHandlers = guarded_call_handlers  # type: ignore[method-assign]
