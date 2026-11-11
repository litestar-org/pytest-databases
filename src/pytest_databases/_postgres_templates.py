"""Database clone, drop, and template helpers shared by the PostgreSQL service classes.

Every helper takes a :class:`SQLRunner` callable, so container services (``psql`` inside the container),
embedded clusters, and external PostgreSQL endpoints (both over the stdlib v3 wire protocol) share one
implementation.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Self

import filelock

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Sequence

__all__ = (
    "DEFAULT_TEMPLATE_NAME",
    "DEFAULT_WORKER_PREFIX",
    "PostgresTemplateSupport",
    "SQLRunner",
    "clone_database",
    "compute_fingerprint",
    "create_database_from_template",
    "drop_database",
    "ensure_template",
    "make_connection_string",
    "resolve_template_name",
    "split_template_setup",
    "sweep_databases",
    "validate_identifier",
)

DEFAULT_TEMPLATE_NAME = "pytest_databases_template"
DEFAULT_WORKER_PREFIX = "pytest_databases_"
STAGING_SUFFIX = "_staging"
MAX_IDENTIFIER_LENGTH = 63
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
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
        fingerprint_sources: Sequence[str | bytes | Path] = (),
        lock_dir: Path | str | None = None,
        lock_timeout: float = 180.0,
    ) -> str:
        """Build a template database once and return its name.

        The name is ``template_name`` plus a 12-character digest of ``setup_sql`` (SQL text and file contents) and
        ``fingerprint_sources``, so a changed setup builds a new template instead of reusing a stale one. A setup
        callable cannot be fingerprinted; list its inputs in ``fingerprint_sources``. A file lock in ``lock_dir``
        (default: the system temp directory) scoped to this server makes concurrent workers build it only once.

        Args:
            template_name: Template name, or the name prefix when a digest is appended.
            setup_fn: Callable receiving a copy of this service pointed at the staging database.
            setup_sql: SQL statements or ``.sql`` file paths executed against the staging database.
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
    template_name: str,
    *,
    setup_sql: Sequence[str | Path] = (),
    fingerprint_sources: Sequence[str | bytes | Path] = (),
) -> str:
    """Return ``template_name`` with a digest of the setup SQL and fingerprint sources appended.

    Returns:
        The validated template name.
    """
    sources: list[str | bytes | Path] = [
        statement if isinstance(statement, Path) else statement.encode() for statement in setup_sql
    ]
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
    setup_fn: Callable[[str], object] | None = None,
    fingerprint_sources: Sequence[str | bytes | Path] = (),
    lock_dir: Path | str | None = None,
    lock_timeout: float = 180.0,
    lock_scope: str = "",
) -> str:
    """Build a template database once and return its name.

    The template is built in ``<name>_staging`` (setup SQL, then ``setup_fn(staging_name)``), marked
    ``is_template = true allow_connections = false``, and renamed. An existing template with the same name is
    reused; the double-checked file lock makes concurrent callers build it only once.

    Returns:
        The template database name.

    Raises:
        RuntimeError: If a setup statement or a DDL step fails.
    """
    name = resolve_template_name(template_name, setup_sql=setup_sql, fingerprint_sources=fingerprint_sources)
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
            _build_template(run_sql, staging=staging, name=name, setup_sql=setup_sql, setup_fn=setup_fn)
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
) -> None:
    """Run the setup in the existing ``staging`` database, mark it as a template, and rename it to ``name``."""
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
