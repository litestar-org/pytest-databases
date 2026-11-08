"""Cloudflare KV, R2, and D1 emulator fixtures backed by Miniflare's Local Explorer API.

The container runs `Miniflare <https://github.com/cloudflare/workers-sdk/tree/main/packages/miniflare>`_ in a stock
``node`` image with one placeholder Worker that binds every configured KV namespace, R2 bucket, and D1 database. The
fixtures and the service helpers talk to Miniflare over HTTP with the standard library:

* ``/cdn-cgi/local/explorer/api``: the Local Explorer API, which answers with the Cloudflare v4 JSON envelope
  (``{"success": ..., "errors": [...], "messages": [...], "result": ...}``).
* ``/cdn-cgi/local/r2/s3``: an S3-compatible endpoint for the R2 buckets (AWS Signature Version 4, path-style
  addressing, region ``auto``) that accepts the configured access key pair.

Only Miniflare 5 serves these paths; Miniflare 4 routes them to the user Worker. On first start the container installs
``ca-certificates`` (``workerd`` needs system CA certificates) and ``miniflare`` from npm, so it needs network access;
an image that already provides both skips the installs.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_count, get_xdist_worker_num, http_get_json, http_request
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from pytest_databases._service import ContainerService

__all__ = (
    "CLOUDFLARE_PORT",
    "DEFAULT_CLOUDFLARE_IMAGE",
    "DEFAULT_MINIFLARE_VERSION",
    "LOCAL_EXPLORER_PATH",
    "R2_S3_PATH",
    "R2_S3_REGION",
    "CloudflareService",
    "cloudflare_access_key_id",
    "cloudflare_d1_databases",
    "cloudflare_image",
    "cloudflare_kv_namespaces",
    "cloudflare_miniflare_version",
    "cloudflare_r2_buckets",
    "cloudflare_secret_access_key",
    "cloudflare_service",
    "cloudflare_startup_timeout",
    "provide_cloudflare_service",
    "xdist_cloudflare_isolation_level",
)

DEFAULT_CLOUDFLARE_IMAGE = "node:22-slim"
DEFAULT_MINIFLARE_VERSION = "5.20261104.0-beta"
CLOUDFLARE_PORT = 8787
LOCAL_EXPLORER_PATH = "/cdn-cgi/local/explorer/api"
R2_S3_PATH = "/cdn-cgi/local/r2/s3"
R2_S3_REGION = "auto"

_APP_DIR = "/app"
_DATA_DIR = "/data"
_COMPATIBILITY_DATE = "2026-01-01"
_CONFIG_ENV = "PYTEST_DATABASES_CLOUDFLARE_CONFIG"
_SERVER_ENV = "PYTEST_DATABASES_CLOUDFLARE_SERVER"
_VERSION_ENV = "PYTEST_DATABASES_MINIFLARE_VERSION"

_SERVER_SCRIPT = """\
import { Miniflare } from "miniflare";

const config = JSON.parse(process.env.PYTEST_DATABASES_CLOUDFLARE_CONFIG);
const credentials = { accessKeyId: config.access_key_id, secretAccessKey: config.secret_access_key };
const env = {};
config.kv_namespaces.forEach((id, index) => {
  env[`KV_${index}`] = { type: "kv", id };
});
config.r2_buckets.forEach((name, index) => {
  env[`R2_${index}`] = { type: "r2", name, dev: { experimentalS3Credentials: credentials } };
});
config.d1_databases.forEach((id, index) => {
  env[`D1_${index}`] = { type: "d1", id };
});

