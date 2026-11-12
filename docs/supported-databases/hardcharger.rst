Hardcharger
===========

Integration with `Hardcharger <https://github.com/gizmodata/hardcharger>`_, an analytics server built on DuckDB. Clients talk to it over `Chargewire <https://github.com/gizmodata/chargewire>`_, an HTTP protocol that carries results as Apache Arrow.

.. note::

   The container serves plain HTTP (no TLS) and keeps its database in memory, so every new container starts empty.
   ``HardchargerService.uri`` already carries ``?tls=false``.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

The fixture needs no database client: it validates container readiness by running ``SELECT 4242`` through the ``hardcharger`` command-line client inside the container and then checking the published port. To connect from your own tests, install the client you normally use, for example the ADBC driver:

.. code-block:: bash

   pip install adbc-driver-hardcharger

Usage Example
-------------

Connect using the ``uri`` and ``connection_kwargs`` properties on ``HardchargerService``:

.. code-block:: python

    from adbc_driver_hardcharger import dbapi as hardcharger
    from pytest_databases.docker.hardcharger import HardchargerService

    pytest_plugins = ["pytest_databases.docker.hardcharger"]


    def test(hardcharger_service: HardchargerService) -> None:
        with hardcharger.connect(
            uri=hardcharger_service.uri,
            db_kwargs=hardcharger_service.connection_kwargs,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE test_table (id INTEGER, name VARCHAR)")
                cur.execute("INSERT INTO test_table VALUES (1, 'test')")

            with conn.cursor() as cur:
                cur.execute("SELECT * FROM test_table")
                result = cur.fetchone()
                assert result is not None
                assert result[0] == 1

``exec_hardcharger`` runs SQL with the client bundled in the container, which is useful for seeding data without installing a driver. It returns the exit code and the output as CSV with a header row:

.. code-block:: python

    from pytest_databases.docker.hardcharger import HardchargerService, exec_hardcharger

    pytest_plugins = ["pytest_databases.docker.hardcharger"]


    def test(hardcharger_service: HardchargerService) -> None:
        exit_code, output = exec_hardcharger(
            container=hardcharger_service.container,
            sql="SELECT 42 AS answer",
            user=hardcharger_service.username,
            password=hardcharger_service.password,
        )
        assert exit_code == 0
        assert output.decode().splitlines() == ["answer", "42"]

Available Fixtures
------------------

* ``hardcharger_image``: The container image to use for Hardcharger (default: ``ghcr.io/gizmodata/hardcharger:latest``).
* ``hardcharger_username``: The administrator's user name (default: ``hardcharger_username``).
* ``hardcharger_password``: The administrator's password (default: ``hardcharger_password``).
* ``hardcharger_service``: A running Hardcharger service.
* ``xdist_hardcharger_isolation_level``: ``database`` (default) keeps worker containers until the session's
  containers are cleaned up; ``server`` removes each one when its fixture is torn down.

Override ``hardcharger_image`` to pin a version:

.. code-block:: python

    @pytest.fixture(scope="session")
    def hardcharger_image():
        return "ghcr.io/gizmodata/hardcharger:2.10.0"

Parallel Testing (xdist)
------------------------

Hardcharger assigns each ``pytest-xdist`` worker its own container (``hardcharger_<worker>``) because the server's
in-memory DuckDB database cannot be split into independent databases per worker. This holds for both isolation levels;
``xdist_hardcharger_isolation_level`` only controls when those containers are removed.

.. code-block:: python

    @pytest.fixture(scope="session")
    def xdist_hardcharger_isolation_level():
        return "server"

Service API
-----------

.. automodule:: pytest_databases.docker.hardcharger
   :members:
   :undoc-members:
   :show-inheritance:
