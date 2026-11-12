"""Tests for Oracle Database and Autonomous Database Free container fixtures and wallet helpers."""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import io
import tarfile
import zipfile
from functools import partial
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker import oracle
from pytest_databases.docker.oracle import (
    DEFAULT_ORACLE_ADB_IMAGE,
    DEFAULT_ORACLE_ADB_PASSWORD,
    ORACLE_ADB_ADW_SERVICES,
    ORACLE_ADB_AJD_SERVICES,
    ORACLE_ADB_APEX_SERVICES,
    ORACLE_ADB_ATP_SERVICES,
    OracleADBService,
    OracleService,
    _is_transient_oracle_error,
    enable_oracle_ords_schema,
    ensure_oracle_adb_user,
    ensure_oracle_user,
    exec_oracle_sql,
    exec_sqlplus,
    oracle_18c_connection,
    oracle_18c_service,
    oracle_23ai_connection,
    oracle_23ai_image,
    oracle_23ai_service,
    oracle_23ai_service_name,
    oracle_26ai_connection,
    oracle_26ai_image,
    oracle_26ai_port,
    oracle_26ai_service,
    oracle_26ai_service_name,
    oracle_adb_image,
    oracle_adb_service,
    oracle_adb_startup_timeout,
    oracle_port,
    oracle_service,
    oracle_startup_connection,
    oracle_startup_timeout,
    parse_tnsnames,
    provide_oracle_adb_service,
    provide_oracle_service,
    rewrite_sqlnet_ora,
    rewrite_tnsnames,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import run_recording_deprecations, unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from pytest import MonkeyPatch, Pytester

    from pytest_databases.types import XdistIsolationLevel

pytest_plugins = ["pytest_databases.docker.oracle"]

SAMPLE_TNSNAMES = """\
myatp_high = (DESCRIPTION = (RETRY_COUNT=20)(RETRY_DELAY=3)(ADDRESS = (PROTOCOL = TCPS)(PORT = 1522)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_high.adb.oraclecloud.com))(SECURITY = (SSL_SERVER_DN_MATCH = YES)))

myatp_tp = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(PORT = 1521)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_tp.adb.oraclecloud.com)))
"""
SAMPLE_SQLNET = """\
WALLET_LOCATION = (SOURCE = (METHOD = file) (METHOD_DATA = (DIRECTORY="/u01/app/oracle/wallets/tls_wallet")))
SSL_SERVER_DN_MATCH=yes
"""


def test_plugin_imports_without_oracledb(pytester: pytest.Pytester) -> None:
    """Ensure the Oracle module imports cleanly when oracledb is absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in {"oracledb", "cx_Oracle"}:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.oracle")
            assert module.OracleADBService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_oracle_isolation_level_default(xdist_oracle_isolation_level: str) -> None:
    """Ensure xdist_oracle_isolation_level defaults to database."""
    assert xdist_oracle_isolation_level == "database"


def test_oracle_database_isolation_naming_and_user() -> None:
    """Ensure database isolation preserves shared name and assigns per-worker user."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=1521)
    mock_docker.run.return_value.__enter__.return_value = mock_service

    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=2),
        patch("pytest_databases.docker.oracle.tcp_port_open", return_value=True) as mock_tcp,
        patch("pytest_databases.docker.oracle.ensure_oracle_user", return_value=True) as mock_ensure,
        patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"1")),
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle26ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            isolation_level="database",
        ) as service,
    ):
        assert service.user == "app_2"
        call_kwargs = mock_docker.run.call_args[1]
        assert call_kwargs["name"] == "oracle26ai"
        assert call_kwargs["transient"] is False
        assert call_kwargs["timeout"] == 180
        assert isinstance(call_kwargs["pause"], float)
        assert call_kwargs["pause"] == pytest.approx(1.0, abs=0.0)
        check_fn = call_kwargs["check"]
        assert check_fn(mock_service) is True
        mock_tcp.assert_called_once_with("127.0.0.1", 1521)
        mock_ensure.assert_called_once_with(
            mock_container,
            user="app_2",
            password="secret",
            service_name="FREEPDB1",
            system_password="sys-secret",
        )


