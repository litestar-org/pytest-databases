"""MySQL container service fixtures."""

from __future__ import annotations

import contextlib
import os
import shlex
import time
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from docker.errors import APIError, NotFound

from pytest_databases._service import DockerService, ServiceContainer
from pytest_databases.helpers import (
    env_port,
    exec_output_to_bytes,
    get_xdist_worker_num,
    read_init_scripts,
    resolve_legacy_platform,
    run_container_init_once,
    simple_string_hash,
    tcp_port_open,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence
    from pathlib import Path

    from docker.models.containers import Container

    from pytest_databases.types import XdistIsolationLevel

__all__ = [
    "MySQLService",
    "exec_mysql",
    "mysql_8_service",
    "mysql_56_service",
    "mysql_57_service",
    "mysql_84_service",
    "mysql_96_service",
    "mysql_97_service",
    "mysql_database",
    "mysql_password",
    "mysql_platform",
    "mysql_port",
    "mysql_root_password",
    "mysql_service",
    "mysql_user",
    "platform",
    "provide_mysql_service",
    "xdist_mysql_isolation_level",
]


@dataclass
class MySQLService(ServiceContainer):
    """Service handle for a running MySQL container."""

    db: str
    user: str
    password: str

    def exec_sql(
        self,
        sql: str,
        *,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        batch: bool = True,
    ) -> tuple[int, bytes]:
        """Execute ``sql`` via the in-container ``mysql`` client over TCP loopback.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        return exec_mysql(
            self.container,
            sql,
            user=self.user if user is None else user,
            password=self.password if password is None else password,
            database=self.db if database is None else database,
            batch=batch,
        )


def exec_mysql(
    container: Container,
    sql: str,
    *,
    user: str = "root",
    password: str = "",
    database: str | None = None,
    batch: bool = True,
) -> tuple[int, bytes]:
    """Execute ``sql`` inside a MySQL container using ``MYSQL_PWD`` authentication.

    Args:
        container: Running MySQL container handle.
        sql: SQL statement(s) passed to ``mysql -e``.
        user: MySQL user name.
        password: Password passed via ``MYSQL_PWD`` environment variable.
        database: Optional target database name.
        batch: When ``True``, adds ``--batch --skip-column-names`` for clean scalar/tabular parsing.

    Returns:
        Tuple of ``(exit_code, output_bytes)``.
    """
    cmd = ["mysql", "--protocol=tcp", "-h", "127.0.0.1", f"--user={user}"]
    if batch:
        cmd.extend(["--batch", "--skip-column-names"])
    if database:
        cmd.extend(["-D", database])
    cmd.extend(["-e", sql])
    env = {"MYSQL_PWD": password} if password else None
    try:
        result = container.exec_run(cmd, environment=env)
    except (APIError, NotFound) as exc:
        return -1, str(exc).encode()
    code = result.exit_code if result.exit_code is not None else -1
    return code, exec_output_to_bytes(result.output)


@contextlib.contextmanager
def provide_mysql_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    platform: str | None,
    user: str,
    password: str,
    root_password: str,
    database: str,
    *,
    host_port: int | None = None,
    command: str | Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
    timeout: int = 120,
    pause: float = 1.0,
) -> Generator[MySQLService, None, None]:
    """Start and manage a MySQL container service with ``performance_schema`` enabled by default.

    Yields:
        Active :class:`MySQLService` instance bound to ``database`` (or ``<database>_<worker>`` under xdist).

    Raises:
        ValueError: If ``database`` or ``user`` is invalid.
        RuntimeError: If database provisioning, user grants, or ``init_sql`` fails.
    """
    base_db = _validate_mysql_identifier(database)
    if not user:
        msg = "MySQL user must be non-empty."
        raise ValueError(msg)
    resolved_name, db_name = _resolve_mysql_targets(name, base_db, isolation_level)

    def check(_service: ServiceContainer) -> bool:
        code, _ = exec_mysql(_service.container, "SELECT 1", user="root", password=root_password)
        return code == 0 and tcp_port_open(_service.host, _service.port)

    with docker_service.run(
        image=image,
        check=check,
        container_port=3306,
        name=resolved_name,
        command=_build_mysql_command(command),
        env=_build_mysql_env(
            user=user,
            password=password,
            root_password=root_password,
            database=base_db,
            extra_env=env,
        ),
        timeout=timeout,
        pause=pause,
        transient=isolation_level == "server",
        platform=platform,
        host_port=host_port,
    ) as service:
        _provision_mysql_database(
            service.container,
            fixture_name=resolved_name,
            db_name=db_name,
            user=user,
            password=password,
            root_password=root_password,
        )
        _apply_mysql_init_sql(
            service.container,
            db_name=db_name,
            root_password=root_password,
            init_sql=init_sql,
        )
        yield MySQLService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(scope="session")
def xdist_mysql_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for MySQL."""
    return "database"


@pytest.fixture(scope="session")
def mysql_platform(request: pytest.FixtureRequest) -> str | None:
    """Return the container platform used by MySQL 5.6 and 5.7, which publish x86_64 images only."""
    return resolve_legacy_platform(request, "mysql_platform", "linux/x86_64")


@pytest.fixture(scope="session")
def platform() -> str:
    """Return the legacy ``linux/x86_64`` platform string.

    .. deprecated:: 0.20.0
        Use ``mysql_platform`` instead. ``platform`` will be removed in v1.0.0.
    """
    warnings.warn(
        "The 'platform' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'mysql_platform', 'dolt_platform', or 'bigquery_platform' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return "linux/x86_64"


@pytest.fixture(scope="session")
def mysql_user() -> str:
    """Return the MySQL application user."""
    return os.getenv("MYSQL_USER", "app")


@pytest.fixture(scope="session")
def mysql_password() -> str:
    """Return the MySQL application password."""
    return os.getenv("MYSQL_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mysql_root_password() -> str:
    """Return the MySQL root password."""
    return os.getenv("MYSQL_ROOT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mysql_database() -> str:
    """Return the MySQL database name."""
    return os.getenv("MYSQL_DATABASE", "db")


@pytest.fixture(scope="session")
def mysql_port() -> int | None:
    """Return an optional pinned host port for MySQL containers from ``MYSQL_PORT``."""
    return env_port("MYSQL_PORT")


@pytest.fixture(scope="session")
def mysql_service(mysql_84_service: MySQLService) -> MySQLService:
    """Provide the default MySQL container service."""
    return mysql_84_service


def _make_mysql_legacy_service_fixture(fixture_name: str, image: str, name: str, doc: str) -> Any:
    """Create a session-scoped MySQL 5.x service fixture honoring ``mysql_platform``."""

    def _fixture(
        docker_service: DockerService,
        xdist_mysql_isolation_level: XdistIsolationLevel,
        mysql_platform: str | None,
        mysql_user: str,
        mysql_password: str,
        mysql_root_password: str,
        mysql_database: str,
        mysql_port: int | None,
    ) -> Generator[MySQLService, None, None]:
        with provide_mysql_service(
            image=image,
            name=name,
            docker_service=docker_service,
            isolation_level=xdist_mysql_isolation_level,
            platform=mysql_platform,
            user=mysql_user,
            password=mysql_password,
            root_password=mysql_root_password,
            database=mysql_database,
            host_port=mysql_port,
        ) as service:
            yield service

    _fixture.__name__ = fixture_name
    _fixture.__qualname__ = fixture_name
    _fixture.__doc__ = doc
    _fixture.__module__ = __name__
    return pytest.fixture(scope="session")(_fixture)


def _make_mysql_modern_service_fixture(fixture_name: str, image: str, name: str, doc: str) -> Any:
    """Create a session-scoped MySQL 8+/9+ service fixture with legacy ``platform`` fallback."""

    def _fixture(
        request: pytest.FixtureRequest,
        docker_service: DockerService,
        xdist_mysql_isolation_level: XdistIsolationLevel,
        mysql_user: str,
        mysql_password: str,
        mysql_root_password: str,
        mysql_database: str,
        mysql_port: int | None,
    ) -> Generator[MySQLService, None, None]:
        with provide_mysql_service(
            image=image,
            name=name,
            docker_service=docker_service,
            isolation_level=xdist_mysql_isolation_level,
            platform=resolve_legacy_platform(request, None, None),
            user=mysql_user,
            password=mysql_password,
            root_password=mysql_root_password,
            database=mysql_database,
            host_port=mysql_port,
        ) as service:
            yield service

    _fixture.__name__ = fixture_name
    _fixture.__qualname__ = fixture_name
    _fixture.__doc__ = doc
    _fixture.__module__ = __name__
    return pytest.fixture(scope="session")(_fixture)


mysql_56_service = _make_mysql_legacy_service_fixture(
    "mysql_56_service",
    "mysql:5.6",
    "mysql-56",
    "Provide a running MySQL 5.6 container service.",
)
mysql_57_service = _make_mysql_legacy_service_fixture(
    "mysql_57_service",
    "mysql:5.7",
    "mysql-57",
    "Provide a running MySQL 5.7 container service.",
)
mysql_8_service = _make_mysql_modern_service_fixture(
    "mysql_8_service",
    "mysql:8",
    "mysql-8",
    "Provide a running MySQL 8 container service.",
)
mysql_84_service = _make_mysql_modern_service_fixture(
    "mysql_84_service",
    "mysql:8.4",
    "mysql-8.4",
    "Provide a running MySQL 8.4 LTS container service.",
)
mysql_96_service = _make_mysql_modern_service_fixture(
    "mysql_96_service",
    "mysql:9.6",
    "mysql-9.6",
    "Provide a running MySQL 9.6 container service.",
)
mysql_97_service = _make_mysql_modern_service_fixture(
    "mysql_97_service",
    "mysql:9.7",
    "mysql-9.7",
    "Provide a running MySQL 9.7 container service.",
)


def _validate_mysql_identifier(name: str) -> str:
    """Validate that ``name`` fits MySQL's 64-character identifier rules without NUL or control bytes."""
    if not name or len(name) > 64 or any(ord(ch) < 32 for ch in name):
        msg = f"Invalid MySQL database identifier: {name!r}"
        raise ValueError(msg)
    return name


def _quote_mysql_identifier(name: str) -> str:
    """Quote a MySQL schema identifier with backticks."""
    return f"`{name.replace('`', '``')}`"


def _quote_mysql_literal(value: str) -> str:
    """Quote a MySQL string literal escaping backslashes and single quotes."""
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _resolve_mysql_targets(name: str, base_db: str, isolation_level: XdistIsolationLevel) -> tuple[str, str]:
    """Compute container logical name and database name for the active pytest-xdist worker."""
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return name, base_db
    suffix = f"_{worker_num}"
    if isolation_level == "server":
        return f"{name}{suffix}", base_db
    return name, _validate_mysql_identifier(f"{base_db}{suffix}")


def _build_mysql_command(command: str | Sequence[str] | None) -> str | list[str]:
    """Build ``mysqld`` command flags keeping ``--performance-schema=ON`` unless explicitly overridden."""
    if command is None:
        return "--performance-schema=ON"
    args = shlex.split(command) if isinstance(command, str) else list(command)
    has_perf_flag = any(
        arg.startswith(("--performance-schema", "--performance_schema", "--skip-performance-schema")) for arg in args
    )
    return args if has_perf_flag else ["--performance-schema=ON", *args]


def _build_mysql_env(
    *,
    user: str,
    password: str,
    root_password: str,
    database: str,
    extra_env: Mapping[str, str] | None,
) -> dict[str, str]:
    """Compose container environment variables for MySQL initialization."""
    container_env: dict[str, str] = {
        "MYSQL_ROOT_PASSWORD": root_password,
        "MYSQL_DATABASE": database,
        "MYSQL_ROOT_HOST": "%",
        "LANG": "C.UTF-8",
    }
    if user != "root":
        container_env["MYSQL_USER"] = user
        container_env["MYSQL_PASSWORD"] = password
    if extra_env:
        container_env.update(extra_env)
    return container_env


def _provision_mysql_database(
    container: Container,
    *,
    fixture_name: str,
    db_name: str,
    user: str,
    password: str,
    root_password: str,
) -> None:
    """Ensure ``db_name`` exists and ``user`` has global privileges and verified login access."""
    quoted_db = _quote_mysql_identifier(db_name)
    setup_parts = [f"CREATE DATABASE IF NOT EXISTS {quoted_db}"]
    if user != "root":
        setup_parts.extend((
            f"GRANT ALL PRIVILEGES ON *.* TO {_quote_mysql_literal(user)}@'%'",
            "FLUSH PRIVILEGES",
        ))
    setup_sql = "; ".join(setup_parts) + ";"
    last_err = b""
    for attempt in range(15):
        setup_code, setup_out = exec_mysql(container, setup_sql, user="root", password=root_password, batch=False)
        if setup_code == 0:
            verify_code, verify_out = exec_mysql(container, "SELECT 1", user=user, password=password, database=db_name)
            if verify_code == 0:
                return
            last_err = verify_out
        else:
            last_err = setup_out
        time.sleep(1 + attempt * 0.5)
    msg = (
        f"MySQL fixture {fixture_name!r}: user {user!r} could not reach database "
        f"{db_name!r} after 15 attempts. Last output: {last_err!r}"
    )
    raise RuntimeError(msg)


def _apply_mysql_init_sql(
    container: Container,
    *,
    db_name: str,
    root_password: str,
    init_sql: str | Path | Sequence[str | Path] | None,
) -> None:
    """Execute ``init_sql`` statements once per ``(container, db_name)`` as ``root``."""
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = simple_string_hash("\n;\n".join(statements))

    def _run() -> None:
        for statement in statements:
            code, output = exec_mysql(
                container,
                statement,
                user="root",
                password=root_password,
                database=db_name,
                batch=False,
            )
            if code != 0:
                detail = output.decode(errors="replace").strip()
                msg = f"MySQL init_sql failed on database {db_name!r} (exit {code}): {detail}"
                raise RuntimeError(msg)

    run_container_init_once(container, f"mysql:{db_name}", fingerprint, _run)
