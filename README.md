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

Ready-made database fixtures for your pytest tests.

## Features

- 🚀 Easy-to-use database fixtures
- 🔄 Support for multiple database types
- 🐳 Docker integration for isolated testing environments
- ⚡ Fast and efficient test execution
- 🔧 Highly configurable

`pytest-databases` uses the Docker Python SDK to manage the startup and shutdown of database services in containers. The following databases are currently available:

- **Postgres**: Version 12, 13, 14, 15, 16, 17 and 18 are available
- **MySQL**: Version 5.6, 5.7 and 8 are available
- **Oracle**: Version 18c XE and 23C Free are available
- **SQL Server**: Version 2022 is available
- **Google AlloyDB Omni**: Simplified Omni installation for easy testing.
- **Google Spanner**: The latest cloud-emulator from Google is available
- **Google BigQuery**: Unofficial BigQuery emulator
- **CockroachDB**: Version latest is available
- **Redis**: Latest version
- **Valkey**: Latest version
- **Dragonfly**: Latest version
- **KeyDB**: Latest version
- **Elasticsearch**: Version 7 and 8 are available
- **Azure blob storage**: Via azurite
- **Minio**: Latest version

## Installation

Quick install for postgres:

```bash
pip install pytest-databases[postgres]
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

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- The Litestar Framework team
- The pytest community