def test_oracle_server_isolation_naming_and_user() -> None:
    """Ensure server isolation suffixes name and retains default user."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=1521)
    mock_docker.run.return_value.__enter__.return_value = mock_service

    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=3),
        patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"1")),
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle26ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            isolation_level="server",
        ) as service,
    ):
        assert service.user == "app"

    call_kwargs = mock_docker.run.call_args[1]
    assert call_kwargs["name"] == "oracle26ai_3"
    assert call_kwargs["transient"] is True


def test_ensure_oracle_user_invokes_sysdba() -> None:
    """Ensure ensure_oracle_user connects as sysdba to create user."""
    mock_container = MagicMock()
    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_exec:
        assert (
            ensure_oracle_user(
                container=mock_container,
                user="app_1",
                password="secret",
                service_name="FREEPDB1",
                system_password="sys-secret",
            )
            is True
        )

    mock_exec.assert_called_once()
    _, kwargs = mock_exec.call_args
    assert kwargs["user"] == "sys"
    assert kwargs["password"] == "sys-secret"
    assert kwargs["service_name"] == "FREEPDB1"
    assert kwargs["as_sysdba"] is True
    assert kwargs["whenever_sqlerror"] == "EXIT SQL.SQLCODE"
    assert "IF SQLCODE != -1920 THEN" in kwargs["sql"]
    assert "IF SQLCODE != -28007 THEN" in kwargs["sql"]
    assert 'CREATE USER app_1 IDENTIFIED BY "secret"' in kwargs["sql"]
    assert 'ALTER USER app_1 IDENTIFIED BY "secret"' in kwargs["sql"]
    assert "ALTER USER app_1 ACCOUNT UNLOCK;" in kwargs["sql"]
    assert "GRANT CONNECT, RESOURCE, DBA TO app_1;" in kwargs["sql"]
    assert "ALTER USER app_1 QUOTA UNLIMITED ON USERS;" in kwargs["sql"]


@pytest.mark.parametrize(
    ("exec_results", "expected_result", "expected_calls", "expected_sleeps"),
    [
        (
            [MagicMock(exit_code=0, output=b"")],
            True,
            1,
            [],
        ),
        (
            [
                MagicMock(exit_code=1, output=b"ORA-12514: TNS:listener does not currently know of service"),
                MagicMock(exit_code=1, output=b"ORA-12514: TNS:listener does not currently know of service"),
                MagicMock(exit_code=0, output=b""),
            ],
            True,
            3,
            [0.5, 1.0],
        ),
        (
            [MagicMock(exit_code=1, output=b"ORA-00054: resource busy") for _ in range(5)],
            False,
            5,
            [0.5, 1.0, 1.5, 2.0],
        ),
        (
            [MagicMock(exit_code=942, output=b"ORA-00942: table or view does not exist")],
            False,
            1,
            [],
        ),
        (
            [MagicMock(exit_code=1031, output=b"ORA-01031: insufficient privileges")],
            False,
            1,
            [],
        ),
    ],
)
def test_ensure_oracle_user_retry_and_failure_paths(
    exec_results: list[MagicMock],
    expected_result: bool,
    expected_calls: int,
    expected_sleeps: list[float],
) -> None:
    """Verify ensure_oracle_user retries transient ORA errors and aborts immediately on fatal errors."""
    container = MagicMock()
    container.exec_run.side_effect = exec_results
    with patch("pytest_databases.docker.oracle.time.sleep") as mock_sleep:
        result = ensure_oracle_user(
            container=container,
            user="app_1",
            password="secret",
            service_name="FREEPDB1",
            system_password="sys-secret",
        )

    assert result is expected_result
    assert container.exec_run.call_count == expected_calls
    assert [call.args[0] for call in mock_sleep.call_args_list] == expected_sleeps
    command = container.exec_run.call_args.args[0][2]
    assert "WHENEVER SQLERROR EXIT SQL.SQLCODE" in command
    assert "IF SQLCODE != -1920 THEN" in command


@pytest.mark.parametrize(
    ("password", "expected_password"),
    [
        ("secret", "secret"),
        ("pa'ss", "pa''ss"),
    ],
)
def test_ensure_oracle_user_escapes_single_quotes_in_password(
    password: str,
    expected_password: str,
) -> None:
    """Verify ensure_oracle_user escapes single quotes inside the generated PL/SQL EXECUTE IMMEDIATE block."""
    mock_container = MagicMock()
    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_exec:
        assert (
            ensure_oracle_user(
                container=mock_container,
                user="app_1",
                password=password,
                service_name="FREEPDB1",
                system_password="sys-secret",
            )
            is True
        )

    mock_exec.assert_called_once()
    _, kwargs = mock_exec.call_args
    expected_create = f"""EXECUTE IMMEDIATE 'CREATE USER app_1 IDENTIFIED BY "{expected_password}"';"""
    expected_alter = f"""EXECUTE IMMEDIATE 'ALTER USER app_1 IDENTIFIED BY "{expected_password}"';"""
    assert expected_create in kwargs["sql"]
    assert expected_alter in kwargs["sql"]


@pytest.mark.parametrize(
    ("password", "expected_password"),
    [
        ("Welcome12345!", "Welcome12345!"),
        ("Wel'come12345!", "Wel''come12345!"),
    ],
)
def test_ensure_oracle_adb_user_escapes_single_quotes_in_password(
    password: str,
    expected_password: str,
) -> None:
    """Verify ensure_oracle_adb_user escapes single quotes in both CREATE USER and ALTER USER PL/SQL literals."""
    mock_container = MagicMock()
    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_exec:
        ensure_oracle_adb_user(
            container=mock_container,
            user="app_1",
            password=password,
            service_name="myatp_high.adb.oraclecloud.com",
            admin_password=DEFAULT_ORACLE_ADB_PASSWORD,
        )

    mock_exec.assert_called_once()
    _, kwargs = mock_exec.call_args
    expected_create = (
        f'EXECUTE IMMEDIATE \'CREATE USER app_1 IDENTIFIED BY "{expected_password}" '
        "DEFAULT TABLESPACE DATA TEMPORARY TABLESPACE TEMP';"
    )
    expected_alter = f"EXECUTE IMMEDIATE 'ALTER USER app_1 IDENTIFIED BY \"{expected_password}\"';"
    assert expected_create in kwargs["sql"]
    assert expected_alter in kwargs["sql"]


@pytest.mark.parametrize(
    ("user", "url_mapping_pattern", "expected_schema", "expected_pattern"),
    [
        ("app_1", None, "APP_1", "app_1"),
        ("ap'p", "custom'slug", "AP''P", "custom''slug"),
    ],
)
def test_enable_oracle_ords_schema_escapes_single_quotes(
    user: str,
    url_mapping_pattern: str | None,
    expected_schema: str,
    expected_pattern: str,
) -> None:
    """Verify enable_oracle_ords_schema escapes single quotes inside generated PL/SQL arguments."""
    mock_container = MagicMock()
    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_ords:
        enable_oracle_ords_schema(
            mock_container,
            user=user,
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            service_name="myatp_high.adb.oraclecloud.com",
            url_mapping_pattern=url_mapping_pattern,
        )

    mock_ords.assert_called_once()
    _, kwargs = mock_ords.call_args
    assert f"p_schema => '{expected_schema}'" in kwargs["sql"]
    assert f"p_url_mapping_pattern => '{expected_pattern}'" in kwargs["sql"]


@pytest.mark.parametrize(
    ("raw_exit_code", "output", "whenever_sqlerror", "expected_exit_code"),
    [
        (0, b"1\n", "EXIT SQL.SQLCODE", 0),
        (0, b"", "EXIT SQL.SQLCODE", 0),
        (0, b"ERROR:\nORA-01536: space quota exceeded for tablespace 'USERS'\n", "EXIT SQL.SQLCODE", 1),
        (0, b"ORA-20224: ORDS schema configuration failed\n", "EXIT SQL.SQLCODE", 1),
        (0, b'PLS-00103: Encountered the symbol "END"\n', "EXIT SQL.SQLCODE", 1),
        (0, b"SP2-0640: Not connected\n", "EXIT SQL.SQLCODE", 1),
        (0, b"ORA-01920: user name conflicts\n", "CONTINUE", 0),
        (None, b"", "EXIT SQL.SQLCODE", -1),
    ],
)
def test_exec_sqlplus_normalizes_exit_zero_error_output(
    raw_exit_code: int | None,
    output: bytes,
    whenever_sqlerror: str,
    expected_exit_code: int,
) -> None:
    """Verify _exec_sqlplus normalizes modulo-256 truncated exit-zero SQL*Plus errors unless CONTINUE is set."""
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=raw_exit_code, output=output)
    exit_code, out_bytes = oracle._exec_sqlplus(
        container,
        user="app",
        password="secret",
        service_name="FREEPDB1",
        sql="SELECT 1 FROM dual",
        whenever_sqlerror=whenever_sqlerror,
    )
    assert exit_code == expected_exit_code
    assert out_bytes == output


@pytest.mark.parametrize("attempts", [0, -1])
def test_run_sqlplus_with_retry_rejects_non_positive_attempts(attempts: int) -> None:
    """Verify _run_sqlplus_with_retry raises ValueError for non-positive attempts before calling exec_run."""
    container = MagicMock()
    with pytest.raises(ValueError, match="attempts must be >= 1"):
        oracle._run_sqlplus_with_retry(
            container,
            user="sys",
            password="sys-secret",
            service_name="FREEPDB1",
            sql="SELECT 1 FROM dual",
            attempts=attempts,
        )
    container.exec_run.assert_not_called()


def test_parse_and_rewrite_tnsnames() -> None:
    """Verify parse_tnsnames and rewrite_tnsnames handle multi-entry tnsnames.ora content."""
    entries = parse_tnsnames(SAMPLE_TNSNAMES)
    assert set(entries) == {"myatp_high", "myatp_tp"}
    assert entries["myatp_high"]["protocol"] == "TCPS"
    assert entries["myatp_high"]["port"] == "1522"
    assert entries["myatp_high"]["host"] == "adb-free.local"
    assert entries["myatp_high"]["service_name"] == "myatp_high.adb.oraclecloud.com"
    assert entries["myatp_tp"]["protocol"] == "TCP"
    assert entries["myatp_tp"]["port"] == "1521"

    rewritten = rewrite_tnsnames(SAMPLE_TNSNAMES, host="127.0.0.1", port=31521, tls_port=31522)
    assert "SSL_SERVER_DN_MATCH = NO" in rewritten
    rewritten_entries = parse_tnsnames(rewritten)
    assert rewritten_entries["myatp_high"]["host"] == "127.0.0.1"
    assert rewritten_entries["myatp_high"]["port"] == "31522"
    assert rewritten_entries["myatp_tp"]["host"] == "127.0.0.1"
    assert rewritten_entries["myatp_tp"]["port"] == "31521"


def test_extract_adb_wallet_unpacks_and_rewrites_tnsnames_and_sqlnet(tmp_path: Path) -> None:
    """Verify extract_adb_wallet extracts wallet files and rewrites tnsnames.ora and sqlnet.ora."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        tns_bytes = SAMPLE_TNSNAMES.encode("utf-8")
        tns_info = tarfile.TarInfo(name="tls_wallet/tnsnames.ora")
        tns_info.size = len(tns_bytes)
        tar.addfile(tns_info, io.BytesIO(tns_bytes))

        sqlnet_bytes = SAMPLE_SQLNET.encode("utf-8")
        sqlnet_info = tarfile.TarInfo(name="tls_wallet/sqlnet.ora")
        sqlnet_info.size = len(sqlnet_bytes)
        tar.addfile(sqlnet_info, io.BytesIO(sqlnet_bytes))

        sso_bytes = b"wallet-binary"
        sso_info = tarfile.TarInfo(name="tls_wallet/cwallet.sso")
        sso_info.size = len(sso_bytes)
        tar.addfile(sso_info, io.BytesIO(sso_bytes))

        cert_bytes = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
        cert_info = tarfile.TarInfo(name="tls_wallet/adb_container.cert")
        cert_info.size = len(cert_bytes)
        tar.addfile(cert_info, io.BytesIO(cert_bytes))

    mock_container = MagicMock()
    mock_container.get_archive.return_value = ([tar_buffer.getvalue()], {})

    target_wallet_dir = tmp_path / "wallet"
    service = OracleADBService(
        container=mock_container,
        host="127.0.0.1",
        port=41521,
        tls_port=41522,
        ords_port=48443,
        mongo_port=47017,
        wallet_dir=target_wallet_dir,
        user="app",
        password=DEFAULT_ORACLE_ADB_PASSWORD,
        system_password=DEFAULT_ORACLE_ADB_PASSWORD,
        service_name="myatp_high.adb.oraclecloud.com",
        wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
        workload_type="ATP",
        service_names=ORACLE_ADB_ATP_SERVICES,
    )
    wallet_dir = service.extract_wallet(target_wallet_dir)
    assert (wallet_dir / "cwallet.sso").read_bytes() == b"wallet-binary"
    assert service.ca_cert_path is not None
    assert service.ca_cert_path == wallet_dir / "adb_container.cert"
    assert service.ca_cert_path.read_bytes() == cert_bytes
    assert service.ords_url == "https://127.0.0.1:48443/ords/"
    assert service.apex_url == "https://127.0.0.1:48443/ords/apex"
    assert service.sql_developer_url == "https://127.0.0.1:48443/ords/sql-developer"
    assert "127.0.0.1:47017/app" in service.mongo_uri

    sqlnet_rewritten = (wallet_dir / "sqlnet.ora").read_text(encoding="utf-8")
    assert str(wallet_dir.resolve()) in sqlnet_rewritten
    assert "SSL_SERVER_DN_MATCH=NO" in sqlnet_rewritten
    assert rewrite_sqlnet_ora(SAMPLE_SQLNET, wallet_dir) == sqlnet_rewritten

    tns_parsed = parse_tnsnames((wallet_dir / "tnsnames.ora").read_text(encoding="utf-8"))
    assert tns_parsed["myatp_high"]["host"] == "127.0.0.1"
    assert tns_parsed["myatp_high"]["port"] == "41522"
    assert tns_parsed["myatp_tp"]["port"] == "41521"


