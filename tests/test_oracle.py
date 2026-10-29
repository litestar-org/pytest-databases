"""Tests for Oracle Database and Autonomous Database Free container fixtures and wallet helpers."""

from __future__ import annotations

import io
import tarfile
from typing import TYPE_CHECKING
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
    enable_oracle_ords_schema,
    ensure_oracle_adb_user,
    ensure_oracle_user,
    open_oracle_connection,
    parse_tnsnames,
    provide_oracle_adb_service,
    provide_oracle_service,
    rewrite_sqlnet_ora,
    rewrite_tnsnames,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

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
        patch("pytest_databases.docker.oracle.ensure_oracle_user", return_value=True) as mock_ensure,
        patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"1")),
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle23ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            isolation_level="database",
        ) as service,
    ):
        assert service.user == "app_2"
        call_kwargs = mock_docker.run.call_args[1]
        assert call_kwargs["name"] == "oracle23ai"
        assert call_kwargs["transient"] is False
        check_fn = call_kwargs["check"]
        assert check_fn(mock_service) is True
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
            name="oracle23ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            isolation_level="server",
        ) as service,
    ):
        assert service.user == "app"

    call_kwargs = mock_docker.run.call_args[1]
    assert call_kwargs["name"] == "oracle23ai_3"
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
    assert kwargs["as_sysdba"] is True
    assert kwargs["whenever_sqlerror"] == "CONTINUE"
    assert "CREATE USER app_1" in kwargs["sql"]


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
    """Verify ensure_oracle_adb_user connects as ADMIN without SYSDBA and enable_oracle_ords_schema runs ORDS.ENABLE_SCHEMA."""
    mock_container = MagicMock()
    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_exec:
        assert (
            ensure_oracle_adb_user(
                container=mock_container,
                user="app_1",
                password=DEFAULT_ORACLE_ADB_PASSWORD,
                service_name="myatp_high.adb.oraclecloud.com",
                admin_password=DEFAULT_ORACLE_ADB_PASSWORD,
            )
            is True
        )

    mock_exec.assert_called_once()
    _, kwargs = mock_exec.call_args
    assert kwargs["user"] == "admin"
    assert kwargs["as_sysdba"] is False
    assert "DEFAULT TABLESPACE DATA" in kwargs["sql"]
    assert "DWROLE" in kwargs["sql"]

    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_ords:
        assert (
            enable_oracle_ords_schema(
                mock_container,
                user="app_1",
                password=DEFAULT_ORACLE_ADB_PASSWORD,
                service_name="myatp_high.adb.oraclecloud.com",
            )
            is True
        )
    _, ords_kwargs = mock_ords.call_args
    assert ords_kwargs["user"] == "app_1"
    assert ords_kwargs["as_sysdba"] is False
    assert "ORDS.ENABLE_SCHEMA" in ords_kwargs["sql"]
    assert "p_schema => 'APP_1'" in ords_kwargs["sql"]
    assert ords_kwargs["sql"].endswith("/")


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
        patch("pytest_databases.docker.oracle.ensure_oracle_adb_user", return_value=True) as mock_ensure_adb,
        patch("pytest_databases.docker.oracle.enable_oracle_ords_schema", return_value=True) as mock_enable_ords,
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
        assert call_kwargs["volumes"] == {"/host/wallet": {"bind": "/u01/app/oracle/wallets/tls_wallet", "mode": "rw"}}
        assert call_kwargs["env"]["WORKLOAD_TYPE"] == "AJD"
        assert call_kwargs["env"]["WALLET_PASSWORD"] == DEFAULT_ORACLE_ADB_PASSWORD
        assert call_kwargs["env"]["MY_TZ"] == "America/Los_Angeles"
        check_fn = call_kwargs["check"]
        assert check_fn(mock_service) is True
        mock_ensure_adb.assert_called_once()
        mock_enable_ords.assert_called_once()
        mock_extract.assert_called_once_with(
            mock_container,
            wallet_target,
            host="127.0.0.1",
            port=41521,
            tls_port=41522,
        )


def test_deprecated_oracle_connection_helpers_emit_warnings(monkeypatch: MonkeyPatch) -> None:
    """Verify deprecated oracle_responsive and open_oracle_connection emit DeprecationWarning."""
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = (1,)
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.__enter__.return_value = fake_conn

    fake_oracledb = MagicMock()
    fake_oracledb.connect.return_value = fake_conn
    monkeypatch.setattr(oracle, "_load_oracledb", lambda: fake_oracledb)

    with pytest.deprecated_call(match="oracle_responsive"):
        assert oracle.oracle_responsive("127.0.0.1", 1521, "FREEPDB1", "app", "secret") is True

    service = OracleService(
        container=MagicMock(),
        host="127.0.0.1",
        port=1521,
        user="app",
        password="secret",
        system_password="sys-secret",
        service_name="FREEPDB1",
    )
    with (
        pytest.deprecated_call(match="oracle_23ai_connection"),
        open_oracle_connection(service, "oracle_23ai_connection") as conn,
    ):
        assert conn is fake_conn


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
        "oracle_23ai_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str, oracle_test_helpers: str) -> None:
    """Run integration smoke tests against Oracle 18c and 23ai service fixtures."""
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
