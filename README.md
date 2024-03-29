# pytest-databases

Reusable test fixtures for any and all databases.

<div align="center">

| Project   |     | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| --------- | :-- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CI/CD     |     | [![Latest Release](https://github.com/jolt-org/pytest-databases/actions/workflows/publish.yaml/badge.svg)](https://github.com/jolt-org/pytest-databases/actions/workflows/publish.yaml) [![Tests And Linting](https://github.com/jolt-org/pytest-databases/actions/workflows/ci.yaml/badge.svg)](https://github.com/jolt-org/pytest-databases/actions/workflows/ci.yaml) [![Documentation Building](https://github.com/jolt-org/pytest-databases/actions/workflows/docs.yaml/badge.svg)](https://github.com/jolt-org/pytest-databases/actions/workflows/docs.yaml)                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Quality   |     | [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=jolt-org_pytest-databases&metric=coverage)](https://sonarcloud.io/summary/new_code?id=jolt-org_pytest-databases) [![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=jolt-org_pytest-databases&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=jolt-org_pytest-databases) [![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=jolt-org_pytest-databases&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=jolt-org_pytest-databases) [![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=jolt-org_pytest-databases&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=jolt-org_pytest-databases) [![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=jolt-org_pytest-databases&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=jolt-org_pytest-databases)                            |
| Community |     | [![Discord](https://img.shields.io/discord/1149784127659319356?labelColor=F50057&color=202020&label=chat%20on%20discord&logo=discord&logoColor=202020)](https://discord.gg/XpFNTjjtTK)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Meta      |     | [![Jolt Project](https://img.shields.io/badge/Jolt%20Org-%E2%AD%90-F50057.svg?logo=python&labelColor=F50057&color=202020&logoColor=202020)](https://github.com/jolt-org/) [![types - Mypy](https://img.shields.io/badge/types-Mypy-F50057.svg?logo=python&labelColor=F50057&color=202020&logoColor=202020)](https://github.com/python/mypy) [![License - MIT](https://img.shields.io/badge/license-MIT-F50057.svg?logo=python&labelColor=F50057&color=202020&logoColor=202020)](https://spdx.org/licenses/) [![Jolt Sponsors](https://img.shields.io/badge/Sponsor-%E2%9D%A4-%23202020.svg?&logo=github&logoColor=202020&labelColor=F50057)](https://github.com/sponsors/jolt-org) [![linting - Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json&labelColor=F50057)](https://github.com/astral-sh/ruff) [![code style - Black](https://img.shields.io/badge/code%20style-black-000000.svg?logo=python&labelColor=F50057&logoColor=202020)](https://github.com/psf/black) |

</div>

> [!WARNING] > **Pre-Release Alpha Stage**
>
> Please note that pytest-databases is currently in a pre-release alpha stage of development. This means the library is still under
> active development, and its API is subject to change. We encourage developers to experiment with pytest-databases and provide
> feedback, but we recommend against using it in production environments until a stable release is available.`

## About

The `pytest-databases` library aims to make testing with a database as simple as possible.
It is designed to offer pre-configured testing setups for many different types and versions of databases.

## Features

`pytest-databases` currently utilizes `docker compose` (or the legacy `docker-compose`) commands to manage the startup and shutdown of each database service. The following databases are currently available:

- **Postgres**: Version 12, 13, 14, 15, and 16 are available
- **MySQL**: Version 5.6, 5.7 and 8 are available
- **Oracle**: Version 18c XE and 23C Free are available
- **SQL Server**: Version 2022 is available
- **Spanner**: The latest cloud-emulator from Google is available
- **Cockroach**: Version 23.1-latest is available

## Contributing

All [Jolt][jolt-org] projects will always be a community-centered, available for contributions of any size.

Before contributing, please review the [contribution guide][contributing].

If you have any questions, reach out to us on [Discord][discord], our org-wide [GitHub discussions][jolt-discussions] page,
or the [project-specific GitHub discussions page][project-discussions].

<hr>

<!-- markdownlint-disable -->
<p align="center">
  <!-- github-banner-start -->
  <img src="https://raw.githubusercontent.com/jolt-org/meta/2901c9c5c5895a83fbfa56944c33bca287f88d42/branding/SVG%20-%20Transparent/logo-full-wide.svg" alt="Litestar Logo - Light" width="20%" height="auto" />
  <br>A <a href="https://github.com/jolt-org">Jolt Organization</a> Project
  <!-- github-banner-end -->
</p>

[jolt-org]: https://github.com/jolt-org
[contributing]: https://docs.pytest-databases.jolt.rs/latest/contribution-guide.html
[discord]: https://discord.gg/XpFNTjjtTK
[jolt-discussions]: https://github.com/orgs/jolt-org/discussions
[project-discussions]: https://github.com/jolt-org/pytest-databases/discussions
[project-docs]: https://docs.pytest-databases.jolt.rs
[install-guide]: https://docs.pytest-databases.jolt.rs/latest/#installation
[newrepo]: https://github.com/organizations/jolt-org/repositories/new?template=pytest-databases
