"""MongoDB retrievers — collection find / in-process cosine (no SQL templates)."""

from __future__ import annotations

import re
from typing import Any

from recql.catalog.bindings import DataBindings
from recql.encode import encode_query
from recql.errors import ExecuteError
from recql.execute.merge import Candidate, RetrieveBag
from recql.language import ast as A
from recql.plugins.base import FilterPlugin, RetrieveRequest, Retriever
from recql.plugins.sql_common import attrs_dict, bindings_for_request, flatten_id_list, resolve_param
from recql_mongodb.db import as_float_vector
from recql_mongodb.pushdown import assert_pushdown_or_raise, supports_prefilter
from recql_mongodb.schema import (
    ALS_ITEM_VECTOR_INDEX,
    ITEMS_SEARCH_INDEX,
    TEXT_VECTOR_INDEX,
)

_attrs = attrs_dict
_resolve_param = resolve_param


def _bindings(req: RetrieveRequest) -> DataBindings:
    return bindings_for_request(req, default_backend="mongodb")


def _item_attrs(doc: dict[str, Any]) -> dict[str, Any]:
    raw = doc.get("attrs")
    if isinstance(raw, dict):
        return dict(raw)
    # Flatten common demo fields into attrs for scorers / filters.
    out = {k: v for k, v in doc.items() if k not in ("_id", "item_id", "embedding")}
    return _attrs(out) if not isinstance(out, dict) else out


class MongoDBColumnOrderRetriever(Retriever):
    def __init__(self, db: Any) -> None:
        self.db = db

    def supports_prefilter(self, expr: A.Expr | str | None) -> bool:
        return supports_prefilter("column_order", expr)

    async def retrieve(self, req: RetrieveRequest) -> RetrieveBag:
        step = req.step
        name = getattr(step, "name", None) or "column_order"
        limit = int(getattr(step, "limit", 100) or 100)
        where = getattr(step, "where", None)
        if where is not None:
            assert_pushdown_or_raise("column_order", where)
        bindings = _bindings(req)
        items = bindings.entity(req.entity_type)
        coll = self.db[(items.from_sql or "items").strip('"')]
        columns = getattr(step, "columns", None) or []
        sort: list[tuple[str, int]] = []
        for c in columns:
            cname = c.name if hasattr(c, "name") else c.get("name")
            asc = c.ascending if hasattr(c, "ascending") else c.get("ascending", True)
            if cname in (
                items.popular_rank_column,
                "_derived_popular_rank",
                "derived_popular_rank",
            ):
                col = items.popular_rank_column or "derived_popular_rank"
            elif cname in (items.created_at_column, "created_at"):
                col = items.created_at_column or "created_at"
            else:
                col = str(cname)
            sort.append((col, 1 if asc else -1))
        if not sort:
            sort = [("item_id", 1)]
        cursor = coll.find({}).sort(sort).limit(limit)
        docs = [doc async for doc in cursor]
        n = len(docs)
        return RetrieveBag(
            name=str(name),
            candidates=[
                Candidate(
                    id=str(d.get(items.id_column) or d.get("item_id")),
                    retrieval_score=float(n - i),
                    attributes=_item_attrs(d),
                )
                for i, d in enumerate(docs)
            ],
        )


