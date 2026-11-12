"""Helper utilities for hashing, pytest-xdist worker discovery, HTTP probes, S3 provisioning, and Postgres templates."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import http.client
import json
import os
import platform
import re
import socket
import ssl
import tempfile
import time
import urllib.error
import urllib.request
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request

import filelock

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence

    import pytest

__all__ = (
    "BUCKET_EXISTS_CODES",
    "DEFAULT_REGION",
    "DEFAULT_TEMPLATE_NAME",
    "DEFAULT_WORKER_PREFIX",
    "EMPTY_PAYLOAD_SHA256",
    "IDENTIFIER_PATTERN",
    "MAX_IDENTIFIER_LENGTH",
    "SIGNED_HEADERS",
    "STAGING_SUFFIX",
    "TRUE_VALUES",
    "PostgresTemplateSupport",
    "SQLRunner",
    "build_bucket_request",
    "clone_database",
    "compute_fingerprint",
    "create_database_from_template",
    "create_s3_bucket",
    "derive_signing_key",
    "drop_database",
    "ensure_template",
    "env_port",
    "exec_output_to_bytes",
    "get_cpu_architecture",
    "get_xdist_worker_count",
    "get_xdist_worker_id",
    "get_xdist_worker_num",
    "http_get_json",
    "http_get_ok",
    "http_request",
    "is_fixture_registered",
    "make_connection_string",
    "read_init_scripts",
    "resolve_legacy_platform",
    "resolve_template_name",
    "run_container_init_once",
    "send_http_request",
    "simple_string_hash",
    "split_template_setup",
    "sweep_databases",
    "tcp_port_open",
    "validate_identifier",
)

TRUE_VALUES: set[str] = {"True", "true", "1", "yes", "y", "Y", "T", "on", "enabled", "ok"}
DEFAULT_REGION = "us-east-1"
EMPTY_PAYLOAD_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SIGNED_HEADERS = "host;x-amz-content-sha256;x-amz-date"
BUCKET_EXISTS_CODES = ("BucketAlreadyOwnedByYou", "BucketAlreadyExists")
DEFAULT_TEMPLATE_NAME = "pytest_databases_template"
DEFAULT_WORKER_PREFIX = "pytest_databases_"
STAGING_SUFFIX = "_staging"
MAX_IDENTIFIER_LENGTH = 63
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_RETRYABLE_HTTP_STATUS = 503
_RETRY_INTERVAL_SECONDS = 0.25
_LIBPQ_PLAIN_VALUE = re.compile(r"[^\s'\\]+")
_LOCK_SCOPE_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


class SQLRunner(Protocol):
    """Execute one SQL statement against ``database`` and return ``(exit_code, output)``."""

    def __call__(self, database: str, sql: str, *, tuples_only: bool = False) -> tuple[int, bytes]: ...


class PostgresTemplateSupport:
    """Clone, drop, and template methods shared by the PostgreSQL service dataclasses.

    Subclasses are dataclasses with ``host``, ``port``, and ``database`` fields and implement :meth:`_run_sql`.
    """

    host: str
    port: int
    database: str

    def clone_template_database(self, target_db: str, *, source_db: str | None = None) -> str:
        """Clone ``source_db`` (defaults to ``self.database``) into ``target_db``.

        Returns:
            The name of the created database.
        """
        return clone_database(self._run_sql, source=source_db or self.database, target=target_db)

    def drop_database_force(self, db_name: str) -> None:
        """Terminate active backends and drop ``db_name`` if it exists."""
        drop_database(self._run_sql, db_name)

    def ensure_template(
        self,
        template_name: str = DEFAULT_TEMPLATE_NAME,
        *,
        setup_fn: Callable[[Self], object] | None = None,
        setup_sql: str | Path | Sequence[str | Path] | None = None,
        init_sql: str | Path | Sequence[str | Path] | None = None,
        fingerprint_sources: Sequence[str | bytes | Path] = (),
        lock_dir: Path | str | None = None,
        lock_timeout: float = 180.0,
    ) -> str:
        """Build a template database once and return its name.

        The name is ``template_name`` plus a 12-character digest of ``init_sql``, ``setup_sql`` (SQL text and file
        contents), and ``fingerprint_sources``, so a changed setup builds a new template instead of reusing a stale one.
        A setup callable cannot be fingerprinted; list its inputs in ``fingerprint_sources``. A file lock in
        ``lock_dir`` (default: the system temp directory) scoped to this server makes concurrent workers build it only
        once.

        Args:
            template_name: Template name, or the name prefix when a digest is appended.
            setup_fn: Callable receiving a copy of this service pointed at the staging database.
            setup_sql: SQL statements or ``.sql`` file paths executed against the staging database.
            init_sql: Optional provider extension bootstrap statements or ``.sql`` paths executed strictly before
                ``setup_sql`` and ``setup_fn``.
            fingerprint_sources: Extra strings, bytes, files, or directories folded into the digest.
            lock_dir: Directory for the cross-process lock file.
            lock_timeout: Seconds to wait for the lock.

        Returns:
            The template database name.
        """
        return ensure_template(
            self._run_sql,
            template_name=template_name,
            setup_sql=_as_statements(setup_sql),
            init_sql=_as_statements(init_sql),
            setup_fn=None if setup_fn is None else lambda staging: setup_fn(self._with_database(staging)),
            fingerprint_sources=fingerprint_sources,
            lock_dir=lock_dir,
            lock_timeout=lock_timeout,
            lock_scope=f"{self.host}_{self.port}",
        )

    def create_worker_database_from_template(self, template_name: str, worker_db: str) -> str:
        """Drop ``worker_db`` if present and recreate it from ``template_name``.

        Returns:
            The name of the created database.
        """
        return create_database_from_template(self._run_sql, template=template_name, target=worker_db)

    def sweep_worker_databases(self, prefix: str = DEFAULT_WORKER_PREFIX) -> list[str]:
        """Drop non-template databases whose names start with ``prefix``.

        This is a session-end helper: it also drops databases that other workers are still using. Template and
        ``*_staging`` databases, ``postgres``, and this service's own database are kept.

        Returns:
            The dropped database names.
        """
        return sweep_databases(self._run_sql, prefix=prefix, exclude=(self.database, "postgres"))

    @staticmethod
    def compute_fingerprint(*sources: str | bytes | Path) -> str:
        """Compute a 12-character SHA-256 digest of strings, bytes, files, or directories.

        Returns:
            The lowercase hex digest.
        """
        return compute_fingerprint(*sources)

    def _with_database(self, database: str) -> Self:
        """Return a copy of this service pointed at ``database``.

        Returns:
            The copied service.
        """
        return dataclasses.replace(self, database=database)  # type: ignore[type-var]

    def _run_sql(self, database: str, sql: str, *, tuples_only: bool = False) -> tuple[int, bytes]:
        """Execute ``sql`` against ``database`` on this server.

        Raises:
            NotImplementedError: Always; service classes override it.
        """
        raise NotImplementedError


def exec_output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    """Normalize Docker ``exec_run`` output payloads into ``bytes``."""
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def is_fixture_registered(request: pytest.FixtureRequest, name: str) -> bool:
    """Return whether pytest has registered a fixture named ``name`` for the current node."""
    return bool(request.session._fixturemanager.getfixturedefs(name, request.node))


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


def send_http_request(
    url_or_request: str | urllib.request.Request,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Send an HTTP or HTTPS request bypassing environment proxies.

    When ``url_or_request`` is a :class:`urllib.request.Request`, the instance is opened directly without
    modifying its headers, body, or method so pre-signed AWS SigV4 and Azure SharedKey signatures stay intact.
    HTTP error responses are read and closed deterministically instead of raising :class:`urllib.error.HTTPError`.

    Args:
        url_or_request: Target ``http://`` or ``https://`` URL string or pre-built ``Request``.
        method: HTTP method when ``url_or_request`` is a URL string.
        data: Request body when ``url_or_request`` is a URL string.
        headers: Request headers when ``url_or_request`` is a URL string.
        timeout: Socket timeout in seconds.
        ssl_context: Optional TLS context for ``https://`` requests.

    Returns:
        Tuple of ``(status, headers, body)``.

    Raises:
        ValueError: If the target URL does not start with ``http://`` or ``https://``, or if ``data`` or
            ``headers`` are passed alongside a pre-built ``Request`` object.
    """
    if isinstance(url_or_request, urllib.request.Request):
        if data is not None or headers is not None:
            msg = "Cannot pass 'data' or 'headers' when 'url_or_request' is already a Request instance."
            raise ValueError(msg)
        target_url = url_or_request.full_url
        if not target_url.startswith(("http://", "https://")):
            msg = f"Only http:// and https:// URLs can be requested, got {target_url!r}"
            raise ValueError(msg)
        request = url_or_request
    else:
        if not url_or_request.startswith(("http://", "https://")):
            msg = f"Only http:// and https:// URLs can be requested, got {url_or_request!r}"
            raise ValueError(msg)
        request = urllib.request.Request(url_or_request, data=data, method=method, headers=dict(headers or {}))

    opener = (
        _DIRECT_OPENER
        if ssl_context is None
        else urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl_context),
        )
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            resp_headers = dict(response.headers.items()) if response.headers is not None else {}
            return int(response.status), resp_headers, response.read()
    except urllib.error.HTTPError as exc:
        try:
            err_headers = dict(exc.headers.items()) if exc.headers is not None else {}
            return int(exc.code), err_headers, exc.read()
        finally:
            exc.close()


