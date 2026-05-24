Basic Usage
===========

Once a plugin is enabled (e.g., PostgreSQL), you can use its fixtures directly in your tests. The fixture you'll use most often is the **Service Fixture** (e.g., ``postgres_service``), which provides details about the running database service (host, port, credentials, etc.) so you can connect with your own client.

.. code-block:: python

   # Assuming you have installed pytest-databases[postgres] and enabled the plugin.
   # Install your preferred PostgreSQL client alongside it: pip install psycopg
   import psycopg
   from pytest_databases.docker.postgres import PostgresService

   def test_connection_with_service_details(postgres_service: PostgresService) -> None:
       conn_str = (
           f"postgresql://{postgres_service.user}:{postgres_service.password}@"
           f"{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
       )
       with psycopg.connect(conn_str, autocommit=True) as conn, conn.cursor() as cursor:
           cursor.execute("SELECT 1")
           assert cursor.fetchone() == (1,)

   def test_write_and_read(postgres_service: PostgresService) -> None:
       conn_str = (
           f"postgresql://{postgres_service.user}:{postgres_service.password}@"
           f"{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
       )
       with psycopg.connect(conn_str, autocommit=True) as conn, conn.cursor() as cursor:
           cursor.execute("CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY, name TEXT);")
           cursor.execute("INSERT INTO users (id, name) VALUES (1, 'Alice');")
           cursor.execute("SELECT name FROM users WHERE id = 1;")
           assert cursor.fetchone() == ("Alice",)
