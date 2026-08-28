"""Open a Motor client + RecQL plugin registry from a DSN."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from recql.catalog import EngineCatalog
from recql.plugins.base import PluginRegistry


async def open_connection(
    dsn: str,
    *,
    catalog: EngineCatalog | None = None,
    **kwargs: Any,
) -> tuple[PluginRegistry, Callable[[], Awaitable[None]]]:
    """Return ``(registry, close)`` for ``mongodb://…`` DSNs."""
    from recql_mongodb import open_registry
    from recql_mongodb.db import create_client

    client, db = await create_client(dsn)
    registry = await open_registry(catalog=catalog, pool=db, **kwargs)

    async def close() -> None:
        client.close()

    return registry, close
