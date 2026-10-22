<!-- markdownlint-disable no-inline-html -->
<!-- prettier-ignore-start -->
<div align="center">

| Project   |     | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| --------- | :-- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CI/CD     |     | [![Latest Release](https://github.com/litestar-org/pytest-databases/actions/workflows/release.yaml/badge.svg)](https://github.com/litestar-org/pytest-databases/actions/workflows/release.yaml) [![ci](https://github.com/litestar-org/pytest-databases/actions/workflows/ci.yaml/badge.svg)](https://github.com/litestar-org/pytest-databases/actions/workflows/ci.yaml) [![Documentation Building](https://github.com/litestar-org/pytest-databases/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/litestar-org/pytest-databases/actions/workflows/docs.yml)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Quality   |     | [![Coverage](https://codecov.io/github/litestar-org/pytest-databases/graph/badge.svg?token=vKez4Pycrc)](https://codecov.io/github/litestar-org/pytest-databases) [![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases) [![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases) [![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases) [![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases)                                                                                           |
| Package   |     | [![PyPI - Version](https://img.shields.io/pypi/v/pytest-databases?labelColor=202235&color=edb641&logo=python&logoColor=edb641)](https://badge.fury.io/py/pytest-databases) ![PyPI - Support Python Versions](https://img.shields.io/pypi/pyversions/pytest-databases?labelColor=202235&color=edb641&logo=python&logoColor=edb641)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Community |     | [![Discord](https://img.shields.io/discord/919193495116337154?labelColor=202235&color=edb641&label=chat%20on%20discord&logo=discord&logoColor=edb641)](https://discord.gg/litestar-919193495116337154) [![Matrix](https://img.shields.io/badge/chat%20on%20Matrix-bridged-202235?labelColor=202235&color=edb641&logo=matrix&logoColor=edb641)](https://matrix.to/#/#litestar:matrix.org) [![Medium](https://img.shields.io/badge/Medium-202235?labelColor=202235&color=edb641&logo=medium&logoColor=edb641)](https://blog.litestar.dev) [![Twitter](https://img.shields.io/twitter/follow/LitestarAPI?labelColor=202235&color=edb641&logo=twitter&logoColor=edb641&style=flat)](https://twitter.com/LitestarAPI) [![Blog](https://img.shields.io/badge/Blog-litestar.dev-202235?logo=blogger&labelColor=202235&color=edb641&logoColor=edb641)](https://blog.litestar.dev)                                                                                                                                                                                                                                                 |
| Meta      |     | [![Litestar Project](https://img.shields.io/badge/Litestar%20Org-%E2%AD%90%20Litestar-202235.svg?logo=python&labelColor=202235&color=edb641&logoColor=edb641)](https://github.com/litestar-org/pytest-databases) [![types - Mypy](https://img.shields.io/badge/types-Mypy-202235.svg?logo=python&labelColor=202235&color=edb641&logoColor=edb641)](https://github.com/python/mypy) [![License - MIT](https://img.shields.io/badge/license-MIT-202235.svg?logo=python&labelColor=202235&color=edb641&logoColor=edb641)](https://spdx.org/licenses/) [![Litestar Sponsors](https://img.shields.io/badge/Sponsor-%E2%9D%A4-%23edb641.svg?&logo=github&logoColor=edb641&labelColor=202235)](https://github.com/sponsors/litestar-org) [![linting - Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json&labelColor=202235)](https://github.com/astral-sh/ruff) [![code style - Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/format.json&labelColor=202235)](https://github.com/psf/black) |

</div>

# Pytest Databases

Ready-made database and cloud emulator fixtures for your pytest tests.

## Features

- 🚀 Clientless container fixtures with zero required database driver dependencies in the base package
- 🔄 Support for 20+ relational, NoSQL, analytical, streaming, and cloud emulator services
- 🐳 Docker and Podman runtime support with deterministic session ownership and `pytest-xdist` isolation
- ⚡ Fast readiness checks using standard library probes and in-container CLI tools
- 🔧 Configurable via pytest CLI options, `pyproject.toml`, and environment variables

`pytest-databases` manages the startup and shutdown of database and cloud emulator services in Docker or Podman containers. The following services are available:

- **PostgreSQL / pgvector / ParadeDB**: PostgreSQL 12–18, pgvector, and ParadeDB
- **Google AlloyDB Omni**: PostgreSQL 15–18 compatible AlloyDB Omni
- **MySQL**: MySQL 5.6, 5.7, 8.0, 8.4 LTS, 9.6, and 9.7
- **MariaDB**: MariaDB 11.3, 11.4 LTS, 11.8 LTS, 12.2, 12.3, and 13.0
- **Dolt**: Versioned MySQL-compatible database
- **Oracle Database**: Oracle 18c XE, 23ai Free, and Autonomous Database Free (23ai) with TLS/mTLS wallet extraction
- **Microsoft SQL Server**: SQL Server 2022 and 2025
- **IBM Db2**: Db2 Community Edition (`icr.io/db2_community/db2`)
- **Google Cloud Spanner**: Cloud Spanner emulator
- **Google BigQuery**: BigQuery emulator (`goccy/bigquery-emulator`)
- **Snowflake (Embucket)**: Embucket Snowflake-compatible SQL and Iceberg emulator
- **CockroachDB**: Distributed SQL database
- **YugabyteDB**: Distributed PostgreSQL-compatible database
- **MongoDB**: Document database
- **GizmoSQL**: Apache Arrow Flight SQL service (DuckDB & SQLite backends)
- **Redis / Valkey / Dragonfly / KeyDB**: In-memory key-value stores
- **Elasticsearch**: Elasticsearch 7, 8, and 9
- **Azure Blob Storage**: Azurite emulator
- **MinIO & RustFS**: S3-compatible object storage
- **Redpanda**: Kafka-compatible streaming platform
- **LocalStack**: AWS cloud service emulator (S3, SQS, SNS, DynamoDB, Secrets Manager, KMS, EventBridge, Kinesis)
- **Google Cloud Pub/Sub**: Cloud Pub/Sub emulator
- **RabbitMQ**: RabbitMQ 4.3 AMQP and Management HTTP broker
- **Floci Cloud Emulators**: Lightweight single-port emulators for GCP (`gcs_service`), OCI, AWS, and Azure

## Installation

```bash
pip install pytest-databases
```

## Quick Start

- Add to your pytest `conftest.py`:

```py
pytest_plugins = ["pytest_databases.docker.postgres"]
```

- Use in your tests:

```python
from pytest_databases.docker.postgres import PostgresService
import psycopg

def test_one(postgres_service: PostgresService) -> None:
    with psycopg.connect(
        f"postgresql://{postgres_service.user}:{postgres_service.password}@{postgres_service.host}:{postgres_service.port}/{postgres_service.database}",
        autocommit=True,
    ) as conn:
        result = conn.execute("SELECT 1")
        assert result
```

## Documentation

Full documentation is available at [https://litestar-org.github.io/pytest-databases/latest/](https://litestar-org.github.io/pytest-databases/latest/)

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.rst) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- The Litestar Framework team
- The pytest community