def test_ensure_oracle_adb_user_and_enable_ords_schema() -> None:
    """Verify ADMIN provisioning tolerates an existing user, stops on other errors, and ORDS runs ENABLE_SCHEMA."""
    mock_container = MagicMock()
    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_exec:
        ensure_oracle_adb_user(
            container=mock_container,
            user="app_1",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            service_name="myatp_high.adb.oraclecloud.com",
            admin_password=DEFAULT_ORACLE_ADB_PASSWORD,
        )

    mock_exec.assert_called_once()
    _, kwargs = mock_exec.call_args
    assert kwargs["user"] == "admin"
    assert kwargs["as_sysdba"] is False
    assert kwargs["whenever_sqlerror"] == "EXIT SQL.SQLCODE"
    assert "IF SQLCODE != -1920 THEN" in kwargs["sql"]
    assert "IF SQLCODE != -28007 THEN" in kwargs["sql"]
    lines = kwargs["sql"].splitlines()
    assert "      EXECUTE IMMEDIATE 'ALTER USER app_1 IDENTIFIED BY \"Welcome12345!\"';" in lines
    assert "ALTER USER app_1 DEFAULT TABLESPACE DATA TEMPORARY TABLESPACE TEMP ACCOUNT UNLOCK;" in lines
    assert not any(line.startswith("ALTER USER app_1 IDENTIFIED BY") for line in lines)
    assert "GRANT CONNECT, RESOURCE, DWROLE, UNLIMITED TABLESPACE TO app_1;" in kwargs["sql"]

    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_ords:
        enable_oracle_ords_schema(
            mock_container,
            user="app_1",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            service_name="myatp_high.adb.oraclecloud.com",
        )
    _, ords_kwargs = mock_ords.call_args
    assert ords_kwargs["user"] == "app_1"
    assert ords_kwargs["as_sysdba"] is False
    assert ords_kwargs["whenever_sqlerror"] == "EXIT SQL.SQLCODE"
    assert "p_schema => 'APP_1'" in ords_kwargs["sql"]
    assert ords_kwargs["sql"].endswith("/")


@pytest.mark.parametrize(
    ("helper", "message"),
    [
        (
            lambda: ensure_oracle_adb_user(
                MagicMock(), "app_1", DEFAULT_ORACLE_ADB_PASSWORD, "myatp_high.adb.oraclecloud.com", "admin-secret"
            ),
            "Failed to provision Oracle ADB user 'app_1'",
        ),
        (
            lambda: enable_oracle_ords_schema(
                MagicMock(), "app_1", DEFAULT_ORACLE_ADB_PASSWORD, "myatp_high.adb.oraclecloud.com"
            ),
            "Failed to REST-enable schema 'APP_1'",
        ),
    ],
)
def test_oracle_adb_provisioning_failures_raise(helper: Callable[[], None], message: str) -> None:
    """Verify GRANT and ORDS failures surface the SQL*Plus error instead of being ignored."""
    with (
        patch(
            "pytest_databases.docker.oracle._exec_sqlplus", return_value=(1031, b"ORA-01031: insufficient privileges")
        ),
        pytest.raises(RuntimeError, match=message) as exc_info,
    ):
        helper()
    assert "ORA-01031" in str(exc_info.value)


def test_oracle_adb_mongo_uri_escapes_credentials() -> None:
    """Verify the MongoDB API URI percent-encodes the user and password."""
    service = OracleADBService(
        container=MagicMock(),
        host="127.0.0.1",
        port=41521,
        tls_port=41522,
        ords_port=48443,
        mongo_port=47017,
        wallet_dir=None,
        system_password="admin",
        user="app",
        password="Pa:ss@word/1#",
        service_name="myatp_high.adb.oraclecloud.com",
        wallet_password="wallet",
        workload_type="ATP",
        service_names=ORACLE_ADB_ATP_SERVICES,
    )
    assert service.mongo_uri.startswith("mongodb://app:Pa%3Ass%40word%2F1%23@127.0.0.1:47017/app?")


def test_provide_oracle_adb_service_rejects_unknown_workload() -> None:
    """Verify an unknown workload type raises instead of silently falling back to ATP service names."""
    mock_docker = MagicMock()
    with (
        pytest.raises(ValueError, match="Unknown Oracle ADB workload type 'OLTP'"),
        provide_oracle_adb_service(
            docker_service=mock_docker,
            image=DEFAULT_ORACLE_ADB_IMAGE,
            name="oracle_adb",
            workload_type="OLTP",
            hostname="adb-free.local",
            user="app",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            system_password=DEFAULT_ORACLE_ADB_PASSWORD,
            wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
        ),
    ):
        pass
    mock_docker.run.assert_not_called()


def test_provide_oracle_adb_service_configures_ports_and_capabilities(tmp_path: Path) -> None:
    """Verify provide_oracle_adb_service configures all 4 ports, wallet extraction, workload profiles, and volumes."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.ports = {
        "1521/tcp": [{"HostPort": "41521"}],
        "1522/tcp": [{"HostPort": "41522"}],
        "8443/tcp": [{"HostPort": "48443"}],
        "27017/tcp": [{"HostPort": "47017"}],
    }
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=41521)
    mock_docker.run.return_value.__enter__.return_value = mock_service

    wallet_target = tmp_path / "auto_wallet"
    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=None),
        patch("pytest_databases.docker.oracle.tcp_port_open", return_value=True) as mock_tcp,
        patch("pytest_databases.docker.oracle.ensure_oracle_adb_user", return_value=None) as mock_ensure_adb,
        patch("pytest_databases.docker.oracle.enable_oracle_ords_schema", return_value=None) as mock_enable_ords,
        patch("pytest_databases.docker.oracle.extract_adb_wallet", return_value=wallet_target) as mock_extract,
        patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"1")),
        provide_oracle_adb_service(
            docker_service=mock_docker,
            image=DEFAULT_ORACLE_ADB_IMAGE,
            name="oracle_adb",
            workload_type="AJD",
            hostname="adb-free.local",
            user="app",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            system_password=DEFAULT_ORACLE_ADB_PASSWORD,
            wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
            isolation_level="database",
            tz="America/Los_Angeles",
            wallet_dir=wallet_target,
            volumes={"/host/wallet": {"bind": "/u01/app/oracle/wallets/tls_wallet", "mode": "rw"}},
        ) as adb_service,
    ):
        assert adb_service.port == 41521
        assert adb_service.tls_port == 41522
        assert adb_service.ords_port == 48443
        assert adb_service.mongo_port == 47017
        assert adb_service.wallet_dir == wallet_target
        assert adb_service.workload_type == "AJD"
        assert adb_service.service_names == ORACLE_ADB_AJD_SERVICES
        assert adb_service.service_name == "myajd_high.adb.oraclecloud.com"
        assert ORACLE_ADB_ADW_SERVICES[0] == "myadw_high"
        assert ORACLE_ADB_APEX_SERVICES[0] == "myapex_high"
        call_kwargs = mock_docker.run.call_args[1]
        assert call_kwargs["extra_ports"] == {1522: None, 8443: None, 27017: None}
        assert call_kwargs["hostname"] == "adb-free.local"
        assert call_kwargs["cap_add"] == ["SYS_ADMIN"]
        assert call_kwargs["devices"] is None
        assert call_kwargs["volumes"] == {"/host/wallet": {"bind": "/u01/app/oracle/wallets/tls_wallet", "mode": "rw"}}
        assert call_kwargs["entrypoint"] == ["/bin/bash", "-c"]
        assert "*.filesystemio_options='NONE'" in call_kwargs["command"][0]
        assert call_kwargs["env"]["WORKLOAD_TYPE"] == "AJD"
        assert call_kwargs["env"]["WALLET_PASSWORD"] == DEFAULT_ORACLE_ADB_PASSWORD
        assert call_kwargs["env"]["MY_TZ"] == "America/Los_Angeles"
        assert call_kwargs["timeout"] == 420
        assert isinstance(call_kwargs["pause"], float)
        assert call_kwargs["pause"] == pytest.approx(2.0, abs=0.0)
        check_fn = call_kwargs["check"]
        assert check_fn(mock_service) is True
        mock_tcp.assert_called_once_with("127.0.0.1", 41521)
        mock_ensure_adb.assert_called_once()
        mock_enable_ords.assert_called_once()
        mock_extract.assert_called_once_with(
            mock_container,
            wallet_target,
            host="127.0.0.1",
            port=41521,
            tls_port=41522,
        )


@pytest.mark.parametrize(
    ("filesystemio_options", "expected_value"),
    [("NONE", "NONE"), ("setall", "SETALL"), (" async ", "ASYNC"), (None, None)],
)
def test_provide_oracle_adb_service_filesystemio_options_command(
    filesystemio_options: str | None, expected_value: str | None
) -> None:
    """Verify the container command rewrites the spfile with the requested value before the image entrypoint runs."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        container=mock_container, host="127.0.0.1", port=41521
    )
    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=None),
        patch("pytest_databases.docker.oracle.ContainerService.resolve_port", return_value=41522),
        provide_oracle_adb_service(
            docker_service=mock_docker,
            image=DEFAULT_ORACLE_ADB_IMAGE,
            name="oracle_adb",
            workload_type="ATP",
            hostname="adb-free.local",
            user="app",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            system_password=DEFAULT_ORACLE_ADB_PASSWORD,
            wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
            filesystemio_options=filesystemio_options,
        ),
    ):
        pass
    call_kwargs = mock_docker.run.call_args.kwargs
    if expected_value is None:
        assert call_kwargs["entrypoint"] is None
        assert call_kwargs["command"] is None
        return
    assert call_kwargs["entrypoint"] == ["/bin/bash", "-c"]
    script = call_kwargs["command"][0]
    create_pfile = script.index("CREATE PFILE='$HOME/pytest-databases-init.ora' FROM SPFILE;")
    drop_old = script.index("sed -i '/^\\*\\.filesystemio_options=/d' \"$HOME/pytest-databases-init.ora\"")
    add_new = script.index(f'echo "*.filesystemio_options=\'{expected_value}\'" >> "$HOME/pytest-databases-init.ora"')
    create_spfile = script.index("CREATE SPFILE FROM PFILE='$HOME/pytest-databases-init.ora';")
    run_entrypoint = script.index('exec "${RUNTIME_SCRIPTS:-/u01/scripts}/${ENTRYPOINT_SCRIPT:-entrypoint.sh}"')
    assert script.startswith("set -e\n")
    assert create_pfile < drop_old < add_new < create_spfile < run_entrypoint
    assert script.count("WHENEVER SQLERROR EXIT FAILURE") == 2


