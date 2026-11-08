Doltgres
========

Integration with `Doltgres <https://www.dolthub.com/blog/2023-11-01-announcing-doltgresql/>`_ using the `dolthub/doltgresql Docker Image <https://hub.docker.com/r/dolthub/doltgresql>`_.

Doltgres is a PostgreSQL-compatible database with Git-like version control for tables and schemas.

Installation
------------

The fixture starts a running Doltgres service and validates readiness using the ``psql`` CLI bundled inside the container image, so no Python client driver is required to start the service:

.. code-block:: bash

    pip install pytest-databases

Usage Example
-------------

.. code-block:: python

    import psycopg
    from pytest_databases.docker.doltgres import DoltgresService

    pytest_plugins = ["pytest_databases.docker.doltgres"]


    def test_doltgres(doltgres_service: DoltgresService) -> None:
        with psycopg.connect(
            host=doltgres_service.host,
            port=doltgres_service.port,
            user=doltgres_service.user,
            password=doltgres_service.password,
            dbname=doltgres_service.database,
        ) as conn:
            row = conn.execute("SELECT 1").fetchone()
            assert row is not None and row[0] == 1

Available Fixtures
------------------

* ``doltgres_service``: Session-scoped fixture that provides a :class:`~pytest_databases.docker.doltgres.DoltgresService` instance.
* ``doltgres_image``: The Docker image to use for Doltgres (defaults to ``"dolthub/doltgresql:latest"``, override with ``DOLTGRES_IMAGE``).
* ``doltgres_user``: The application user configured in the container (defaults to ``"doltgres"``, override with ``DOLTGRES_USER``).
* ``doltgres_password``: The application user password configured in the container (defaults to ``"super-secret"``, override with ``DOLTGRES_PASSWORD``).
* ``doltgres_root_password``: The ``postgres`` superuser password configured in the container (defaults to ``"super-secret"``, override with ``DOLTGRES_ROOT_PASSWORD``).
* ``doltgres_database``: The initial database configured in the container (defaults to ``"pytest_databases"``, override with ``DOLTGRES_DATABASE``).
* ``doltgres_port``: Optional pinned host port for Doltgres (defaults to ``None``, override with ``DOLTGRES_PORT``).

Isolation Level
---------------

By default, the ``doltgres_service`` fixture uses ``database`` isolation, where each worker gets its own database on a shared server. You can change this to ``server`` isolation by overriding the ``xdist_doltgres_isolation_level`` fixture:

.. code-block:: python

    import pytest


    @pytest.fixture(scope="session")
    def xdist_doltgres_isolation_level():
        return "server"

Service API
-----------

.. automodule:: pytest_databases.docker.doltgres
   :members:
   :undoc-members:
   :show-inheritance:
