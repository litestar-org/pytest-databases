Changelog
=========

All notable changes to this project will be documented in this file.

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
