"""Redpanda container service fixtures and stdlib Kafka metadata probes."""

from __future__ import annotations

import contextlib
import os
import socket
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.runtime import default_host_from_base_url
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService

__all__ = [
    "DEFAULT_REDPANDA_IMAGE",
    "REDPANDA_EXTERNAL_PORT",
    "REDPANDA_INTERNAL_PORT",
    "RedpandaService",
    "fetch_kafka_brokers",
    "provide_redpanda_service",
    "redpanda_image",
    "redpanda_port",
    "redpanda_service",
    "xdist_redpanda_isolation_level",
]

DEFAULT_REDPANDA_IMAGE = "docker.redpanda.com/redpandadata/redpanda:v26.1.13"
REDPANDA_INTERNAL_PORT = 9092
REDPANDA_EXTERNAL_PORT = 19092
_KAFKA_METADATA_API_KEY = 3
_KAFKA_METADATA_API_VERSION = 0
_KAFKA_CORRELATION_ID = 1


@dataclass
class RedpandaService(ServiceContainer):
    """Metadata for a Kafka-compatible Redpanda broker."""

    bootstrap_servers: str
    topic_prefix: str


def fetch_kafka_brokers(host: str, port: int, *, timeout: float = 2.0) -> list[tuple[str, int]]:
    """Fetch advertised brokers from a Kafka-compatible listener using a v0 MetadataRequest.

    Args:
        host: Broker hostname or IP address.
        port: Mapped broker TCP port.
        timeout: Socket timeout in seconds.

    Returns:
        List of ``(advertised_host, advertised_port)`` tuples reported by the broker.
    """
    client_id = b"pytest-databases"
    payload = struct.pack(
        f">hhih{len(client_id)}si",
        _KAFKA_METADATA_API_KEY,
        _KAFKA_METADATA_API_VERSION,
        _KAFKA_CORRELATION_ID,
        len(client_id),
        client_id,
        0,
    )
    frame = struct.pack(">i", len(payload)) + payload
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(frame)
        size_bytes = _recv_exact(sock, 4)
        (response_size,) = struct.unpack(">i", size_bytes)
        if response_size <= 0 or response_size > 1_048_576:
            msg = f"Invalid Kafka metadata response size: {response_size}"
            raise ValueError(msg)
        body = _recv_exact(sock, response_size)

    if len(body) < 8:
        msg = "Truncated Kafka metadata response header"
        raise ValueError(msg)
    correlation_id, broker_count = struct.unpack(">ii", body[:8])
    if correlation_id != _KAFKA_CORRELATION_ID or broker_count <= 0:
        return []

    offset = 8
    brokers: list[tuple[str, int]] = []
    for _ in range(broker_count):
        if offset + 6 > len(body):
            break
        _node_id, host_len = struct.unpack(">ih", body[offset : offset + 6])
        offset += 6
        if host_len < 0 or offset + host_len + 4 > len(body):
            break
        broker_host = body[offset : offset + host_len].decode("utf-8", errors="replace")
        offset += host_len
        (broker_port,) = struct.unpack(">i", body[offset : offset + 4])
        offset += 4
        brokers.append((broker_host, broker_port))
    return brokers


@contextlib.contextmanager
def provide_redpanda_service(
    container_service: ContainerService,
    redpanda_image: str,
    redpanda_port: int | None,
    xdist_redpanda_isolation_level: XdistIsolationLevel,
) -> Generator[RedpandaService, None, None]:
    """Start and manage a clientless Redpanda service with reachable advertised metadata.

    Yields:
        Service metadata for the running Redpanda broker.
    """
    worker_num = get_xdist_worker_num()
    name = "redpanda"
    topic_prefix = "pytest_databases_"
    transient = False
    if worker_num is not None:
        if xdist_redpanda_isolation_level == "server":
            name = f"{name}_{worker_num}"
            topic_prefix = ""
            transient = True
        else:
            topic_prefix = f"pytest_databases_{worker_num}_"

    base_url = getattr(container_service, "base_url", None)
    advertised_host = (default_host_from_base_url(base_url) if isinstance(base_url, str) else None) or "127.0.0.1"
    target_port = redpanda_port if redpanda_port is not None else _allocate_free_port()
    ready = False
    attempts = 0
    last_output = b"Redpanda readiness was not attempted"

    def check(service: ServiceContainer) -> bool:
        nonlocal attempts, last_output, ready
        attempts += 1

        health = service.container.exec_run([
            "sh",
            "-c",
            f"timeout 5 rpk cluster health --exit-when-healthy -X brokers=127.0.0.1:{REDPANDA_INTERNAL_PORT}",
        ])
        last_output = exec_output_to_bytes(health.output)
        if health.exit_code != 0:
            if attempts >= 20:
                message = f"Redpanda rpk readiness failed: {last_output.decode(errors='replace').strip()}"
                raise RuntimeError(message)
            return False

        if not ready:
            try:
                brokers = fetch_kafka_brokers(service.host, service.port)
            except (OSError, ValueError) as exc:
                last_output = str(exc).encode("utf-8", errors="replace")
                return False
            if (service.host, service.port) not in brokers:
                last_output = repr(brokers).encode("utf-8", errors="replace")
                if attempts >= 20:
                    message = (
                        "Redpanda metadata did not advertise the mapped endpoint: "
                        f"{last_output.decode(errors='replace').strip()}"
                    )
                    raise RuntimeError(message)
                return False
            ready = True
        return True

    with container_service.run(
        image=redpanda_image,
        container_port=REDPANDA_EXTERNAL_PORT,
        name=name,
        command=_redpanda_command(target_port, advertised_host=advertised_host),
        check=check,
        timeout=120,
        pause=0.5,
        transient=transient,
        host_port=target_port,
    ) as service:
        yield RedpandaService(
            container=service.container,
            host=service.host,
            port=service.port,
            bootstrap_servers=f"{service.host}:{service.port}",
            topic_prefix=topic_prefix,
        )


