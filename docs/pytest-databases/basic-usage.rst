Basic Usage
===========

1.  **Configure pytest:** Add the desired database plugin to your `pytest.ini` or `conftest.py`. For example, for PostgreSQL:

    .. code-block:: ini
       :caption: pytest.ini

       [pytest]
       pytest_plugins = pytest_databases.docker.postgres

    Or in `conftest.py`:

    .. code-block:: python
       :caption: conftest.py

       pytest_plugins = ["pytest_databases.docker.postgres"]

2.  **Use fixtures in your tests:** The plugin provides fixtures like `postgres_service` (for service details) and `postgres_connection` (for a ready-to-use database connection).

    .. code-block:: python

       from pytest_databases.docker.postgres import PostgresService
       import psycopg

       # postgres_service provides connection details for the running service
       def test_service_connection(postgres_service: PostgresService) -> None:
            """Example test connecting directly using service details."""
            conn_str = (
                f"postgresql://{postgres_service.user}:{postgres_service.password}@"
                f"{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
            )
            with psycopg.connect(conn_str, autocommit=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    assert cursor.fetchone() == (1,)

       # postgres_connection provides a ready-made connection object
       def test_direct_connection_fixture(postgres_connection: psycopg.Connection) -> None:
            """Example test using the direct connection fixture."""
            with postgres_connection.cursor() as cursor:
                cursor.execute("CREATE TABLE IF NOT EXISTS foo (id INT);")
                cursor.execute("INSERT INTO foo (id) VALUES (1);")
                cursor.execute("SELECT COUNT(*) FROM foo;")
                assert cursor.fetchone() == (1,)