def test_provide_oracle_adb_service_rejects_invalid_filesystemio_options() -> None:
    """Verify an unknown ``filesystemio_options`` value raises before any container starts."""
    mock_docker = MagicMock()
    with (
        pytest.raises(ValueError, match="Invalid filesystemio_options 'OFF'"),
        provide_oracle_adb_service(
            docker_service=mock_docker,
            image=DEFAULT_ORACLE_ADB_IMAGE,
            name="oracle_adb",
            workload_type="ATP",
            hostname="adb-free.local",
            user="app",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            system_password=DEFAULT_ORACLE_ADB_PASSWORD,
            wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
            filesystemio_options="OFF",
        ),
    ):
        pass
    mock_docker.run.assert_not_called()


@pytest.mark.parametrize(("env_value", "expected"), [(None, "NONE"), ("SETALL", "SETALL")])
def test_oracle_adb_filesystemio_options_fixture(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, env_value: str | None, expected: str
) -> None:
    """Verify ``oracle_adb_filesystemio_options`` defaults to ``NONE`` and honors ``ORACLE_ADB_FILESYSTEMIO_OPTIONS``."""
    if env_value is None:
        monkeypatch.delenv("ORACLE_ADB_FILESYSTEMIO_OPTIONS", raising=False)
    else:
        monkeypatch.setenv("ORACLE_ADB_FILESYSTEMIO_OPTIONS", env_value)
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.oracle"]

    def test_value(oracle_adb_filesystemio_options) -> None:
        assert oracle_adb_filesystemio_options == {expected!r}
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.fixture
def fake_oracledb(monkeypatch: MonkeyPatch) -> MagicMock:
    """Replace the lazy ``oracledb`` import with a mock whose connection returns ``1`` from ``dual``."""
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = (1,)
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.__enter__.return_value = fake_conn
    fake_module = MagicMock()
    fake_module.connect.return_value = fake_conn
    monkeypatch.setattr(oracle, "_load_oracledb", lambda: fake_module)
    return fake_module


def test_oracle_responsive_emits_one_warning(fake_oracledb: MagicMock) -> None:
    """Verify the deprecated oracle_responsive helper warns once at the caller and still probes."""
    with pytest.warns(DeprecationWarning, match="oracle_responsive") as record:
        assert oracle.oracle_responsive("127.0.0.1", 1521, "FREEPDB1", "app", "secret") is True

    assert len(record) == 1
    assert record[0].filename == __file__
    fake_oracledb.connect.assert_called_once()


@pytest.mark.parametrize(
    ("fixture_def", "fixture_name", "takes_request"),
    [
        (oracle_18c_connection, "oracle_18c_connection", False),
        (oracle_23ai_connection, "oracle_23ai_connection", True),
        (oracle_26ai_connection, "oracle_26ai_connection", False),
        (oracle_startup_connection, "oracle_startup_connection", False),
    ],
)
def test_deprecated_oracle_connection_fixtures_emit_one_warning(
    fake_oracledb: MagicMock,
    fixture_def: object,
    fixture_name: str,
    takes_request: bool,
) -> None:
    """Verify each Oracle connection fixture warns once, attributed to the module, and connects."""
    service = OracleService(
        container=MagicMock(),
        host="127.0.0.1",
        port=1521,
        user="app",
        password="secret",
        system_password="sys-secret",
        service_name="FREEPDB1",
    )
    mock_request = MagicMock()
    mock_request._fixturemanager.getfixturedefs.return_value = []
    mock_request.getfixturevalue.return_value = service
    arg: object = mock_request if takes_request else service
    with pytest.warns(DeprecationWarning, match=fixture_name) as record:
        conn_gen = unwrap_fixture(fixture_def)(arg)
        assert next(conn_gen) is fake_oracledb.connect.return_value
        with pytest.raises(StopIteration):
            next(conn_gen)

    assert len(record) == 1
    assert record[0].filename == oracle.__file__
    fake_oracledb.connect.assert_called_once_with(
        host="127.0.0.1",
        port=1521,
        user="app",
        service_name="FREEPDB1",
        password="secret",
    )


@pytest.fixture(scope="module")
def oracle_test_helpers() -> str:
    """Provide SQL*Plus execution helper code for pytester integration tests."""
    return """
    import shlex

    def run_sqlplus(service, sql):
        statement = sql.strip()
        if not statement.endswith(";"):
            statement = f"{statement};"
        script = "\\n".join([
            "SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF",
            "WHENEVER OSERROR EXIT 9",
            "WHENEVER SQLERROR EXIT SQL.SQLCODE",
            statement,
            "EXIT",
            "",
        ])
        connect_string = f"{service.user}/{service.password}@//localhost:1521/{service.service_name}"
        command = f"printf '%s' {shlex.quote(script)} | sqlplus -L -S {shlex.quote(connect_string)}"
        result = service.container.exec_run(["bash", "-lc", command])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return [line.strip() for line in result.output.decode().splitlines() if line.strip()]
    """


@pytest.mark.parametrize(
    "service_fixture",
    [
        "oracle_18c_service",
        "oracle_26ai_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str, oracle_test_helpers: str) -> None:
    """Run integration smoke tests against Oracle 18c and 26ai service fixtures."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.oracle"]

    {oracle_test_helpers}

    def test({service_fixture}):
        assert run_sqlplus({service_fixture}, "SELECT 1 FROM dual") == ["1"]
        run_sqlplus({service_fixture}, "CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        assert run_sqlplus({service_fixture}, "select * from simple_table") == ["1"]
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_oracle_adb_service_live(pytester: pytest.Pytester) -> None:
    """Verify a live ADB-Free container provisions the user, REST-enables the schema, and extracts a usable wallet."""
    pytester.makepyfile("""
    from pytest_databases.docker.oracle import _exec_sqlplus, parse_tnsnames

    pytest_plugins = ["pytest_databases.docker.oracle"]

    def test_adb(oracle_adb_service) -> None:
        exit_code, output = _exec_sqlplus(
            oracle_adb_service.container,
            oracle_adb_service.user,
            oracle_adb_service.password,
            oracle_adb_service.service_name,
            "SELECT status FROM user_ords_schemas",
        )
        assert exit_code == 0, output
        assert output.strip() == b"ENABLED"
        assert oracle_adb_service.wallet_dir is not None
        assert (oracle_adb_service.wallet_dir / "cwallet.sso").is_file()
        entries = parse_tnsnames((oracle_adb_service.wallet_dir / "tnsnames.ora").read_text())
        high = entries[oracle_adb_service.service_names[0]]
        assert high["host"] == oracle_adb_service.host
        assert high["port"] in {str(oracle_adb_service.port), str(oracle_adb_service.tls_port)}
        exit_code, output = _exec_sqlplus(
            oracle_adb_service.container,
            oracle_adb_service.user,
            oracle_adb_service.password,
            oracle_adb_service.service_name,
            "SELECT 6 * 7 FROM dual",
        )
        assert exit_code == 0, output
        assert output.strip() == b"42"
        spfile = oracle_adb_service.container.exec_run(
            ["bash", "-c", 'strings "$ORACLE_HOME/dbs/spfile$ORACLE_SID.ora" | grep filesystemio_options']
        )
        assert spfile.exit_code == 0
        assert b"*.filesystemio_options='NONE'" in spfile.output
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv", timeout=1200)
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (b"ORA-01033: ORACLE initialization or shutdown in progress", True),
        (b"ORA-01034: ORACLE not available", True),
        (b"ORA-12514: TNS:listener does not currently know of service", True),
        (b"ORA-12516: TNS:listener could not find available handler with matching protocol stack", True),
        (b"ORA-12519: TNS:no appropriate service handler found", True),
        (b"ORA-12520: TNS:listener could not find available handler for requested type of server", True),
        (b"ORA-12528: TNS:listener: all appropriate instances are blocking new connections", True),
        (b"ORA-00054: resource busy and acquire with NOWAIT specified", True),
        (b"ORA-00060: deadlock detected while waiting for resource", True),
        (b"ORA-04021: timeout occurred while waiting to lock object", True),
        (b"ORA-00942: table or view does not exist", False),
        (b"ORA-01017: invalid username/password; logon denied", False),
    ],
)
def test_is_transient_oracle_error(output: bytes, expected: bool) -> None:
    """Verify transient Oracle Listener/startup/lock error code detection."""
    assert _is_transient_oracle_error(output) is expected


def test_ensure_oracle_adb_user_and_ords_retries_on_transient_ora_error() -> None:
    """Verify ensure_oracle_adb_user and enable_oracle_ords_schema retry transient ORA errors."""
    container = MagicMock()
    container.exec_run.side_effect = [
        MagicMock(exit_code=1, output=b"ORA-12514: listener does not know of service"),
        MagicMock(exit_code=0, output=b"PL/SQL procedure successfully completed."),
        MagicMock(exit_code=1, output=b"ORA-00054: resource busy"),
        MagicMock(exit_code=0, output=b"PL/SQL procedure successfully completed."),
    ]
    with patch("pytest_databases.docker.oracle.time.sleep"):
        ensure_oracle_adb_user(
            container,
            user="pytest_0",
            password="Password123",
            service_name="myatp_high.adb.oraclecloud.com",
            admin_password="Password123",
        )
        enable_oracle_ords_schema(
            container,
            user="pytest_0",
            password="Password123",
            service_name="myatp_high.adb.oraclecloud.com",
        )
    assert container.exec_run.call_count == 4


@pytest.mark.parametrize(
    ("fixture_def", "env_var", "env_value", "expected"),
    [
        (oracle_startup_timeout, "ORACLE_STARTUP_TIMEOUT", None, 180),
        (oracle_adb_startup_timeout, "ORACLE_ADB_STARTUP_TIMEOUT", None, 420),
        (oracle_startup_timeout, "ORACLE_STARTUP_TIMEOUT", " 240 ", 240),
        (oracle_adb_startup_timeout, "ORACLE_ADB_STARTUP_TIMEOUT", "600", 600),
        (oracle_startup_timeout, "ORACLE_STARTUP_TIMEOUT", "", ValueError),
        (oracle_startup_timeout, "ORACLE_STARTUP_TIMEOUT", "invalid", ValueError),
        (oracle_startup_timeout, "ORACLE_STARTUP_TIMEOUT", "0", ValueError),
        (oracle_startup_timeout, "ORACLE_STARTUP_TIMEOUT", "-5", ValueError),
        (oracle_adb_startup_timeout, "ORACLE_ADB_STARTUP_TIMEOUT", "", ValueError),
        (oracle_adb_startup_timeout, "ORACLE_ADB_STARTUP_TIMEOUT", "invalid", ValueError),
        (oracle_adb_startup_timeout, "ORACLE_ADB_STARTUP_TIMEOUT", "0", ValueError),
        (oracle_adb_startup_timeout, "ORACLE_ADB_STARTUP_TIMEOUT", "-5", ValueError),
    ],
)
def test_oracle_startup_timeout_fixtures(
    monkeypatch: MonkeyPatch,
    fixture_def: object,
    env_var: str,
    env_value: str | None,
    expected: int | type[ValueError],
) -> None:
    """Verify Oracle startup timeout fixtures resolve defaults, parse valid env overrides, and reject invalid values."""
    if env_value is None:
        monkeypatch.delenv(env_var, raising=False)
    else:
        monkeypatch.setenv(env_var, env_value)
    assert "oracle_startup_timeout" in oracle.__all__
    assert "oracle_adb_startup_timeout" in oracle.__all__
    fn = unwrap_fixture(fixture_def)
    if isinstance(expected, type):
        with pytest.raises(expected, match=env_var):
            fn()
    else:
        assert fn() == expected


@pytest.mark.parametrize(
    ("provider_kind", "timeout_value", "pause_value", "expected", "error_match"),
    [
        ("oracle", None, None, (180, 1.0), ""),
        ("oracle", 240, None, (240, 1.0), ""),
        ("oracle", 240, 0.25, (240, 0.25), ""),
        ("oracle", None, 3, (180, 3.0), ""),
        ("oracle_adb", None, None, (420, 2.0), ""),
        ("oracle_adb", 500, None, (500, 2.0), ""),
        ("oracle_adb", 500, 0.5, (500, 0.5), ""),
        ("oracle_adb", None, 4, (420, 4.0), ""),
        ("oracle", 0, None, ValueError, "timeout"),
        ("oracle", -1, None, ValueError, "timeout"),
        ("oracle", True, None, ValueError, "timeout"),
        ("oracle", False, None, ValueError, "timeout"),
        ("oracle", 1.5, None, ValueError, "timeout"),
        ("oracle", "180", None, ValueError, "timeout"),
        ("oracle_adb", 0, None, ValueError, "timeout"),
        ("oracle_adb", -1, None, ValueError, "timeout"),
        ("oracle_adb", True, None, ValueError, "timeout"),
        ("oracle_adb", False, None, ValueError, "timeout"),
        ("oracle_adb", 1.5, None, ValueError, "timeout"),
        ("oracle_adb", "180", None, ValueError, "timeout"),
        ("oracle", None, 0, ValueError, "pause"),
        ("oracle", None, -0.5, ValueError, "pause"),
        ("oracle", None, True, ValueError, "pause"),
        ("oracle", None, False, ValueError, "pause"),
        ("oracle", None, float("nan"), ValueError, "pause"),
        ("oracle", None, float("inf"), ValueError, "pause"),
        ("oracle", None, "1.0", ValueError, "pause"),
        ("oracle_adb", None, 0, ValueError, "pause"),
        ("oracle_adb", None, -1.0, ValueError, "pause"),
        ("oracle_adb", None, True, ValueError, "pause"),
        ("oracle_adb", None, False, ValueError, "pause"),
        ("oracle_adb", None, float("nan"), ValueError, "pause"),
        ("oracle_adb", None, float("inf"), ValueError, "pause"),
        ("oracle_adb", None, "2.0", ValueError, "pause"),
    ],
)
def test_provide_oracle_timeout_validation_and_forwarding(
    provider_kind: str,
    timeout_value: object,
    pause_value: object,
    expected: tuple[int, float] | type[ValueError],
    error_match: str,
) -> None:
    """Verify Oracle providers validate timeout and pause upfront and forward custom settings."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.ports = {
        "1521/tcp": [{"HostPort": "41521"}],
        "1522/tcp": [{"HostPort": "41522"}],
        "8443/tcp": [{"HostPort": "48443"}],
        "27017/tcp": [{"HostPort": "47017"}],
    }
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        container=mock_container, host="127.0.0.1", port=41521
    )

    kwargs: dict[str, Any] = {}
    if timeout_value is not None:
        kwargs["timeout"] = timeout_value
    if pause_value is not None:
        kwargs["pause"] = pause_value

    if provider_kind == "oracle":
        oracle_call = partial(
            provide_oracle_service,
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle26ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
        )
        ctx = oracle_call(**kwargs)
    else:
        adb_call = partial(
            provide_oracle_adb_service,
            docker_service=mock_docker,
            image=DEFAULT_ORACLE_ADB_IMAGE,
            name="oracle_adb",
            workload_type="ATP",
            hostname="adb-free.local",
            user="app",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            system_password=DEFAULT_ORACLE_ADB_PASSWORD,
            wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
        )
        ctx = adb_call(**kwargs)

    if isinstance(expected, type):
        with pytest.raises(expected, match=error_match), ctx:
            pass
        mock_docker.run.assert_not_called()
        return

    with ctx:
        pass
    call_kwargs = mock_docker.run.call_args.kwargs
    expected_timeout, expected_pause = expected
    assert call_kwargs["timeout"] == expected_timeout
    assert isinstance(call_kwargs["pause"], float)
    assert call_kwargs["pause"] == pytest.approx(expected_pause, abs=0.0)


@pytest.mark.parametrize(
    ("fixture_name", "timeout_override"),
    [
        ("oracle_26ai_service", 240),
        ("oracle_18c_service", 240),
        ("oracle_adb_service", 500),
    ],
)
def test_oracle_service_fixtures_forward_startup_timeout(
    tmp_path: Path,
    fixture_name: str,
    timeout_override: int,
) -> None:
    """Verify Oracle service fixtures inject and forward overridden startup timeout fixture values."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.ports = {
        "1521/tcp": [{"HostPort": "41521"}],
        "1522/tcp": [{"HostPort": "41522"}],
        "8443/tcp": [{"HostPort": "48443"}],
        "27017/tcp": [{"HostPort": "47017"}],
    }
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        container=mock_container, host="127.0.0.1", port=41521
    )

    if fixture_name == "oracle_26ai_service":
        gen = unwrap_fixture(oracle_26ai_service)(
            docker_service=mock_docker,
            xdist_oracle_isolation_level="database",
            oracle_26ai_image="gvenzl/oracle-free:23-slim-faststart",
            oracle_26ai_service_name="FREEPDB1",
            oracle_user="app",
            oracle_password="secret",
            oracle_system_password="sys-secret",
            oracle_startup_timeout=timeout_override,
            oracle_26ai_port=None,
        )
        next(gen)
        with pytest.raises(StopIteration):
            next(gen)
    elif fixture_name == "oracle_18c_service":
        gen = unwrap_fixture(oracle_18c_service)(
            docker_service=mock_docker,
            xdist_oracle_isolation_level="database",
            oracle_18c_image="gvenzl/oracle-xe:18-slim-faststart",
            oracle_18c_service_name="xepdb1",
            oracle_user="app",
            oracle_password="secret",
            oracle_system_password="sys-secret",
            oracle_startup_timeout=timeout_override,
            oracle_18c_port=None,
        )
        next(gen)
        with pytest.raises(StopIteration):
            next(gen)
    else:
        with patch("pytest_databases.docker.oracle.extract_adb_wallet", return_value=tmp_path):
            adb_gen = unwrap_fixture(oracle_adb_service)(
                docker_service=mock_docker,
                xdist_oracle_isolation_level="database",
                oracle_adb_image=DEFAULT_ORACLE_ADB_IMAGE,
                oracle_adb_workload_type="ATP",
                oracle_adb_hostname="adb-free.local",
                oracle_adb_tz="UTC",
                oracle_user="app",
                oracle_adb_password=DEFAULT_ORACLE_ADB_PASSWORD,
                oracle_adb_admin_password=DEFAULT_ORACLE_ADB_PASSWORD,
                oracle_adb_wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
                oracle_adb_wallet_dir=tmp_path,
                oracle_adb_volumes=None,
                oracle_adb_devices=None,
                oracle_adb_filesystemio_options="NONE",
                oracle_adb_startup_timeout=timeout_override,
                oracle_adb_port=None,
            )
            next(adb_gen)
            with pytest.raises(StopIteration):
                next(adb_gen)

    assert mock_docker.run.call_args.kwargs["timeout"] == timeout_override