@pytest.fixture(scope="session")
def redpanda_image() -> str:
    """Provide the pinned Redpanda image, optionally overridden by the environment.

    Returns:
        Redpanda container image reference.
    """
    return _resolve_redpanda_image()


@pytest.fixture(scope="session")
def redpanda_port() -> int | None:
    """Provide an optional host port override for the external Kafka listener.

    Returns:
        Explicit port number or None.
    """
    return _resolve_redpanda_port()


@pytest.fixture(scope="session")
def xdist_redpanda_isolation_level() -> XdistIsolationLevel:
    """Share one broker with worker topic prefixes by default.

    Returns:
        Default isolation level string.
    """
    return "database"


@pytest.fixture(scope="session")
def redpanda_service(
    container_service: ContainerService,
    redpanda_image: str,
    redpanda_port: int | None,
    xdist_redpanda_isolation_level: XdistIsolationLevel,
) -> Generator[RedpandaService, None, None]:
    """Start a clientless Redpanda service with reachable advertised metadata.

    Yields:
        Service metadata for the running Redpanda broker.
    """
    with provide_redpanda_service(
        container_service=container_service,
        redpanda_image=redpanda_image,
        redpanda_port=redpanda_port,
        xdist_redpanda_isolation_level=xdist_redpanda_isolation_level,
    ) as service:
        yield service


def _allocate_free_port(host: str = "127.0.0.1") -> int:
    """Allocate an available non-ephemeral TCP port on ``host``.

    Returns:
        Available TCP port number.

    Raises:
        RuntimeError: If no free port can be allocated.
    """
    base = 19100
    span = 10000
    offset = (os.getpid() * 37) % span
    for step in range(span):
        candidate = base + ((offset + step) % span)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, candidate))
        except OSError:
            continue
        return candidate
    msg = "Unable to allocate a free TCP port for Redpanda"
    raise RuntimeError(msg)


def _redpanda_command(advertised_port: int = REDPANDA_EXTERNAL_PORT, advertised_host: str = "127.0.0.1") -> str:
    """Build the ``rpk`` arguments that start a single-node development Redpanda broker.

    Returns:
        Command string for ``redpanda start``.
    """
    return " ".join([
        "redpanda",
        "start",
        "--mode",
        "dev-container",
        "--smp",
        "1",
        "--memory",
        "512M",
        "--reserve-memory",
        "0M",
        "--overprovisioned",
        "--kafka-addr",
        f"internal://0.0.0.0:{REDPANDA_INTERNAL_PORT},external://0.0.0.0:{REDPANDA_EXTERNAL_PORT}",
        "--advertise-kafka-addr",
        f"internal://127.0.0.1:{REDPANDA_INTERNAL_PORT},external://{advertised_host}:{advertised_port}",
        "--default-log-level=info",
    ])


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    """Read an exact byte count from a blocking socket.

    Returns:
        Exact byte sequence of length ``length``.

    Raises:
        OSError: If EOF is encountered before ``length`` bytes are read.
    """
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            msg = "Unexpected EOF while reading Kafka metadata response"
            raise OSError(msg)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _resolve_redpanda_image() -> str:
    """Resolve the Redpanda container image from the environment or default constant.

    Returns:
        Redpanda image tag.
    """
    return os.environ.get("REDPANDA_IMAGE", DEFAULT_REDPANDA_IMAGE)


def _resolve_redpanda_port() -> int | None:
    """Resolve an optional host port override for the external Kafka listener.

    Returns:
        Port number or None.
    """
    value = os.environ.get("REDPANDA_PORT")
    return int(value) if value else None
