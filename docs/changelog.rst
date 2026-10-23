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
* Under ``pytest-xdist`` with the default ``database`` isolation, ``bigquery_service`` starts one shared emulator and
  gives each worker its own dataset (``BigQueryService.dataset`` = ``test-dataset_<worker>``), instead of one
  emulator per worker with ``test-dataset``. Read the dataset from ``BigQueryService.dataset``.
* Under ``pytest-xdist`` with the default ``database`` isolation, Oracle services start one shared container per
  version and give each worker its own user, so ``OracleService.user`` is ``app_<worker>`` instead of ``app``. Set
  ``xdist_oracle_isolation_level`` to ``server`` for the previous container per worker.
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
* ``oracle_18c_connection``, ``oracle_23ai_connection``, ``oracle_startup_connection`` and ``oracle_responsive``;
  use ``oracle_service`` (or the versioned services) and open your own ``oracledb`` connection. Removal in 1.0.0.
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
