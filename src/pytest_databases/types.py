"""Shared service container types, archive transfer helpers, and command execution."""

from __future__ import annotations

import dataclasses
import io
import posixpath
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, TypeAlias, TypedDict, runtime_checkable

from docker.errors import NotFound

from pytest_databases.helpers import DEFAULT_TEMPLATE_NAME, DEFAULT_WORKER_PREFIX, exec_output_to_bytes

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from docker.models.containers import Container

__all__ = (
    "PostgresBackend",
    "PostgresServiceProtocol",
    "PostgresXdistIsolationLevel",
    "ServiceContainer",
    "XdistIsolationLevel",
    "copy_from_container",
    "copy_to_container",
    "exec_container_command",
)

PostgresBackend: TypeAlias = Literal["docker", "embedded"]
XdistIsolationLevel = Literal["database", "server"]
PostgresXdistIsolationLevel = Literal["database", "server", "template"]


@runtime_checkable
class PostgresServiceProtocol(Protocol):
    """Runtime-checkable structural interface shared by Docker, external, and embedded PostgreSQL services."""

    @property
    def host(self) -> str:
        """Hostname or IP address accepting PostgreSQL connections."""
        ...

    @property
    def port(self) -> int:
        """TCP port accepting PostgreSQL connections."""
        ...

    @property
    def user(self) -> str:
        """Database role name used for connections and SQL execution."""
        ...

    @property
    def password(self) -> str:
        """Database role password (empty string when trust authentication is active)."""
        ...

    @property
    def database(self) -> str:
        """Target database name."""
        ...

    @property
    def dsn(self) -> str:
        """Formatted libpq connection string for this service."""
        ...

    @property
    def connection_config(self) -> dict[str, Any]:
        """Driver keyword arguments (``host``, ``port``, ``user``, ``database``, and optional ``password``)."""
        ...

    def exec_sql(
        self,
        sql: str,
        *,
        database: str | None = None,
        tuples_only: bool = False,
        timeout: float = 30.0,
    ) -> tuple[int, bytes]:
        """Execute ``sql`` against ``database`` (defaults to ``self.database``)."""
        ...

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
        """Build an immutable PostgreSQL template database once and return its name."""
        ...

    def create_worker_database_from_template(self, template_name: str, worker_db: str) -> str:
        """Recreate ``worker_db`` cloned from ``template_name`` and verify connectivity."""
        ...

    def clone_template_database(self, target_db: str, *, source_db: str | None = None) -> str:
        """Clone ``source_db`` (defaults to ``self.database``) into ``target_db``."""
        ...

    def drop_database_force(self, db_name: str) -> None:
        """Terminate active sessions and drop ``db_name`` if it exists."""
        ...

    def sweep_worker_databases(self, prefix: str = DEFAULT_WORKER_PREFIX) -> list[str]:
        """Drop worker databases matching ``prefix`` while preserving templates and active targets."""
        ...


