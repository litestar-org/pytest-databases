"""Minimal clientless PostgreSQL v3 simple-query wire protocol client.

Supports ``trust`` (``AuthenticationOk``), ``password`` (cleartext), ``md5``, and ``scram-sha-256`` SASL
authentication over TCP using only the Python standard library, so neither a ``psql`` binary nor a third-party Python
database driver is required for embedded clusters or pre-started PostgreSQL endpoints.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import socket
import struct
import unicodedata

__all__ = ("run_simple_query",)

_PROTOCOL_VERSION = 196608
_AUTHENTICATION_OK = 0
_AUTHENTICATION_CLEARTEXT = 3
_AUTHENTICATION_MD5 = 5
_AUTHENTICATION_SASL = 10
_AUTHENTICATION_SASL_CONTINUE = 11
_AUTHENTICATION_SASL_FINAL = 12
_CONNECTION_FAILED = 2
_QUERY_FAILED = 1
_SCRAM_MECHANISM = "SCRAM-SHA-256"
_SCRAM_GS2_HEADER_B64 = "biws"


def run_simple_query(
    host: str,
    port: int,
    *,
    user: str,
    database: str,
    sql: str,
    password: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, bytes]:
    """Run ``sql`` with the PostgreSQL v3 simple query protocol and return ``(exit_code, output)``.

    Output mirrors ``psql -tA``: one line per row, ``|`` between columns, NULL as an empty value. Statements that
    return no rows yield their command tags instead (for example ``CREATE DATABASE``). Exit code ``0`` is success,
    ``1`` an SQL error (the output holds the ``ERROR:`` text), and ``2`` a connection or authentication failure.
    Several statements in one string run in one implicit transaction, as with ``psql -c``.

    Args:
        host: PostgreSQL server hostname or IP address.
        port: PostgreSQL server TCP port.
        user: Role name used for the startup session.
        database: Target database name.
        sql: SQL statement or multi-statement script to execute.
        password: Optional password for cleartext, MD5, or SCRAM-SHA-256 authentication challenges.
        timeout: Socket connection and I/O timeout in seconds.

    Returns:
        The exit code and output bytes.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            return _run_session(sock, user=user, database=database, sql=sql, password=password)
    except (OSError, struct.error) as exc:
        return _CONNECTION_FAILED, f"connection to {host}:{port} failed: {exc}".encode()


def _run_session(
    sock: socket.socket,
    *,
    user: str,
    database: str,
    sql: str,
    password: str | None,
) -> tuple[int, bytes]:
    """Start a session on ``sock``, authenticate, run ``sql``, and terminate the session.

    Returns:
        The exit code and output bytes.
    """
    reader = _MessageReader(sock)
    sock.sendall(_startup_message(user=user, database=database))
    startup_error = _await_ready_for_query(sock, reader, user=user, password=password)
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


def _await_ready_for_query(
    sock: socket.socket,
    reader: _MessageReader,
    *,
    user: str,
    password: str | None,
) -> bytes | None:
    """Consume startup and authentication responses until ``ReadyForQuery``.

    Returns:
        None when the session is ready, otherwise the error text.
    """
    while True:
        kind, payload = reader.read()
        if kind == b"R":
            auth_error = _handle_auth_request(sock, reader, payload, user=user, password=password)
            if auth_error is not None:
                return auth_error
        elif kind == b"E":
            return _error_text(payload)
        elif kind == b"Z":
            return None


def _handle_auth_request(
    sock: socket.socket,
    reader: _MessageReader,
    payload: bytes,
    *,
    user: str,
    password: str | None,
) -> bytes | None:
    """Respond to a PostgreSQL ``Authentication*`` message payload."""
    (code,) = struct.unpack("!I", payload[:4])
    if code == _AUTHENTICATION_OK:
        return None
    if password is None:
        return f"authentication method {code} is not supported; the cluster must use trust auth".encode()
    if code == _AUTHENTICATION_CLEARTEXT:
        sock.sendall(_message(b"p", password.encode("utf-8") + b"\x00"))
        return None
    if code == _AUTHENTICATION_MD5:
        if len(payload) < 8:
            return b"malformed MD5 authentication challenge"
        salt = payload[4:8]
        inner = hashlib.md5(password.encode("utf-8") + user.encode("utf-8"), usedforsecurity=False).hexdigest()
        outer = hashlib.md5(inner.encode("ascii") + salt, usedforsecurity=False).hexdigest()
        sock.sendall(_message(b"p", f"md5{outer}".encode("ascii") + b"\x00"))
        return None
    if code == _AUTHENTICATION_SASL:
        return _authenticate_scram_sha256(sock, reader, payload[4:], password=password)
    return f"authentication method {code} is not supported".encode()


