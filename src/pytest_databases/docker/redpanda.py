from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from docker.errors import ContainerError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService


DEFAULT_REDPANDA_IMAGE = "docker.redpanda.com/redpandadata/redpanda:v26.1.13"
REDPANDA_INTERNAL_PORT = 9092
REDPANDA_EXTERNAL_PORT = 19092
REDPANDA_PORT_FILE = "/var/lib/redpanda/data/.pytest-databases-host-port"


@dataclass
class RedpandaService(ServiceContainer):
    """Metadata for a Kafka-compatible Redpanda broker."""

    bootstrap_servers: str
    topic_prefix: str


def _redpanda_command() -> list[str]:
    """Delay broker startup until the mapped host port can be advertised."""
    script = "\n".join([
        "set -eu",
        f'while [ ! -s "{REDPANDA_PORT_FILE}" ]; do sleep 0.1; done',
        f'advertised_port="$(cat {REDPANDA_PORT_FILE})"',
        "exec rpk redpanda start \\",
        "  --mode dev-container \\",
        "  --smp 1 \\",
        f"  --kafka-addr internal://0.0.0.0:{REDPANDA_INTERNAL_PORT},external://0.0.0.0:{REDPANDA_EXTERNAL_PORT} \\",
        (
            f"  --advertise-kafka-addr internal://127.0.0.1:{REDPANDA_INTERNAL_PORT},"
            "external://127.0.0.1:${advertised_port} \\"
        ),
        "  --default-log-level=info",
    ])
    return ["-c", script]


def _output_to_bytes(output: object) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return str(output).encode()


@pytest.fixture(scope="session")
def redpanda_image() -> str:
    """Return the pinned Redpanda image, optionally overridden by the environment."""
    return os.environ.get("REDPANDA_IMAGE", DEFAULT_REDPANDA_IMAGE)


@pytest.fixture(scope="session")
def redpanda_port() -> int | None:
    """Return an optional host port override for the external Kafka listener."""
    value = os.environ.get("REDPANDA_PORT")
    return int(value) if value else None


@pytest.fixture(scope="session")
def xdist_redpanda_isolation_level() -> XdistIsolationLevel:
    """Share one broker with worker topic prefixes by default."""
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

    port_injected = False
    ready = False
    attempts = 0
    last_output = b"Redpanda readiness was not attempted"

    def check(service: ServiceContainer) -> bool:
        nonlocal attempts, last_output, port_injected, ready
        attempts += 1
        if not port_injected:
            result = service.container.exec_run([
                "sh",
                "-c",
                f"printf '%s' {service.port} > {REDPANDA_PORT_FILE}",
            ])
            last_output = _output_to_bytes(result.output)
            if result.exit_code != 0:
                return False
            port_injected = True

        health = service.container.exec_run([
            "sh",
            "-c",
            (f"timeout 5 rpk cluster health --exit-when-healthy -X brokers=127.0.0.1:{REDPANDA_INTERNAL_PORT}"),
        ])
        last_output = _output_to_bytes(health.output)
        if health.exit_code != 0:
            if attempts >= 20:
                message = f"Redpanda rpk readiness failed: {last_output.decode(errors='replace').strip()}"
                raise RuntimeError(message)
            return False

        if not ready:
            bootstrap_servers = f"{service.host}:{service.port}"
            try:
                external_info = container_service.run_container(
                    redpanda_image,
                    service_name=f"{name}-external-readiness",
                    entrypoint=["rpk"],
                    command=["cluster", "info", "-X", f"brokers={bootstrap_servers}"],
                    network_mode="host",
                    remove=True,
                )
            except ContainerError as error:
                last_output = _output_to_bytes(error.stderr or str(error))
                return False
            last_output = _output_to_bytes(external_info)
            expected_host, _, expected_port = bootstrap_servers.partition(":")
            if expected_host.encode() not in last_output or expected_port.encode() not in last_output:
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
        command=_redpanda_command(),
        entrypoint=["/bin/sh"],
        check=check,
        timeout=120,
        pause=0.5,
        transient=transient,
        host_port=redpanda_port,
    ) as service:
        yield RedpandaService(
            container=service.container,
            host=service.host,
            port=service.port,
            bootstrap_servers=f"{service.host}:{service.port}",
            topic_prefix=topic_prefix,
        )
