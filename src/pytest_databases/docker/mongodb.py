"""MongoDB container service fixtures."""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import re
import secrets
import shlex
import tempfile
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict
from urllib.parse import quote

import filelock
import pytest
from docker.errors import APIError, NotFound

from pytest_databases.helpers import (
    env_port,
    exec_output_to_bytes,
    get_xdist_worker_num,
    read_init_scripts,
    run_container_init_once,
    simple_string_hash,
    tcp_port_open,
)
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, Sequence

    from docker.models.containers import Container

    from pytest_databases._service import DockerService

__all__ = (
    "MONGODB_DATABASE",
    "MONGODB_PASSWORD",
    "MONGODB_USER",
    "MongoDBService",
    "exec_mongosh",
    "mongodb_connection",
    "mongodb_database",
    "mongodb_database_name",
    "mongodb_image",
    "mongodb_password",
    "mongodb_port",
    "mongodb_replica_set",
    "mongodb_service",
    "mongodb_username",
    "provide_mongodb_service",
    "xdist_mongodb_isolation_level",
)

MONGODB_USER = "mongo_user"
MONGODB_PASSWORD = "mongo_password"
MONGODB_DATABASE = "pytest_db"
_REPLICA_SET_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_KEYFILE_PATH = "/data/configdb/ptdb-keyfile"
_KEYFILE_ENV = "PTDB_MONGO_KEYFILE_SECRET"