@pytest.mark.parametrize("provider_kind", ["oracle", "oracle_adb"])
def test_oracle_check_short_circuits_when_tcp_port_closed(provider_kind: str) -> None:
    """Verify check() returns False before spawning sqlplus when the mapped host TCP port is not open yet."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.ports = {
        "1521/tcp": [{"HostPort": "41521"}],
        "1522/tcp": [{"HostPort": "41522"}],
        "8443/tcp": [{"HostPort": "48443"}],
        "27017/tcp": [{"HostPort": "47017"}],
    }
    port = 1521 if provider_kind == "oracle" else 41521
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=port)
    mock_docker.run.return_value.__enter__.return_value = mock_service

    ctx = (
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle26ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
        )
        if provider_kind == "oracle"
        else provide_oracle_adb_service(
            docker_service=mock_docker,
            image=DEFAULT_ORACLE_ADB_IMAGE,
            name="oracle_adb",
            workload_type="ATP",
            hostname="adb-free.local",
            user="app",
            password=DEFAULT_ORACLE_ADB_PASSWORD,
            system_password=DEFAULT_ORACLE_ADB_PASSWORD,
            wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
        )
    )

    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=1),
        patch("pytest_databases.docker.oracle.tcp_port_open", return_value=False) as mock_tcp,
        ctx,
    ):
        check_fn = mock_docker.run.call_args.kwargs["check"]
        assert check_fn(mock_service) is False

    mock_tcp.assert_called_once_with("127.0.0.1", port)
    assert mock_container.exec_run.call_count == 0


def test_oracle_all_fixtures_inprocess(pytester: Pytester, monkeypatch: MonkeyPatch) -> None:
    """Verify all Oracle fixtures execute in-process when service and connection providers are mocked."""
    for var in (
        "ORACLE_STARTUP_TIMEOUT",
        "ORACLE_ADB_STARTUP_TIMEOUT",
        "ORACLE_PORT",
        "ORACLE_26AI_PORT",
        "ORACLE_26AI_IMAGE",
        "ORACLE_26AI_SERVICE_NAME",
        "ORACLE_18C_PORT",
        "ORACLE_ADB_PORT",
        "ORACLE_ADB_IMAGE",
        "ORACLE_USER",
        "ORACLE_PASSWORD",
        "ORACLE_SYSTEM_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest

    pytest_plugins = ["pytest_databases.docker.oracle"]

    @pytest.fixture(scope="session")
    def docker_service() -> MagicMock:
        return MagicMock()

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_ora = MagicMock()
        mock_adb = MagicMock()

        @contextmanager
        def fake_ora(*args, **kwargs):
            yield mock_ora

        @contextmanager
        def fake_adb(*args, **kwargs):
            yield mock_adb

        fake_module = MagicMock()
        fake_conn = MagicMock()
        fake_conn.__enter__.return_value = fake_conn
        fake_module.connect.return_value = fake_conn

        with (
            patch("pytest_databases.docker.oracle.provide_oracle_service", side_effect=fake_ora),
            patch("pytest_databases.docker.oracle.provide_oracle_adb_service", side_effect=fake_adb),
            patch("pytest_databases.docker.oracle._load_oracledb", return_value=fake_module),
        ):
            assert request.getfixturevalue("oracle_startup_timeout") == 180
            assert request.getfixturevalue("oracle_adb_startup_timeout") == 420
            assert request.getfixturevalue("oracle_adb_image") == (
                "container-registry.oracle.com/database/adb-free:latest-26ai"
            )
            assert request.getfixturevalue("oracle_26ai_image") == "gvenzl/oracle-free:23-slim-faststart"
            assert request.getfixturevalue("oracle_26ai_service_name") == "FREEPDB1"
            assert request.getfixturevalue("oracle_23ai_image") == "gvenzl/oracle-free:23-slim-faststart"
            assert request.getfixturevalue("oracle_23ai_service_name") == "FREEPDB1"
            assert request.getfixturevalue("oracle_port") is None
            assert request.getfixturevalue("oracle_26ai_port") is None
            assert request.getfixturevalue("oracle_18c_port") is None
            assert request.getfixturevalue("oracle_adb_port") is None
            assert request.getfixturevalue("oracle_26ai_service") is mock_ora
            assert request.getfixturevalue("oracle_23ai_service") is mock_ora
            assert request.getfixturevalue("oracle_18c_service") is mock_ora
            assert request.getfixturevalue("oracle_service") is mock_ora
            assert request.getfixturevalue("oracle_adb_service") is mock_adb
            assert request.getfixturevalue("oracle_18c_connection") is fake_conn
            assert request.getfixturevalue("oracle_23ai_connection") is fake_conn
            assert request.getfixturevalue("oracle_26ai_connection") is fake_conn
            assert request.getfixturevalue("oracle_startup_connection") is fake_conn
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_user", "expected_name"),
    [
        (None, "database", "app", "oracle26ai"),
        (2, "database", "app_2", "oracle26ai"),
        (2, "server", "app", "oracle26ai_2"),
    ],
)
def test_provide_oracle_service_grants_privileges_in_all_concurrency_modes(
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    expected_user: str,
    expected_name: str,
) -> None:
    """Verify ensure_oracle_user runs identically in single-process, xdist database, and xdist server modes."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "oracid1234567890"
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=31521)
    mock_docker.run.return_value.__enter__.return_value = mock_service

    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=worker_num),
        patch("pytest_databases.docker.oracle.tcp_port_open", return_value=True),
        patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"1\n")),
        patch("pytest_databases.docker.oracle.ensure_oracle_user", return_value=True) as mock_ensure,
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle26ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            isolation_level=isolation_level,
        ) as svc,
    ):
        assert svc.user == expected_user
        run_kwargs = mock_docker.run.call_args.kwargs
        assert run_kwargs["name"] == expected_name
        check_fn = run_kwargs["check"]
        assert check_fn(mock_service) is True
        assert check_fn(mock_service) is True

    mock_ensure.assert_called_once_with(
        mock_container,
        user=expected_user,
        password="secret",
        service_name="FREEPDB1",
        system_password="sys-secret",
    )


def test_exec_oracle_sql_and_service_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify exec_oracle_sql TNS + CDB$ROOT modes, OracleService.exec_sql, and resource/init_sql options."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(oracle.tempfile, "tempdir", str(tmp_path))

    mock_container = MagicMock()
    mock_container.id = "oracid9876543210"
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"CDB$ROOT\n")

    code, out = exec_oracle_sql(mock_container, "SELECT sys_context('USERENV','CON_NAME') FROM dual", as_sysdba=True)
    assert (code, out) == (0, b"CDB$ROOT\n")
    cdb_cmd = mock_container.exec_run.call_args.args[0][2]
    assert "sqlplus -L -S / as sysdba" in cdb_cmd

    with pytest.raises(ValueError, match="requires 'service_name'"):
        exec_oracle_sql(mock_container, "SELECT 1 FROM dual")

    mock_docker = MagicMock()
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=21521)
    mock_docker.run.return_value.__enter__.return_value = mock_service
    sql_path = tmp_path / "oracle_seed.sql"
    sql_path.write_text("CREATE TABLE ora_seed (id NUMBER);", encoding="utf-8")

    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=None),
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle26ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            host_port=21521,
            env={"ORACLE_CHARACTERSET": "AL32UTF8"},
            volumes={"/host/data": {"bind": "/opt/oracle/oradata", "mode": "rw"}},
            shm_size="2g",
            mem_limit="4g",
            init_sql=sql_path,
        ) as svc,
    ):
        assert svc.exec_sql("SELECT 1 FROM dual")[0] == 0
        assert svc.exec_sql("SELECT 1 FROM v$instance", as_sysdba=True)[0] == 0
        assert svc.exec_sql("SHOW CON_NAME", cdb_root=True)[0] == 0

    run_kwargs = mock_docker.run.call_args.kwargs
    assert run_kwargs["host_port"] == 21521
    assert run_kwargs["shm_size"] == "2g"
    assert run_kwargs["mem_limit"] == "4g"
    assert run_kwargs["env"]["ORACLE_CHARACTERSET"] == "AL32UTF8"
    assert run_kwargs["volumes"] == {"/host/data": {"bind": "/opt/oracle/oradata", "mode": "rw"}}


