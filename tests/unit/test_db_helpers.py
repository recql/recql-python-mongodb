"""MongoDB-specific helpers (DSN / cosine)."""

from __future__ import annotations

import pytest

from recql_mongodb.db import cosine_similarity, parse_mongodb_dsn


def test_parse_mongodb_dsn():
    kw = parse_mongodb_dsn("mongodb://127.0.0.1:27018/recql")
    assert kw["db"] == "recql"
    assert "27018" in kw["uri"]


def test_parse_mongodb_dsn_default_db():
    kw = parse_mongodb_dsn("mongodb://localhost:27017")
    assert kw["db"] == "recql"


def test_cosine_identical():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