@dataclass
class MongoDBService(ServiceContainer):
    """Service handle for a running MongoDB container."""

    username: str | None = MONGODB_USER
    password: str | None = MONGODB_PASSWORD
    database: str = MONGODB_DATABASE
    replica_set: str | None = None

    @property
    def uri(self) -> str:
        """Standard ``mongodb://`` connection URI reflecting credentials and replica-set mode.

        Returns:
            Percent-encoded MongoDB connection URI targeting ``self.database``.
        """
        host_part = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        auth_prefix = ""
        params: list[str] = []
        if self.username is not None:
            encoded_user = quote(self.username, safe="")
            encoded_pw = quote(self.password or "", safe="")
            auth_prefix = f"{encoded_user}:{encoded_pw}@"
            params.append("authSource=admin")
        if self.replica_set:
            params.extend((f"replicaSet={quote(self.replica_set, safe='')}", "directConnection=true"))
        db_segment = quote(self.database, safe="")
        query = f"?{'&'.join(params)}" if params else ""
        return f"mongodb://{auth_prefix}{host_part}:{self.port}/{db_segment}{query}"

    def exec_js(
        self,
        eval_script: str,
        *,
        database: str | None = None,
        auth_source: str = "admin",
    ) -> tuple[int, bytes]:
        """Execute a JavaScript snippet via in-container ``mongosh``.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        return exec_mongosh(
            self.container,
            eval_script,
            user=self.username,
            password=self.password if self.username is not None else None,
            database=self.database if database is None else database,
            auth_source=auth_source,
        )

    def set_profiling_level(
        self,
        level: Literal[0, 1, 2],
        *,
        slow_ms: int | None = None,
        database: str | None = None,
    ) -> None:
        """Configure the MongoDB query profiler (``system.profile``) on ``database``.

        Args:
            level: Profiling level (``0`` off, ``1`` slow operations, ``2`` all operations).
            slow_ms: Optional slow-operation threshold in milliseconds.
            database: Target database (defaults to ``self.database``).

        Raises:
            ValueError: If ``level`` is not ``0``, ``1``, or ``2``, or ``slow_ms`` is negative.
            RuntimeError: If ``db.setProfilingLevel`` fails inside the container.
        """
        if isinstance(level, bool) or level not in {0, 1, 2}:
            msg = f"MongoDB profiling level must be 0, 1, or 2, got {level!r}."
            raise ValueError(msg)
        if slow_ms is not None and (isinstance(slow_ms, bool) or slow_ms < 0):
            msg = f"slow_ms must be >= 0, got {slow_ms!r}."
            raise ValueError(msg)
        target_db = self.database if database is None else database
        options_js = f", {{ slowms: {slow_ms} }}" if slow_ms is not None else ""
        script = (
            f"const res = db.setProfilingLevel({level}{options_js}); "
            "if (!res || res.ok !== 1) { throw new Error(JSON.stringify(res)); } print(res.ok);"
        )
        code, output = self.exec_js(script, database=target_db)
        if code != 0:
            detail = output.decode(errors="replace").strip()
            msg = f"Failed to set MongoDB profiling level {level} on {target_db!r} (exit {code}): {detail}"
            raise RuntimeError(msg)


def exec_mongosh(
    container: Container,
    eval_script: str,
    *,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    auth_source: str = "admin",
) -> tuple[int, bytes]:
    """Execute ``eval_script`` inside a MongoDB container via ``mongosh --quiet``.

    Supports both authenticated sessions (``user`` and ``password`` provided) and
    unauthenticated sessions (both ``user`` and ``password`` set to ``None``).

    Returns:
        Tuple of ``(exit_code, output_bytes)``.

    Raises:
        ValueError: If only one of ``user`` or ``password`` is provided.
    """
    if (user is None) != (password is None):
        msg = "Provide both 'user' and 'password' to exec_mongosh, or omit both for unauthenticated mode."
        raise ValueError(msg)
    cmd = ["mongosh", "--quiet", "--host", "localhost", "--port", "27017"]
    if user is not None and password is not None:
        cmd.extend(["-u", user, "-p", password, "--authenticationDatabase", auth_source])
    if database is not None:
        cmd.append(database)
    cmd.extend(["--eval", eval_script])
    try:
        result = container.exec_run(cmd)
    except (APIError, NotFound) as exc:
        return -1, str(exc).encode()
    exit_code = result.exit_code if result.exit_code is not None else -1
    return exit_code, exec_output_to_bytes(result.output)


@contextlib.contextmanager
def provide_mongodb_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    *,
    username: str | None = MONGODB_USER,
    password: str | None = MONGODB_PASSWORD,
    database: str = MONGODB_DATABASE,
    host_port: int | None = None,
    replica_set: str | None = None,
    command: str | Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    init_js: str | Path | Sequence[str | Path] | None = None,
    profiling_level: Literal[0, 1, 2] | None = None,
    slow_ms: int | None = None,
    timeout: int = 120,
    pause: float = 0.5,
) -> Generator[MongoDBService, None, None]:
    """Start and manage a MongoDB container service.

    Supports authenticated and unauthenticated deployments (``username=None``), single-node
    replica sets (``replica_set="rs0"``, automatically generating an internal ``--keyFile``
    when authentication is enabled and electing a writable ``PRIMARY``), custom ``mongod`` flags,
    ``init_js`` bootstrap scripts, and ``system.profile`` activation.

    Yields:
        Active MongoDBService instance.
    """
    auth_password = _validate_mongodb_options(username=username, password=password, replica_set=replica_set)
    container_name, database_name = _resolve_mongodb_targets(name, database, isolation_level)
    entrypoint, cmd_list, container_env = _build_mongodb_startup(
        username=username,
        password=auth_password,
        replica_set=replica_set,
        command=command,
        extra_env=env,
    )

    def check(_service: ServiceContainer) -> bool:
        if not tcp_port_open(_service.host, _service.port):
            return False
        exit_code, output = exec_mongosh(
            _service.container,
            "print(db.adminCommand('ping').ok)",
            user=username,
            password=auth_password,
        )
        return exit_code == 0 and output.strip().endswith(b"1")

    with docker_service.run(
        **_build_mongodb_run_kwargs(
            image=image,
            name=container_name,
            env=container_env,
            entrypoint=entrypoint,
            command=cmd_list,
            host_port=host_port,
            check=check,
            pause=pause,
            timeout=timeout,
            transient=isolation_level == "server",
        )
    ) as service:
        handle = MongoDBService(
            host=service.host,
            port=service.port,
            container=service.container,
            username=username,
            password=auth_password,
            database=database_name,
            replica_set=replica_set,
        )
        _finalize_mongodb_service(
            handle,
            init_js=init_js,
            profiling_level=profiling_level,
            slow_ms=slow_ms,
            timeout=timeout,
            pause=pause,
        )
        yield handle


@pytest.fixture(scope="session")
def xdist_mongodb_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for MongoDB."""
    return "database"