class MongoDBFilterRetriever(Retriever):
    """Trust engine-authored Mongo filter dicts passed as ``where`` JSON/string."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def supports_prefilter(self, expr: A.Expr | str | None) -> bool:
        return supports_prefilter("filter", expr)

    async def retrieve(self, req: RetrieveRequest) -> RetrieveBag:
        step = req.step
        name = getattr(step, "name", None) or "filter"
        limit = int(getattr(step, "limit", 100) or 100)
        where = getattr(step, "where", None)
        bindings = _bindings(req)
        items = bindings.entity(req.entity_type)
        coll = self.db[(items.from_sql or "items").strip('"')]
        query: dict[str, Any] = {}
        if isinstance(where, dict):
            query = where
        elif isinstance(where, str) and where.strip() and where.strip() not in ("1=1", "TRUE"):
            # Minimal equality: field = 'value'
            m = re.match(r"^\s*(\w+)\s*=\s*'([^']*)'\s*$", where)
            if m:
                query = {m.group(1): m.group(2)}
        cursor = coll.find(query).limit(limit)
        docs = [doc async for doc in cursor]
        n = len(docs)
        return RetrieveBag(
            name=str(name),
            candidates=[
                Candidate(
                    id=str(d.get(items.id_column) or d.get("item_id")),
                    retrieval_score=float(n - i),
                    attributes=_item_attrs(d),
                )
                for i, d in enumerate(docs)
            ],
        )


class MongoDBCandidateIdsRetriever(Retriever):
    def __init__(self, db: Any) -> None:
        self.db = db

    def supports_prefilter(self, expr: A.Expr | str | None) -> bool:
        return supports_prefilter("candidate_ids", expr)

    async def retrieve(self, req: RetrieveRequest) -> RetrieveBag:
        step = req.step
        name = getattr(step, "name", None) or "candidate_ids"
        raw = (
            getattr(step, "item_ids", None)
            or getattr(step, "ids", None)
            or getattr(step, "candidate_ids", None)
            or []
        )
        flat = flatten_id_list(raw, req.params or {})
        limit = getattr(step, "limit", None)
        if limit is not None:
            flat = flat[: int(limit)]
        if not flat:
            return RetrieveBag(name=str(name), candidates=[])
        bindings = _bindings(req)
        items = bindings.entity(req.entity_type)
        id_col = items.id_column or "item_id"
        coll = self.db[(items.from_sql or "items").strip('"')]
        docs = {
            str(d.get(id_col)): d
            async for d in coll.find({id_col: {"$in": flat}})
        }
        cands: list[Candidate] = []
        for i, eid in enumerate(flat):
            d = docs.get(eid)
            if d is None:
                continue
            cands.append(
                Candidate(
                    id=eid,
                    retrieval_score=float(len(flat) - i),
                    attributes=_item_attrs(d),
                )
            )
        return RetrieveBag(name=str(name), candidates=cands)


class MongoDBSimilarityRetriever(Retriever):
    def __init__(self, db: Any, *, dims: int = 8) -> None:
        self.db = db
        self.dims = dims

    def supports_prefilter(self, expr: A.Expr | str | None) -> bool:
        return supports_prefilter("similarity", expr)

    async def retrieve(self, req: RetrieveRequest) -> RetrieveBag:
        step = req.step
        name = getattr(step, "name", None) or "similarity"
        limit = int(getattr(step, "limit", 100) or 100)
        where = getattr(step, "where", None)
        if where is not None:
            assert_pushdown_or_raise("similarity", where)
        bindings = _bindings(req)
        emb_ref = getattr(step, "embedding_ref", None) or "als"
        enc = getattr(step, "query_encoder", None)
        etype = getattr(enc, "type", None) if enc is not None else None

        qvec: list[float] | None = None
        exclude_id: str | None = None
        if etype == "precomputed_user":
            uid = str(_resolve_param(enc.input_user_id, req.params or {}))
            doc = await self.db.als_user_embeddings.find_one({"user_id": uid})
            if doc is None:
                return RetrieveBag(name=str(name), candidates=[])
            qvec = as_float_vector(doc.get("embedding"))
            search_coll = self.db.als_item_embeddings
            index_name = ALS_ITEM_VECTOR_INDEX
            id_field = "item_id"
        elif etype == "precomputed_item":
            iid = str(_resolve_param(enc.input_item_id, req.params or {}))
            exclude_id = iid
            doc = await self.db.als_item_embeddings.find_one({"item_id": iid})
            if doc is None:
                return RetrieveBag(name=str(name), candidates=[])
            qvec = as_float_vector(doc.get("embedding"))
            search_coll = self.db.als_item_embeddings
            index_name = ALS_ITEM_VECTOR_INDEX
            id_field = "item_id"
        else:
            raise ExecuteError(f"encoder type {etype} not implemented yet")

        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": "embedding",
                    "queryVector": qvec,
                    "numCandidates": max(limit * 20, 100),
                    "limit": limit + (1 if exclude_id else 0),
                }
            },
            {
                "$project": {
                    id_field: 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        scored: list[tuple[str, float]] = []
        async for doc in search_coll.aggregate(pipeline):
            eid = str(doc.get(id_field))
            if exclude_id is not None and eid == exclude_id:
                continue
            scored.append((eid, float(doc.get("score") or 0.0)))
            if len(scored) >= limit:
                break
        items = bindings.entity(req.entity_type)
        item_coll = self.db[(items.from_sql or "items").strip('"')]
        id_col = items.id_column or "item_id"
        by_id = {
            str(d.get(id_col)): d
            async for d in item_coll.find({id_col: {"$in": [e for e, _ in scored]}})
        }
        return RetrieveBag(
            name=str(name),
            candidates=[
                Candidate(
                    id=eid,
                    retrieval_score=score,
                    attributes=_item_attrs(by_id.get(eid, {})),
                )
                for eid, score in scored
            ],
        )


class MongoDBTextSearchRetriever(Retriever):
    def __init__(self, db: Any, *, encoder=None) -> None:
        self.db = db
        self.encoder = encoder

    def supports_prefilter(self, expr: A.Expr | str | None) -> bool:
        return supports_prefilter("text_search", expr)

    async def retrieve(self, req: RetrieveRequest) -> RetrieveBag:
        step = req.step
        name = getattr(step, "name", None) or "text_search"
        limit = int(getattr(step, "limit", 100) or 100)
        where = getattr(step, "where", None)
        if where is not None:
            assert_pushdown_or_raise("text_search", where)
        bindings = _bindings(req)
        items = bindings.entity(req.entity_type)
        q = str(_resolve_param(getattr(step, "input_text_query", ""), req.params or {}))
        mode = step.mode
        mtype = getattr(mode, "type", None) or (
            mode.get("type") if isinstance(mode, dict) else None
        )
        item_coll = self.db[(items.from_sql or "items").strip('"')]
        id_col = items.id_column or "item_id"

        if mtype == "vector":
            ref = getattr(mode, "text_embedding_ref", None) or (
                mode.get("text_embedding_ref") if isinstance(mode, dict) else None
            )
            ref = ref or "content_embedding"
            qvec = list(encode_query(q, encoder=self.encoder))
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": TEXT_VECTOR_INDEX,
                        "path": "embedding",
                        "queryVector": qvec,
                        "numCandidates": max(limit * 20, 100),
                        "limit": limit,
                        "filter": {"embedding_name": str(ref)},
                    }
                },
                {
                    "$project": {
                        "entity_id": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
            ]
            scored = [
                (str(doc.get("entity_id")), float(doc.get("score") or 0.0))
                async for doc in self.db.text_embeddings.aggregate(pipeline)
            ]
            by_id = {
                str(d.get(id_col)): d
                async for d in item_coll.find({id_col: {"$in": [e for e, _ in scored]}})
            }
            return RetrieveBag(
                name=str(name),
                candidates=[
                    Candidate(
                        id=eid,
                        retrieval_score=score,
                        attributes=_item_attrs(by_id.get(eid, {})),
                    )
                    for eid, score in scored
                ],
            )

        # Lexical: MongoDB Search ($search) over lucene-mapped text fields.
        pipeline = [
            {
                "$search": {
                    "index": ITEMS_SEARCH_INDEX,
                    "text": {
                        "query": q,
                        "path": ["search_text", "title", "description"],
                    },
                }
            },
            {"$limit": limit},
            {
                "$project": {
                    id_col: 1,
                    "attrs": 1,
                    "search_text": 1,
                    "title": 1,
                    "description": 1,
                    "genre": 1,
                    "derived_popular_rank": 1,
                    "created_at": 1,
                    "score": {"$meta": "searchScore"},
                }
            },
        ]
        docs = [doc async for doc in item_coll.aggregate(pipeline)]
        return RetrieveBag(
            name=str(name),
            candidates=[
                Candidate(
                    id=str(d.get(id_col)),
                    retrieval_score=float(d.get("score") or 0.0),
                    attributes=_item_attrs(d),
                )
                for d in docs
            ],
        )


class MongoDBPrebuiltFilter(FilterPlugin):
    """``exclude_seen`` via interactions collection."""

    def __init__(self, db: Any, *, bindings: DataBindings) -> None:
        self.db = db
        self.bindings = bindings

    async def apply(self, step, rows, ctx):
        ref = getattr(step, "filter_ref", "") or ""
        filt = self.bindings.personal_filter(ref)
        if filt is None:
            return rows
        params = ctx.get("params") or {}
        uid = resolve_param(getattr(step, "input_user_id", None), params)
        if uid is None:
            return rows
        coll_name = (filt.from_sql or "interactions").strip('"')
        # Query-shaped from_sql from SQL packs may appear; use interactions.
        if "(" in coll_name or " " in coll_name:
            coll_name = "interactions"
        user_col = filt.user_id_column or "user_id"
        item_col = filt.item_id_column or "item_id"
        banned = {
            str(d.get(item_col))
            async for d in self.db[coll_name].find({user_col: str(uid)}, {item_col: 1})
        }
        return [c for c in rows if c.id not in banned]
