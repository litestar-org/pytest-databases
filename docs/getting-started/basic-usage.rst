Basic Usage
===========

Once a provider plugin is enabled (for example ``pytest_databases.docker.postgres``), inject its ``*_service`` fixture into your tests or application fixtures.

Service Fixtures (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Service fixtures start and verify the container and return a typed ``ServiceContainer`` handle with connection metadata (``host``, ``port``, credentials, database name, and endpoints) that you pass to your own driver, connection pool, or ORM:

.. code-block:: python

   import psycopg
   from pytest_databases.docker.postgres import PostgresService

   pytest_plugins = ["pytest_databases.docker.postgres"]

   def test_connection_with_service_details(postgres_service: PostgresService) -> None:
       conn_str = (
           f"postgresql://{postgres_service.user}:{postgres_service.password}@"
           f"{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
       )
       with psycopg.connect(conn_str, autocommit=True) as conn:
           with conn.cursor() as cursor:
               cursor.execute("SELECT 1")
               assert cursor.fetchone() == (1,)
