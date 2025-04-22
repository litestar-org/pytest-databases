Examples
========

This guide provides detailed examples of how to use Pytest Databases with various database types.

PostgreSQL
----------

.. code-block:: python

   import pytest
   import psycopg
   from pytest_databases.docker.postgres import PostgresService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.postgres"]

   # Example 1: Using the service fixture
   def test_postgres_service(postgres_service: PostgresService) -> None:
       with psycopg.connect(
           f"postgresql://{postgres_service.user}:{postgres_service.password}@{postgres_service.host}:{postgres_service.port}/{postgres_service.database}",
           autocommit=True,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("CREATE TABLE test (id SERIAL PRIMARY KEY, name TEXT)")
               cursor.execute("INSERT INTO test (name) VALUES ('test')")
               cursor.execute("SELECT * FROM test")
               result = cursor.fetchone()
               assert result[1] == "test"

   # Example 2: Using the connection fixture
   def test_postgres_connection(postgres_connection) -> None:
       with postgres_connection.cursor() as cursor:
           cursor.execute("CREATE TABLE test (id SERIAL PRIMARY KEY, name TEXT)")
           cursor.execute("INSERT INTO test (name) VALUES ('test')")
           cursor.execute("SELECT * FROM test")
           result = cursor.fetchone()
           assert result[1] == "test"

   # Example 3: Using a specific version
   def test_postgres_14(postgres_14_service: PostgresService) -> None:
       with psycopg.connect(
           f"postgresql://{postgres_14_service.user}:{postgres_14_service.password}@{postgres_14_service.host}:{postgres_14_service.port}/{postgres_14_service.database}",
           autocommit=True,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("SELECT version()")
               version = cursor.fetchone()[0]
               assert "PostgreSQL 14" in version

MySQL
-----

.. code-block:: python

   import pytest
   import mysql.connector
   from pytest_databases.docker.mysql import MySQLService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.mysql"]

   # Example 1: Using the service fixture
   def test_mysql_service(mysql_service: MySQLService) -> None:
       with mysql.connector.connect(
           host=mysql_service.host,
           port=mysql_service.port,
           user=mysql_service.user,
           password=mysql_service.password,
           database=mysql_service.db,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("CREATE TABLE test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255))")
               cursor.execute("INSERT INTO test (name) VALUES ('test')")
               cursor.execute("SELECT * FROM test")
               result = cursor.fetchone()
               assert result[1] == "test"

   # Example 2: Using the connection fixture
   def test_mysql_connection(mysql_connection) -> None:
       with mysql_connection.cursor() as cursor:
           cursor.execute("CREATE TABLE test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255))")
           cursor.execute("INSERT INTO test (name) VALUES ('test')")
           cursor.execute("SELECT * FROM test")
           result = cursor.fetchone()
           assert result[1] == "test"

   # Example 3: Using a specific version
   def test_mysql_8(mysql_8_service: MySQLService) -> None:
       with mysql.connector.connect(
           host=mysql_8_service.host,
           port=mysql_8_service.port,
           user=mysql_8_service.user,
           password=mysql_8_service.password,
           database=mysql_8_service.db,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("SELECT VERSION()")
               version = cursor.fetchone()[0]
               assert "8." in version

MariaDB
-------

.. code-block:: python

   import pytest
   import mariadb
   from pytest_databases.docker.mariadb import MariaDBService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.mariadb"]

   # Example 1: Using the service fixture
   def test_mariadb_service(mariadb_service: MariaDBService) -> None:
       with mariadb.connect(
           host=mariadb_service.host,
           port=mariadb_service.port,
           user=mariadb_service.user,
           password=mariadb_service.password,
           database=mariadb_service.db,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("CREATE TABLE test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255))")
               cursor.execute("INSERT INTO test (name) VALUES ('test')")
               cursor.execute("SELECT * FROM test")
               result = cursor.fetchone()
               assert result[1] == "test"

   # Example 2: Using the connection fixture
   def test_mariadb_connection(mariadb_connection) -> None:
       with mariadb_connection.cursor() as cursor:
           cursor.execute("CREATE TABLE test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255))")
           cursor.execute("INSERT INTO test (name) VALUES ('test')")
           cursor.execute("SELECT * FROM test")
           result = cursor.fetchone()
           assert result[1] == "test"

Oracle
------

.. code-block:: python

   import pytest
   import oracledb
   from pytest_databases.docker.oracle import OracleService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.oracle"]

   # Example 1: Using the service fixture
   def test_oracle_service(oracle_service: OracleService) -> None:
       with oracledb.connect(
           user=oracle_service.user,
           password=oracle_service.password,
           service_name=oracle_service.service_name,
           host=oracle_service.host,
           port=oracle_service.port,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("CREATE TABLE test (id NUMBER GENERATED ALWAYS AS IDENTITY, name VARCHAR2(255))")
               cursor.execute("INSERT INTO test (name) VALUES ('test')")
               cursor.execute("SELECT * FROM test")
               result = cursor.fetchone()
               assert result[1] == "test"

   # Example 2: Using the connection fixture
   def test_oracle_connection(oracle_connection) -> None:
       with oracle_connection.cursor() as cursor:
           cursor.execute("CREATE TABLE test (id NUMBER GENERATED ALWAYS AS IDENTITY, name VARCHAR2(255))")
           cursor.execute("INSERT INTO test (name) VALUES ('test')")
           cursor.execute("SELECT * FROM test")
           result = cursor.fetchone()
           assert result[1] == "test"

   # Example 3: Using a specific version
   def test_oracle_18c(oracle_18c_service: OracleService) -> None:
       with oracledb.connect(
           user=oracle_18c_service.user,
           password=oracle_18c_service.password,
           service_name=oracle_18c_service.service_name,
           host=oracle_18c_service.host,
           port=oracle_18c_service.port,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("SELECT * FROM v$version")
               version = cursor.fetchone()[0]
               assert "Oracle Database 18c" in version

SQL Server
----------

.. code-block:: python

   import pytest
   import pymssql
   from pytest_databases.docker.mssql import MSSQLService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.mssql"]

   # Example 1: Using the service fixture
   def test_mssql_service(mssql_service: MSSQLService) -> None:
       with pymssql.connect(
           user=mssql_service.user,
           password=mssql_service.password,
           database=mssql_service.database,
           host=mssql_service.host,
           port=str(mssql_service.port),
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("CREATE TABLE test (id INT IDENTITY(1,1) PRIMARY KEY, name NVARCHAR(255))")
               cursor.execute("INSERT INTO test (name) VALUES ('test')")
               cursor.execute("SELECT * FROM test")
               result = cursor.fetchone()
               assert result[1] == "test"

   # Example 2: Using the connection fixture
   def test_mssql_connection(mssql_connection) -> None:
       with mssql_connection.cursor() as cursor:
           cursor.execute("CREATE TABLE test (id INT IDENTITY(1,1) PRIMARY KEY, name NVARCHAR(255))")
           cursor.execute("INSERT INTO test (name) VALUES ('test')")
           cursor.execute("SELECT * FROM test")
           result = cursor.fetchone()
           assert result[1] == "test"

   # Example 3: Using the connection string property
   def test_mssql_connection_string(mssql_service: MSSQLService) -> None:
       with pymssql.connect(mssql_service.connection_string) as conn:
           with conn.cursor() as cursor:
               cursor.execute("SELECT @@VERSION")
               version = cursor.fetchone()[0]
               assert "Microsoft SQL Server 2022" in version

AlloyDB
-------

.. code-block:: python

   import pytest
   import psycopg
   from pytest_databases.docker.alloydb_omni import AlloyDBService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.alloydb_omni"]

   # Example 1: Using the service fixture
   def test_alloydb_service(alloydb_omni_service: AlloyDBService) -> None:
       with psycopg.connect(
           f"postgresql://{alloydb_omni_service.user}:{alloydb_omni_service.password}@{alloydb_omni_service.host}:{alloydb_omni_service.port}/{alloydb_omni_service.database}",
           autocommit=True,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("CREATE TABLE test (id SERIAL PRIMARY KEY, name TEXT)")
               cursor.execute("INSERT INTO test (name) VALUES ('test')")
               cursor.execute("SELECT * FROM test")
               result = cursor.fetchone()
               assert result[1] == "test"

   # Example 2: Using the connection fixture
   def test_alloydb_connection(alloydb_omni_connection) -> None:
       with alloydb_omni_connection.cursor() as cursor:
           cursor.execute("CREATE TABLE test (id SERIAL PRIMARY KEY, name TEXT)")
           cursor.execute("INSERT INTO test (name) VALUES ('test')")
           cursor.execute("SELECT * FROM test")
           result = cursor.fetchone()
           assert result[1] == "test"

Spanner
-------

.. code-block:: python

   import pytest
   from google.cloud import spanner
   from pytest_databases.docker.spanner import SpannerService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.spanner"]

   # Example 1: Using the service fixture
   def test_spanner_service(spanner_service: SpannerService) -> None:
       client = spanner.Client(
           project=spanner_service.project,
           credentials=spanner_service.credentials,
           client_options=spanner_service.client_options,
       )
       instance = client.instance(spanner_service.instance_name)
       database = instance.database(spanner_service.database_name)

       with database.batch() as batch:
           batch.insert(
               "test",
               columns=["id", "name"],
               values=[(1, "test")],
           )

       with database.snapshot() as snapshot:
           results = list(snapshot.execute_sql("SELECT * FROM test"))
           assert results[0][1] == "test"

   # Example 2: Using the connection fixture
   def test_spanner_connection(spanner_connection) -> None:
       with spanner_connection.batch() as batch:
           batch.insert(
               "test",
               columns=["id", "name"],
               values=[(1, "test")],
           )

       with spanner_connection.snapshot() as snapshot:
           results = list(snapshot.execute_sql("SELECT * FROM test"))
           assert results[0][1] == "test"

BigQuery
--------

.. code-block:: python

   import pytest
   from google.cloud import bigquery
   from pytest_databases.docker.bigquery import BigQueryService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.bigquery"]

   # Example 1: Using the service fixture
   def test_bigquery_service(bigquery_service: BigQueryService) -> None:
       client = bigquery.Client(
           project=bigquery_service.project,
           credentials=bigquery_service.credentials,
           client_options=bigquery_service.client_options,
       )

       dataset_ref = client.dataset(bigquery_service.dataset)
       table_ref = dataset_ref.table("test")

       schema = [
           bigquery.SchemaField("id", "INTEGER", mode="REQUIRED"),
           bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
       ]

       table = bigquery.Table(table_ref, schema=schema)
       client.create_table(table)

       rows_to_insert = [(1, "test")]
       errors = client.insert_rows(table, rows_to_insert)
       assert not errors

       query_job = client.query(f"SELECT * FROM {bigquery_service.project}.{bigquery_service.dataset}.test")
       results = list(query_job)
       assert results[0].name == "test"

   # Example 2: Using the connection fixture
   def test_bigquery_connection(bigquery_connection) -> None:
       dataset_ref = bigquery_connection.dataset(bigquery_service.dataset)
       table_ref = dataset_ref.table("test")

       schema = [
           bigquery.SchemaField("id", "INTEGER", mode="REQUIRED"),
           bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
       ]

       table = bigquery.Table(table_ref, schema=schema)
       bigquery_connection.create_table(table)

       rows_to_insert = [(1, "test")]
       errors = bigquery_connection.insert_rows(table, rows_to_insert)
       assert not errors

       query_job = bigquery_connection.query(f"SELECT * FROM {bigquery_service.project}.{bigquery_service.dataset}.test")
       results = list(query_job)
       assert results[0].name == "test"

CockroachDB
-----------

.. code-block:: python

   import pytest
   import psycopg
   from pytest_databases.docker.cockroachdb import CockroachDBService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.cockroachdb"]

   # Example 1: Using the service fixture
   def test_cockroachdb_service(cockroachdb_service: CockroachDBService) -> None:
       with psycopg.connect(
           f"postgresql://{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}",
           **cockroachdb_service.driver_opts,
       ) as conn:
           with conn.cursor() as cursor:
               cursor.execute("CREATE TABLE test (id SERIAL PRIMARY KEY, name TEXT)")
               cursor.execute("INSERT INTO test (name) VALUES ('test')")
               cursor.execute("SELECT * FROM test")
               result = cursor.fetchone()
               assert result[1] == "test"

   # Example 2: Using the connection fixture
   def test_cockroachdb_connection(cockroachdb_connection) -> None:
       with cockroachdb_connection.cursor() as cursor:
           cursor.execute("CREATE TABLE test (id SERIAL PRIMARY KEY, name TEXT)")
           cursor.execute("INSERT INTO test (name) VALUES ('test')")
           cursor.execute("SELECT * FROM test")
           result = cursor.fetchone()
           assert result[1] == "test"

Redis
-----

.. code-block:: python

   import pytest
   from redis import Redis
   from pytest_databases.docker.redis import RedisService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.redis"]

   # Example 1: Using the service fixture
   def test_redis_service(redis_service: RedisService) -> None:
       client = Redis(host=redis_service.host, port=redis_service.port, db=redis_service.db)
       client.set("test", "value")
       value = client.get("test")
       assert value == b"value"

   # Example 2: Using the connection fixture
   def test_redis_connection(redis_connection) -> None:
       redis_connection.set("test", "value")
       value = redis_connection.get("test")
       assert value == b"value"

Elasticsearch
-------------

.. code-block:: python

   import pytest
   from elasticsearch import Elasticsearch
   from pytest_databases.docker.elastic_search import ElasticsearchService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.elastic_search"]

   # Example 1: Using the service fixture
   def test_elasticsearch_service(elasticsearch_service: ElasticsearchService) -> None:
       client = Elasticsearch(
           f"{elasticsearch_service.scheme}://{elasticsearch_service.host}:{elasticsearch_service.port}",
           basic_auth=(elasticsearch_service.user, elasticsearch_service.password),
       )

       client.indices.create(index="test")
       client.index(index="test", document={"name": "test"})
       client.indices.refresh(index="test")

       response = client.search(index="test", query={"match": {"name": "test"}})
       assert response["hits"]["total"]["value"] == 1
       assert response["hits"]["hits"][0]["_source"]["name"] == "test"

   # Example 2: Using the connection fixture
   def test_elasticsearch_connection(elasticsearch_connection) -> None:
       elasticsearch_connection.indices.create(index="test")
       elasticsearch_connection.index(index="test", document={"name": "test"})
       elasticsearch_connection.indices.refresh(index="test")

       response = elasticsearch_connection.search(index="test", query={"match": {"name": "test"}})
       assert response["hits"]["total"]["value"] == 1
       assert response["hits"]["hits"][0]["_source"]["name"] == "test"

Azure Blob Storage
------------------

.. code-block:: python

   import pytest
   from azure.storage.blob import BlobServiceClient
   from pytest_databases.docker.azure_blob import AzureBlobService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.azure_blob"]

   # Example 1: Using the service fixture
   def test_azure_blob_service(azure_blob_service: AzureBlobService) -> None:
       client = BlobServiceClient.from_connection_string(azure_blob_service.connection_string)
       container_client = client.get_container_client("test-container")

       container_client.create_container()

       blob_client = container_client.get_blob_client("test-blob")
       blob_client.upload_blob(b"test data")

       downloaded_data = blob_client.download_blob().readall()
       assert downloaded_data == b"test data"

   # Example 2: Using the connection fixture
   def test_azure_blob_connection(azure_blob_connection) -> None:
       container_client = azure_blob_connection.get_container_client("test-container")

       container_client.create_container()

       blob_client = container_client.get_blob_client("test-blob")
       blob_client.upload_blob(b"test data")

       downloaded_data = blob_client.download_blob().readall()
       assert downloaded_data == b"test data"

MinIO
-----

.. code-block:: python

   import pytest
   from minio import Minio
   from pytest_databases.docker.minio import MinioService

   # Add to your conftest.py
   pytest_plugins = ["pytest_databases.docker.minio"]

   # Example 1: Using the service fixture
   def test_minio_service(minio_service: MinioService) -> None:
       client = Minio(
           minio_service.endpoint,
           access_key=minio_service.access_key,
           secret_key=minio_service.secret_key,
           secure=minio_service.secure,
       )

       client.make_bucket("test-bucket")
       client.put_object("test-bucket", "test-object", b"test data", 9)

       data = client.get_object("test-bucket", "test-object").read()
       assert data == b"test data"

   # Example 2: Using the connection fixture
   def test_minio_connection(minio_connection) -> None:
       minio_connection.make_bucket("test-bucket")
       minio_connection.put_object("test-bucket", "test-object", b"test data", 9)

       data = minio_connection.get_object("test-bucket", "test-object").read()
       assert data == b"test data"

Next Steps
----------

* See :ref:`configuration` for advanced configuration options
* Check out the :doc:`../api/index` reference for detailed API documentation