def http_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    ssl_context: ssl.SSLContext | None = None,
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
        ssl_context: Optional TLS context for ``https://`` requests.

    Returns:
        Tuple of ``(status, body)``.

    Raises:
        ValueError: If ``url`` is not an ``http://`` or ``https://`` URL.
    """
    status, _resp_headers, body = send_http_request(
        url,
        method=method,
        data=data,
        headers=headers,
        timeout=timeout,
        ssl_context=ssl_context,
    )
    return status, body


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


def derive_signing_key(secret_key: str, *, date_stamp: str, region: str, service: str) -> bytes:
    """Derive an AWS Signature Version 4 signing key.

    Args:
        secret_key: Secret access key.
        date_stamp: Request date as ``YYYYMMDD``.
        region: Signing region.
        service: Signing service name.

    Returns:
        The derived signing key.
    """
    key_date = hmac.new(f"AWS4{secret_key}".encode(), date_stamp.encode(), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region.encode(), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode(), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def build_bucket_request(
    method: str,
    endpoint_url: str,
    bucket_name: str,
    *,
    access_key: str,
    secret_key: str,
    region: str = DEFAULT_REGION,
    timestamp: datetime | None = None,
) -> Request:
    """Build a SigV4-signed path-style bucket request with an empty body.

    Args:
        method: HTTP method, such as ``PUT`` to create the bucket or ``HEAD`` to check that it exists.
        endpoint_url: ``http`` or ``https`` endpoint of the S3 service. A path, such as ``/cdn-cgi/local/r2/s3``,
            is kept as the prefix of the bucket path.
        bucket_name: Target bucket.
        access_key: Access key ID.
        secret_key: Secret access key.
        region: Signing region.
        timestamp: Signing time; defaults to the current UTC time.

    Returns:
        The signed request.

    Raises:
        ValueError: If ``endpoint_url`` is not an absolute ``http`` or ``https`` URL.
    """
    parsed = urlsplit(endpoint_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"S3 endpoint_url must be a valid http(s) URL, got {endpoint_url!r}"
        raise ValueError(msg)

    signed_at = (timestamp or datetime.now(UTC)).astimezone(UTC)
    amz_date = signed_at.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = signed_at.strftime("%Y%m%d")
    canonical_uri = f"{parsed.path.rstrip('/')}/{bucket_name}"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    canonical_headers = f"host:{parsed.netloc}\nx-amz-content-sha256:{EMPTY_PAYLOAD_SHA256}\nx-amz-date:{amz_date}\n"
    canonical_request = f"{method}\n{canonical_uri}\n\n{canonical_headers}\n{SIGNED_HEADERS}\n{EMPTY_PAYLOAD_SHA256}"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    signing_key = derive_signing_key(secret_key, date_stamp=date_stamp, region=region, service="s3")
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={SIGNED_HEADERS}, Signature={signature}"
        ),
        "Content-Length": "0",
        "x-amz-content-sha256": EMPTY_PAYLOAD_SHA256,
        "x-amz-date": amz_date,
    }
    return Request(f"{parsed.scheme}://{parsed.netloc}{canonical_uri}", data=None, method=method, headers=headers)


def create_s3_bucket(
    endpoint_url: str,
    bucket_name: str,
    *,
    access_key: str,
    secret_key: str,
    region: str = DEFAULT_REGION,
    timeout: float = 10.0,
    ssl_context: ssl.SSLContext | None = None,
) -> bool:
    """Create a bucket idempotently with a SigV4-signed HTTP ``PUT`` bypassing proxies.

    An existing bucket returns ``False`` instead of raising an error. Transient HTTP ``503`` responses
    (such as RustFS waiting for storage quorum) are retried until ``timeout`` elapses. ``https`` endpoints
    default to an unverified TLS context when ``ssl_context`` is ``None`` because targets are typically local
    emulators with self-signed certificates.

    Args:
        endpoint_url: ``http`` or ``https`` endpoint of the S3 service.
        bucket_name: Bucket to create.
        access_key: Access key ID.
        secret_key: Secret access key.
        region: Signing region.
        timeout: Socket and retry deadline timeout in seconds.
        ssl_context: Optional TLS context for ``https`` endpoints.

    Returns:
        ``True`` when the bucket is newly created (HTTP ``200`` or ``204``), and ``False`` when it already
        exists (HTTP ``409`` carrying ``BucketAlreadyOwnedByYou`` or ``BucketAlreadyExists``).

    Raises:
        RuntimeError: If the service rejects the request or cannot be reached.
    """
    request = build_bucket_request(
        "PUT", endpoint_url, bucket_name, access_key=access_key, secret_key=secret_key, region=region
    )
    context = (
        ssl_context
        if ssl_context is not None
        else (_unverified_ssl_context() if request.full_url.startswith("https:") else None)
    )
    deadline = time.monotonic() + timeout
    attempt_timeout = timeout
    while True:
        try:
            status, _headers, raw_body = send_http_request(request, timeout=attempt_timeout, ssl_context=context)
        except (URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            msg = f"Failed to create bucket {bucket_name!r} on {endpoint_url}: {exc}"
            raise RuntimeError(msg) from exc
        if status in {200, 204}:
            return True
        body = raw_body.decode("utf-8", errors="replace")
        if status == 409 and any(code in body for code in BUCKET_EXISTS_CODES):
            return False
        if status == _RETRYABLE_HTTP_STATUS:
            now = time.monotonic()
            if now < deadline:
                time.sleep(_RETRY_INTERVAL_SECONDS)
                attempt_timeout = max(0.05, deadline - now)
                request = build_bucket_request(
                    "PUT", endpoint_url, bucket_name, access_key=access_key, secret_key=secret_key, region=region
                )
                continue
        msg = f"Failed to create bucket {bucket_name!r}: HTTP {status}" + (f" - {body}" if body else "")
        raise RuntimeError(msg)


def validate_identifier(identifier: str) -> str:
    """Return ``identifier`` if it is a plain PostgreSQL identifier of at most 63 characters.

    Returns:
        The unchanged identifier.

    Raises:
        ValueError: If the identifier contains anything other than letters, digits, ``_``, or ``$``.
    """
    if len(identifier) > MAX_IDENTIFIER_LENGTH or IDENTIFIER_PATTERN.fullmatch(identifier) is None:
        msg = f"Invalid PostgreSQL database identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier


def make_connection_string(host: str, port: int, user: str, password: str, database: str) -> str:
    """Format a libpq keyword/value connection string.

    Values containing whitespace, quotes, or backslashes are single-quoted and escaped; empty values are omitted.

    Returns:
        The connection string.
    """
    pairs = (("dbname", database), ("user", user), ("host", host), ("port", str(port)), ("password", password))
    return " ".join(f"{key}={_quote_libpq_value(value)}" for key, value in pairs if value)


def compute_fingerprint(*sources: str | bytes | Path) -> str:
    """Compute a 12-character SHA-256 digest of strings, bytes, files, or directories.

    A ``str`` naming an existing path is hashed as that path; any other ``str`` is hashed as text.

    Returns:
        The lowercase hex digest.
    """
    hasher = hashlib.sha256()
    for source in sources:
        if isinstance(source, bytes):
            hasher.update(b"bytes:")
            hasher.update(source)
            continue
        path = Path(source)
        if path.exists():
            _hash_path(hasher, path)
        elif isinstance(source, Path):
            hasher.update(b"path:")
            hasher.update(str(source).encode())
        else:
            hasher.update(b"str:")
            hasher.update(source.encode())
    return hasher.hexdigest()[:12]


def split_template_setup(
    setup: Callable[[Any], object] | str | Path | Sequence[str | Path] | None,
) -> tuple[Callable[[Any], object] | None, str | Path | Sequence[str | Path] | None]:
    """Split a fixture-style template setup into ``(setup_fn, setup_sql)``.

    Returns:
        The callable (or None) and the SQL statements or paths (or None).
    """
    if callable(setup):
        return setup, None
    return None, setup


def resolve_template_name(
    template_name: str = DEFAULT_TEMPLATE_NAME,
    *,
    setup_sql: Sequence[str | Path] = (),
    init_sql: Sequence[str | Path] = (),
    fingerprint_sources: Sequence[str | bytes | Path] = (),
) -> str:
    """Return ``template_name`` with a digest of the init SQL, setup SQL, and fingerprint sources appended.

    Returns:
        The validated template name.
    """
    sources: list[str | bytes | Path] = []
    for statement in init_sql:
        sources.extend((b"init:", statement if isinstance(statement, Path) else statement.encode()))
    sources.extend(statement if isinstance(statement, Path) else statement.encode() for statement in setup_sql)
    sources.extend(fingerprint_sources)
    if not sources:
        return validate_identifier(template_name)
    return validate_identifier(f"{template_name}_{compute_fingerprint(*sources)}")


def drop_database(run_sql: SQLRunner, database: str) -> None:
    """Terminate backends connected to ``database`` and drop it if it exists.

    Raises:
        RuntimeError: If ``DROP DATABASE`` fails.
    """
    name = validate_identifier(database)
    _terminate_backends(run_sql, name)
    _require_success(run_sql("postgres", f'DROP DATABASE IF EXISTS "{name}";'), f"Failed to drop database {name!r}")


def clone_database(run_sql: SQLRunner, *, source: str, target: str) -> str:
    """Create ``target`` with ``CREATE DATABASE ... TEMPLATE source`` after disconnecting ``source`` sessions.

    Returns:
        The target database name.

    Raises:
        RuntimeError: If ``CREATE DATABASE`` fails.
    """
    source_name = validate_identifier(source)
    target_name = validate_identifier(target)
    _terminate_backends(run_sql, source_name)
    _require_success(
        run_sql("postgres", f'CREATE DATABASE "{target_name}" TEMPLATE "{source_name}";'),
        f"Failed to clone template database {source_name!r} to {target_name!r}",
    )
    return target_name


def create_database_from_template(run_sql: SQLRunner, *, template: str, target: str) -> str:
    """Drop ``target`` if present, recreate it from ``template``, and verify it accepts connections.

    ``CREATE DATABASE`` cannot run inside a transaction block, so it is sent on its own. The clone gets
    ``datallowconn = true`` by default even though the template has connections disabled.

    Returns:
        The target database name.

    Raises:
        RuntimeError: If the clone or the verification query fails.
    """
    template_name = validate_identifier(template)
    target_name = validate_identifier(target)
    drop_database(run_sql, target_name)
    _require_success(
        run_sql("postgres", f'CREATE DATABASE "{target_name}" TEMPLATE "{template_name}";'),
        f"Failed to clone template database {template_name!r} into {target_name!r}",
    )
    exit_code, output = run_sql(target_name, "SELECT 1", tuples_only=True)
    if exit_code != 0 or output.strip() != b"1":
        msg = f"Verification SELECT against {target_name!r} failed: {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)
    return target_name


def ensure_template(
    run_sql: SQLRunner,
    *,
    template_name: str = DEFAULT_TEMPLATE_NAME,
    setup_sql: Sequence[str | Path] = (),
    init_sql: Sequence[str | Path] = (),
    setup_fn: Callable[[str], object] | None = None,
    fingerprint_sources: Sequence[str | bytes | Path] = (),
    lock_dir: Path | str | None = None,
    lock_timeout: float = 180.0,
    lock_scope: str = "",
) -> str:
    """Build a template database once and return its name.

    The template is built in ``<name>_staging`` (``init_sql``, then ``setup_sql``, then ``setup_fn(staging_name)``),
    marked ``is_template = true allow_connections = false``, and renamed. An existing template with the same name is
    reused; the double-checked file lock makes concurrent callers build it only once.

    Returns:
        The template database name.

    Raises:
        RuntimeError: If a setup statement or a DDL step fails.
    """
    name = resolve_template_name(
        template_name,
        setup_sql=setup_sql,
        init_sql=init_sql,
        fingerprint_sources=fingerprint_sources,
    )
    staging = validate_identifier(f"{name}{STAGING_SUFFIX}")
    if _template_exists(run_sql, name):
        return name
    lock_base = Path(lock_dir) if lock_dir is not None else Path(tempfile.gettempdir())
    lock_base.mkdir(parents=True, exist_ok=True)
    scope = _LOCK_SCOPE_UNSAFE.sub("_", lock_scope).strip("_")
    lock_path = lock_base / f"pytest_databases_tpl_{scope + '_' if scope else ''}{name}.lock"
    with filelock.FileLock(str(lock_path), timeout=lock_timeout):
        if _template_exists(run_sql, name):
            return name
        drop_database(run_sql, staging)
        _require_success(
            run_sql("postgres", f'CREATE DATABASE "{staging}";'), f"Failed to create staging database {staging!r}"
        )
        try:
            _build_template(
                run_sql,
                staging=staging,
                name=name,
                init_sql=init_sql,
                setup_sql=setup_sql,
                setup_fn=setup_fn,
            )
        except BaseException:
            _drop_staging(run_sql, staging)
            raise
    return name


def sweep_databases(run_sql: SQLRunner, *, prefix: str, exclude: Collection[str] = ()) -> list[str]:
    """Drop non-template databases whose names start with ``prefix``.

    ``_`` in the prefix is matched literally, and ``*_staging`` databases and names in ``exclude`` are kept.

    Returns:
        The dropped database names.

    Raises:
        RuntimeError: If listing the databases fails.
    """
    safe_prefix = validate_identifier(prefix)
    query = (
        "SELECT datname FROM pg_database "
        f"WHERE datname LIKE '{_escape_like(safe_prefix)}%' ESCAPE '\\' "
        f"AND datname NOT LIKE '%{_escape_like(STAGING_SUFFIX)}' ESCAPE '\\' "
        "AND datistemplate = false ORDER BY datname;"
    )
    exit_code, output = run_sql("postgres", query, tuples_only=True)
    _require_success((exit_code, output), f"Failed to list databases matching {safe_prefix!r}")
    dropped: list[str] = []
    for name in _decode_names(output.splitlines()):
        if name in exclude:
            continue
        drop_database(run_sql, name)
        dropped.append(name)
    return dropped


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


def _unverified_ssl_context() -> ssl.SSLContext:
    """Return a TLS context that skips certificate and hostname verification.

    Returns:
        The TLS context.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _as_statements(setup_sql: str | Path | Sequence[str | Path] | None) -> tuple[str | Path, ...]:
    """Normalize ``setup_sql`` into a tuple of statements and paths.

    Returns:
        The statements and paths in order.
    """
    if setup_sql is None:
        return ()
    if isinstance(setup_sql, (str, Path)):
        return (setup_sql,)
    return tuple(setup_sql)


