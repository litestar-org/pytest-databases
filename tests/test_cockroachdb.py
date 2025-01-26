from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from pytest_databases.docker.cockroachdb import CockroachDBService

pytest_plugins = [
    "pytest_databases.docker.cockroachdb",
]


def test_cockroachdb_default_config(cockroachdb_driver_opts: dict[str, str]) -> None:
    assert cockroachdb_driver_opts == {"sslmode": "disable"}


def test_cockroachdb_service(
    cockroachdb_service: CockroachDBService,
) -> None:
    opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
    with psycopg.connect(
        f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
    ) as conn:
        conn.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        result = conn.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1


def test_cockroachdb_services_after_start(
    cockroachdb_startup_connection: psycopg.Connection,
) -> None:
    cockroachdb_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
    result = cockroachdb_startup_connection.execute("select * from simple_table").fetchone()
    assert result is not None and result[0] == 1