@pytest.fixture(autouse=False, scope="session")
def mongodb_image() -> str:
    """Return the MongoDB container image."""
    return os.environ.get("MONGODB_IMAGE", "mongo:latest")


@pytest.fixture(autouse=False, scope="session")
def mongodb_username() -> str | None:
    """Return the root username for MongoDB, or ``None`` when ``MONGODB_USER=""`` disables auth."""
    raw = os.environ.get("MONGODB_USER")
    if raw is None:
        return MONGODB_USER
    return raw or None


@pytest.fixture(autouse=False, scope="session")
def mongodb_password() -> str | None:
    """Return the root password for MongoDB."""
    return os.environ.get("MONGODB_PASSWORD", MONGODB_PASSWORD)


@pytest.fixture(autouse=False, scope="session")
def mongodb_database_name() -> str:
    """Return the default session database name for MongoDB (``MONGODB_DATABASE``)."""
    return os.environ.get("MONGODB_DATABASE", MONGODB_DATABASE)


@pytest.fixture(autouse=False, scope="session")
def mongodb_port() -> int | None:
    """Return an optional pinned host TCP port for MongoDB (``MONGODB_PORT``)."""
    return env_port("MONGODB_PORT")


@pytest.fixture(autouse=False, scope="session")
def mongodb_replica_set() -> str | None:
    """Return an optional replica-set name for MongoDB (``MONGODB_REPLICA_SET``)."""
    value = os.environ.get("MONGODB_REPLICA_SET", "").strip()
    return value or None


