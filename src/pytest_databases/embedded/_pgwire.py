"""Minimal PostgreSQL simple-query client for the embedded service.

The embedded service talks to its cluster over the frontend/backend protocol directly, so it needs no ``psql`` binary
and no Python driver. Only trust authentication is supported, which is what ``initdb --auth=trust`` configures.
"""

from __future__ import annotations

import socket
import struct

__all__ = ("run_simple_query",)

_PROTOCOL_VERSION = 196608
_AUTHENTICATION_OK = 0
_CONNECTION_FAILED = 2
_QUERY_FAILED = 1


def run_simple_query(
    host: str,
    port: int,
    *,
    user: str,
    database: str,
    sql: str,
    timeout: float = 30.0,
) -> tuple[int, bytes]:
    """Run ``sql`` with the simple query protocol and return ``(exit_code, output)``.

    Output mirrors ``psql -tA``: one line per row, ``|`` between columns, NULL as an empty value. Statements that
    return no rows yield their command tags instead (for example ``CREATE DATABASE``). Exit code ``0`` is success,
    ``1`` an SQL error (the output holds the ``ERROR:`` text), and ``2`` a connection or authentication failure.
    Several statements in one string run in one implicit transaction, as with ``psql -c``.

    Returns:
        The exit code and output bytes.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            return _run_session(sock, user=user, database=database, sql=sql)
    except (OSError, struct.error) as exc:
        return _CONNECTION_FAILED, f"connection to {host}:{port} failed: {exc}".encode()


def _run_session(sock: socket.socket, *, user: str, database: str, sql: str) -> tuple[int, bytes]:
    """Start a session on ``sock``, run ``sql``, and terminate the session.

    Returns:
        The exit code and output bytes.
    """
    reader = _MessageReader(sock)
    sock.sendall(_startup_message(user=user, database=database))
    startup_error = _await_ready_for_query(reader)
    if startup_error is not None:
        return _CONNECTION_FAILED, startup_error
    sock.sendall(_message(b"Q", sql.encode() + b"\x00"))
    result = _collect_query_results(reader)
    sock.sendall(_message(b"X", b""))
    return result


class _MessageReader:
    """Read typed backend messages from a socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buffer = bytearray()

    def read(self) -> tuple[bytes, bytes]:
        """Read one backend message.

        Returns:
            The message type byte and its payload.
        """
        header = self._read_exact(5)
        (length,) = struct.unpack("!I", header[1:])
        return header[:1], self._read_exact(length - 4)

    def _read_exact(self, size: int) -> bytes:
        """Read exactly ``size`` bytes.

        Returns:
            The bytes read.

        Raises:
            ConnectionError: If the server closes the connection first.
        """
        while len(self._buffer) < size:
            chunk = self._sock.recv(65536)
            if not chunk:
                msg = "server closed the connection unexpectedly"
                raise ConnectionError(msg)
            self._buffer.extend(chunk)
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data


def _message(kind: bytes, payload: bytes) -> bytes:
    """Frame a frontend message.

    Returns:
        The framed message.
    """
    return kind + struct.pack("!I", len(payload) + 4) + payload


def _startup_message(*, user: str, database: str) -> bytes:
    """Build the ``StartupMessage`` for protocol 3.0.

    Returns:
        The framed startup message.
    """
    params = b"user\x00" + user.encode() + b"\x00database\x00" + database.encode() + b"\x00\x00"
    body = struct.pack("!I", _PROTOCOL_VERSION) + params
    return struct.pack("!I", len(body) + 4) + body


def _await_ready_for_query(reader: _MessageReader) -> bytes | None:
    """Consume startup responses until ``ReadyForQuery``.

    Returns:
        None when the session is ready, otherwise the error text.
    """
    while True:
        kind, payload = reader.read()
        if kind == b"R":
            (code,) = struct.unpack("!I", payload[:4])
            if code != _AUTHENTICATION_OK:
                return f"authentication method {code} is not supported; the cluster must use trust auth".encode()
        elif kind == b"E":
            return _error_text(payload)
        elif kind == b"Z":
            return None


def _collect_query_results(reader: _MessageReader) -> tuple[int, bytes]:
    """Consume query responses until ``ReadyForQuery``.

    Returns:
        The exit code and ``psql -tA`` style output.
    """
    rows: list[bytes] = []
    tags: list[bytes] = []
    error: bytes | None = None
    while True:
        kind, payload = reader.read()
        if kind == b"D":
            rows.append(_data_row(payload))
        elif kind == b"C":
            tags.append(payload.rstrip(b"\x00"))
        elif kind == b"E":
            error = _error_text(payload)
        elif kind == b"Z":
            break
    if error is not None:
        return _QUERY_FAILED, error
    return 0, b"\n".join(rows) if rows else b"\n".join(tags)


def _data_row(payload: bytes) -> bytes:
    """Render a ``DataRow`` payload as ``|``-separated text.

    Returns:
        The rendered row.
    """
    (count,) = struct.unpack("!H", payload[:2])
    offset = 2
    values: list[bytes] = []
    for _ in range(count):
        (length,) = struct.unpack("!i", payload[offset : offset + 4])
        offset += 4
        if length < 0:
            values.append(b"")
            continue
        values.append(payload[offset : offset + length])
        offset += length
    return b"|".join(values)


def _error_text(payload: bytes) -> bytes:
    """Render an ``ErrorResponse`` as ``SEVERITY:  message``.

    Returns:
        The error text.
    """
    fields: dict[bytes, bytes] = {}
    for field in payload.split(b"\x00"):
        if field:
            fields[field[:1]] = field[1:]
    severity = fields.get(b"V") or fields.get(b"S") or b"ERROR"
    return severity + b":  " + fields.get(b"M", b"unknown error")