const miniflare = new Miniflare({
  host: "0.0.0.0",
  port: config.port,
  unsafeLocalExplorer: true,
  resourcePersistencePath: config.persist_path,
  workers: [
    {
      config: {
        name: "pytest-databases",
        compatibilityDate: config.compatibility_date,
        manifest: {
          mainModule: "index.mjs",
          modulesRoot: config.app_dir,
          modules: {
            "index.mjs": {
              type: "esm",
              contents: 'export default { fetch() { return new Response("ok"); } }',
            },
          },
        },
        env,
      },
    },
  ],
});
await miniflare.ready;
console.log("pytest-databases Cloudflare emulator ready");
"""

_BOOTSTRAP = f"""\
set -e
mkdir -p {_APP_DIR} {_DATA_DIR}
cd {_APP_DIR}
if [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ca-certificates >/dev/null
fi
if ! node --input-type=module -e "await import.meta.resolve('miniflare')" >/dev/null 2>&1; then
  npm install --no-audit --no-fund --loglevel=error "miniflare@${_VERSION_ENV}"
fi
printf '%s' "${_SERVER_ENV}" > server.mjs
exec node server.mjs
"""


@dataclass
class CloudflareService(ServiceContainer):
    """Endpoints, credentials, resource names, and stdlib helpers for a running Miniflare emulator.

    ``kv_namespaces``, ``r2_buckets``, and ``d1_databases`` hold the resource names this service may use; under
    pytest-xdist with ``database`` isolation they carry the worker suffix (``default_0``, ``default_1``, ...). The
    helpers accept only these names, so a test cannot write into another worker's resources by accident.
    """

    access_key_id: str
    secret_access_key: str
    kv_namespaces: tuple[str, ...]
    r2_buckets: tuple[str, ...]
    d1_databases: tuple[str, ...]

    @property
    def endpoint_url(self) -> str:
        """Base URL of the Miniflare HTTP server."""
        return f"http://{self.host}:{self.port}"

    @property
    def api_base_url(self) -> str:
        """Base URL of the Local Explorer API (Cloudflare v4 JSON envelope)."""
        return f"{self.endpoint_url}{LOCAL_EXPLORER_PATH}"

    @property
    def r2_s3_endpoint_url(self) -> str:
        """S3-compatible R2 endpoint; sign requests with ``access_key_id``, ``secret_access_key``, region ``auto``."""
        return f"{self.endpoint_url}{R2_S3_PATH}"

    def kv_put(self, namespace: str, key: str, value: bytes | str) -> None:
        """Write a value to a KV namespace.

        Args:
            namespace: One of ``kv_namespaces``.
            key: Key to write; any characters are allowed.
            value: Value to store; ``str`` values are encoded as UTF-8.
        """
        self._send(
            "PUT", self._kv_value_path(namespace, key), data=_encode(value), content_type="application/octet-stream"
        )

    def kv_get(self, namespace: str, key: str) -> bytes | None:
        """Read a value from a KV namespace.

        Args:
            namespace: One of ``kv_namespaces``.
            key: Key to read.

        Returns:
            The stored bytes, or None when the key does not exist.
        """
        return self._read(self._kv_value_path(namespace, key))

    def r2_put(self, bucket: str, key: str, value: bytes | str) -> None:
        """Write an object to an R2 bucket through the Local Explorer API.

        Args:
            bucket: One of ``r2_buckets``.
            key: Object key; ``/`` is kept as part of the key.
            value: Object body; ``str`` values are encoded as UTF-8.
        """
        self._send(
            "PUT", self._r2_object_path(bucket, key), data=_encode(value), content_type="application/octet-stream"
        )

    def r2_get(self, bucket: str, key: str) -> bytes | None:
        """Read an object from an R2 bucket through the Local Explorer API.

        Args:
            bucket: One of ``r2_buckets``.
            key: Object key.

        Returns:
            The object body, or None when the object does not exist.
        """
        return self._read(self._r2_object_path(bucket, key))

    def d1_query(self, database: str, sql: str, params: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """Run one SQL statement against a D1 database and return its rows.

        Args:
            database: One of ``d1_databases``.
            sql: SQL statement with ``?`` placeholders. When several statements are sent, the emulator returns only
                the rows of the last one.
            params: Placeholder values. The API accepts strings only; SQLite column affinity converts them on insert.

        Returns:
            One dictionary per row, keyed by column name.

        Raises:
            RuntimeError: If the statement fails or the response has no result set.
        """
        _require_resource("D1 database", database, self.d1_databases)
        payload: dict[str, Any] = {"sql": sql}
        if params is not None:
            payload["params"] = list(params)
        result = self._send(
            "POST",
            f"/d1/database/{_quote(database)}/raw",
            data=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )
        if not isinstance(result, list) or not result or not isinstance(result[-1], dict):
            msg = f"D1 query on {database!r} returned no result set: {result!r}"
            raise RuntimeError(msg)
        results = result[-1].get("results") or {}
        columns = results.get("columns") or []
        return [dict(zip(columns, row, strict=True)) for row in results.get("rows") or []]

    def _kv_value_path(self, namespace: str, key: str) -> str:
        _require_resource("KV namespace", namespace, self.kv_namespaces)
        return f"/storage/kv/namespaces/{_quote(namespace)}/values/{_quote(key)}"

    def _r2_object_path(self, bucket: str, key: str) -> str:
        _require_resource("R2 bucket", bucket, self.r2_buckets)
        return f"/r2/buckets/{_quote(bucket)}/objects/{_quote(key)}"

    def _send(self, method: str, path: str, *, data: bytes, content_type: str) -> Any:
        """Send a Local Explorer write request and return the ``result`` of its v4 envelope.

        Raises:
            RuntimeError: If the response status is not 200 or the envelope reports ``success: false``.
        """
        status, body = http_request(
            f"{self.api_base_url}{path}", method=method, data=data, headers={"Content-Type": content_type}
        )
        try:
            envelope = json.loads(body)
        except ValueError:
            envelope = None
        if status != 200 or not isinstance(envelope, dict) or envelope.get("success") is not True:
            msg = f"Cloudflare emulator {method} {path} failed: HTTP {status} {_describe_errors(envelope, body)}"
            raise RuntimeError(msg)
        return envelope.get("result")

    def _read(self, path: str) -> bytes | None:
        """Return the raw body of a Local Explorer ``GET``, or None on 404.

        Raises:
            RuntimeError: If the response status is neither 200 nor 404.
        """
        status, body = http_request(f"{self.api_base_url}{path}")
        if status == 404:
            return None
        if status != 200:
            msg = f"Cloudflare emulator GET {path} failed: HTTP {status} {body[:200]!r}"
            raise RuntimeError(msg)
        return body


@contextmanager
def provide_cloudflare_service(
    container_service: ContainerService,
    cloudflare_image: str,
    cloudflare_miniflare_version: str,
    cloudflare_kv_namespaces: Sequence[str],
    cloudflare_r2_buckets: Sequence[str],
    cloudflare_d1_databases: Sequence[str],
    cloudflare_access_key_id: str,
    cloudflare_secret_access_key: str,
    xdist_cloudflare_isolation_level: XdistIsolationLevel,
    cloudflare_startup_timeout: int = 300,
) -> Generator[CloudflareService, None, None]:
    """Start and yield a ready Miniflare Cloudflare emulator container.

    Without pytest-xdist the configured names are used as given. Under pytest-xdist with ``database`` isolation all
    workers share one container named ``cloudflare``, which binds ``<name>_<worker>`` for every worker, and each
    worker's service lists only its own names. With ``server`` isolation each worker starts its own transient
    container named ``cloudflare_<worker>`` with the names as given.

    Args:
        container_service: Session container service.
        cloudflare_image: Image with Node.js 22 or later on glibc.
        cloudflare_miniflare_version: Miniflare npm version installed when the image does not provide ``miniflare``.
        cloudflare_kv_namespaces: KV namespace ids.
        cloudflare_r2_buckets: R2 bucket names.
        cloudflare_d1_databases: D1 database ids.
        cloudflare_access_key_id: Access key ID accepted by the R2 S3 endpoint.
        cloudflare_secret_access_key: Secret access key accepted by the R2 S3 endpoint.
        xdist_cloudflare_isolation_level: pytest-xdist isolation level.
        cloudflare_startup_timeout: Seconds to wait for the emulator; the first start installs packages.

    Yields:
        A configured CloudflareService instance.

    Raises:
        RuntimeError: If a reused container does not bind every resource this worker needs.
    """
    worker_num = get_xdist_worker_num()
    name = "cloudflare"
    transient = False
    shared_workers: range | None = None
    suffix_worker: int | None = None
    if worker_num is not None and xdist_cloudflare_isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True
    elif worker_num is not None:
        shared_workers = range(max(get_xdist_worker_count(), worker_num + 1))
        suffix_worker = worker_num

    kv_namespaces = _resource_names(cloudflare_kv_namespaces, suffix_worker)
    r2_buckets = _resource_names(cloudflare_r2_buckets, suffix_worker)
    d1_databases = _resource_names(cloudflare_d1_databases, suffix_worker)
    config = _miniflare_config(
        kv_namespaces=_bound_names(cloudflare_kv_namespaces, shared_workers),
        r2_buckets=_bound_names(cloudflare_r2_buckets, shared_workers),
        d1_databases=_bound_names(cloudflare_d1_databases, shared_workers),
        access_key_id=cloudflare_access_key_id,
        secret_access_key=cloudflare_secret_access_key,
    )

    with container_service.run(
        image=cloudflare_image,
        name=name,
        container_port=CLOUDFLARE_PORT,
        entrypoint=["/bin/sh", "-c"],
        command=[_BOOTSTRAP],
        env={
            _CONFIG_ENV: json.dumps(config, ensure_ascii=True),
            _SERVER_ENV: _SERVER_SCRIPT,
            _VERSION_ENV: cloudflare_miniflare_version,
        },
        check=_is_cloudflare_ready,
        timeout=cloudflare_startup_timeout,
        pause=1.0,
        transient=transient,
    ) as container:
        service = CloudflareService(
            container=container.container,
            host=container.host,
            port=container.port,
            access_key_id=cloudflare_access_key_id,
            secret_access_key=cloudflare_secret_access_key,
            kv_namespaces=kv_namespaces,
            r2_buckets=r2_buckets,
            d1_databases=d1_databases,
        )
        missing = _missing_resources(service)
        if missing:
            msg = (
                f"The Cloudflare emulator container {name!r} does not bind {', '.join(missing)}. It was started with "
                "a different resource configuration or pytest-xdist worker count (for example, kept by an earlier "
                "run with --keep-containers); remove the container and run again."
            )
            raise RuntimeError(msg)
        yield service


@pytest.fixture(scope="session")
def xdist_cloudflare_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for the Cloudflare emulator (``database``: one shared container)."""
    return "database"


@pytest.fixture(scope="session")
def cloudflare_image() -> str:
    """Provide the Node.js image that runs Miniflare."""
    return os.getenv("CLOUDFLARE_IMAGE", DEFAULT_CLOUDFLARE_IMAGE)


@pytest.fixture(scope="session")
def cloudflare_miniflare_version() -> str:
    """Provide the Miniflare npm version installed when the image does not ship ``miniflare``."""
    return os.getenv("CLOUDFLARE_MINIFLARE_VERSION", DEFAULT_MINIFLARE_VERSION)


@pytest.fixture(scope="session")
def cloudflare_kv_namespaces() -> tuple[str, ...]:
    """Provide the KV namespace ids bound by the emulator."""
    return ("default",)


@pytest.fixture(scope="session")
def cloudflare_r2_buckets() -> tuple[str, ...]:
    """Provide the R2 bucket names bound by the emulator."""
    return ("default",)


@pytest.fixture(scope="session")
def cloudflare_d1_databases() -> tuple[str, ...]:
    """Provide the D1 database ids bound by the emulator."""
    return ("default",)


@pytest.fixture(scope="session")
def cloudflare_access_key_id() -> str:
    """Provide the access key ID accepted by the R2 S3 endpoint."""
    return os.getenv("CLOUDFLARE_ACCESS_KEY_ID", "pytest-databases")


@pytest.fixture(scope="session")
def cloudflare_secret_access_key() -> str:
    """Provide the secret access key accepted by the R2 S3 endpoint."""
    return os.getenv("CLOUDFLARE_SECRET_ACCESS_KEY", "pytest-databases-secret")


@pytest.fixture(scope="session")
def cloudflare_startup_timeout() -> int:
    """Provide the emulator startup timeout in seconds; the first start downloads Miniflare and ``workerd``."""
    return int(os.getenv("CLOUDFLARE_STARTUP_TIMEOUT", "300"))


@pytest.fixture(scope="session")
def cloudflare_service(
    container_service: ContainerService,
    cloudflare_image: str,
    cloudflare_miniflare_version: str,
    cloudflare_kv_namespaces: tuple[str, ...],
    cloudflare_r2_buckets: tuple[str, ...],
    cloudflare_d1_databases: tuple[str, ...],
    cloudflare_access_key_id: str,
    cloudflare_secret_access_key: str,
    xdist_cloudflare_isolation_level: XdistIsolationLevel,
    cloudflare_startup_timeout: int,
) -> Generator[CloudflareService, None, None]:
    """Start and yield a ready Miniflare Cloudflare emulator container.

    Yields:
        A configured CloudflareService instance.
    """
    with provide_cloudflare_service(
        container_service=container_service,
        cloudflare_image=cloudflare_image,
        cloudflare_miniflare_version=cloudflare_miniflare_version,
        cloudflare_kv_namespaces=cloudflare_kv_namespaces,
        cloudflare_r2_buckets=cloudflare_r2_buckets,
        cloudflare_d1_databases=cloudflare_d1_databases,
        cloudflare_access_key_id=cloudflare_access_key_id,
        cloudflare_secret_access_key=cloudflare_secret_access_key,
        xdist_cloudflare_isolation_level=xdist_cloudflare_isolation_level,
        cloudflare_startup_timeout=cloudflare_startup_timeout,
    ) as service:
        yield service


def _miniflare_config(
    *,
    kv_namespaces: Sequence[str],
    r2_buckets: Sequence[str],
    d1_databases: Sequence[str],
    access_key_id: str,
    secret_access_key: str,
) -> dict[str, Any]:
    """Return the JSON document the server script reads from ``PYTEST_DATABASES_CLOUDFLARE_CONFIG``.

    The script parses it with ``JSON.parse``, so resource names and credentials are never spliced into code.
    """
    return {
        "port": CLOUDFLARE_PORT,
        "app_dir": _APP_DIR,
        "persist_path": _DATA_DIR,
        "compatibility_date": _COMPATIBILITY_DATE,
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "kv_namespaces": list(kv_namespaces),
        "r2_buckets": list(r2_buckets),
        "d1_databases": list(d1_databases),
    }


def _resource_names(names: Sequence[str], worker_num: int | None) -> tuple[str, ...]:
    """Return the names one service uses: as given, or with the ``_<worker>`` suffix."""
    if worker_num is None:
        return tuple(names)
    return tuple(f"{name}_{worker_num}" for name in names)


def _bound_names(names: Sequence[str], shared_workers: range | None) -> tuple[str, ...]:
    """Return the names the container binds: as given, or one suffixed copy per pytest-xdist worker."""
    if shared_workers is None:
        return tuple(names)
    return tuple(f"{name}_{worker}" for worker in shared_workers for name in names)


def _is_cloudflare_ready(service: ServiceContainer) -> bool:
    """Return whether the Local Explorer API lists KV namespaces successfully."""
    payload = http_get_json(f"http://{service.host}:{service.port}{LOCAL_EXPLORER_PATH}/storage/kv/namespaces")
    return isinstance(payload, dict) and payload.get("success") is True


def _missing_resources(service: CloudflareService) -> list[str]:
    """Return the service resources the running emulator does not bind, as ``"<kind> '<name>'"`` strings."""
    kv = _result(http_get_json(f"{service.api_base_url}/storage/kv/namespaces")) or []
    r2 = _result(http_get_json(f"{service.api_base_url}/r2/buckets")) or {}
    d1 = _result(http_get_json(f"{service.api_base_url}/d1/database")) or []
    bound_kv = {item.get("id") for item in kv}
    bound_r2 = {item.get("name") for item in r2.get("buckets", [])}
    bound_d1 = {item.get("uuid") for item in d1}
    return [
        *(f"KV namespace {name!r}" for name in service.kv_namespaces if name not in bound_kv),
        *(f"R2 bucket {name!r}" for name in service.r2_buckets if name not in bound_r2),
        *(f"D1 database {name!r}" for name in service.d1_databases if name not in bound_d1),
    ]


def _result(envelope: Any) -> Any:
    """Return the ``result`` of a successful v4 envelope, or None."""
    if isinstance(envelope, dict) and envelope.get("success") is True:
        return envelope.get("result")
    return None


def _require_resource(kind: str, name: str, configured: tuple[str, ...]) -> None:
    """Raise ``ValueError`` when ``name`` is not one of the service's configured resources."""
    if name not in configured:
        msg = f"{kind} {name!r} is not configured for this service; use one of {configured!r}"
        raise ValueError(msg)


def _describe_errors(envelope: Any, body: bytes) -> str:
    """Return the ``errors`` messages of a v4 envelope, or the start of the raw body."""
    if isinstance(envelope, dict) and isinstance(envelope.get("errors"), list) and envelope["errors"]:
        return "; ".join(str(error.get("message", error)) for error in envelope["errors"] if isinstance(error, dict))
    return repr(body[:200])


def _quote(segment: str) -> str:
    """Percent-encode one URL path segment, including ``/``."""
    return urllib.parse.quote(segment, safe="")


def _encode(value: bytes | str) -> bytes:
    """Return ``value`` as bytes, encoding ``str`` as UTF-8."""
    return value.encode("utf-8") if isinstance(value, str) else value
