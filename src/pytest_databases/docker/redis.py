"""Redis, KeyDB, and Dragonfly container service fixtures."""

from __future__ import annotations

import dataclasses
import importlib
import socket
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator
    from io import BufferedReader

    from redis import Redis

    from pytest_databases._service import DockerService

__all__ = (
    "RedisService",
    "dragonfly_client",
    "dragonfly_connection",
    "dragonfly_host",
    "dragonfly_image",
    "dragonfly_port",
    "dragonfly_service",
    "encode_resp_command",
    "keydb_client",
    "keydb_connection",
    "keydb_host",
    "keydb_image",
    "keydb_port",
    "keydb_service",
    "provide_deprecated_redis_client",
    "provide_redis_service",
    "read_resp_reply",
    "redis_client",
    "redis_connection",
    "redis_host",
    "redis_image",
    "redis_port",
    "redis_responsive",
    "redis_service",
    "send_resp_command",
    "xdist_redis_isolation_level",
)


@dataclasses.dataclass
class RedisService(ServiceContainer):
    """Connection metadata for a running Redis-compatible container service."""

    db: int


def encode_resp_command(*args: str) -> bytes:
    """Encode a command argument tuple into a RESP bulk-string array frame.

    Args:
        *args: Command tokens to serialize.

    Returns:
        Encoded RESP frame bytes.
    """
    parts = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        arg_bytes = str(arg).encode("utf-8")
        parts.append(f"${len(arg_bytes)}\r\n".encode() + arg_bytes + b"\r\n")
    return b"".join(parts)


def read_resp_reply(reader: BufferedReader) -> str | int | None:
    """Read a single RESP reply frame from a buffered socket reader.

    Args:
        reader: Buffered binary socket reader.

    Returns:
        Decoded string, integer, or None for a RESP null bulk string.

    Raises:
        ConnectionError: If the socket closes before a frame is received.
        RuntimeError: If the server returns a RESP error frame.
    """
    line = reader.readline()
    if not line:
        msg = "Empty RESP response from server"
        raise ConnectionError(msg)
    prefix = line[:1]
    payload = line[1:-2]
    if prefix == b"+":
        return payload.decode("utf-8", errors="replace")
    if prefix == b"-":
        msg = payload.decode("utf-8", errors="replace")
        raise RuntimeError(msg)
    if prefix == b":":
        return int(payload)
    if prefix == b"$":
        length = int(payload)
        if length == -1:
            return None
        data = reader.read(length)
        reader.read(2)
        return data.decode("utf-8", errors="replace")
    msg = f"Unsupported RESP prefix: {prefix!r}"
    raise RuntimeError(msg)


def send_resp_command(
    host: str,
    port: int,
    *args: str,
    db: int = 0,
    timeout: float = 2.0,
) -> str | int | None:
    """Execute a command over a direct stdlib TCP socket using the RESP protocol.

    Args:
        host: Target Redis-compatible server hostname or IP.
        port: Target Redis-compatible server TCP port.
        *args: Command arguments (for example ``("PING",)`` or ``("SET", "k", "v")``).
        db: Logical database index to select before issuing the command.
        timeout: Socket connection and read timeout in seconds.

    Returns:
        Parsed RESP response value.
    """
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        with sock.makefile("rb") as reader:
            if db != 0:
                sock.sendall(encode_resp_command("SELECT", str(db)))
                read_resp_reply(reader)
            sock.sendall(encode_resp_command(*args))
            return read_resp_reply(reader)


def redis_responsive(service_container: ServiceContainer) -> bool:
    """Check whether a Redis-compatible service responds to a RESP PING command.

    Args:
        service_container: Running service container metadata.

    Returns:
        True when the endpoint replies with ``PONG``, otherwise False.
    """
    try:
        return send_resp_command(service_container.host, service_container.port, "PING") == "PONG"
    except (OSError, RuntimeError, ValueError):
        return False


@contextmanager
def provide_redis_service(
    docker_service: DockerService,
    image: str,
    base_name: str,
    isolation_level: XdistIsolationLevel,
) -> Generator[RedisService, None, None]:
    """Start and yield a Redis-compatible service container.

    Args:
        docker_service: Docker service manager.
        image: Container image name.
        base_name: Base container name prefix.
        isolation_level: xdist isolation mode.

    Yields:
        A configured ``RedisService`` instance.
    """
    worker_num = get_xdist_worker_num()
    name = base_name
    db = 0
    if worker_num is not None:
        if isolation_level == "database":
            container_num = worker_num // 15
            if container_num > 0:
                name += f"_{container_num + 1}"
            db = worker_num % 15
        else:
            name += f"_{worker_num + 1}"

    with docker_service.run(
        image,
        check=redis_responsive,
        container_port=6379,
        name=name,
        transient=isolation_level == "server",
    ) as service:
        yield RedisService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db,
        )


