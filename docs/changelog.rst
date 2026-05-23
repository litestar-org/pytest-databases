Changelog
=========

All notable changes to this project will be documented in this file.

0.19.0
------

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
