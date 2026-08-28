"""MongoDB plugin pack — document store with native Search / Vector Search (8.2+).

Uses ``$search`` and ``$vectorSearch`` (mongot). No SQL dialect — see
``DOCUMENT_BACKEND_FEATURES``.
"""

from __future__ import annotations

from typing import Any

from recql.plugins.base import PluginRegistry
from recql.testing.features import DOCUMENT_BACKEND_FEATURES
from recql_mongodb.registry import mongodb_registry

__all__ = [
    "DOCUMENT_BACKEND_FEATURES",
    "mongodb_registry",
    "open_registry",
]


async def open_registry(
    *,
    catalog=None,
    pool=None,
    connection=None,
    plugin_cfg: dict[str, Any] | None = None,
    **kwargs: Any,
) -> PluginRegistry:
    """Entry-point adapter for ``recql.backends`` (called by core factory)."""
    handle = pool if pool is not None else connection
    if handle is None:
        raise ValueError("mongodb backend requires pool= or connection= (Motor database)")
    return await mongodb_registry(
        handle, catalog=catalog, plugin_cfg=plugin_cfg, **kwargs
    )
