"""Litestar Asyncpg

This example demonstrates how to use a Asyncpg database in a Litestar application.

The example uses the `SQLSpec` extension to create a connection to a Asyncpg database.

The Asyncpg database also demonstrates how to use the plugin loader and `secrets` configuration manager built into SQLSpec.
"""
# /// script
# dependencies = [
#   "sqlspec[psycopg,asyncpg,performance]",
#   "litestar[standard]",
# ]
# ///

from typing import Annotated, Optional

from litestar import Litestar, get
from litestar.params import Dependency
from sqlspec.adapters.asyncpg import AsyncpgConfig, AsyncpgDriver, AsyncpgPoolConfig
from sqlspec.extensions.litestar import DatabaseConfig, SQLSpec, providers
from sqlspec.filters import FilterTypes


@get(
    "/",
    dependencies=providers.create_filter_dependencies({"search": "greeting", "search_ignore_case": True}),
)
async def simple_asyncpg(
    db_session: AsyncpgDriver, filters: Annotated[list[FilterTypes], Dependency(skip_validation=True)]
) -> Optional[dict[str, str]]:
    return await db_session.select_one_or_none(
        "SELECT greeting FROM (select 'Hello, world!' as greeting) as t", *filters
    )


sqlspec = SQLSpec(
    config=[
        DatabaseConfig(
            config=AsyncpgConfig(
                pool_config=AsyncpgPoolConfig(dsn="postgres://app:app@localhost:15432/app", min_size=1, max_size=3),
            ),
            commit_mode="autocommit",
        )
    ]
)
app = Litestar(route_handlers=[simple_asyncpg], plugins=[sqlspec])

if __name__ == "__main__":
    import os

    from litestar.cli import litestar_group

    os.environ["LITESTAR_APP"] = "sqlapp:app"

    litestar_group()