@pytest.fixture(autouse=False, scope="session")
def mongodb_service(
    docker_service: DockerService,
    xdist_mongodb_isolation_level: XdistIsolationLevel,
    mongodb_image: str,
    mongodb_username: str | None,
    mongodb_password: str | None,
    mongodb_database_name: str,
    mongodb_port: int | None,
    mongodb_replica_set: str | None,
) -> Generator[MongoDBService, None, None]:
    """Provide a running MongoDB container service.

    Yields:
        Active MongoDBService instance.
    """
    with provide_mongodb_service(
        docker_service,
        mongodb_image,
        "mongodb",
        xdist_mongodb_isolation_level,
        username=mongodb_username,
        password=mongodb_password,
        database=mongodb_database_name,
        host_port=mongodb_port,
        replica_set=mongodb_replica_set,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mongodb_connection(mongodb_service: MongoDBService) -> Generator[Any, None, None]:
    """Provide a deprecated pymongo MongoClient connected to MongoDB.

    Yields:
        Active pymongo MongoClient instance.
    """
    warnings.warn(
        "The 'mongodb_connection' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'mongodb_service' and instantiate your pymongo client directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    with _open_mongo_client(mongodb_service) as client:
        yield client


@pytest.fixture(autouse=False, scope="function")
def mongodb_database(mongodb_service: MongoDBService) -> Generator[Any, None, None]:
    """Provide a deprecated pymongo Database instance for testing.

    Yields:
        Active pymongo Database instance.
    """
    warnings.warn(
        "The 'mongodb_database' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'mongodb_service' and instantiate your pymongo client directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    with _open_mongo_client(mongodb_service) as client:
        yield client[mongodb_service.database]


@contextlib.contextmanager
def _open_mongo_client(service: MongoDBService) -> Generator[Any, None, None]:
    """Open a pymongo client for ``service`` and close it on exit.

    Yields:
        Active pymongo MongoClient instance.
    """
    pymongo = importlib.import_module("pymongo")
    client_kwargs: dict[str, Any] = {"host": service.host, "port": service.port}
    if service.username is not None:
        client_kwargs["username"] = service.username
        client_kwargs["password"] = service.password
    if service.replica_set:
        client_kwargs["replicaSet"] = service.replica_set
        client_kwargs["directConnection"] = True
    client = pymongo.MongoClient(**client_kwargs)
    try:
        yield client
    finally:
        client.close()


def _validate_mongodb_options(
    *,
    username: str | None,
    password: str | None,
    replica_set: str | None,
) -> str | None:
    """Validate credential pairing and replica-set identifier format."""
    if username == "":
        msg = "MongoDB username must be non-empty or None for unauthenticated mode."
        raise ValueError(msg)
    if username is not None and password is None:
        msg = "MongoDB password must not be None when username is set."
        raise ValueError(msg)
    if replica_set is not None and not _REPLICA_SET_PATTERN.fullmatch(replica_set):
        msg = f"Invalid MongoDB replica_set name {replica_set!r}."
        raise ValueError(msg)
    return password if username is not None else None


def _resolve_mongodb_targets(
    name: str,
    database: str,
    isolation_level: XdistIsolationLevel,
) -> tuple[str, str]:
    """Resolve ``(container_name, database_name)`` for the active xdist worker."""
    if not database:
        msg = "MongoDB database name must be non-empty."
        raise ValueError(msg)
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return name, database
    suffix = f"_{worker_num}"
    if isolation_level == "server":
        return f"{name}{suffix}", database
    return name, f"{database}{suffix}"


def _normalize_mongod_flags(command: str | Sequence[str] | None) -> list[str]:
    """Normalize optional custom ``mongod`` flags into an argument list without a leading ``mongod``."""
    if command is None:
        return []
    parts = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    if parts and parts[0] == "mongod":
        return parts[1:]
    return parts


def _build_mongodb_startup(
    *,
    username: str | None,
    password: str | None,
    replica_set: str | None,
    command: str | Sequence[str] | None,
    extra_env: Mapping[str, str] | None,
) -> tuple[list[str] | None, list[str] | None, dict[str, str]]:
    """Build ``(entrypoint, command, env)`` covering auth, unauth, replicaSet+keyFile, and custom flags."""
    container_env: dict[str, str] = {}
    if username is not None and password is not None:
        container_env["MONGO_INITDB_ROOT_USERNAME"] = username
        container_env["MONGO_INITDB_ROOT_PASSWORD"] = password
    if extra_env:
        container_env.update(extra_env)

    extra_flags = _normalize_mongod_flags(command)
    if replica_set is None:
        cmd_list = ["mongod", *extra_flags] if extra_flags else None
        return None, cmd_list, container_env

    if username is None:
        return None, ["mongod", "--replSet", replica_set, "--bind_ip_all", *extra_flags], container_env

    container_env.setdefault(_KEYFILE_ENV, secrets.token_urlsafe(64))
    mongod_args = ["mongod", "--replSet", replica_set, "--keyFile", _KEYFILE_PATH, "--bind_ip_all", *extra_flags]
    quoted_mongod = " ".join(shlex.quote(arg) for arg in mongod_args)
    script = (
        f'umask 077 && printf "%s\\n" "${_KEYFILE_ENV}" > {_KEYFILE_PATH} && '
        f"chmod 400 {_KEYFILE_PATH} && "
        f"(chown mongodb:mongodb {_KEYFILE_PATH} 2>/dev/null || true) && "
        f"exec docker-entrypoint.sh {quoted_mongod}"
    )
    return ["/bin/sh", "-c"], [script], container_env


class _MongoRunKwargs(TypedDict):
    image: str
    name: str
    container_port: int
    env: dict[str, str]
    check: Callable[[ServiceContainer], bool]
    pause: float
    timeout: int
    transient: bool
    entrypoint: NotRequired[list[str]]
    command: NotRequired[list[str]]
    host_port: NotRequired[int]


def _build_mongodb_run_kwargs(
    *,
    image: str,
    name: str,
    env: dict[str, str],
    entrypoint: list[str] | None,
    command: list[str] | None,
    host_port: int | None,
    check: Callable[[ServiceContainer], bool],
    pause: float,
    timeout: int,
    transient: bool,
) -> _MongoRunKwargs:
    """Assemble keyword arguments forwarded to :meth:`DockerService.run`."""
    kwargs: _MongoRunKwargs = {
        "image": image,
        "name": name,
        "container_port": 27017,
        "env": env,
        "check": check,
        "pause": pause,
        "timeout": timeout,
        "transient": transient,
    }
    if entrypoint is not None:
        kwargs["entrypoint"] = entrypoint
    if command is not None:
        kwargs["command"] = command
    if host_port is not None:
        kwargs["host_port"] = host_port
    return kwargs


def _finalize_mongodb_service(
    service: MongoDBService,
    *,
    init_js: str | Path | Sequence[str | Path] | None,
    profiling_level: Literal[0, 1, 2] | None,
    slow_ms: int | None,
    timeout: int,
    pause: float,
) -> None:
    """Initialize replica set primary election, run ``init_js`` once, and configure profiling."""
    if service.replica_set is not None:
        _ensure_mongodb_replica_set(service, timeout=timeout, pause=pause)
    scripts = read_init_scripts(init_js)
    if scripts:
        fingerprint = simple_string_hash("\n;\n".join(scripts))

        def _run_init() -> None:
            for script in scripts:
                code, output = service.exec_js(script)
                if code != 0:
                    detail = output.decode(errors="replace").strip()
                    msg = f"MongoDB init_js failed on database {service.database!r} (exit {code}): {detail}"
                    raise RuntimeError(msg)

        run_container_init_once(service.container, f"mongodb:{service.database}", fingerprint, _run_init)
    if profiling_level is not None:
        service.set_profiling_level(profiling_level, slow_ms=slow_ms)


def _ensure_mongodb_replica_set(service: MongoDBService, *, timeout: int, pause: float) -> None:
    """Initiate a single-node replica set idempotently and wait until it becomes writable ``PRIMARY``."""
    rs_config = json.dumps({"_id": service.replica_set, "members": [{"_id": 0, "host": "localhost:27017"}]})
    init_script = (
        "try { "
        "const st = rs.status(); if (st && st.ok === 1) { print('ok'); quit(0); } "
        "} catch (err) { "
        "if (err.codeName !== 'NotYetInitialized' && err.code !== 94) { throw err; } "
        "} "
        f"try {{ const r = rs.initiate({rs_config}); if (!r || r.ok !== 1) {{ throw new Error(JSON.stringify(r)); }} "
        "print('ok'); } catch (err) { "
        "if (err.codeName === 'AlreadyInitialized' || err.code === 23) { print('ok'); quit(0); } throw err; }"
    )
    container_id = getattr(service.container, "id", None)
    lock_cm: contextlib.AbstractContextManager[object] = contextlib.nullcontext()
    if isinstance(container_id, str) and container_id:
        lock_path = Path(tempfile.gettempdir()) / f"pytest-databases-mongo-rs-{container_id[:12]}.lock"
        lock_cm = filelock.FileLock(str(lock_path), timeout=120.0)
    with lock_cm:
        code, output = service.exec_js(init_script, database="admin")
        if code != 0:
            detail = output.decode(errors="replace").strip()
            msg = f"Failed to initialize MongoDB replica set {service.replica_set!r} (exit {code}): {detail}"
            raise RuntimeError(msg)

    deadline = time.monotonic() + max(timeout, 1)
    probe_js = "const h = db.hello(); print(Boolean(h && (h.isWritablePrimary || h.ismaster)));"
    last_out = b""
    while True:
        code, last_out = service.exec_js(probe_js, database="admin")
        lines = [line.strip() for line in last_out.splitlines() if line.strip()]
        if code == 0 and lines and lines[-1] == b"true":
            return
        if time.monotonic() >= deadline:
            detail = last_out.decode(errors="replace").strip()
            msg = f"MongoDB replica set {service.replica_set!r} did not elect a writable PRIMARY within {timeout}s: {detail}"
            raise TimeoutError(msg)
        time.sleep(pause)
