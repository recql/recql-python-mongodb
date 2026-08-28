"""MongoDB model scorer — load Binary blob once, predict on hot path."""

from __future__ import annotations

import json
from typing import Any

from bson.binary import Binary

from recql.artifacts import (
    check_feature_spec_compat,
    pins_from_deployment,
    resolve_version,
)
from recql.catalog.bindings import DataBindings, default_fixture_bindings
from recql.errors import ExecuteError
from recql.execute.merge import Candidate
from recql.expr import ExpressionScorer
from recql.plugins.base import Scorer
from recql.scoring import click_through_rate_features, load_lgbm_booster, predict_lgbm


class LoadedModel:
    __slots__ = ("name", "version", "booster", "feature_spec")

    def __init__(self, *, name: str, version: str, booster: Any, feature_spec: dict) -> None:
        self.name = name
        self.version = version
        self.booster = booster
        self.feature_spec = feature_spec


class MongoDBModelScorer(Scorer):
    def __init__(self, db: Any, *, catalog=None, bindings: DataBindings | None = None) -> None:
        self.db = db
        self.catalog = catalog
        self.bindings = bindings or (
            catalog.bindings()
            if catalog is not None
            else default_fixture_bindings(backend="mongodb")
        )
        self._expr = ExpressionScorer()
        self._loaded: dict[tuple[str, str], LoadedModel] = {}

    def _pinned_version(self, name: str) -> str:
        pins = pins_from_deployment(
            self.catalog.deployment if self.catalog is not None else None
        )
        return resolve_version(name, pins, fallback="v1")

    async def warm(self, names: list[str] | None = None) -> list[str]:
        if names is None:
            names = list(self.catalog.models.keys()) if self.catalog is not None else []
        out = []
        for name in names:
            version = self._pinned_version(name)
            await self._ensure_loaded(name, version)
            out.append(f"{name}@{version}")
        return out

    async def _ensure_loaded(self, name: str, version: str) -> LoadedModel:
        key = (name, version)
        if key in self._loaded:
            return self._loaded[key]
        store = self.bindings.models
        coll = self.db[(store.from_sql or "models").strip('"')]
        name_col = store.name_column or "name"
        doc = await coll.find_one({name_col: name, "version": version})
        if doc is None:
            doc = await coll.find_one({name_col: name}, sort=[("created_at", -1)])
        if doc is None or doc.get(store.blob_column or "blob") is None:
            raise ExecuteError(f"missing ranking model artifact: {name} version={version}")
        found_ver = str(doc.get("version"))
        if found_ver != version:
            raise ExecuteError(
                f"model version pin mismatch for {name}: wanted {version}, found {found_ver}"
            )
        spec = doc.get(store.feature_spec_column or "feature_spec") or {}
        if isinstance(spec, (bytes, bytearray, Binary)):
            spec = bytes(spec).decode("utf-8")
        if isinstance(spec, str):
            spec = json.loads(spec)
        blob = doc[store.blob_column or "blob"]
        if isinstance(blob, Binary):
            blob = bytes(blob)
        booster = load_lgbm_booster(bytes(blob))
        loaded = LoadedModel(
            name=name,
            version=version,
            booster=booster,
            feature_spec=dict(spec or {}),
        )
        self._loaded[key] = loaded
        return loaded

    async def score_many(
        self, plan: Any, candidates: list[Candidate], ctx: dict[str, Any]
    ) -> list[float]:
        vm = getattr(plan, "value_model", None) or ""
        if vm and all(c.isalnum() or c == "_" for c in vm):
            version = self._pinned_version(vm)
            model = await self._ensure_loaded(vm, version)
            expected = None
            if self.catalog is not None:
                m = self.catalog.model(vm)
                if m is not None:
                    expected = (m.raw or {}).get("feature_spec")
            check_feature_spec_compat(expected, model.feature_spec)
            feats = [click_through_rate_features(c) for c in candidates]
            return predict_lgbm(model.booster, feats)
        return await self._expr.score_many(plan, candidates, ctx)
