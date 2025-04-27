Basic Usage
===========

Once a plugin is enabled (e.g., PostgreSQL), you can use its fixtures directly in your tests. There are typically two main types of fixtures:

1.  **Service Fixture** (e.g., `postgres_service`): Provides details about the running database service (host, port, credentials, etc.). Useful for connecting with your own client.
2.  **Connection Fixture** (e.g., `postgres_connection`): Provides a ready-to-use connection object (where applicable) to the database service.

.. code-block:: python

   # Assuming you have installed pytest-databases[postgres] and enabled the plugin
   # Also assuming a client like psycopg is installed: pip install psycopg
   import psycopg
   from pytest_databases.docker.postgres import PostgresService

   # Example using the Service Fixture
   def test_connection_with_service_details(postgres_service: PostgresService) -> None:
       conn_str = (
           f"postgresql://{postgres_service.user}:{postgres_service.password}@"
           f"{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
       )
       with psycopg.connect(conn_str, autocommit=True) as conn:
           with conn.cursor() as cursor:
               cursor.execute("SELECT 1")
               assert cursor.fetchone() == (1,)

   # Example using the Connection Fixture
   def test_with_direct_connection(postgres_connection) -> None:
      # postgres_connection is often a configured client or connection object
      with postgres_connection.cursor() as cursor:
          cursor.execute("CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY, name TEXT);")
          cursor.execute("INSERT INTO users (id, name) VALUES (1, 'Alice');")
          cursor.execute("SELECT name FROM users WHERE id = 1;")
          assert cursor.fetchone() == ('Alice',)
