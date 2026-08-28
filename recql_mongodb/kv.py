"""MongoDB pagination KV (seen-item exclusion)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from recql.catalog.bindings import PaginationKvBinding
from recql.plugins.base import KvStore
from recql_mongodb.schema import ensure_operational_collections


class MongoDBKvStore(KvStore):
    def __init__(self, db: Any, *, binding: PaginationKvBinding | None = None) -> None:
        self.db = db
        self.binding = binding or PaginationKvBinding()
        self._ensured = False

    async def _ensure(self) -> None:
        if self._ensured:
            return
        await ensure_operational_collections(self.db, kv=self.binding)
        self._ensured = True

    def _coll(self):
        # Fixture / engine default table name maps to collection.
        name = (self.binding.from_sql or "pagination_seen").strip('"')
        return self.db[name]

    async def load_seen(self, key: str) -> set[str]:
        await self._ensure()
        b = self.binding
        now = datetime.now(timezone.utc)
        cursor = self._coll().find(
            {b.key_column: key, b.expires_at_column: {"$gt": now}},
            {b.item_id_column: 1},
        )
        return {str(doc[b.item_id_column]) async for doc in cursor}

    async def remember(self, key: str, ids: list[str], ttl: int) -> None:
        if not ids:
            return
        await self._ensure()
        b = self.binding
        expires = datetime.now(timezone.utc) + timedelta(seconds=int(ttl))
        coll = self._coll()
        for iid in ids:
            await coll.update_one(
                {b.key_column: key, b.item_id_column: iid},
                {"$set": {b.expires_at_column: expires}},
                upsert=True,
            )
