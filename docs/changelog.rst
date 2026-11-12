Changelog
=========

All notable changes to this project will be documented in this file.

0.20.0 (unreleased)
-------------------

Added
~~~~~

* ``MinioService.endpoint_url`` and ``RustfsService.endpoint_url`` (``http://`` or ``https://`` per ``secure``),
  and ``MinioService.ensure_bucket(name)`` / ``RustfsService.ensure_bucket(name)`` to create extra buckets.
* ``minio_image`` (default ``cgr.dev/chainguard/minio:latest``) and ``rustfs_image`` (default
  ``rustfs/rustfs:latest``) fixtures; overriding them changes the image ``minio_service`` / ``rustfs_service`` start.
* Python 3.14 and 3.15 classifiers.
* Podman support. The runtime is resolved from ``PYTEST_DATABASES_CONTAINER_RUNTIME_ENDPOINT``, ``DOCKER_HOST``,
  ``CONTAINER_HOST``, the current Docker context, the default Docker socket, Podman connection files, and the
  rootless and rootful Podman sockets, preferring Docker in ``auto`` mode.
* ``--container-runtime`` option and ``container_runtime`` ini setting (``auto``, ``docker`` or ``podman``); the
  ``PYTEST_DATABASES_CONTAINER_RUNTIME`` environment variable sets the same choice.
* ``container_runtime``, ``container_client`` and ``container_service`` fixtures. ``docker_client`` and
  ``docker_service`` remain as aliases, and ``DockerService`` is an alias of ``ContainerService``.
* ``ContainerRuntimeConfig``, ``RuntimeType``, ``RuntimeCandidate``, ``RuntimeResolutionError``,
  ``derive_session_owner_id``, ``stop_owned_containers``, ``stop_all_containers`` and the ``MANAGED_LABEL``,
  ``OWNER_LABEL`` and ``SERVICE_LABEL`` constants exported from ``pytest_databases``.
* ``PYTEST_DATABASES_NAMESPACE`` environment variable, appended to the session owner ID so concurrent runs from the
  same checkout do not share containers.
* ``ContainerService.run_container``, ``resolve_port``, ``get_internal_network_ip`` and the ``extra_ports``
  argument of ``ContainerService.run``.
* ``xdist_spanner_isolation_level`` (default ``database``), ``spanner_project``, ``spanner_instance_name`` and
  ``spanner_database_name`` fixtures, ``SpannerService.rest_port`` / ``rest_endpoint``,
  ``provide_spanner_service`` and ``bootstrap_spanner_emulator(host, rest_port, ...)``.
* Keyword-only ``ContainerService.run`` arguments ``wait_for_health``, ``entrypoint``, ``privileged``,
  ``ipc_mode``, ``cap_add``, ``devices``, ``hostname`` and ``volumes``, forwarded to the container runtime;
  ``command`` also accepts a list.
* ``wait_for_container_health(container, service_name, timeout, pause)``, which waits for ``State.Health.Status`` to
  become ``healthy`` and fails at once when the image defines no ``HEALTHCHECK``. ``run(wait_for_health=True)`` uses
  it before the other readiness checks.
* ``--keep-containers`` option and ``PYTEST_DATABASES_KEEP_CONTAINERS`` environment variable to leave session
  containers running after pytest exits, plus ``should_keep_containers(config)``.
* ``gizmosql_duckdb_service`` and ``gizmosql_sqlite_service`` fixtures (``gizmosql_service`` stays the DuckDB
  service), ``GizmoSQLService.backend`` and ``connection_kwargs``, and ``exec_gizmosql``.
* ``alloydb_omni_18_service``, ``alloydb_omni_18_connection`` and ``alloydb_omni_18_port`` (env
  ``ALLOYDB_OMNI_18_PORT``).
* ``exec_psql``, ``create_worker_database``, ``make_connection_string``, ``clone_template_database`` and
  ``drop_database_force`` in ``pytest_databases.docker.postgres``, plus ``PostgresService.clone_template_database``
  and ``PostgresService.drop_database_force``.
* ``pytest_databases.helpers.tcp_port_open(host, port, timeout)``.
* ``ensure_azurite_container``, ``azurite_container_exists`` and ``build_shared_key_authorization`` in
  ``pytest_databases.docker.azure_blob`` for stdlib SharedKey-signed Azurite requests.
* ``query_bigquery_emulator``, ``provide_bigquery_service`` and ``provide_bigquery_client`` in
  ``pytest_databases.docker.bigquery``.
* ``elasticsearch_9_service`` with ``elasticsearch_7_image``, ``elasticsearch_8_image`` and ``elasticsearch_9_image``
  (default ``elasticsearch:9.5.5``) fixtures, and ``provide_elasticsearch_service``.
* ``mariadb_118_service`` (``mariadb:11.8``), ``mariadb_123_service`` (``mariadb:12.3``), ``mariadb_130_service``
  (``mariadb:13.0``) and ``provide_mariadb_service``.
* ``mysql_97_service`` (``mysql:9.7``) and ``provide_mysql_service``.
* ``mssql_2022_service`` and ``mssql_2025_service`` with ``mssql_2022_image`` and ``mssql_2025_image`` (default
  ``mcr.microsoft.com/mssql/server:2025-latest``), ``exec_sqlcmd`` (tries the ``mssql-tools18``, ``mssql-tools`` and
  ``PATH`` ``sqlcmd`` binaries) and ``provide_mssql_service``.
* ``xdist_oracle_isolation_level`` (default ``database``), ``oracle_user``, ``oracle_password`` and
  ``oracle_system_password`` fixtures, ``ensure_oracle_user`` and ``provide_oracle_service``.
* ``provide_cockroachdb_service``, ``provide_mongodb_service`` and ``provide_dolt_service``; ``dolt_image`` fixture
  (default ``dolthub/dolt-sql-server:latest``).
* ``mysql_platform``, ``dolt_platform`` and ``bigquery_platform`` fixtures. ``mysql_56_service`` /
  ``mysql_57_service``, ``dolt_service`` and ``bigquery_service`` read their container platform from these.
* ``redpanda_service`` (``RedpandaService`` with ``bootstrap_servers`` and ``topic_prefix``), ``redpanda_image``
  (default ``docker.redpanda.com/redpandadata/redpanda:v26.1.13``, env ``REDPANDA_IMAGE``), ``redpanda_port`` (env
  ``REDPANDA_PORT``), ``xdist_redpanda_isolation_level`` (default ``database``), ``provide_redpanda_service`` and
  ``fetch_kafka_brokers``. The broker advertises the host port the runtime maps.
* ``localstack_service`` (``LocalStackService`` with ``endpoint_url``, credentials, ``resource_prefix`` and
  ``exec_aws_cli()``), ``provide_localstack_service`` and the ``localstack_image``, ``localstack_auth_token``,
  ``localstack_region``, ``localstack_access_key``, ``localstack_secret_key``, ``localstack_services``,
  ``localstack_resource_prefix`` and ``xdist_localstack_isolation_level`` fixtures (each with a ``LOCALSTACK_*``
  environment variable). The default image is MiniStack (``ministackorg/ministack:latest``); set
  ``LOCALSTACK_IMAGE`` and ``LOCALSTACK_AUTH_TOKEN`` for a LocalStack image.
* ``pytest_databases.helpers.http_get_ok(url, *, timeout)`` and ``http_get_json(url, *, timeout)`` HTTP readiness
  probes.
* ``pubsub_service`` (``PubSubService`` with ``project``, ``emulator_host`` and ``endpoint``), ``pubsub_image``
  (default ``gcr.io/google.com/cloudsdktool/google-cloud-cli:577.0.0-emulators``, env ``PUBSUB_IMAGE``),
  ``pubsub_project``, ``xdist_pubsub_isolation_level`` (default ``database``: one emulator, a project per worker) and
  ``provide_pubsub_service``.
* ``rabbitmq_service`` (``RabbitMQService`` with ``amqp_url``, ``management_port`` and ``management_url``),
  ``rabbitmq_image`` (default ``rabbitmq:4.3-management``), ``rabbitmq_username``, ``rabbitmq_password``,
  ``rabbitmq_vhost``, ``xdist_rabbitmq_isolation_level`` (default ``database``: one broker, a virtual host per worker)
  and ``provide_rabbitmq_service``.
* ``db2_service`` (``Db2Service`` with ``dsn``, ``connection_config``, ``exec_sql()`` and
  ``create_worker_database()``), ``db2_image`` (default ``icr.io/db2_community/db2:12.1.5.0``, env ``DB2_IMAGE``),
  ``db2_dbname``, ``db2_username``, ``db2_password``, ``db2_startup_timeout``, ``xdist_db2_isolation_level`` (default
  ``database``: one container, a ``ptdb_<worker>`` database per worker), ``exec_db2_sql``, ``create_worker_database``,
  ``validate_db2_database_name`` and ``provide_db2_service``. The container runs privileged. ``db2_4k_device_support``
  (default ``True``, env ``DB2_4K_DEVICE_SUPPORT``) sets ``DB2_4K_DEVICE_SUPPORT=ON`` and ``DB2_DIRECT_IO=NO`` before
  the first ``db2start`` so the database is created on storage with 4096-byte logical sectors.
* ``oracle_adb_service`` (``OracleADBService`` with TLS, mTLS, ORDS and MongoDB API ports, ``wallet_dir``,
  ``ords_url``, ``apex_url``, ``sql_developer_url``, ``mongo_uri``, ``extract_wallet()`` and ``enable_ords_schema()``)
  for Oracle Autonomous AI Database Free (default ``container-registry.oracle.com/database/adb-free:latest-26ai``, env
  ``ORACLE_ADB_IMAGE``), the ``oracle_adb_image``, ``oracle_adb_workload_type``, ``oracle_adb_hostname``,
  ``oracle_adb_tz``, ``oracle_adb_password``, ``oracle_adb_admin_password``, ``oracle_adb_wallet_password``,
  ``oracle_adb_wallet_dir``, ``oracle_adb_volumes``, ``oracle_adb_devices`` and ``oracle_adb_filesystemio_options``
  fixtures, and ``provide_oracle_adb_service``, ``ensure_oracle_adb_user``, ``enable_oracle_ords_schema``,
  ``extract_adb_wallet``, ``parse_tnsnames``, ``rewrite_tnsnames`` and ``rewrite_sqlnet_ora``.
  ``oracle_adb_filesystemio_options`` (default ``NONE``, env ``ORACLE_ADB_FILESYSTEMIO_OPTIONS``) rewrites the server
  parameter file before the database starts so the instance opens on storage with 4096-byte logical sectors.
* Floci cloud emulators in ``pytest_databases.docker.floci``: ``floci_aws_service`` (``FlociAWSService`` with
  ``ensure_bucket(bucket_name) -> None``, image ``floci/floci:2.4.0``, port ``4566``), ``floci_az_service``
  (``FlociAzureService`` with ``blob_endpoint``, ``floci/floci-az:0.16.0``, port ``4577``), ``floci_gcp_service``
  (``FlociGCPService`` with ``ensure_bucket()``, ``storage_emulator_host`` and ``pubsub_emulator_host``,
  ``floci/floci-gcp:0.12.0``, port ``4588``) backed by the session-scoped ``floci_gcp_compat_proxy``
  (``FLOCI_GCP_COMPAT_PROXY``, default ``True``) for ``obstore``, ``gcsfs``, and ``google-cloud-storage``
  compatibility, and ``floci_oci_service`` (``FlociOCIService`` with ``ensure_bucket()``,
  ``floci/floci-oci:0.6.0``, port ``4599``), with ``floci_<cloud>_image`` fixtures (env ``FLOCI_AWS_IMAGE``,
  ``FLOCI_AZ_IMAGE``, ``FLOCI_GCP_IMAGE``, ``FLOCI_OCI_IMAGE``), ``floci_aws_region``, ``floci_aws_access_key``,
  ``floci_aws_secret_key``, ``floci_az_account_name``, ``floci_az_account_key``, ``floci_gcp_project``,
  ``floci_oci_namespace`` (default ``floci-local``), ``floci_oci_region``, ``floci_oci_compartment_id``,
  ``floci_resource_prefix``, ``xdist_floci_isolation_level`` (default ``database``: one container per cloud),
  ``provide_floci_container``, ``provide_floci_gcp_service``, ``check_floci_health``, ``ensure_gcs_bucket``,
  ``ensure_oci_bucket``, ``FLOCI_CONTAINER_PORTS`` and ``FLOCI_HEALTH_PATHS`` (gh-188).
* ``snowflake_service`` (``SnowflakeService`` with ``endpoint``, ``connection_kwargs``, ``login()`` and ``query()``)
  for the Embucket Snowflake-compatible emulator (default ``embucket/embucket:0.2.2``, env ``SNOWFLAKE_IMAGE``, port
  ``3000``), the ``snowflake_image``, ``snowflake_user``, ``snowflake_password``, ``snowflake_account``,
  ``snowflake_database``, ``snowflake_schema``, ``snowflake_warehouse``, ``snowflake_role``,
  ``snowflake_wire_compat`` (``SNOWFLAKE_WIRE_COMPAT``, default ``True``) and ``xdist_snowflake_isolation_level``
  (default ``database``: one container, a ``public_<worker>`` schema per worker) fixtures, and
  ``provide_snowflake_service(..., wire_compat=True)`` (enabling gzip decompression, positional ``?`` binding
  substitution, and stringified ``rowset`` cells for ``snowflake-connector-python``), ``check_snowflake_health``,
  ``login_snowflake_emulator`` and ``query_snowflake_emulator``. ``query()`` logs in as ``snowflake_user`` and runs
  in ``snowflake_database`` / ``snowflake_schema`` (gh-187).
* ``sybase_service`` (``SybaseService`` with ``connection_config``, ``dsn``, ``exec_sql()`` and
  ``create_worker_database()``) for SAP ASE (default ``datagrip/sybase:16.0``, env ``SYBASE_IMAGE``, port ``5000``),
  the ``sybase_image``, ``sybase_user``, ``sybase_password``, ``sybase_database``, ``sybase_startup_timeout`` and
  ``xdist_sybase_isolation_level`` (default ``database``: one container and a ``<sybase_database>_<worker>``
  database per worker, ``pytestdb_<worker>`` when ``sybase_database`` is ``master``) fixtures, and
  ``provide_sybase_service``, ``exec_isql``, ``create_worker_database`` and ``validate_sybase_database_name``.
* ``sqlanywhere_service`` (``SQLAnywhereService`` with ``connection_config``, ``dsn`` and ``exec_sql()``) for SAP SQL
  Anywhere (default ``jaschweder/sybase:latest``, env ``SQLANYWHERE_IMAGE``, port ``2638``), the
  ``sqlanywhere_image``, ``sqlanywhere_user``, ``sqlanywhere_password``, ``sqlanywhere_database``,
  ``sqlanywhere_server``, ``sqlanywhere_startup_timeout`` and ``xdist_sqlanywhere_isolation_level`` (default and only
  supported value ``server``: one container per worker) fixtures, the ``sqlanywhere_client_libs`` fixture (extracts
  the native client libraries and sets ``SQLANY16`` / ``SQLANY_API_DLL`` for the session), and
  ``provide_sqlanywhere_service``, ``exec_dbisql``, ``extract_sqlanywhere_client_libs`` and
  ``sqlanywhere_client_environment``.
* ``"template"`` value for ``xdist_postgres_isolation_level`` (typed ``PostgresXdistIsolationLevel``): one container,
  a template database built once under a file lock, and the service database cloned from it with
  ``CREATE DATABASE ... TEMPLATE``, with or without ``pytest-xdist``, for every PostgreSQL family service. Fixtures
  ``postgres_template_name``, ``postgres_template_setup`` (SQL statements, ``.sql`` paths, or a callable),
  ``postgres_template_fingerprint_sources``, ``postgres_template_lock_dir`` and ``postgres_template_options``
  (``PostgresTemplateOptions``); the setup SQL and file contents are hashed into the template name
  (``pytest_databases_template_<digest>``). ``PostgresService.ensure_template()``,
  ``create_worker_database_from_template()``, ``sweep_worker_databases()`` and ``compute_fingerprint()``.
* ``pytest_databases.embedded.postgres``: ``embedded_postgres_service`` (``EmbeddedPostgresService`` with ``dsn``,
  ``connection_config``, ``password`` defaulting to ``""``, ``exec_sql(..., tuples_only=False, timeout=30.0) -> tuple[int, bytes]``,
  and the same template helpers including ``init_sql`` staging as ``PostgresService``) runs local ``initdb`` /
  ``postgres`` binaries with trust authentication on a loopback port, without a container runtime or ``psql``.
  Binaries come from ``embedded_postgres_bin_dir``, ``PG_BIN_DIR``, the new ``embedded-postgres`` extra (``pgembed``
  on Python 3.12+, ``pgserver`` on 3.11), the ``PATH``, ``pg_config --bindir``, or common install directories.
  Fixtures ``embedded_postgres_user``, ``embedded_postgres_database``, ``embedded_postgres_port``,
  ``embedded_postgres_bin_dir``, ``embedded_postgres_template_name``, ``embedded_postgres_template_setup``,
  ``embedded_postgres_template_fingerprint_sources``, ``embedded_postgres_template_lock_dir``, ``postgres_any_service``,
  and ``xdist_embedded_postgres_isolation_level`` (default ``template``: xdist workers share one cluster and each gets a
  database cloned from the template). ``provide_embedded_postgres_service(..., password="", init_sql=None)``,
  ``resolve_postgres_binaries`` and ``PostgresBinaries`` (gh-185, gh-193).
* ``cloudflare_service`` (``CloudflareService`` with ``api_base_url``, ``r2_s3_endpoint_url``, ``kv_put()``,
  ``kv_get()``, ``r2_put()``, ``r2_get()`` and ``d1_query()``) for Cloudflare KV, R2 and D1, backed by Miniflare's
  Local Explorer API and R2 S3 endpoint in a ``node:22-slim`` container (env ``CLOUDFLARE_IMAGE``, port ``8787``;
  Miniflare ``5.20261104.0-beta`` is installed from npm on first start unless the image provides it). Fixtures
  ``cloudflare_image``, ``cloudflare_miniflare_version``, ``cloudflare_kv_namespaces``, ``cloudflare_r2_buckets``,
  ``cloudflare_d1_databases`` (default ``("default",)``), ``cloudflare_access_key_id``,
  ``cloudflare_secret_access_key``, ``cloudflare_startup_timeout`` (default ``300``) and
  ``xdist_cloudflare_isolation_level`` (default ``database``: one container binding ``<name>_<worker>`` for every
  worker), and ``provide_cloudflare_service``.
* ``ContainerService.temp_dir`` exposing a session-scoped temporary :class:`pathlib.Path` on ``container_service`` /
  ``docker_service`` for cross-worker ``FileLock`` and session state coordination (gh-184, gh-186).
* ``pytest_databases.send_http_request`` (returning ``(status, headers, body)``), ``ssl_context`` support on
  ``pytest_databases.helpers.http_request`` (returning ``(status, body)``), and public
  ``pytest_databases.create_s3_bucket(..., timeout=10.0, ssl_context=None) -> bool`` (also exported from
  ``pytest_databases.helpers``) for creating S3 buckets without routing through ambient
  ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``ALL_PROXY`` variables (gh-184, gh-188).
* ``PostgresServiceProtocol``, ``PostgresBackend``, ``--postgres-backend`` CLI flag / ``postgres_backend`` ini
  setting / ``PYTEST_DATABASES_POSTGRES_BACKEND`` env var (resolved via ``resolve_postgres_backend``), and portable
  session-scoped ``postgres_any_service`` fixture switching cleanly between Docker and embedded PostgreSQL (gh-193).
* ``postgres_startup_timeout`` (default ``60``), ``alloydb_omni_shm_size`` (default ``"256m"``),
  ``alloydb_omni_startup_timeout`` (default ``90``), ``alloydb_omni_command`` and ``alloydb_omni_legacy_command``
  (``build_alloydb_omni_command``), automatic ``CREATE EXTENSION IF NOT EXISTS vector`` across ``pgvector_service``
  and ``pgvector_13_service``..``pgvector_18_service``, out-of-the-box AlloyDB Omni ``google_columnar_engine``,
  ``pg_stat_statements``, ``vector``, ``alloydb_scann``, ``google_ml_integration``, and ``alloydb_ai_nl`` (versions
  15–18) plus ``pg_textsearch`` BM25 (versions 17/18), and ``init_sql`` staging on
  ``PostgresTemplateSupport.ensure_template`` (gh-185).
* ``CockroachDBService.user`` (default ``"root"``), ``CockroachDBService.dsn``,
  ``CockroachDBService.connection_config`` (``"database"`` key aligned with ``PostgresService``),
  ``CockroachDBService.exec_sql(...) -> tuple[int, bytes]``, and public ``exec_cockroach_sql`` (gh-193).
* ``SpannerService.emulator_host`` and ``configure_spanner_emulator_client_guards`` disabling built-in client metrics,
  shortening ``DatabaseSessionsManager._MAINTENANCE_THREAD_POLLING_INTERVAL`` to 100ms, raising session-manager logger
  verbosity to ``WARNING``, and suppressing closed-stream ``ValueError`` teardown tracebacks (gh-189).
* ``BigQueryService.is_healthy(*, timeout=5.0)`` and ``BIGQUERY_IMAGE`` environment override on ``bigquery_image``
  (gh-190).
* ``db2_volumes`` fixture (gh-186), public ``exec_sqlplus``, ``OracleADBService.mtls_alias``, and
  ``OracleADBService.build_wallet_zip`` with optional ``cryptography`` PKCS#12 ``ewallet.p12`` synthesis (gh-191), and
  ``SybaseService.write_freetds_conf`` plus session-scoped ``sybase_freetds_alias`` for FreeTDS 5.0 clients (gh-192).
* ``oracle_startup_timeout`` (default ``180``, env ``ORACLE_STARTUP_TIMEOUT``) and ``oracle_adb_startup_timeout``
  (default ``420``, env ``ORACLE_ADB_STARTUP_TIMEOUT``) fixtures, plus validated keyword-only ``timeout`` and ``pause``
  parameters on ``provide_oracle_service`` (defaults ``180`` and ``1.0``) and ``provide_oracle_adb_service``
  (defaults ``420`` and ``2.0``).
* ``copy_to_container``, ``copy_from_container`` and ``exec_container_command`` in ``pytest_databases.types`` (also
  exported from ``pytest_databases``), plus ``ServiceContainer.copy_to()``, ``ServiceContainer.copy_from()`` and
  ``ServiceContainer.exec_command()`` for transferring files and executing commands inside service containers over the
  Docker/Podman SDK archive API.
* ``has_active_owner_sessions(owner_id)`` and advisory OS ``FileLock`` session leases so concurrent local ``pytest``
  runs sharing an owner ID leave containers running until the final active session exits, while sweeping stale leases
  from crashed processes automatically.
* Keyword-only ``user``, ``tmpfs`` and ``extra_hosts`` parameters on ``ContainerService.run``, plus
  ``pytest_databases.helpers.env_port``, ``read_init_scripts`` and ``run_container_init_once``.
* ``ExternalPostgresService``, ``provide_external_postgres_service``, ``postgres_external_host`` (env
  ``POSTGRES_EXTERNAL_HOST``), ``postgres_external_port`` (env ``POSTGRES_EXTERNAL_PORT``) and
  ``postgres_external_service`` in ``pytest_databases.docker.postgres`` for attaching to pre-started PostgreSQL
  endpoints with ``"database"`` or ``"template"`` isolation over the stdlib v3 wire client (which now supports
  ``trust``, cleartext, MD5 and ``SCRAM-SHA-256`` authentication).
* ``PostgresService.dsn``, ``PostgresService.connection_config`` and ``PostgresService.exec_sql()``, the
  ``postgres_database`` fixture (default ``"pytest_databases"``, env ``POSTGRES_DATABASE``), ``POSTGRES_USER`` env
  override on ``postgres_user``, and keyword-only ``database``, ``command``, ``env``, ``shm_size``, ``mem_limit``,
  ``volumes`` and ``init_sql`` parameters on ``provide_postgres_service``.
* ``teradata_service`` (``TeradataService``) and ``teradata_external_service`` (``ExternalTeradataService``) in
  ``pytest_databases.docker.teradata`` with ``dbs_port``, ``connection_config``, ``provide_teradata_service``,
  ``provide_external_teradata_service``, and session fixtures ``teradata_image`` (env ``TERADATA_IMAGE`` /
  ``TERADATA_TEST_IMAGE``), ``teradata_external_host`` (env ``TERADATA_EXTERNAL_HOST`` / ``TERADATA_HOST``),
  ``teradata_external_port`` (env ``TERADATA_EXTERNAL_PORT`` / ``TERADATA_PORT``), ``teradata_port``,
  ``teradata_user``, ``teradata_password``, ``teradata_database``, ``teradata_logmech``, ``teradata_logdata``,
  ``teradata_sslmode``, ``teradata_encryptdata``, ``teradata_tmode``, ``teradata_startup_timeout`` (default
  ``300.0``), ``teradata_service_environment`` and ``xdist_teradata_isolation_level`` (default ``"server"``),
  plus ``image_required`` support in the CI provider manifest.
* ``exec_mysql`` / ``MySQLService.exec_sql()`` and ``exec_mariadb`` / ``MariaDBService.exec_sql()`` (passing
  credentials via ``MYSQL_PWD``), ``mysql_port`` (env ``MYSQL_PORT``) and ``mariadb_port`` (env ``MARIADB_PORT``)
  fixtures, ``MYSQL_*`` / ``MARIADB_*`` environment variable lookups on user/password/database fixtures, ``root``
  application user support, and keyword-only ``host_port``, ``command``, ``env`` and ``init_sql`` parameters on
  ``provide_mysql_service`` and ``provide_mariadb_service``.
* ``MSSQLService.exec_sql()``, ``mssql_port`` (env ``MSSQL_PORT``), ``MSSQL_USER`` / ``MSSQL_PASSWORD`` /
  ``MSSQL_DATABASE`` environment variable overrides, multi-batch standalone ``GO`` and ``sql_file`` staging with
  ``SQLCMDPASSWORD`` credential delivery and ``query_timeout`` in ``exec_sqlcmd``, and keyword-only ``host_port``,
  ``env``, ``mem_limit``, ``shm_size`` and ``init_sql`` parameters on ``provide_mssql_service``.
* ``oracle_26ai_service`` (aliased by ``oracle_service``), ``oracle_26ai_image`` (default
  ``gvenzl/oracle-free:23-slim-faststart`` delivering Oracle AI Database 26ai Free ``23.26.x``, env
  ``ORACLE_26AI_IMAGE``), ``oracle_26ai_service_name`` (env ``ORACLE_26AI_SERVICE_NAME``), ``exec_oracle_sql`` and
  ``OracleService.exec_sql()`` (supporting both PDB TNS targets and OS-authenticated ``CDB$ROOT``
  ``sqlplus -L -S / as sysdba`` execution), ``oracle_port`` (env ``ORACLE_PORT``), ``oracle_26ai_port`` (env
  ``ORACLE_26AI_PORT``, falling back to ``oracle_port``), ``oracle_18c_port`` (env ``ORACLE_18C_PORT``) and
  ``oracle_adb_port`` (env ``ORACLE_ADB_PORT``) fixtures, ``ORACLE_USER`` / ``ORACLE_PASSWORD`` /
  ``ORACLE_SYSTEM_PASSWORD`` environment variable overrides, and keyword-only ``host_port``, ``env``, ``volumes``,
  ``shm_size``, ``mem_limit`` and ``init_sql`` parameters on ``provide_oracle_service`` and
  ``provide_oracle_adb_service``.
* ``activate_db2_database``, ``Db2Service.activate_database()``, ``db2_activate_database`` (default ``True``, env
  ``DB2_ACTIVATE_DATABASE``, keeping in-memory ``MON_GET_*`` metrics alive across disconnects), ``db2_port`` (env
  ``DB2_PORT``), and keyword-only ``activate_database``, ``host_port``, ``env``, ``registry_vars``, ``shm_size``,
  ``mem_limit``, ``platform`` and ``init_sql`` parameters on ``provide_db2_service``.
* ``configure_sybase_monitoring``, ``sybase_enable_monitoring`` (default ``False``, env ``SYBASE_ENABLE_MONITORING``)
  and ``sybase_port`` (env ``SYBASE_PORT``) fixtures, ``user`` / ``password`` overrides on
  ``SybaseService.exec_sql()``, and keyword-only ``enable_monitoring``, ``host_port``, ``env`` and ``init_sql``
  parameters on ``provide_sybase_service``.
* ``exec_mongosh``, ``MongoDBService.uri``, ``MongoDBService.exec_js()``, ``MongoDBService.set_profiling_level()`` and
  ``MongoDBService.replica_set``, session fixtures ``mongodb_username`` (env ``MONGODB_USER``; ``""`` or ``None`` for
  unauthenticated mode), ``mongodb_password`` (env ``MONGODB_PASSWORD``), ``mongodb_database_name`` (env
  ``MONGODB_DATABASE``), ``mongodb_port`` (env ``MONGODB_PORT``) and ``mongodb_replica_set`` (env
  ``MONGODB_REPLICA_SET``, bootstrapping a single-node replica set with an automatic internal ``--keyFile`` and
  writable ``PRIMARY`` election), and keyword-only ``host_port``, ``replica_set``, ``command``, ``env``, ``init_js``,
  ``profiling_level`` and ``slow_ms`` parameters on ``provide_mongodb_service``.

Changed
~~~~~~~

* Default MinIO image changed from ``quay.io/minio/minio`` to ``cgr.dev/chainguard/minio:latest``.
* ``minio_service`` and ``rustfs_service`` create the default bucket with an AWS SigV4-signed HTTP ``PUT`` from the
  test process. The ``minio/mc:latest`` and ``rustfs/rc:latest`` helper containers (run with
  ``network_mode="host"``) are no longer pulled or started. With ``minio_secure`` / ``rustfs_secure`` enabled the
  request skips TLS certificate verification.
* Containers start with a dynamic host port retry when the runtime reports the port is already in use, and a
  container that exits during startup fails the fixture at once with its last log lines.
* ``ContainerService.run(shm_size=...)`` is now passed to the container runtime (it was accepted and ignored) and
  also accepts size strings such as ``"2g"``.
* Without ``pytest-xdist``, an interpreter-exit hook stops the session's containers if pytest exits before its
  normal teardown.
* ``spanner_service`` creates the emulator instance and database through the emulator REST API (port 9020) instead of
  running the ``gcr.io/google.com/cloudsdktool/cloud-sdk:slim`` image. Under ``pytest-xdist`` with the default
  ``database`` isolation, workers share one emulator and each gets ``emulator-test-database_<worker>``.
* ``yugabyte_service`` readiness verifies the database inside the service container and probes the mapped port,
  instead of starting a second ``ysqlsh`` container with ``network_mode="host"``.
* ``redis_service``, ``dragonfly_service``, ``keydb_service`` and ``valkey_service`` check readiness with a RESP
  ``PING`` over a stdlib socket; the ``redis`` and ``valkey`` packages are no longer imported by the plugin.
* Under ``pytest-xdist`` with the default ``database`` isolation, Redis-family services give each worker logical
  database ``<worker> % 16`` and start an extra shared container (``<service>_shared_<n>``) for every 16 workers,
  instead of using database ``<worker>`` in one container.
* ``valkey_service`` under ``pytest-xdist`` with the default ``database`` isolation now shares one container and
  gives each worker its own logical database (``ValkeyService.db``), instead of starting a container per worker.
* ``gizmosql_service`` checks readiness by running ``SELECT 4242`` through ``gizmosql_client`` inside the container
  and matching the exact value; ``adbc-driver-flightsql`` is no longer imported by the plugin.
* GizmoSQL container names include the backend (``gizmosql-duckdb``, ``gizmosql-sqlite``); under ``pytest-xdist``
  every worker still gets its own container per backend for both isolation levels.
* Postgres-family services (``postgres_*``, ``pgvector_*``, ``paradedb_*``, ``alloydb_omni_*``) check readiness
  with ``psql`` inside the container followed by a TCP probe of the published port, and create the per-worker
  database with ``psql``; ``psycopg`` is no longer imported by the plugin.
* Default ``alloydb_omni_image`` changed from ``google/alloydbomni:17`` to ``gcr.io/alloydb-omni/alloydbomni:18``.
* ``alloydb_omni_15_service``, ``alloydb_omni_16_service`` and ``alloydb_omni_17_service`` pull from
  ``gcr.io/alloydb-omni/alloydbomni:<version>`` instead of ``google/alloydbomni:<version>``.
* ``azure_blob_service`` checks readiness and creates its default container with stdlib HTTP requests signed with
  SharedKey; ``azure-storage-blob`` is no longer imported by the plugin.
* ``bigquery_service`` checks readiness with a stdlib HTTP query against the emulator REST API; the Google Cloud
  libraries are no longer imported by the plugin. ``bigquery_client`` now closes its client at teardown.
* Pinned default ``bigquery_image`` to ``ghcr.io/goccy/bigquery-emulator:0.8.1`` (``DEFAULT_BIGQUERY_IMAGE``) and
  changed default ``xdist_bigquery_isolation_level`` to ``"server"`` (non-transient shared container in single-process
  sessions, transient per-worker containers under ``pytest-xdist`` to avoid SQLite catalog DDL races); override
  ``xdist_bigquery_isolation_level`` to ``"database"`` for per-worker ``test-dataset_<worker>`` datasets on a shared
  container (gh-190).
* Default ``db2_ipc_mode`` changed to ``"host"`` across Docker and Podman (set ``DB2_IPC_MODE=""`` or override
  ``db2_ipc_mode`` to ``None`` to opt into private container IPC namespaces) to prevent ``SQL1042C`` SysV semaphore
  exhaustion (gh-186).
* Under ``pytest-xdist`` with the default ``database`` isolation, Oracle services start one shared container per
  version and give each worker its own user, so ``OracleService.user`` is ``app_<worker>`` instead of ``app``. Set
  ``xdist_oracle_isolation_level`` to ``server`` for the previous container per worker.
* ``oracle_service`` now aliases ``oracle_26ai_service``, and the default Oracle Free logical service label/container
  stem changed from ``oracle23ai`` to ``oracle26ai``.
* ``dolt_service`` and ``mysql_8_service`` / ``mysql_84_service`` / ``mysql_96_service`` run the native image
  platform instead of ``linux/x86_64``. ``mysql_56_service`` and ``mysql_57_service`` keep ``linux/x86_64``.
* MySQL and MariaDB services start with ``--performance-schema=ON``.
* ``elasticsearch_service_memory_limit`` default changed from ``500m`` to ``1g`` and is now applied to the
  Elasticsearch containers (0.19.0 always used ``1g``).
* ``mssql_service`` reuses the ``mssql_2022_service`` container when ``mssql_image`` equals ``mssql_2022_image``,
  and SQL Server services wait until the per-worker database is ``ONLINE``.
* ``elasticsearch_service`` and ``oracle_startup_connection`` resolve again; in 0.19.0 they requested the undefined
  fixtures ``elasticsearch8_service`` and ``oracle_23ai_startup_connection``.
* The deprecated ``@contextmanager`` connection helpers warn with ``stacklevel=3``, which attributes the warning to
  the fixture rather than ``contextlib``.
* CI workflows ``docs.yml`` and ``release.yaml`` enforce ``uv sync --frozen``, and the unused ``cd.yaml`` workflow is
  removed.
* ``scripts/ci/select_provider_tests.py`` computes provider cost budgets dynamically from
  ``.github/ci/provider-groups.json``, dropping the unused ``cloud-sdk:slim`` image from ``spanner``.

Fixed
~~~~~

* Bypass ambient ``HTTP_PROXY``, ``HTTPS_PROXY``, and ``ALL_PROXY`` variables across S3, MinIO, RustFS, Azurite,
  Elasticsearch, Snowflake, Floci, Spanner, and BigQuery HTTP readiness probes while preserving SigV4 and SharedKey
  signatures (gh-184).
* Serialize concurrent ``pytest-xdist`` user grant provisioning in ``provide_mysql_service`` and
  ``provide_mariadb_service``, serialize Db2 4Kn ``db2stop force`` recovery (``SQL1013N`` / SQLSTATE ``42705``) and
  ``create_worker_database`` via ``FileLock`` under ``ContainerService.temp_dir`` and in-container ``flock``, and
  fast-fail immediately on Db2 ``SQL1042C`` / ``SQLSTATE=57019`` container startup errors (gh-184, gh-186).
* Forward ``command``, ``timeout``, ``shm_size``, and ``init_sql`` through PostgreSQL family fixture factories and run
  provider ``init_sql`` statements inside containerized, external, and embedded staging template databases prior to
  user ``postgres_template_setup`` and ``embedded_postgres_template_setup`` hooks (gh-185).
* Loading the ``pytest11`` plugin (``pytest_databases._service``) no longer imports ``pytest_databases.docker`` on
  startup; ``TRUE_VALUES`` is now defined in ``pytest_databases.helpers`` and re-exported from
  ``pytest_databases.docker`` for backward compatibility.
* ``provide_oracle_service`` (``timeout=180``, ``pause=1.0``) and ``provide_oracle_adb_service`` (``timeout=420``,
  ``pause=2.0``) now gate ``sqlplus`` readiness probes with ``tcp_port_open`` before running in-container queries,
  ``ensure_oracle_user`` synchronizes and unlocks existing ``pytest-xdist`` worker users idempotently (tolerating
  ``ORA-01920`` and ``ORA-28007``), and ``ensure_oracle_user``, ``ensure_oracle_adb_user``, and
  ``enable_oracle_ords_schema`` escape single quotes in PL/SQL literals and retry transient ``ORA-*`` startup,
  listener, and lock errors.
* ``provide_postgres_service`` now forwards ``POSTGRES_USER`` and ``POSTGRES_DB`` into the container environment (and
  omits an empty ``POSTGRES_PASSWORD`` when ``POSTGRES_HOST_AUTH_METHOD=trust`` is supplied) so non-``postgres``
  superusers and custom base database names pass readiness and provisioning cleanly.
* ``provide_mysql_service`` and ``provide_mariadb_service`` now honor their ``database`` parameter on ``service.db``
  (and ``<database>_<worker>`` under ``pytest-xdist`` ``"database"`` isolation) instead of hardcoding
  ``"pytest_databases"``, and combine in-container readiness queries with ``tcp_port_open`` (alongside ``db2`` and
  ``mongodb``).
* ``provide_oracle_service`` now runs ``ensure_oracle_user`` under a cross-worker file lock in single-process runs and
  ``pytest-xdist`` ``"server"`` isolation as well as ``"database"`` isolation, granting consistent ``CONNECT``,
  ``RESOURCE``, ``DBA`` and ``QUOTA UNLIMITED ON USERS`` privileges across all execution modes.
* ``ContainerService.run(exec_after_start=...)`` now runs once per shared container under a cross-worker file lock and
  raises ``RuntimeError`` when the post-start command exits with a non-zero status.

Deprecated
~~~~~~~~~~

* ``pytest_databases.docker.valkey.valkey_responsive``; use ``pytest_databases.docker.redis.redis_responsive``.
  Removal in 1.0.0.
* ``gizmosql_connection``; use ``gizmosql_service`` with its ``uri`` and ``connection_kwargs`` and open your own
  ADBC Flight SQL connection. Removal in 1.0.0.
* Postgres-family ``*_connection`` fixtures (``postgres_connection``, ``postgres_<version>_connection``,
  ``pgvector_*_connection``, ``paradedb_*_connection``, ``alloydb_omni_*_connection``); use the matching
  ``*_service`` fixture and open your own ``psycopg`` connection. Removal in 1.0.0.
* ``azure_blob_container_client`` and ``azure_blob_async_container_client``; use ``azure_blob_service`` and build
  your own ``ContainerClient`` from ``connection_string``. Removal in 1.0.0.
* ``bigquery_client``, ``BigQueryService.credentials``, ``BigQueryService.client_options`` and the
  ``credentials`` argument of ``BigQueryService`` (now ignored); build ``AnonymousCredentials()`` and
  ``ClientOptions(api_endpoint=service.endpoint)`` yourself. Removal in 1.0.0.
* ``cockroachdb_connection``; use ``cockroachdb_service`` and open your own ``psycopg`` connection. Removal in 1.0.0.
* ``mongodb_connection`` and ``mongodb_database``; use ``mongodb_service`` and open your own ``pymongo`` client.
  Each now emits a single warning. Removal in 1.0.0.
* ``oracle_18c_connection``, ``oracle_23ai_connection``, ``oracle_26ai_connection``, ``oracle_startup_connection``
  and ``oracle_responsive``; use ``oracle_service`` (or the versioned services) and open your own ``oracledb``
  connection. Removal in 1.0.0.
* ``oracle_23ai_service``, ``oracle_23ai_image`` and ``oracle_23ai_service_name``, and overriding them outside
  ``pytest_databases``; use and override ``oracle_26ai_service``, ``oracle_26ai_image`` and
  ``oracle_26ai_service_name`` instead. Removal in 1.0.0.
* ``spanner_connection``, ``SpannerService.credentials``, ``SpannerService.client_options`` and the ``credentials``
  argument of ``SpannerService`` (now ignored); build the client, ``AnonymousCredentials()`` and
  ``ClientOptions(api_endpoint=service.endpoint)`` yourself. Removal in 1.0.0.
* ``elasticsearch7_responsive`` and ``elasticsearch8_responsive``; the Elasticsearch services check readiness
  without a client. Removal in 1.0.0.
* The bare ``platform`` fixture and overriding it. A ``platform`` override defined outside ``pytest_databases`` is
  still honored by the MySQL, Dolt and BigQuery services with one warning; override ``mysql_platform``,
  ``dolt_platform`` or ``bigquery_platform`` instead. Removal in 1.0.0.
* ``DockerServiceRegistry``; use the ``docker_service`` fixture. Removal in 1.0.0.

Breaking
~~~~~~~~

* ``requires-python`` raised from ``>=3.9`` to ``>=3.11``. Python 3.9 and 3.10 are no longer supported.
* The ``all`` optional extra has been removed; install the specific provider extras or client packages directly.
* Container names changed from ``pytest_databases_<service>`` to ``pytest_databases_<service>_<owner>``, where
  ``<owner>`` is derived from the pytest root path (plus ``PYTEST_DATABASES_NAMESPACE``). Scripts that address
  containers by the old name must filter on the ``pytest_databases.service`` label instead.
* Container labels changed from the list ``["pytest_databases"]`` to a mapping with ``pytest_databases``,
  ``pytest_databases.owner`` and ``pytest_databases.service`` keys.
* Session start and end only remove containers carrying this session's ``pytest_databases.owner`` label, instead
  of every container labelled ``pytest_databases``. Use ``stop_all_containers`` for the previous behavior.
* ``get_docker_host()`` returns the endpoint of the resolved runtime instead of parsing ``docker context ls``, and
  raises ``RuntimeResolutionError`` when no Docker or Podman endpoint is reachable.
* Under ``pytest-xdist`` with the default ``database`` isolation, ``minio_default_bucket_name`` and
  ``rustfs_default_bucket_name`` are now ``pytest-databases-<worker>`` (previously ``pytest-databases`` for all
  workers). Read the bucket from the fixture instead of hard-coding it.
* A failure to create the MinIO or RustFS default bucket now raises ``RuntimeError`` during fixture setup instead of
  being ignored.
* ``azure_blob_service`` creates the ``azure_blob_default_container_name`` container (``pytest-databases``) before
  yielding, so ``azure_blob_container_client.create_container()`` on the default container now raises
  ``ResourceExistsError``. Drop the call or guard it with ``exists()``.
* The ``cockroachdb`` (``psycopg``), ``elasticsearch7``, ``elasticsearch8``, ``mongodb`` (``pymongo``), ``oracle``
  (``oracledb``) and ``valkey`` extras no longer install a driver, because the services check readiness without
  one. If you use the deprecated ``cockroachdb_connection``, ``mongodb_connection``, ``mongodb_database`` or
  ``oracle_*_connection`` fixtures, install ``psycopg``, ``pymongo`` or ``oracledb`` directly.

0.19.0 (2026-05-23)
-------------------

Added
~~~~~

* ``host_port`` kwarg on ``DockerService.run`` that pins a specific host-side
  port for the container instead of letting Docker pick one. Closes
  `gh-131 <https://github.com/litestar-org/pytest-databases/issues/131>`_.
* Per-version ``*_port`` fixtures for every postgres-family service
  (``postgres_NN_port``, ``pgvector_NN_port``, ``paradedb_NN_port``,
  ``alloydb_omni_NN_port``) that read a matching ``*_PORT`` env var.
* Per-version pgvector services: ``pgvector_13_service`` through
  ``pgvector_18_service`` (plus matching ``_connection`` fixtures).
* Per-version ParadeDB services: ``paradedb_15_service`` through
  ``paradedb_18_service`` (plus matching ``_connection`` fixtures).
* Per-version AlloyDB Omni services: ``alloydb_omni_15_service`` through
  ``alloydb_omni_17_service`` (plus matching ``_connection`` fixtures).

Changed
~~~~~~~

* Bumped default ``pgvector_image`` from ``pgvector/pgvector:pg15`` to
  ``pgvector/pgvector:pg18``.
* Bumped default ``paradedb_image`` from ``paradedb/paradedb:0.21.5-pg16`` to
  ``paradedb/paradedb:latest-pg18``.
* Bumped default ``alloydb_omni_image`` from ``google/alloydbomni:16`` to
  ``google/alloydbomni:17``.
* RustFS credential defaults changed from ``rustfsadmin`` /
  ``rustfsadmin`` (which current ``rustfs/rustfs:latest`` images reject as
  "insecure default credentials") to ``pytest-databases-rustfs`` /
  ``pytest-databases-rustfs-secret``. Closes
  `gh-132 <https://github.com/litestar-org/pytest-databases/issues/132>`_.

Fixed
~~~~~

* ``alloydb_omni_service`` was using the ``pgvector_image`` fixture instead of
  ``alloydb_omni_image``; ``alloydb_omni_connection`` was wired to
  ``pgvector_service`` instead of ``alloydb_omni_service``. Both fixtures now
  use their own image / service.
* ``DockerService.run``'s ``contextmanager`` now wraps its ``yield`` in
  ``try/finally`` so transient teardown always runs even when the test body
  raises (previously could leak containers).


0.18.0 (2026-05-12)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat(rustfs): add RustFS object storage support by @cofin in `#117 <https://github.com/litestar-org/pytest-databases/pull/117>`_
* feat(mysql,mariadb): migrate to oneshot and add new versions by @cofin in `#118 <https://github.com/litestar-org/pytest-databases/pull/118>`_
* feat(dolt): add dolt database service support by @cofin in `#119 <https://github.com/litestar-org/pytest-databases/pull/119>`_
* ci: pre-pull docker images with retry to fight registry flakes by @cofin in `#122 <https://github.com/litestar-org/pytest-databases/pull/122>`_
* feat: expose container by @provinzkraut in `#121 <https://github.com/litestar-org/pytest-databases/pull/121>`_
* ci: Add missing Python versions by @provinzkraut in `#124 <https://github.com/litestar-org/pytest-databases/pull/124>`_
* feat: move MariaDB to clientless validation by @cofin in `#126 <https://github.com/litestar-org/pytest-databases/pull/126>`_
* feat: move Dolt to clientless validation by @cofin in `#125 <https://github.com/litestar-org/pytest-databases/pull/125>`_


**Full Changelog**: `v0.17.0...v0.18.0 <https://github.com/litestar-org/pytest-databases/compare/v0.17.0...v0.18.0>`_


0.17.0 (2026-03-10)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat: postgres paradedb extension support by @ftsartek in `#110 <https://github.com/litestar-org/pytest-databases/pull/110>`_
* docs: add ParadeDB fixtures to PostgreSQL documentation by @cofin in `#112 <https://github.com/litestar-org/pytest-databases/pull/112>`_


New Contributors
~~~~~~~~~~~~~~~~
* @ftsartek made their first contribution in `#110 <https://github.com/litestar-org/pytest-databases/pull/110>`_

**Full Changelog**: `v0.16.0...v0.17.0 <https://github.com/litestar-org/pytest-databases/compare/v0.16.0...v0.17.0>`_


0.16.0 (2026-01-20)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat(gizmosql): add GizmoSQL database fixture by @cofin in `#108 <https://github.com/litestar-org/pytest-databases/pull/108>`_
* feat: implement support for `yugabyte` by @cofin in `#84 <https://github.com/litestar-org/pytest-databases/pull/84>`_
* feat: implement support for `mongodb` by @cofin in `#85 <https://github.com/litestar-org/pytest-databases/pull/85>`_


**Full Changelog**: `v0.15.1...v0.16.0 <https://github.com/litestar-org/pytest-databases/compare/v0.15.1...v0.16.0>`_


0.15.1 (2026-01-05)
-------------------

What's Changed
~~~~~~~~~~~~~~
* fix(mysql): handle InterfaceError during health check by @cofin in `#105 <https://github.com/litestar-org/pytest-databases/pull/105>`_


**Full Changelog**: `v0.15.0...v0.15.1 <https://github.com/litestar-org/pytest-databases/compare/v0.15.0...v0.15.1>`_


0.15.0 (2025-10-06)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat: Add support for PostgreSQL 18 by @Kumzy in `#98 <https://github.com/litestar-org/pytest-databases/pull/98>`_
* fix: resolve `StopIteration` error in BigQuery emulator fixture by @cofin in `#99 <https://github.com/litestar-org/pytest-databases/pull/99>`_


**Full Changelog**: `v0.14.1...v0.15.0 <https://github.com/litestar-org/pytest-databases/compare/v0.14.1...v0.15.0>`_


0.14.1 (2025-09-11)
-------------------

What's Changed
~~~~~~~~~~~~~~

* docs: update documentation link in README.md by @tylovejoy in `#95 <https://github.com/litestar-org/pytest-databases/pull/95>`_
* fix(redis): Prevent redis service from always using server isolation mode by @provinzkraut in `#96 <https://github.com/litestar-org/pytest-databases/pull/96>`_


New Contributors
~~~~~~~~~~~~~~~~
* @tylovejoy made their first contribution in `#95 <https://github.com/litestar-org/pytest-databases/pull/95>`_

**Full Changelog**: `v0.14.0...v0.14.1 <https://github.com/litestar-org/pytest-databases/compare/v0.14.0...v0.14.1>`_


0.14.0 (2025-06-14)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat: Enhance Postgres Services with configurable container host by @am1ter in `#87 <https://github.com/litestar-org/pytest-databases/pull/87>`_


New Contributors
~~~~~~~~~~~~~~~~
* @am1ter made their first contribution in `#87 <https://github.com/litestar-org/pytest-databases/pull/87>`_

**Full Changelog**: `v0.13.0...v0.14.0 <https://github.com/litestar-org/pytest-databases/compare/v0.13.0...v0.14.0>`_


0.13.0 (2025-05-25)
-------------------

What's Changed
~~~~~~~~~~~~~~
* chore(docs): initial revision of docs by @cofin in `#74 <https://github.com/litestar-org/pytest-databases/pull/74>`_
* chore(docs): build redirect index by @cofin in `#77 <https://github.com/litestar-org/pytest-databases/pull/77>`_
* chore(docs): ensure output directory exists by @cofin in `#78 <https://github.com/litestar-org/pytest-databases/pull/78>`_
* fix: tests failing on ARM MacOS by @peterHoburg in `#82 <https://github.com/litestar-org/pytest-databases/pull/82>`_
* feat: add `valkey` module and `keydb` and `dragonfly` redis services by @cofin in `#83 <https://github.com/litestar-org/pytest-databases/pull/83>`_


New Contributors
~~~~~~~~~~~~~~~~
* @peterHoburg made their first contribution in `#82 <https://github.com/litestar-org/pytest-databases/pull/82>`_

**Full Changelog**: `v0.12.3...v0.13.0 <https://github.com/litestar-org/pytest-databases/compare/v0.12.3...v0.13.0>`_


0.12.3 (2025-04-21)
-------------------

What's Changed
~~~~~~~~~~~~~~
* fix(oracle): correct service names used in fixture by @cofin in `#73 <https://github.com/litestar-org/pytest-databases/pull/73>`_


**Full Changelog**: `v0.12.2...v0.12.3 <https://github.com/litestar-org/pytest-databases/compare/v0.12.2...v0.12.3>`_


0.12.1 (2025-04-06)
-------------------

What's Changed
~~~~~~~~~~~~~~
* fix(oracle): use the 18c xe image by @cofin in `#70 <https://github.com/litestar-org/pytest-databases/pull/70>`_


**Full Changelog**: `v0.12.0...v0.12.1 <https://github.com/litestar-org/pytest-databases/compare/v0.12.0...v0.12.1>`_


0.12.2 (2025-04-06)
-------------------

What's Changed
~~~~~~~~~~~~~~
* fix(oracle): additional oracle updates by @cofin in `#71 <https://github.com/litestar-org/pytest-databases/pull/71>`_


**Full Changelog**: `v0.12.1...v0.12.2 <https://github.com/litestar-org/pytest-databases/compare/v0.12.1...v0.12.2>`_


0.12.0 (2025-03-23)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat: add support for `minio` by @cofin in `#69 <https://github.com/litestar-org/pytest-databases/pull/69>`_


**Full Changelog**: `v0.11.1...v0.12.0 <https://github.com/litestar-org/pytest-databases/compare/v0.11.1...v0.12.0>`_


0.11.1 (2025-02-11)
-------------------

What's Changed
~~~~~~~~~~~~~~
* fix: ensure container metadata is available by @provinzkraut in `#67 <https://github.com/litestar-org/pytest-databases/pull/67>`_


**Full Changelog**: `v0.11.0...v0.11.1 <https://github.com/litestar-org/pytest-databases/compare/v0.11.0...v0.11.1>`_


0.11.0 (2025-02-10)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat(everything)!: rewrite, I guess by @provinzkraut in `#54 <https://github.com/litestar-org/pytest-databases/pull/54>`_
* fix(CI): Install missing dependencies by @provinzkraut in `#66 <https://github.com/litestar-org/pytest-databases/pull/66>`_


**Full Changelog**: `v0.10.0...v0.11.0 <https://github.com/litestar-org/pytest-databases/compare/v0.10.0...v0.11.0>`_


0.10.0 (2024-10-20)
-------------------

What's Changed
~~~~~~~~~~~~~~
* feat: Remove volumes when stopping services by @provinzkraut in `#52 <https://github.com/litestar-org/pytest-databases/pull/52>`_
* feat: add support for postgres17 by @Kumzy in `#51 <https://github.com/litestar-org/pytest-databases/pull/51>`_


New Contributors
~~~~~~~~~~~~~~~~
* @Kumzy made their first contribution in `#51 <https://github.com/litestar-org/pytest-databases/pull/51>`_

**Full Changelog**: `v0.9.0...v0.10.0 <https://github.com/litestar-org/pytest-databases/compare/v0.9.0...v0.10.0>`_


0.9.0 (2024-09-07)
------------------

What's Changed
~~~~~~~~~~~~~~
* refactor: Remove async dependency by @provinzkraut in `#50 <https://github.com/litestar-org/pytest-databases/pull/50>`_


**Full Changelog**: `v0.8.0...v0.9.0 <https://github.com/litestar-org/pytest-databases/compare/v0.8.0...v0.9.0>`_


0.8.0 (2024-08-20)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: rebrand Oracle 23 to Oracle 23AI by @cofin in `#48 <https://github.com/litestar-org/pytest-databases/pull/48>`_


**Full Changelog**: `v0.7.2...v0.8.0 <https://github.com/litestar-org/pytest-databases/compare/v0.7.2...v0.8.0>`_


0.7.2 (2024-08-07)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: consolidate groupings by @cofin in `#46 <https://github.com/litestar-org/pytest-databases/pull/46>`_
* fix: correctly check for env variables by @cofin in `#47 <https://github.com/litestar-org/pytest-databases/pull/47>`_


**Full Changelog**: `v0.7.1...v0.7.2 <https://github.com/litestar-org/pytest-databases/compare/v0.7.1...v0.7.2>`_


0.7.1 (2024-07-02)
------------------

What's Changed
~~~~~~~~~~~~~~
* fix(valkey): Use the correct image name by @Alc-Alc in `#45 <https://github.com/litestar-org/pytest-databases/pull/45>`_


New Contributors
~~~~~~~~~~~~~~~~
* @Alc-Alc made their first contribution in `#45 <https://github.com/litestar-org/pytest-databases/pull/45>`_

**Full Changelog**: `v0.7.0...v0.7.1 <https://github.com/litestar-org/pytest-databases/compare/v0.7.0...v0.7.1>`_


0.7.0 (2024-06-11)
------------------

What's Changed
~~~~~~~~~~~~~~
* chore: remove license in each file by @cofin in `#40 <https://github.com/litestar-org/pytest-databases/pull/40>`_
* feat: `valkey` support & `startup_connection` fixture by @cofin in `#42 <https://github.com/litestar-org/pytest-databases/pull/42>`_


**Full Changelog**: `v0.6.0...v0.7.0 <https://github.com/litestar-org/pytest-databases/compare/v0.6.0...v0.7.0>`_


0.6.0 (2024-05-25)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: Add azure blob storage with azurite by @provinzkraut in `#39 <https://github.com/litestar-org/pytest-databases/pull/39>`_


New Contributors
~~~~~~~~~~~~~~~~
* @provinzkraut made their first contribution in `#39 <https://github.com/litestar-org/pytest-databases/pull/39>`_

**Full Changelog**: `v0.5.0...v0.6.0 <https://github.com/litestar-org/pytest-databases/compare/v0.5.0...v0.6.0>`_


0.5.0 (2024-04-21)
------------------

What's Changed
~~~~~~~~~~~~~~
* build(deps): bump codecov/codecov-action from 4.0.1 to 4.3.0 by @dependabot in `#34 <https://github.com/litestar-org/pytest-databases/pull/34>`_
* feat: independent service configurations by @cofin in `#35 <https://github.com/litestar-org/pytest-databases/pull/35>`_


**Full Changelog**: `v0.4.1...v0.5.0 <https://github.com/litestar-org/pytest-databases/compare/v0.4.1...v0.5.0>`_


0.4.0 (2024-04-19)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: BigQuery support by @cofin in `#30 <https://github.com/litestar-org/pytest-databases/pull/30>`_
* chore: documentation updates by @cofin in `#32 <https://github.com/litestar-org/pytest-databases/pull/32>`_


**Full Changelog**: `v0.3.1...v0.4.0 <https://github.com/litestar-org/pytest-databases/compare/v0.3.1...v0.4.0>`_


0.4.1 (2024-04-19)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: enabled codecov by @cofin in `#33 <https://github.com/litestar-org/pytest-databases/pull/33>`_


**Full Changelog**: `v0.4.0...v0.4.1 <https://github.com/litestar-org/pytest-databases/compare/v0.4.0...v0.4.1>`_


0.3.0 (2024-04-18)
------------------

What's Changed
~~~~~~~~~~~~~~
* build(deps): bump sqlparse from 0.4.4 to 0.5.0 in /requirements by @dependabot in `#27 <https://github.com/litestar-org/pytest-databases/pull/27>`_
* feat: split compose into multiple files by @cofin in `#28 <https://github.com/litestar-org/pytest-databases/pull/28>`_
* feat: support for Google AlloyDB Omni by @cofin in `#29 <https://github.com/litestar-org/pytest-databases/pull/29>`_


**Full Changelog**: `v0.2.5...v0.3.0 <https://github.com/litestar-org/pytest-databases/compare/v0.2.5...v0.3.0>`_


0.3.1 (2024-04-18)
------------------

What's Changed
~~~~~~~~~~~~~~
* fix: addresses an issue with the `alloydb omni` integration by @cofin in `#31 <https://github.com/litestar-org/pytest-databases/pull/31>`_


**Full Changelog**: `v0.3.0...v0.3.1 <https://github.com/litestar-org/pytest-databases/compare/v0.3.0...v0.3.1>`_


0.2.4 (2024-04-10)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: custom project name & parallel testing by @cofin in `#26 <https://github.com/litestar-org/pytest-databases/pull/26>`_


**Full Changelog**: `v0.2.3...v0.2.4 <https://github.com/litestar-org/pytest-databases/compare/v0.2.3...v0.2.4>`_


0.2.5 (2024-04-10)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: Add Elasticsearch support by @kedod in `#24 <https://github.com/litestar-org/pytest-databases/pull/24>`_


New Contributors
~~~~~~~~~~~~~~~~
* @kedod made their first contribution in `#24 <https://github.com/litestar-org/pytest-databases/pull/24>`_

**Full Changelog**: `v0.2.4...v0.2.5 <https://github.com/litestar-org/pytest-databases/compare/v0.2.4...v0.2.5>`_


0.2.3 (2024-04-09)
------------------

What's Changed
~~~~~~~~~~~~~~
* fix: set defaults for all env vars by @cofin in `#25 <https://github.com/litestar-org/pytest-databases/pull/25>`_


**Full Changelog**: `v0.2.2...v0.2.3 <https://github.com/litestar-org/pytest-databases/compare/v0.2.2...v0.2.3>`_


0.2.2 (2024-04-06)
------------------

What's Changed
~~~~~~~~~~~~~~
* feat: fixture now configured docker env variables. by @cofin in `#23 <https://github.com/litestar-org/pytest-databases/pull/23>`_


**Full Changelog**: `v0.2.1...v0.2.2 <https://github.com/litestar-org/pytest-databases/compare/v0.2.1...v0.2.2>`_


0.2.1 (2024-04-05)
------------------

What's Changed
~~~~~~~~~~~~~~
* fix(ci): build corrections by @cofin in `#22 <https://github.com/litestar-org/pytest-databases/pull/22>`_


**Full Changelog**: `v0.2.0...v0.2.1 <https://github.com/litestar-org/pytest-databases/compare/v0.2.0...v0.2.1>`_


0.2.0 (2024-04-04)
------------------

What's Changed
~~~~~~~~~~~~~~
* chore(docs): use Litestar branding by @cofin in `#19 <https://github.com/litestar-org/pytest-databases/pull/19>`_
* build(deps): bump actions/download-artifact from 3 to 4 by @dependabot in `#18 <https://github.com/litestar-org/pytest-databases/pull/18>`_
* chore(ci): enable license header requirement by @cofin in `#20 <https://github.com/litestar-org/pytest-databases/pull/20>`_
* feat: add support for `redis`, `keydb`, and `dragonfly` by @cofin in `#21 <https://github.com/litestar-org/pytest-databases/pull/21>`_


**Full Changelog**: `v0.1.0...v0.2.0 <https://github.com/litestar-org/pytest-databases/compare/v0.1.0...v0.2.0>`_


0.1.0 (2024-04-03)
------------------

What's Changed
~~~~~~~~~~~~~~

Initial Release


* feat: implements existing fixtures by @cofin in https://github.com/jolt-org/pytest-databases/pull/6
* build(deps): bump actions/download-artifact from 3 to 4 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/5
* build(deps): bump pypa/gh-action-pypi-publish from 1.6.4 to 1.8.14 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/4
* build(deps): bump softprops/action-gh-release from 1 to 2 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/3
* build(deps): bump actions/checkout from 3 to 4 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/2
* build(deps): bump actions/upload-artifact from 3 to 4 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/1
* fix(build): requirements update by @cofin in https://github.com/jolt-org/pytest-databases/pull/7
* build(deps): bump docker/setup-qemu-action from 2 to 3 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/9
* build(deps): bump pypa/cibuildwheel from 2.11.4 to 2.17.0 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/8
* feat: docs and build pipeline by @cofin in https://github.com/jolt-org/pytest-databases/pull/10
* feat: `mariadb` services and configurable database connections by @cofin in https://github.com/jolt-org/pytest-databases/pull/11
* feat(ci): build updates by @cofin in https://github.com/jolt-org/pytest-databases/pull/12
* build(deps): bump github/codeql-action from 2 to 3 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/17
* build(deps): bump actions/github-script from 6 to 7 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/16
* build(deps): bump actions/upload-artifact from 3 to 4 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/15
* build(deps): bump actions/setup-python from 4 to 5 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/14
* build(deps): bump dawidd6/action-download-artifact from 2 to 3 by @dependabot in https://github.com/jolt-org/pytest-databases/pull/13


New Contributors
~~~~~~~~~~~~~~~~
* @cofin made their first contribution in https://github.com/jolt-org/pytest-databases/pull/6
* @dependabot made their first contribution in https://github.com/jolt-org/pytest-databases/pull/5

**Full Changelog**: https://github.com/jolt-org/pytest-databases/commits/v0.1.0