def test_oracle_26ai_fixtures_and_23ai_deprecation_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Oracle 26ai defaults/env overrides, ADB 26ai default image, and v0.19.0 23ai deprecation shims."""
    assert DEFAULT_ORACLE_ADB_IMAGE == "container-registry.oracle.com/database/adb-free:latest-26ai"
    monkeypatch.delenv("ORACLE_ADB_IMAGE", raising=False)
    assert unwrap_fixture(oracle_adb_image)() == DEFAULT_ORACLE_ADB_IMAGE
    assert not hasattr(oracle, "oracle_23ai_port")
    assert "oracle_23ai_port" not in oracle.__all__
    assert {"oracle_23ai_service", "oracle_23ai_image", "oracle_23ai_service_name", "oracle_23ai_connection"}.issubset(
        oracle.__all__
    )

    monkeypatch.setenv("ORACLE_26AI_IMAGE", "gvenzl/oracle-free:23.26.3-slim-faststart")
    monkeypatch.setenv("ORACLE_26AI_SERVICE_NAME", "PDB26")
    monkeypatch.setenv("ORACLE_PORT", "11521")
    monkeypatch.delenv("ORACLE_26AI_PORT", raising=False)

    mock_request = MagicMock()
    mock_request._fixturemanager.getfixturedefs.return_value = []
    assert unwrap_fixture(oracle_26ai_image)(mock_request) == "gvenzl/oracle-free:23.26.3-slim-faststart"
    assert unwrap_fixture(oracle_26ai_service_name)(mock_request) == "PDB26"

    with pytest.warns(DeprecationWarning, match="oracle_23ai_image") as image_warn:
        assert unwrap_fixture(oracle_23ai_image)() == "gvenzl/oracle-free:23.26.3-slim-faststart"
    assert len(image_warn) == 1
    assert image_warn[0].filename == __file__

    with pytest.warns(DeprecationWarning, match="oracle_23ai_service_name") as svc_name_warn:
        assert unwrap_fixture(oracle_23ai_service_name)() == "PDB26"
    assert len(svc_name_warn) == 1
    assert svc_name_warn[0].filename == __file__

    base_port = unwrap_fixture(oracle_port)()
    assert base_port == 11521
    assert unwrap_fixture(oracle_26ai_port)(base_port) == 11521
    monkeypatch.setenv("ORACLE_26AI_PORT", "12521")
    assert unwrap_fixture(oracle_26ai_port)(base_port) == 12521

    sentinel = MagicMock(spec=OracleService)
    mock_request.getfixturevalue.return_value = sentinel
    assert unwrap_fixture(oracle_service)(mock_request) is sentinel
    mock_request.getfixturevalue.assert_called_once_with("oracle_26ai_service")

    with pytest.warns(DeprecationWarning, match="oracle_23ai_service") as svc_warn:
        assert unwrap_fixture(oracle_23ai_service)(sentinel) is sentinel
    assert len(svc_warn) == 1
    assert svc_warn[0].filename == __file__

    captured: list[dict[str, Any]] = []

    @contextlib.contextmanager
    def _fake_provide(**kwargs: Any) -> Generator[MagicMock, None, None]:
        captured.append(kwargs)
        yield sentinel

    monkeypatch.setattr(oracle, "provide_oracle_service", _fake_provide)
    gen = unwrap_fixture(oracle_26ai_service)(
        docker_service=MagicMock(),
        xdist_oracle_isolation_level="database",
        oracle_26ai_image="gvenzl/oracle-free:23.26.3-slim-faststart",
        oracle_26ai_service_name="PDB26",
        oracle_user="app",
        oracle_password="secret",
        oracle_system_password="sys-secret",
        oracle_startup_timeout=180,
        oracle_26ai_port=12521,
    )
    assert next(gen) is sentinel
    with pytest.raises(StopIteration):
        next(gen)
    assert captured[0]["name"] == "oracle26ai"
    assert captured[0]["image"] == "gvenzl/oracle-free:23.26.3-slim-faststart"
    assert captured[0]["service_name"] == "PDB26"
    assert captured[0]["host_port"] == 12521


@pytest.mark.parametrize(
    ("requested", "override_block", "expected_value", "expected_warnings"),
    [
        ("oracle_26ai_image", "", "gvenzl/oracle-free:23-slim-faststart", []),
        ("oracle_26ai_service_name", "", "FREEPDB1", []),
        (
            "oracle_26ai_image",
            '@pytest.fixture(scope="session")\ndef oracle_23ai_image():\n    return "custom/oracle:23"\n',
            "custom/oracle:23",
            ["Override 'oracle_26ai_image' instead."],
        ),
        (
            "oracle_26ai_service_name",
            '@pytest.fixture(scope="session")\ndef oracle_23ai_service_name():\n    return "CUSTOMPDB"\n',
            "CUSTOMPDB",
            ["Override 'oracle_26ai_service_name' instead."],
        ),
        (
            "oracle_service",
            '@pytest.fixture(scope="session")\ndef oracle_26ai_service():\n    return "canonical-26ai"\n',
            "canonical-26ai",
            [],
        ),
        (
            "oracle_service",
            '@pytest.fixture(scope="session")\ndef oracle_23ai_service():\n    return "legacy-23ai"\n',
            "legacy-23ai",
            ["Override 'oracle_26ai_service' instead."],
        ),
        (
            "oracle_23ai_connection",
            (
                "import sys\nfrom unittest.mock import MagicMock\n"
                "from pytest_databases.docker.oracle import OracleService\n"
                'fake_conn = MagicMock(name="conn")\n'
                'fake_conn.__enter__.return_value = "legacy-conn"\n'
                "fake_oracledb = MagicMock()\n"
                "fake_oracledb.connect.return_value = fake_conn\n"
                'sys.modules["oracledb"] = fake_oracledb\n\n'
                '@pytest.fixture(scope="session")\n'
                "def oracle_23ai_service():\n"
                "    return OracleService(\n"
                "        container=MagicMock(),\n"
                '        host="127.0.0.1",\n'
                "        port=1521,\n"
                '        user="app",\n'
                '        password="p",\n'
                '        system_password="p",\n'
                '        service_name="LEGACY",\n'
                "    )\n"
            ),
            "legacy-conn",
            ["Override 'oracle_26ai_service' instead.", "The 'oracle_23ai_connection' fixture is deprecated"],
        ),
    ],
)
def test_oracle_23ai_override_compatibility(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    override_block: str,
    expected_value: str,
    expected_warnings: list[str],
) -> None:
    """Verify canonical 26ai fixtures stay silent by default and honor user oracle_23ai_* overrides with warnings."""
    monkeypatch.delenv("ORACLE_26AI_IMAGE", raising=False)
    monkeypatch.delenv("ORACLE_26AI_SERVICE_NAME", raising=False)
    recorded = run_recording_deprecations(
        pytester,
        f'import pytest\n\npytest_plugins = ["pytest_databases.docker.oracle"]\n\n{override_block}\n'
        f"def test_oracle_compat({requested}):\n    assert {requested} == {expected_value!r}\n",
    )
    assert len(recorded) == len(expected_warnings), recorded
    for actual, expected_fragment in zip(recorded, expected_warnings, strict=True):
        assert expected_fragment in actual
        assert "v1.0.0" in actual


@pytest.mark.parametrize(
    ("sql", "connect_as", "whenever_sqlerror", "raw_result", "expected_code", "expected_fragments"),
    [
        (
            "SELECT 1 FROM DUAL",
            "/ as sysdba",
            "EXIT SQL.SQLCODE",
            (0, b"1\n"),
            0,
            ("sqlplus -L -S / as sysdba", "SELECT 1 FROM DUAL;"),
        ),
        (
            "BEGIN NULL; END;",
            "/ as sysdba",
            "EXIT SQL.SQLCODE",
            (0, b""),
            0,
            ("sqlplus -L -S / as sysdba", "BEGIN NULL; END;\n/"),
        ),
        (
            "DECLARE v_num NUMBER := 1; BEGIN NULL; END;",
            "/ as sysdba",
            "EXIT SQL.SQLCODE",
            (0, b""),
            0,
            ("DECLARE v_num NUMBER := 1; BEGIN NULL; END;\n/",),
        ),
        (
            "SELECT 1 FROM DUAL",
            "u/p@//127.0.0.1:1521/FREEPDB1",
            "EXIT SQL.SQLCODE",
            (0, b"SP2-0306: Invalid option.\n"),
            1,
            ("sqlplus -L -S u/p@//127.0.0.1:1521/FREEPDB1",),
        ),
        (
            "SELECT 1 FROM missing_table",
            "u/p@//127.0.0.1:1521/FREEPDB1",
            "CONTINUE",
            (0, b"ORA-00942: table or view does not exist\n"),
            0,
            ("WHENEVER SQLERROR CONTINUE",),
        ),
    ],
)
def test_exec_sqlplus_normalizes_plsql_and_error_exit_codes(
    sql: str,
    connect_as: str,
    whenever_sqlerror: str,
    raw_result: tuple[int, bytes],
    expected_code: int,
    expected_fragments: tuple[str, ...],
) -> None:
    """Verify public exec_sqlplus normalizes PL/SQL slashes, connect_as forms, and SQL*Plus error exit codes."""
    assert "exec_sqlplus" in oracle.__all__
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=raw_result[0], output=raw_result[1])

    code, output = exec_sqlplus(container, sql, connect_as=connect_as, whenever_sqlerror=whenever_sqlerror)

    assert code == expected_code
    assert output == raw_result[1].decode("utf-8", errors="replace")
    command = container.exec_run.call_args.args[0][2]
    assert all(fragment in command for fragment in expected_fragments)


def test_exec_sqlplus_rejects_empty_connect_as() -> None:
    """Verify exec_sqlplus raises ValueError when connect_as is empty or whitespace-only."""
    with pytest.raises(ValueError, match="connect_as must be non-empty"):
        exec_sqlplus(MagicMock(), "SELECT 1 FROM DUAL", connect_as="   ")


@pytest.mark.parametrize(
    ("tns_content", "service_name", "expected_alias"),
    [
        (None, "myatp_high.adb.oraclecloud.com", None),
        (
            "myatp_tcp = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(PORT = 1521)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_tcp.adb.oraclecloud.com)))\n",
            "myatp_high.adb.oraclecloud.com",
            None,
        ),
        (
            (
                "myatp_high = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(PORT = 1521)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_high.adb.oraclecloud.com)))\n"
                "myatp_low_tls = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCPS)(PORT = 1522)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_low.adb.oraclecloud.com)))\n"
                "myatp_tp = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCPS)(PORT = 1522)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_tp.adb.oraclecloud.com)))\n"
            ),
            "myatp_custom.adb.oraclecloud.com",
            "myatp_tp",
        ),
        (
            (
                "myatp_tp = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCPS)(PORT = 1522)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_tp.adb.oraclecloud.com)))\n"
                "myatp_tls = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCPS)(PORT = 1522)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = myatp_high.adb.oraclecloud.com)))\n"
            ),
            "myatp_high.adb.oraclecloud.com",
            "myatp_tls",
        ),
        (
            "custom_wallet = (DESCRIPTION = (ADDRESS = (PROTOCOL = TCPS)(PORT = 1522)(HOST = adb-free.local))(CONNECT_DATA = (SERVICE_NAME = other.adb.oraclecloud.com)))\n",
            "myatp_high.adb.oraclecloud.com",
            "custom_wallet",
        ),
    ],
)
def test_oracle_adb_mtls_alias_resolution(
    tmp_path: Path,
    tns_content: str | None,
    service_name: str,
    expected_alias: str | None,
) -> None:
    """Verify OracleADBService.mtls_alias filters out TCP entries and ranks TCPS aliases deterministically."""
    wallet_dir = tmp_path / "wallet" if tns_content is not None else None
    if wallet_dir is not None and tns_content is not None:
        wallet_dir.mkdir(parents=True, exist_ok=True)
        (wallet_dir / "tnsnames.ora").write_text(tns_content, encoding="utf-8")

    service = OracleADBService(
        container=MagicMock(),
        host="127.0.0.1",
        port=41521,
        tls_port=41522,
        ords_port=48443,
        mongo_port=47017,
        wallet_dir=wallet_dir,
        user="app",
        password=DEFAULT_ORACLE_ADB_PASSWORD,
        system_password=DEFAULT_ORACLE_ADB_PASSWORD,
        service_name=service_name,
        wallet_password=DEFAULT_ORACLE_ADB_PASSWORD,
        workload_type="ATP",
        service_names=ORACLE_ADB_ATP_SERVICES,
    )
    assert service.mtls_alias == expected_alias


@pytest.mark.parametrize("include_sso", [True, False])
def test_oracle_adb_build_wallet_zip_preserves_existing_p12_and_sso_option(
    tmp_path: Path,
    include_sso: bool,
) -> None:
    """Verify build_wallet_zip creates parent dirs, respects include_sso, and keeps pre-existing ewallet.p12."""
    wallet_dir = tmp_path / "wallet"
    wallet_dir.mkdir()
    (wallet_dir / "tnsnames.ora").write_text(SAMPLE_TNSNAMES, encoding="utf-8")
    (wallet_dir / "sqlnet.ora").write_text(SAMPLE_SQLNET, encoding="utf-8")
    (wallet_dir / "cwallet.sso").write_bytes(b"sso-data")
    (wallet_dir / "ewallet.p12").write_bytes(b"existing-pkcs12")

    service = OracleADBService(
        container=MagicMock(),
        host="127.0.0.1",
        port=41521,
        tls_port=41522,
        ords_port=48443,
        mongo_port=47017,
        wallet_dir=wallet_dir,
        user="app",
        password=DEFAULT_ORACLE_ADB_PASSWORD,
        system_password=DEFAULT_ORACLE_ADB_PASSWORD,
        service_name="myatp_high.adb.oraclecloud.com",
        wallet_password="WalletPass123",
        workload_type="ATP",
        service_names=ORACLE_ADB_ATP_SERVICES,
    )

    out_zip = service.build_wallet_zip(tmp_path / "nested" / "dir" / "wallet.zip", include_sso=include_sso)
    assert out_zip.is_file()
    with zipfile.ZipFile(out_zip) as archive:
        names = set(archive.namelist())
        assert "tnsnames.ora" in names
        assert "sqlnet.ora" in names
        assert archive.read("ewallet.p12") == b"existing-pkcs12"
        assert ("cwallet.sso" in names) is include_sso


def test_oracle_adb_build_wallet_zip_requires_wallet_dir(tmp_path: Path) -> None:
    """Verify build_wallet_zip raises RuntimeError when wallet_dir is None."""
    service = OracleADBService(
        container=MagicMock(),
        host="127.0.0.1",
        port=41521,
        tls_port=41522,
        ords_port=48443,
        mongo_port=47017,
        wallet_dir=None,
        user="app",
        password=DEFAULT_ORACLE_ADB_PASSWORD,
        system_password=DEFAULT_ORACLE_ADB_PASSWORD,
        service_name="myatp_high.adb.oraclecloud.com",
        wallet_password="WalletPass123",
        workload_type="ATP",
        service_names=ORACLE_ADB_ATP_SERVICES,
    )
    with pytest.raises(RuntimeError, match="wallet directory is not available"):
        service.build_wallet_zip(tmp_path / "wallet.zip")


def test_oracle_adb_build_wallet_zip_falls_back_without_cryptography(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify build_wallet_zip stays clientless and still bundles wallet files if cryptography is absent."""
    wallet_dir = tmp_path / "wallet"
    wallet_dir.mkdir()
    (wallet_dir / "tnsnames.ora").write_text(SAMPLE_TNSNAMES, encoding="utf-8")
    (wallet_dir / "sqlnet.ora").write_text(SAMPLE_SQLNET, encoding="utf-8")
    (wallet_dir / "cwallet.sso").write_bytes(b"sso-data")
    (wallet_dir / "ewallet.pem").write_text("dummy pem content", encoding="utf-8")

    real_import_module = importlib.import_module

    def _blocked_crypto(name: str, package: str | None = None) -> object:
        if name.startswith("cryptography"):
            raise ModuleNotFoundError(name)
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _blocked_crypto)
    service = OracleADBService(
        container=MagicMock(),
        host="127.0.0.1",
        port=41521,
        tls_port=41522,
        ords_port=48443,
        mongo_port=47017,
        wallet_dir=wallet_dir,
        user="app",
        password=DEFAULT_ORACLE_ADB_PASSWORD,
        system_password=DEFAULT_ORACLE_ADB_PASSWORD,
        service_name="myatp_high.adb.oraclecloud.com",
        wallet_password="WalletPass123",
        workload_type="ATP",
        service_names=ORACLE_ADB_ATP_SERVICES,
    )
    out_zip = service.build_wallet_zip(tmp_path / "wallet.zip")
    with zipfile.ZipFile(out_zip) as archive:
        assert set(archive.namelist()) == {"tnsnames.ora", "sqlnet.ora", "cwallet.sso", "ewallet.pem"}