@dataclasses.dataclass
class ServiceContainer:
    """Base metadata and container file/command helpers for a started service."""

    container: Container
    host: str
    port: int

    def copy_to(
        self,
        source: str | Path,
        destination_dir: str,
        *,
        arcname: str | None = None,
        mode: int | None = None,
        uid: int | None = None,
        gid: int | None = None,
    ) -> None:
        """Copy a local file or directory into ``destination_dir`` inside the container.

        Args:
            source: Host file or directory path to archive and upload.
            destination_dir: Destination directory inside the container.
            arcname: Optional relative archive entry name inside ``destination_dir``.
            mode: Optional file permission mask applied to regular file entries.
            uid: Optional numeric owner UID set on uploaded archive entries.
            gid: Optional numeric group GID set on uploaded archive entries.
        """
        copy_to_container(
            self.container,
            source,
            destination_dir,
            arcname=arcname,
            mode=mode,
            uid=uid,
            gid=gid,
        )

    def copy_from(
        self,
        source: str,
        destination: str | Path,
        *,
        strip_components: bool = False,
    ) -> Path:
        """Copy a file or directory from ``source`` inside the container into ``destination``.

        Args:
            source: Path to the file or directory inside the container.
            destination: Host directory where archive contents are extracted.
            strip_components: Strip the leading directory segment emitted by the container archive when extracting
                directories.

        Returns:
            Resolved path to ``destination``.
        """
        return copy_from_container(
            self.container,
            source,
            destination,
            strip_components=strip_components,
        )

    def exec_command(
        self,
        command: str | list[str],
        *,
        user: str | None = None,
        workdir: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> tuple[int, bytes]:
        """Execute ``command`` inside the container and normalize output to ``(exit_code, bytes)``.

        Args:
            command: Command string or argument vector to run.
            user: Optional container user or ``uid[:gid]`` override.
            workdir: Optional working directory inside the container.
            env: Optional environment variables passed to the command process.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        return exec_container_command(
            self.container,
            command,
            user=user,
            workdir=workdir,
            env=env,
        )


def exec_container_command(
    container: Container,
    command: str | list[str],
    *,
    user: str | None = None,
    workdir: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[int, bytes]:
    """Execute ``command`` in ``container`` and return ``(exit_code, output_bytes)``.

    Args:
        container: Running Docker or Podman container handle.
        command: Command string or argument vector to execute.
        user: Optional container user or ``uid[:gid]`` override.
        workdir: Optional working directory inside the container.
        env: Optional environment mapping passed exclusively to the spawned process.

    Returns:
        Tuple of integer exit code and combined stdout/stderr output bytes.
    """
    exec_kwargs: _ExecRunKwargs = {}
    if user is not None:
        exec_kwargs["user"] = user
    if workdir is not None:
        exec_kwargs["workdir"] = workdir
    if env is not None:
        exec_kwargs["environment"] = dict(env)
    exit_code, output = container.exec_run(command, **exec_kwargs)
    resolved_code = -1 if exit_code is None else int(exit_code)
    return resolved_code, exec_output_to_bytes(output)


def copy_to_container(
    container: Container,
    source: str | Path,
    destination_dir: str,
    *,
    arcname: str | None = None,
    mode: int | None = None,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    """Copy a local file or directory into ``destination_dir`` inside ``container`` over the SDK tar API.

    When ``destination_dir`` does not yet exist in the container, ``mkdir -p`` is executed once via ``exec_run`` before
    retrying ``put_archive``. Numeric ``uid``/``gid`` overrides clear symbolic ``uname``/``gname`` fields so the
    container tar extractor honors the numeric identifiers directly.

    Args:
        container: Running Docker or Podman container handle.
        source: Host path to the file or directory to copy.
        destination_dir: Target directory path inside the container.
        arcname: Optional relative name inside ``destination_dir`` (defaults to ``Path(source).name``).
        mode: Optional POSIX mode (for example ``0o755`` or ``0o400``) applied to regular file entries.
        uid: Optional numeric owner UID applied to archive entries.
        gid: Optional numeric group GID applied to archive entries.

    Raises:
        FileNotFoundError: If ``source`` does not exist on the host.
        ValueError: If ``destination_dir`` or ``arcname`` is empty or traverses outside ``destination_dir``.
        RuntimeError: If directory creation fails or the container runtime rejects the archive.
    """
    src_path = Path(source)
    if not src_path.exists():
        msg = f"Source path does not exist: {src_path}"
        raise FileNotFoundError(msg)
    if not destination_dir or not destination_dir.strip():
        msg = "destination_dir must be a non-empty container directory path"
        raise ValueError(msg)

    raw_arcname = arcname if arcname is not None else src_path.name
    clean_arcname = _validate_relative_archive_path(raw_arcname)
    archive_bytes = _build_tar_archive(src_path, clean_arcname, mode=mode, uid=uid, gid=gid)

    try:
        accepted = container.put_archive(destination_dir, archive_bytes)
    except NotFound as exc:
        mkdir_rc, mkdir_out = exec_container_command(container, ["mkdir", "-p", destination_dir])
        if mkdir_rc != 0:
            detail = mkdir_out.decode("utf-8", errors="replace").strip()
            msg = f"Failed to create container directory {destination_dir!r} (exit {mkdir_rc}): {detail}"
            raise RuntimeError(msg) from exc
        accepted = container.put_archive(destination_dir, archive_bytes)

    if accepted is False:
        msg = f"Container rejected archive upload to {destination_dir!r}"
        raise RuntimeError(msg)


def copy_from_container(
    container: Container,
    source: str,
    destination: str | Path,
    *,
    strip_components: bool = False,
) -> Path:
    """Extract a file or directory from ``source`` inside ``container`` into host directory ``destination``.

    Every archive member is validated before extraction to reject absolute paths, ``..`` traversal, device/FIFO special
    files, and symlinks or hardlinks whose target escapes ``destination``.

    Args:
        container: Running Docker or Podman container handle.
        source: Source file or directory path inside the container.
        destination: Host directory path where files are written.
        strip_components: Strip the leading directory component when extracting multi-segment archive paths.

    Returns:
        Resolved ``Path`` to ``destination``.

    Raises:
        ValueError: If ``source`` is empty or any archive entry attempts path or link traversal outside ``destination``.
    """
    if not source or not source.strip():
        msg = "source must be a non-empty container path"
        raise ValueError(msg)

    target_dir = Path(destination)
    target_dir.mkdir(parents=True, exist_ok=True)
    resolved_target = target_dir.resolve()

    bits, _stat = container.get_archive(source)
    archive_bytes = exec_output_to_bytes(bits)
    if not archive_bytes:
        return resolved_target

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
        for member in tar.getmembers():
            rel_parts = _extract_safe_member_parts(member, strip_components=strip_components)
            if not rel_parts:
                continue
            member_path = resolved_target.joinpath(*rel_parts)
            resolved_parent = member_path.parent.resolve()
            if not resolved_parent.is_relative_to(resolved_target):
                msg = f"Unsafe archive member path escaping destination: {member.name!r}"
                raise ValueError(msg)
            _extract_validated_member(tar, member, member_path, resolved_target)

    return resolved_target


class _ExecRunKwargs(TypedDict, total=False):
    user: str
    workdir: str
    environment: dict[str, str]


def _validate_relative_archive_path(raw_path: str) -> str:
    """Validate and normalize a relative POSIX archive member name."""
    stripped = raw_path.replace("\\", "/")
    while stripped.startswith("./"):
        stripped = stripped[2:]
    if not stripped or stripped.startswith("/"):
        msg = f"Archive path must be a non-empty relative path, got {raw_path!r}"
        raise ValueError(msg)
    parts = [part for part in stripped.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        msg = f"Unsafe archive path containing parent traversal: {raw_path!r}"
        raise ValueError(msg)
    return "/".join(parts)


def _build_tar_archive(
    src_path: Path,
    arcname: str,
    *,
    mode: int | None,
    uid: int | None,
    gid: int | None,
) -> bytes:
    """Pack ``src_path`` into an uncompressed tar byte payload."""

    def _filter_entry(info: tarfile.TarInfo) -> tarfile.TarInfo:
        if mode is not None and info.isfile():
            info.mode = mode
        if uid is not None:
            info.uid = uid
            info.uname = ""
        if gid is not None:
            info.gid = gid
            info.gname = ""
        return info

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(str(src_path), arcname=arcname, filter=_filter_entry)
    return buffer.getvalue()


def _extract_safe_member_parts(member: tarfile.TarInfo, *, strip_components: bool) -> tuple[str, ...]:
    """Validate ``member.name`` and return relative path segments inside the destination directory."""
    raw_name = member.name.replace("\\", "/")
    while raw_name.startswith("./"):
        raw_name = raw_name[2:]
    trimmed = raw_name.rstrip("/")
    if not trimmed or trimmed == ".":
        return ()
    if raw_name.startswith("/"):
        msg = f"Unsafe absolute archive member path: {member.name!r}"
        raise ValueError(msg)
    raw_parts = [part for part in trimmed.split("/") if part and part != "."]
    if any(part == ".." for part in raw_parts):
        msg = f"Unsafe archive member path containing traversal: {member.name!r}"
        raise ValueError(msg)
    if strip_components:
        if len(raw_parts) > 1:
            return tuple(raw_parts[1:])
        if member.isdir():
            return ()
    return tuple(raw_parts)


def _extract_validated_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    member_path: Path,
    resolved_target: Path,
) -> None:
    """Write a single validated tar member into ``member_path`` within ``resolved_target``."""
    if member.isdir():
        member_path.mkdir(parents=True, exist_ok=True)
        resolved_dir = member_path.resolve()
        if not resolved_dir.is_relative_to(resolved_target):
            msg = f"Unsafe archive directory target escaping destination: {member.name!r}"
            raise ValueError(msg)
        return

    if member.issym() or member.islnk():
        link_name = member.linkname.replace("\\", "/")
        if not link_name or posixpath.isabs(link_name):
            msg = f"Unsafe absolute link target in archive member {member.name!r}: {member.linkname!r}"
            raise ValueError(msg)
        link_anchor = resolved_target if member.islnk() else member_path.parent
        candidate = (link_anchor / link_name).resolve()
        if not candidate.is_relative_to(resolved_target):
            msg = f"Unsafe link target escaping destination in {member.name!r}: {member.linkname!r}"
            raise ValueError(msg)
        member_path.parent.mkdir(parents=True, exist_ok=True)
        member_path.unlink(missing_ok=True)
        if member.issym():
            member_path.symlink_to(link_name)
        else:
            data = candidate.read_bytes()
            member_path.write_bytes(data)
        return

    if member.isfile():
        extracted = tar.extractfile(member)
        if extracted is None:
            return
        member_path.parent.mkdir(parents=True, exist_ok=True)
        if member_path.is_symlink():
            member_path.unlink()
        resolved_file = member_path.resolve()
        if not resolved_file.is_relative_to(resolved_target):
            msg = f"Unsafe archive file path escaping destination: {member.name!r}"
            raise ValueError(msg)
        member_path.write_bytes(extracted.read())
        file_mode = member.mode & 0o777
        if file_mode:
            member_path.chmod(file_mode)
        return

    msg = f"Unsupported special archive entry {member.name!r} (type={member.type!r})"
    raise ValueError(msg)
