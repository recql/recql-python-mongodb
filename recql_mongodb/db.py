"""MongoDB / Motor helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse


def parse_mongodb_dsn(dsn: str) -> dict[str, Any]:
    """Parse ``mongodb://…/db`` (or ``mongodb+srv://…``) into Motor kwargs + db name."""
    raw = dsn.strip()
    if "://" not in raw:
        raw = "mongodb://" + raw
    parsed = urlparse(raw)
    db = (parsed.path or "/recql").lstrip("/") or "recql"
    # Drop path for Motor URI (db selected separately).
    if parsed.path:
        uri = raw[: raw.rfind(parsed.path)] + (f"?{parsed.query}" if parsed.query else "")
    else:
        uri = raw
    if parsed.username:
        # urlparse already decoded once; keep password as-is for Motor.
        pass
    return {
        "uri": uri,
        "db": unquote(db.split("?")[0]),
    }


async def create_client(dsn: str):
    """Return ``(AsyncIOMotorClient, AsyncIOMotorDatabase)``."""
    from motor.motor_asyncio import AsyncIOMotorClient

    parsed = parse_mongodb_dsn(dsn)
    client = AsyncIOMotorClient(parsed["uri"])
    return client, client[parsed["db"]]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 0 or nb <= 0:
        return 0.0
    return float(dot / (na * nb))


def as_float_vector(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    if hasattr(value, "tolist"):
        return [float(x) for x in value.tolist()]
    return [float(x) for x in value]
