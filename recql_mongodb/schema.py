"""MongoDB operational collections from ``PaginationKvBinding`` (no fixed names)."""

from __future__ import annotations

from typing import Any

from recql.catalog.bindings import PaginationKvBinding

# Default search and vector index names if not specified in engine configuration
TEXT_VECTOR_INDEX = "recql_text_vector"
ALS_ITEM_VECTOR_INDEX = "recql_als_item_vector"
ALS_USER_VECTOR_INDEX = "recql_als_user_vector"
ITEMS_SEARCH_INDEX = "recql_items_text"


async def ensure_operational_collections(db: Any, *, kv: PaginationKvBinding | None = None) -> None:
    """Create RecQL operational collections and indexes when bindings allow."""
    binding = kv or PaginationKvBinding()
    names = await db.list_collection_names()

    if binding.ensure_table:
        kv_coll_name = (binding.from_sql or "pagination_seen").strip('"')
        if kv_coll_name not in names:
            await db.create_collection(kv_coll_name)
        kv_coll = db[kv_coll_name]
        await kv_coll.create_index(
            [(binding.key_column, 1), (binding.item_id_column, 1)], unique=True
        )
        await kv_coll.create_index([(binding.expires_at_column, 1)])

    if "artifact_registry" not in names:
        await db.create_collection("artifact_registry")
    await db.artifact_registry.create_index(
        [("kind", 1), ("name", 1), ("version", 1)], unique=True
    )