def provide_deprecated_redis_client(
    service: RedisService,
    fixture_name: str,
    service_fixture_name: str,
) -> Generator[Redis, None, None]:
    """Yield a deprecated ``redis.Redis`` client while emitting a ``DeprecationWarning``.

    Args:
        service: Active Redis-compatible service container metadata.
        fixture_name: Name of the deprecated fixture requested by the caller.
        service_fixture_name: Replacement ``*_service`` fixture name.

    Yields:
        A connected ``redis.Redis`` client instance.
    """
    warnings.warn(
        f"The '{fixture_name}' fixture is deprecated and will be removed in a future release. "
        f"Use '{service_fixture_name}' and instantiate your own Redis client instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    redis_module = importlib.import_module("redis")
    client = redis_module.Redis(host=service.host, port=service.port, db=service.db)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def xdist_redis_isolation_level() -> XdistIsolationLevel:
    """Return the default pytest-xdist isolation level for Redis-family fixtures."""
    return "database"


@pytest.fixture(autouse=False, scope="session")
def redis_port(redis_service: RedisService) -> int:
    """Return the bound host port for the Redis service."""
    return redis_service.port


@pytest.fixture(autouse=False, scope="session")
def redis_host(redis_service: RedisService) -> str:
    """Return the reachable host address for the Redis service."""
    return redis_service.host


@pytest.fixture(autouse=False, scope="session")
def redis_image() -> str:
    """Return the container image tag for Redis."""
    return "redis:latest"


@pytest.fixture(autouse=False, scope="session")
def redis_service(
    docker_service: DockerService,
    redis_image: str,
    xdist_redis_isolation_level: XdistIsolationLevel,
) -> Generator[RedisService, None, None]:
    """Start and yield a session-scoped Redis service container.

    Yields:
        A running ``RedisService`` instance.
    """
    with provide_redis_service(docker_service, redis_image, "redis", xdist_redis_isolation_level) as service:
        yield service


@pytest.fixture(autouse=False, scope="function")
def redis_client(redis_service: RedisService) -> Generator[Redis, None, None]:
    """Yield a deprecated ``redis.Redis`` client connected to ``redis_service``.

    Yields:
        A connected ``redis.Redis`` client instance.
    """
    yield from provide_deprecated_redis_client(redis_service, "redis_client", "redis_service")


@pytest.fixture(autouse=False, scope="function")
def redis_connection(redis_service: RedisService) -> Generator[Redis, None, None]:
    """Yield a deprecated ``redis.Redis`` connection connected to ``redis_service``.

    Yields:
        A connected ``redis.Redis`` client instance.
    """
    yield from provide_deprecated_redis_client(redis_service, "redis_connection", "redis_service")


@pytest.fixture(autouse=False, scope="session")
def dragonfly_image() -> str:
    """Return the container image tag for Dragonfly."""
    return "docker.dragonflydb.io/dragonflydb/dragonfly"


@pytest.fixture(autouse=False, scope="session")
def dragonfly_service(
    docker_service: DockerService,
    dragonfly_image: str,
    xdist_redis_isolation_level: XdistIsolationLevel,
) -> Generator[RedisService, None, None]:
    """Start and yield a session-scoped Dragonfly service container.

    Yields:
        A running ``RedisService`` instance.
    """
    with provide_redis_service(docker_service, dragonfly_image, "dragonfly", xdist_redis_isolation_level) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def dragonfly_port(dragonfly_service: RedisService) -> int:
    """Return the bound host port for the Dragonfly service."""
    return dragonfly_service.port


@pytest.fixture(autouse=False, scope="session")
def dragonfly_host(dragonfly_service: RedisService) -> str:
    """Return the reachable host address for the Dragonfly service."""
    return dragonfly_service.host


@pytest.fixture(autouse=False, scope="function")
def dragonfly_client(dragonfly_service: RedisService) -> Generator[Redis, None, None]:
    """Yield a deprecated ``redis.Redis`` client connected to ``dragonfly_service``.

    Yields:
        A connected ``redis.Redis`` client instance.
    """
    yield from provide_deprecated_redis_client(dragonfly_service, "dragonfly_client", "dragonfly_service")


@pytest.fixture(autouse=False, scope="function")
def dragonfly_connection(dragonfly_service: RedisService) -> Generator[Redis, None, None]:
    """Yield a deprecated ``redis.Redis`` connection connected to ``dragonfly_service``.

    Yields:
        A connected ``redis.Redis`` client instance.
    """
    yield from provide_deprecated_redis_client(dragonfly_service, "dragonfly_connection", "dragonfly_service")


@pytest.fixture(autouse=False, scope="session")
def keydb_image() -> str:
    """Return the container image tag for KeyDB."""
    return "eqalpha/keydb"


@pytest.fixture(autouse=False, scope="session")
def keydb_service(
    docker_service: DockerService,
    keydb_image: str,
    xdist_redis_isolation_level: XdistIsolationLevel,
) -> Generator[RedisService, None, None]:
    """Start and yield a session-scoped KeyDB service container.

    Yields:
        A running ``RedisService`` instance.
    """
    with provide_redis_service(docker_service, keydb_image, "keydb", xdist_redis_isolation_level) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def keydb_port(keydb_service: RedisService) -> int:
    """Return the bound host port for the KeyDB service."""
    return keydb_service.port


@pytest.fixture(autouse=False, scope="session")
def keydb_host(keydb_service: RedisService) -> str:
    """Return the reachable host address for the KeyDB service."""
    return keydb_service.host


@pytest.fixture(autouse=False, scope="function")
def keydb_client(keydb_service: RedisService) -> Generator[Redis, None, None]:
    """Yield a deprecated ``redis.Redis`` client connected to ``keydb_service``.

    Yields:
        A connected ``redis.Redis`` client instance.
    """
    yield from provide_deprecated_redis_client(keydb_service, "keydb_client", "keydb_service")


@pytest.fixture(autouse=False, scope="function")
def keydb_connection(keydb_service: RedisService) -> Generator[Redis, None, None]:
    """Yield a deprecated ``redis.Redis`` connection connected to ``keydb_service``.

    Yields:
        A connected ``redis.Redis`` client instance.
    """
    yield from provide_deprecated_redis_client(keydb_service, "keydb_connection", "keydb_service")