def _create_test_ca_and_leaf_pem() -> tuple[bytes, object, object]:
    """Build a test CA certificate, RSA client key/cert pair, and PEM bundle."""
    x509 = pytest.importorskip("cryptography.x509")
    hashes = importlib.import_module("cryptography.hazmat.primitives.hashes")
    serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
    rsa = importlib.import_module("cryptography.hazmat.primitives.asymmetric.rsa")
    name_oid = importlib.import_module("cryptography.x509.oid").NameOID

    now = dt.datetime.now(dt.UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(name_oid.COMMON_NAME, "Oracle Test CA")])
    ca_cert = (
        x509
        .CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(name_oid.COMMON_NAME, "Oracle ADB Client")])
    leaf_cert = (
        x509
        .CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .sign(ca_key, hashes.SHA256())
    )
    pem_bundle = (
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        + leaf_cert.public_bytes(serialization.Encoding.PEM)
        + ca_cert.public_bytes(serialization.Encoding.PEM)
    )
    return pem_bundle, leaf_cert, ca_cert


@pytest.mark.parametrize("override_password", [None, "OverridePass456"])
def test_oracle_adb_build_wallet_zip_synthesizes_pkcs12_from_pem(
    tmp_path: Path,
    override_password: str | None,
) -> None:
    """Verify build_wallet_zip synthesizes encrypted ewallet.p12 from ewallet.pem when cryptography is installed."""
    pkcs12 = importlib.import_module("cryptography.hazmat.primitives.serialization.pkcs12")
    pem_bundle, leaf_cert, ca_cert = _create_test_ca_and_leaf_pem()
    wallet_dir = tmp_path / "wallet"
    wallet_dir.mkdir()
    (wallet_dir / "tnsnames.ora").write_text(SAMPLE_TNSNAMES, encoding="utf-8")
    (wallet_dir / "sqlnet.ora").write_text(SAMPLE_SQLNET, encoding="utf-8")
    (wallet_dir / "cwallet.sso").write_bytes(b"sso-data")
    (wallet_dir / "ewallet.pem").write_bytes(pem_bundle)

    service = OracleADBService(
        container=MagicMock(),
        host="127.0.0.1",
        port=41521,
        tls_port=41522,
        ords_port=48443,
        mongo_port=47017,
        wallet_dir=wallet_dir,
        user="app",
        password=DEFAULT_ORACLE_ADB_PASSWORD,
        system_password=DEFAULT_ORACLE_ADB_PASSWORD,
        service_name="myatp_high.adb.oraclecloud.com",
        wallet_password="WalletPass123",
        workload_type="ATP",
        service_names=ORACLE_ADB_ATP_SERVICES,
    )

    out_zip = service.build_wallet_zip(
        tmp_path / "out" / "wallet.zip",
        include_sso=False,
        wallet_password=override_password,
    )
    expected_pw = (override_password or "WalletPass123").encode("utf-8")
    with zipfile.ZipFile(out_zip) as archive:
        names = set(archive.namelist())
        assert "cwallet.sso" not in names
        assert "ewallet.p12" in names
        loaded_key, loaded_cert, loaded_cas = pkcs12.load_key_and_certificates(archive.read("ewallet.p12"), expected_pw)
        assert loaded_key is not None
        assert loaded_cert == leaf_cert
        assert ca_cert in loaded_cas
