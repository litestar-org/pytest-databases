from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg

from pytest_databases.docker.alloydb_omni import AlloyDBService
from pytest_databases.docker.postgres import _make_connection_string

if TYPE_CHECKING:
    pass


# pytestmark = pytest.mark.skip

pytest_plugins = [
    "pytest_databases.docker.alloydb_omni",
]


def check(service: AlloyDBService) -> bool:
    with psycopg.connect(
        _make_connection_string(
            host=service.host,
            port=service.port,
            user=service.user,
            database=service.database,
            password=service.password,
        )
    ) as conn:
        db_open = conn.execute("SELECT 1").fetchone()
        return bool(db_open is not None and db_open[0] == 1)


def test_alloydb_omni_services(alloydb_omni_service: AlloyDBService) -> None:
    assert check(alloydb_omni_service)


def test_alloydb_omni_service_after_start(alloydb_omni_startup_connection: psycopg.Connection) -> None:
    alloydb_omni_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = alloydb_omni_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)