def _build_template(
    run_sql: SQLRunner,
    *,
    staging: str,
    name: str,
    setup_sql: Sequence[str | Path],
    setup_fn: Callable[[str], object] | None,
    init_sql: Sequence[str | Path] = (),
) -> None:
    """Run init SQL and setup in the existing ``staging`` database, mark it as a template, and rename it."""
    for statement in init_sql:
        sql = statement.read_text(encoding="utf-8") if isinstance(statement, Path) else statement
        _require_success(run_sql(staging, sql), f"Template init SQL failed on {staging!r}")
    for statement in setup_sql:
        sql = statement.read_text(encoding="utf-8") if isinstance(statement, Path) else statement
        _require_success(run_sql(staging, sql), f"Template setup SQL failed on {staging!r}")
    if setup_fn is not None:
        setup_fn(staging)
    _terminate_backends(run_sql, staging)
    _require_success(
        run_sql("postgres", f'ALTER DATABASE "{staging}" WITH is_template = true allow_connections = false;'),
        f"Failed to mark {staging!r} as a template",
    )
    drop_database(run_sql, name)
    _require_success(
        run_sql("postgres", f'ALTER DATABASE "{staging}" RENAME TO "{name}";'),
        f"Failed to rename {staging!r} to {name!r}",
    )


