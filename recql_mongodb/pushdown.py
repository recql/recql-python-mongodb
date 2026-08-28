"""MongoDB prefilter pushdown capability matrix."""

from __future__ import annotations

from recql.language import ast as A
from recql.plugins.prefilter import (
    PrefilterShape,
    PushdownCapability,
    assert_pushdown_or_raise as _assert,
    classify_prefilter,
    supports_prefilter as _supports,
)

MONGODB_PUSHDOWN: dict[str, PushdownCapability] = {
    "filter": PushdownCapability(
        "filter",
        frozenset({PrefilterShape.ARBITRARY}),
        "Document filter expressions (trust engine-authored predicates).",
    ),
    "candidate_attributes": PushdownCapability(
        "candidate_attributes",
        frozenset({PrefilterShape.ARBITRARY}),
        "Same as filter retrieve.",
    ),
    "column_order": PushdownCapability(
        "column_order",
        frozenset(
            {
                PrefilterShape.EQUALITY,
                PrefilterShape.IN_LIST,
                PrefilterShape.AND_OR,
            }
        ),
        "Equality / IN / AND-OR only; ranges fail closed.",
    ),
    "text_search": PushdownCapability(
        "text_search",
        frozenset({PrefilterShape.EQUALITY, PrefilterShape.AND_OR}),
        "Equality conjuncts only in v1.",
    ),
    "similarity": PushdownCapability(
        "similarity",
        frozenset(),
        "No ANN+prefilter pushdown in v1; where= fails closed.",
    ),
    "candidate_ids": PushdownCapability(
        "candidate_ids",
        frozenset(),
        "IDs list is the selection; where= not supported.",
    ),
}


def supports_prefilter(retriever_type: str, expr: A.Expr | str | None) -> bool:
    return _supports(MONGODB_PUSHDOWN, retriever_type, expr)


def assert_pushdown_or_raise(retriever_type: str, expr: A.Expr | str | None) -> None:
    _assert(MONGODB_PUSHDOWN, retriever_type, expr)


__all__ = [
    "MONGODB_PUSHDOWN",
    "PrefilterShape",
    "PushdownCapability",
    "assert_pushdown_or_raise",
    "classify_prefilter",
    "supports_prefilter",
]
