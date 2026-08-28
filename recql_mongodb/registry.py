"""Assemble the MongoDB PluginRegistry."""

from __future__ import annotations

from typing import Any

from recql.catalog.bindings import DataBindings, bindings_from_catalog, default_fixture_bindings
from recql.encode import get_encoder, warm_encoders_for_catalog
from recql.plugins.base import PluginRegistry
from recql.plugins.mock import MockExpressionFilter, MockScorer
from recql_mongodb.kv import MongoDBKvStore
from recql_mongodb.retrievers import (
    MongoDBCandidateIdsRetriever,
    MongoDBColumnOrderRetriever,
    MongoDBFilterRetriever,
    MongoDBPrebuiltFilter,
    MongoDBSimilarityRetriever,
    MongoDBTextSearchRetriever,
)
from recql_mongodb.schema import ensure_operational_collections
from recql_mongodb.scorer import MongoDBModelScorer


def _dims_from_catalog(catalog, *, default: int = 8) -> int:
    if catalog is None:
        return default
    embeddings = getattr(catalog, "embeddings", None) or {}
    for preferred in ("content_embedding", "title_embedding"):
        emb = embeddings.get(preferred)
        if emb is not None and getattr(emb, "dims", None):
            return int(emb.dims)
    for emb in embeddings.values():
        if getattr(emb, "dims", None):
            return int(emb.dims)
    return default


async def mongodb_registry(
    handle,
    *,
    catalog=None,
    plugin_cfg: dict[str, Any] | None = None,
    dims: int | None = None,
    bindings: DataBindings | None = None,
    warm_models: bool = True,
    **_kwargs: Any,
) -> PluginRegistry:
    cfg = dict(plugin_cfg or {})
    db = handle
    resolved = bindings or (
        bindings_from_catalog(catalog)
        if catalog is not None
        else default_fixture_bindings(backend="mongodb")
    )
    if dims is None:
        dims = _dims_from_catalog(catalog, default=8)
    encode_backend = str(cfg.get("encode_backend") or "fake")
    warmed = warm_encoders_for_catalog(catalog, backend=encode_backend, dims=dims)
    encoder = warmed[0] if warmed else get_encoder(backend=encode_backend, dims=dims, warm=True)

    await ensure_operational_collections(db, kv=resolved.pagination_kv)

    col = MongoDBColumnOrderRetriever(db)
    filt = MongoDBFilterRetriever(db)
    ids = MongoDBCandidateIdsRetriever(db)
    sim = MongoDBSimilarityRetriever(db, dims=dims)
    text = MongoDBTextSearchRetriever(db, encoder=encoder)
    model_scorer = MongoDBModelScorer(db, catalog=catalog, bindings=resolved)

    registry = PluginRegistry(
        retrievers={
            "column_order": col,
            "filter": filt,
            "candidate_ids": ids,
            "candidate_attributes": filt,
            "text_search": text,
            "similarity": sim,
        },
        scorers={"score_ensemble": model_scorer, "passthrough": MockScorer()},
        reorderers={},
        filters={
            "expression": MockExpressionFilter(),
            "prebuilt": MongoDBPrebuiltFilter(db, bindings=resolved),
            "truncate": MockExpressionFilter(),
        },
        kv=MongoDBKvStore(db, binding=resolved.pagination_kv),
    )
    registry._recql_bindings = resolved  # type: ignore[attr-defined]
    registry._recql_catalog = catalog  # type: ignore[attr-defined]
    registry._recql_encoder = encoder  # type: ignore[attr-defined]
    registry._recql_plugin_cfg = cfg  # type: ignore[attr-defined]
    registry._recql_model_scorer = model_scorer  # type: ignore[attr-defined]
    registry._recql_db = db  # type: ignore[attr-defined]
    if warm_models and catalog is not None and catalog.models:
        try:
            await model_scorer.warm()
        except Exception:
            pass
    return registry