def _decode_names(lines: Iterable[bytes]) -> list[str]:
    """Decode ``psql -tA`` output lines into valid identifiers, skipping anything else.

    Returns:
        The decoded names.
    """
    names: list[str] = []
    for line in lines:
        name = line.decode(errors="replace").strip()
        if name and len(name) <= MAX_IDENTIFIER_LENGTH and IDENTIFIER_PATTERN.fullmatch(name):
            names.append(name)
    return names


def _drop_staging(run_sql: SQLRunner, staging: str) -> None:
    """Drop a half-built staging database, keeping the original error if the drop fails too."""
    try:
        drop_database(run_sql, staging)
    except RuntimeError:
        return


def _escape_like(value: str) -> str:
    """Escape ``LIKE`` wildcards (``_`` and ``%``) with a backslash.

    Returns:
        The escaped pattern fragment.
    """
    return value.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")


def _hash_path(hasher: Any, path: Path) -> None:
    """Feed a file, or every file below a directory in sorted order, into ``hasher``."""
    if path.is_file():
        hasher.update(b"file:")
        hasher.update(path.name.encode())
        hasher.update(path.read_bytes())
        return
    hasher.update(b"dir:")
    hasher.update(path.name.encode())
    for entry in sorted(path.rglob("*")):
        if entry.is_file():
            hasher.update(entry.relative_to(path).as_posix().encode())
            hasher.update(entry.read_bytes())


def _quote_libpq_value(value: str) -> str:
    """Quote a libpq connection string value when it is not a plain token.

    Returns:
        The value, single-quoted and escaped when needed.
    """
    if _LIBPQ_PLAIN_VALUE.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _require_success(result: tuple[int, bytes], message: str) -> None:
    """Raise ``RuntimeError`` with the ``psql`` output when ``result`` has a non-zero exit code.

    Raises:
        RuntimeError: If the exit code is not zero.
    """
    exit_code, output = result
    if exit_code != 0:
        msg = f"{message}: {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)


def _template_exists(run_sql: SQLRunner, name: str) -> bool:
    """Return whether ``name`` exists and is marked as a template.

    Returns:
        True when the template exists.
    """
    exit_code, output = run_sql(
        "postgres", f"SELECT 1 FROM pg_database WHERE datname = '{name}' AND datistemplate = true;", tuples_only=True
    )
    return exit_code == 0 and output.strip() == b"1"


def _terminate_backends(run_sql: SQLRunner, database: str) -> None:
    """Terminate every other session connected to ``database``."""
    run_sql(
        "postgres",
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{database}' "
        "AND pid <> pg_backend_pid();",
    )
