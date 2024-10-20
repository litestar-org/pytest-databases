# Pytest Databases

Reusable test fixtures for any and all databases.

<div align="center">

<!-- prettier-ignore-start -->

| Project   |     | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
|-----------|:----|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CI/CD     |     | [![Latest Release](https://github.com/litestar-org/pytest-databases/actions/workflows/release.yaml/badge.svg)](https://github.com/litestar-org/pytest-databases/actions/workflows/release.yaml) [![ci](https://github.com/litestar-org/pytest-databases/actions/workflows/ci.yaml/badge.svg)](https://github.com/litestar-org/pytest-databases/actions/workflows/ci.yaml) [![Documentation Building](https://github.com/litestar-org/pytest-databases/actions/workflows/docs.yaml/badge.svg?branch=main)](https://github.com/litestar-org/pytest-databases/actions/workflows/docs.yaml)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| Quality   |     | [![Coverage](https://codecov.io/github/litestar-org/pytest-databases/graph/badge.svg?token=vKez4Pycrc)](https://codecov.io/github/litestar-org/pytest-databases) [![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases) [![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases) [![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases) [![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=litestar-org_pytest-databases&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=litestar-org_pytest-databases)                                                                                                                                                                                                                                                                                                                               |
| Package   |     | [![PyPI - Version](https://img.shields.io/pypi/v/pytest-databases?labelColor=202235&color=edb641&logo=python&logoColor=edb641)](https://badge.fury.io/py/pytest-databases) ![PyPI - Support Python Versions](https://img.shields.io/pypi/pyversions/pytest-databases?labelColor=202235&color=edb641&logo=python&logoColor=edb641)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Community |     | [![Discord](https://img.shields.io/discord/919193495116337154?labelColor=202235&color=edb641&label=chat%20on%20discord&logo=discord&logoColor=edb641)](https://discord.gg/litestar-919193495116337154) [![Matrix](https://img.shields.io/badge/chat%20on%20Matrix-bridged-202235?labelColor=202235&color=edb641&logo=matrix&logoColor=edb641)](https://matrix.to/#/#litestar:matrix.org) [![Medium](https://img.shields.io/badge/Medium-202235?labelColor=202235&color=edb641&logo=medium&logoColor=edb641)](https://blog.litestar.dev) [![Twitter](https://img.shields.io/twitter/follow/LitestarAPI?labelColor=202235&color=edb641&logo=twitter&logoColor=edb641&style=flat)](https://twitter.com/LitestarAPI) [![Blog](https://img.shields.io/badge/Blog-litestar.dev-202235?logo=blogger&labelColor=202235&color=edb641&logoColor=edb641)](https://blog.litestar.dev)                                                                                                                                                                                                       |
| Meta      |     | [![Litestar Project](https://img.shields.io/badge/Litestar%20Org-%E2%AD%90%20Litestar-202235.svg?logo=python&labelColor=202235&color=edb641&logoColor=edb641)](https://github.com/litestar-org/pytest-databases) [![types - Mypy](https://img.shields.io/badge/types-Mypy-202235.svg?logo=python&labelColor=202235&color=edb641&logoColor=edb641)](https://github.com/python/mypy) [![License - MIT](https://img.shields.io/badge/license-MIT-202235.svg?logo=python&labelColor=202235&color=edb641&logoColor=edb641)](https://spdx.org/licenses/) [![Litestar Sponsors](https://img.shields.io/badge/Sponsor-%E2%9D%A4-%23edb641.svg?&logo=github&logoColor=edb641&labelColor=202235)](https://github.com/sponsors/litestar-org) [![linting - Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json&labelColor=202235)](https://github.com/astral-sh/ruff) [![code style - Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/format.json&labelColor=202235)](https://github.com/psf/black)|

<!-- prettier-ignore-end -->
</div>

> [!WARNING]
>
> Please note that pytest-databases is currently in a pre-release stage of development. This means the library is still under
> active development, and its initial API is subject to change. We encourage developers to experiment with pytest-databases and provide
> feedback, but we recommend against using it in production environments until a stable release is available.`

## About

The `pytest-databases` library aims to make testing with a database as simple as possible.
It is designed to offer pre-configured testing setups for many different types and versions of databases.

## Features

`pytest-databases` currently utilizes `docker compose` (or the legacy `docker-compose`) commands to manage the startup and shutdown of each database service. The following databases are currently available:

- **Postgres**: Version 12, 13, 14, 15, 16 and 17 are available
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

## Contributing

All [Litestar][litestar-org] projects will always be a community-centered, available for contributions of any size.

Before contributing, please review the [contribution guide][contributing].

If you have any questions, reach out to us on [Discord][discord], our org-wide [GitHub discussions][litestar-discussions] page,
or the [project-specific GitHub discussions page][project-discussions].

<hr>

<!-- markdownlint-disable -->
<p align="center">
  <!-- github-banner-start -->
  <img src="https://raw.githubusercontent.com/litestar-org/meta/2901c9c5c5895a83fbfa56944c33bca287f88d42/branding/SVG%20-%20Transparent/logo-full-wide.svg" alt="Litestar Logo - Light" width="20%" height="auto" />
  <br>A <a href="https://github.com/litestar-org">Litestar Organization</a> Project
  <!-- github-banner-end -->
</p>

[litestar-org]: https://github.com/litestar-org
[contributing]: https://docs.pytest-databases.litestar.dev/latest/contribution-guide.html
[discord]: https://discord.gg/litestar-919193495116337154
[litestar-discussions]: https://github.com/orgs/litestar-org/discussions
[project-discussions]: https://github.com/litestar-org/pytest-databases/discussions
[project-docs]: https://docs.pytest-databases.litestar.dev
[install-guide]: https://docs.pytest-databases.litestar.dev/latest/#installation
[newrepo]: https://github.com/organizations/litestar-org/repositories/new?template=pytest-databases
