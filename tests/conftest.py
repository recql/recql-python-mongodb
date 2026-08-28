"""MongoDB testbed — seeds demo data, exposes ``recql_testbed`` for core suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from recql.catalog import load_engine_catalog
from recql.testing import DOCUMENT_BACKEND_FEATURES, RecqlTestbed


DSN = os.environ.get(
    "RECQL_MONGODB_DSN",
    "mongodb://127.0.0.1:27018/recql?directConnection=true",
)


def _resolve_engine() -> Path:
    if os.environ.get("RECQL_ENGINE"):
        return Path(os.environ["RECQL_ENGINE"])
    local = Path(__file__).resolve().parents[1] / "testdata" / "engine.yaml"
    if local.is_file():
        return local
    pytest.skip("engine.yaml not found — set RECQL_ENGINE")


@pytest.fixture(scope="session")
async def recql_testbed():
    try:
        from examples.generator.catalog import build_demo_catalog
        from examples.generator.mongodb.load import load_catalog
    except ImportError:
        pytest.skip("recql-playground required for seeding")

    try:
        from recql_mongodb.db import create_client

        client, db = await create_client(DSN)
        await db.command("ping")
    except Exception:
        pytest.skip("MongoDB unavailable — run `make up` in this repo")
        return

    catalog_demo = build_demo_catalog(
        dims=8,
        with_als=True,
        with_lgbm=True,
        max_movies=100,
        max_ratings=4000,
        als_max_users=50,
        als_max_items=150,
        als_steps=5,
    )
    await load_catalog(db, catalog_demo)

    catalog = load_engine_catalog(_resolve_engine())
    from recql_mongodb import open_registry

    registry = await open_registry(catalog=catalog, pool=db)

    async def closer():
        client.close()

    bed = RecqlTestbed(
        backend="mongodb",
        registry=registry,
        catalog=catalog,
        dims=8,
        popular_rank_column="derived_popular_rank",
        features=DOCUMENT_BACKEND_FEATURES,
    )
    yield bed
    await closer()