def _authenticate_scram_sha256(
    sock: socket.socket,
    reader: _MessageReader,
    mechanisms_payload: bytes,
    *,
    password: str,
) -> bytes | None:
    """Complete a full RFC 5802 ``SCRAM-SHA-256`` handshake with server signature verification."""
    mechanisms = {item.decode("ascii", errors="replace") for item in mechanisms_payload.split(b"\x00") if item}
    if _SCRAM_MECHANISM not in mechanisms:
        offered = ", ".join(sorted(mechanisms)) or "<none>"
        return f"SCRAM-SHA-256 not offered by server (offered: {offered})".encode()

    client_nonce = base64.b64encode(secrets.token_bytes(18)).decode("ascii")
    client_first_bare = f"n=,r={client_nonce}"
    client_first = f"n,,{client_first_bare}".encode()
    initial = _SCRAM_MECHANISM.encode("ascii") + b"\x00" + struct.pack("!I", len(client_first)) + client_first
    sock.sendall(_message(b"p", initial))

    server_first = _read_sasl_payload(reader, _AUTHENTICATION_SASL_CONTINUE, "negotiation")
    if isinstance(server_first, bytes):
        return server_first

    proof_state = _build_scram_client_final(client_first_bare, client_nonce, server_first, password)
    if isinstance(proof_state, bytes):
        return proof_state
    client_final, salted_password, auth_message = proof_state
    sock.sendall(_message(b"p", client_final))

    server_final = _read_sasl_payload(reader, _AUTHENTICATION_SASL_FINAL, "server signature")
    if isinstance(server_final, bytes):
        return server_final
    return _verify_scram_server_final(server_final, salted_password, auth_message)


def _read_sasl_payload(reader: _MessageReader, expected_code: int, stage: str) -> str | bytes:
    """Read a SASL ``Authentication*`` message and return its UTF-8 text or error bytes."""
    kind, payload = reader.read()
    if kind == b"E":
        return _error_text(payload)
    if kind != b"R" or len(payload) < 4:
        return f"unexpected response during SCRAM-SHA-256 {stage}".encode()
    (code,) = struct.unpack("!I", payload[:4])
    if code != expected_code:
        return f"unexpected SASL auth code {code} during {stage}".encode()
    return payload[4:].decode("utf-8", errors="replace")


def _build_scram_client_final(
    client_first_bare: str,
    client_nonce: str,
    server_first: str,
    password: str,
) -> tuple[bytes, bytes, bytes] | bytes:
    """Derive RFC 5802 SCRAM-SHA-256 client proof and return ``(client_final, salted_pw, auth_msg)``."""
    parsed_continue = _parse_scram_continue(server_first, client_nonce)
    if isinstance(parsed_continue, bytes):
        return parsed_continue
    server_nonce, salt, iterations = parsed_continue
    normalized_pw = unicodedata.normalize("NFC", password).encode("utf-8")
    salted_password = hashlib.pbkdf2_hmac("sha256", normalized_pw, salt, iterations)
    client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    client_final_no_proof = f"c={_SCRAM_GS2_HEADER_B64},r={server_nonce}"
    auth_message = f"{client_first_bare},{server_first},{client_final_no_proof}".encode()
    client_signature = hmac.new(stored_key, auth_message, hashlib.sha256).digest()
    client_proof = bytes(left ^ right for left, right in zip(client_key, client_signature, strict=True))
    proof_b64 = base64.b64encode(client_proof).decode("ascii")
    return f"{client_final_no_proof},p={proof_b64}".encode("ascii"), salted_password, auth_message


def _verify_scram_server_final(server_final: str, salted_password: bytes, auth_message: bytes) -> bytes | None:
    """Verify the server signature inside ``AuthenticationSASLFinal``."""
    verifier_b64 = _parse_scram_attributes(server_final).get("v")
    if not verifier_b64:
        return b"missing server verifier in SCRAM-SHA-256 final message"
    try:
        received_sig = base64.b64decode(verifier_b64, validate=True)
    except ValueError:
        return b"invalid base64 server verifier in SCRAM-SHA-256 final message"
    server_key = hmac.new(salted_password, b"Server Key", hashlib.sha256).digest()
    expected_sig = hmac.new(server_key, auth_message, hashlib.sha256).digest()
    if not hmac.compare_digest(received_sig, expected_sig):
        return b"SCRAM-SHA-256 server signature verification failed"
    return None


def _parse_scram_continue(server_first: str, client_nonce: str) -> tuple[str, bytes, int] | bytes:
    """Validate ``AuthenticationSASLContinue`` attributes and return ``(nonce, salt, iterations)`` or error bytes."""
    attrs = _parse_scram_attributes(server_first)
    server_nonce = attrs.get("r", "")
    salt_b64 = attrs.get("s", "")
    iter_raw = attrs.get("i", "")
    if not server_nonce.startswith(client_nonce) or len(server_nonce) <= len(client_nonce):
        return b"invalid server nonce in SCRAM-SHA-256 challenge"
    try:
        salt = base64.b64decode(salt_b64, validate=True)
        iterations = int(iter_raw)
    except ValueError:
        return b"malformed salt or iteration count in SCRAM-SHA-256 challenge"
    if iterations < 1 or not salt:
        return b"invalid salt or iteration count in SCRAM-SHA-256 challenge"
    return server_nonce, salt, iterations


def _parse_scram_attributes(message: str) -> dict[str, str]:
    """Parse comma-separated ``k=v`` attributes from a SCRAM payload."""
    attrs: dict[str, str] = {}
    for part in message.split(","):
        key, sep, value = part.partition("=")
        if sep and len(key) == 1:
            attrs[key] = value
    return attrs


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
