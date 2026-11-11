"""Helper utilities for hashing, pytest-xdist worker discovery, container output, and port and HTTP probes."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import platform
import socket
import tempfile
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import filelock

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    import pytest

__all__ = (
    "TRUE_VALUES",
    "env_port",
    "exec_output_to_bytes",
    "get_cpu_architecture",
    "get_xdist_worker_count",
    "get_xdist_worker_id",
    "get_xdist_worker_num",
    "http_get_json",
    "http_get_ok",
    "http_request",
    "read_init_scripts",
    "resolve_legacy_platform",
    "run_container_init_once",
    "simple_string_hash",
    "tcp_port_open",
)

TRUE_VALUES: set[str] = {"True", "true", "1", "yes", "y", "Y", "T", "on", "enabled", "ok"}
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def exec_output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    """Normalize Docker ``exec_run`` output payloads into ``bytes``."""
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def simple_string_hash(string_to_hash: str) -> str:
    """Generate a deterministic 12-character SHA-256 hex digest prefix."""
    return hashlib.sha256(string_to_hash.encode("utf-8")).hexdigest()[:12]


def get_xdist_worker_id() -> str | None:
    """Return the active ``pytest-xdist`` worker identifier, if any."""
    return os.getenv("PYTEST_XDIST_WORKER")


def get_xdist_worker_num() -> int | None:
    """Return the numeric ``pytest-xdist`` worker index, or ``None`` on master."""
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return None
    return int(worker_id.replace("gw", ""))


def get_xdist_worker_count() -> int:
    """Return the configured ``pytest-xdist`` worker count."""
    return int(os.getenv("PYTEST_XDIST_WORKER_COUNT", "0"))


def get_cpu_architecture() -> Literal["x86_64", "arm", "unknown"]:
    """Detect whether the host CPU architecture is ``x86_64``, ``arm``, or ``unknown``."""
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine.startswith(("arm", "aarch")):
        return "arm"
    return "unknown"


def tcp_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return whether a TCP connection to ``host:port`` can be opened from the test process.

    Readiness checks that run inside the container do not prove that the published host port is forwarded yet
    (rootless Podman, gvproxy, or Docker Desktop), so callers combine them with this probe.

    Args:
        host: Host name or IP address to connect to.
        port: TCP port to connect to.
        timeout: Connection timeout in seconds.

    Returns:
        True when the connection succeeds, otherwise False.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_get_ok(url: str, *, timeout: float = 2.0) -> bool:
    """Return whether an HTTP ``GET`` of ``url`` answers with status 200.

    Connection errors, timeouts, HTTP error statuses, and malformed responses count as not ready. HTTP error
    responses are closed so probes that run in a loop do not leak sockets.

    Args:
        url: URL to request.
        timeout: Socket timeout in seconds.

    Returns:
        True when the response status is 200, otherwise False.
    """
    return _http_get(url, timeout=timeout) is not None


def http_get_json(url: str, *, timeout: float = 2.0) -> Any | None:
    """Return the decoded JSON body of an HTTP ``GET`` of ``url`` that answers with status 200.

    Args:
        url: URL to request.
        timeout: Socket timeout in seconds.

    Returns:
        The decoded JSON document, or None when the request fails, the status is not 200, or the body is not JSON.
    """
    body = _http_get(url, timeout=timeout)
    if body is None:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def resolve_legacy_platform(request: pytest.FixtureRequest, replacement: str | None, default: str | None) -> str | None:
    """Return a user override of the bare ``platform`` fixture, or ``default``.

    Up to v0.19.0 the MySQL, Dolt, and BigQuery services requested a fixture named ``platform``. The
    ``<backend>_platform`` fixtures replace it, and this function keeps a ``platform`` override defined
    outside ``pytest_databases`` (for example in a ``conftest.py``) working until v1.0.0. When such an
    override is visible from the requesting test, it emits one ``DeprecationWarning`` and returns the
    override's value.

    Args:
        request: The ``request`` of the fixture that used to depend on ``platform``.
        replacement: Fixture to override instead, or None when the image is multi-arch and needs no platform.
        default: Value to return when ``platform`` is not overridden.

    Returns:
        The overriding ``platform`` value, or ``default``.
    """
    fixturedefs = request._fixturemanager.getfixturedefs("platform", request._pyfuncitem)
    if not fixturedefs or fixturedefs[-1].func.__module__.startswith("pytest_databases."):
        return default
    guidance = (
        f"Override '{replacement}' instead."
        if replacement is not None
        else "The image is multi-arch, so remove the override; it is ignored from v1.0.0."
    )
    warnings.warn(
        f"Overriding the 'platform' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. {guidance}",
        DeprecationWarning,
        stacklevel=2,
    )
    return request.getfixturevalue("platform")


def http_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    """Send an HTTP request to a container endpoint and return its status and body.

    Like the probes, the request bypasses ``HTTP_PROXY`` / ``HTTPS_PROXY``. HTTP error statuses are returned instead of
    raised, and their response is closed after the body is read.

    Args:
        url: ``http://`` or ``https://`` URL to request.
        method: HTTP method.
        data: Request body, or None to send no body.
        headers: Request headers.
        timeout: Socket timeout in seconds.

    Returns:
        Tuple of ``(status, body)``.

    Raises:
        ValueError: If ``url`` is not an ``http://`` or ``https://`` URL.
    """
    if not url.startswith(("http://", "https://")):
        msg = f"Only http:// and https:// URLs can be requested, got {url!r}"
        raise ValueError(msg)
    request = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    try:
        with _DIRECT_OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()
        finally:
            exc.close()


def env_port(var_name: str) -> int | None:
    """Return an integer TCP port from environment variable ``var_name`` when set and non-empty.

    Args:
        var_name: Environment variable name to inspect.

    Returns:
        Parsed integer port, or ``None`` when unset or empty.

    Raises:
        ValueError: If the environment variable is non-integer or outside ``1..65535``.
    """
    value = os.environ.get(var_name)
    if not value:
        return None
    port = int(value)
    if port < 1 or port > 65535:
        msg = f"{var_name} must be between 1 and 65535, got {port}."
        raise ValueError(msg)
    return port


def read_init_scripts(scripts: str | Path | Sequence[str | Path] | None) -> tuple[str, ...]:
    """Normalize initialization SQL/JS statements and script file paths into non-empty UTF-8 strings.

    ``Path`` entries are read from disk as UTF-8 text; ``str`` entries are treated as literal script
    statements so multiline SQL or JS text never collides with filesystem lookups.

    Args:
        scripts: Single statement string, ``Path`` to a script file, sequence of strings/paths, or ``None``.

    Returns:
        Ordered tuple of non-empty script strings.
    """
    if scripts is None:
        return ()
    items: Sequence[str | Path] = (scripts,) if isinstance(scripts, (str, Path)) else scripts
    resolved: list[str] = []
    for item in items:
        content = item.read_text(encoding="utf-8") if isinstance(item, Path) else item
        if content.strip():
            resolved.append(content)
    return tuple(resolved)


def run_container_init_once(
    container: object,
    scope: str,
    fingerprint: str,
    action: Callable[[], None],
    *,
    timeout: float = 180.0,
    lock_dir: Path | str | None = None,
) -> bool:
    """Execute ``action`` at most once per ``(container.id, scope, fingerprint)`` across workers.

    When ``container.id`` is not a non-empty string (for example on lightweight unit-test doubles),
    ``action`` runs directly without creating lock or marker files on disk.

    Args:
        container: Container handle exposing an ``id`` attribute, or an external endpoint identifier string.
        scope: Logical resource scope inside the container (such as ``"mysql:db_0"`` or ``"sybase:mda"``).
        fingerprint: Digest or key distinguishing distinct initialization payloads on the same scope.
        action: Callback performing the initialization work; exceptions propagate without writing the marker.
        timeout: Maximum seconds to wait for the cross-worker file lock.
        lock_dir: Optional directory for lock and completion marker files.

    Returns:
        ``True`` when ``action`` executed in this call, ``False`` when a prior caller already completed it.
    """
    container_id = container if isinstance(container, str) else getattr(container, "id", None)
    if not isinstance(container_id, str) or not container_id:
        action()
        return True
    key = simple_string_hash(f"{container_id}:{scope}:{fingerprint}")
    base_dir = Path(lock_dir) if lock_dir is not None else Path(tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)
    done_path = base_dir / f"pytest-databases-init-{key}.done"
    if done_path.exists():
        return False
    lock_path = base_dir / f"pytest-databases-init-{key}.lock"
    with filelock.FileLock(str(lock_path), timeout=timeout):
        if done_path.exists():
            return False
        action()
        done_path.write_text("ok\n", encoding="utf-8")
        return True


def _http_get(url: str, *, timeout: float) -> bytes | None:
    """Return the body of an HTTP ``GET`` of ``url`` when it answers with status 200, otherwise None.

    Raises:
        ValueError: If ``url`` is not an ``http://`` or ``https://`` URL.
    """
    try:
        status, body = http_request(url, timeout=timeout)
    except (OSError, http.client.HTTPException):
        return None
    return body if status == 200 else None
