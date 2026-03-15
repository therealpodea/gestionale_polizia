"""
Helper per caricare le impostazioni globali del dipartimento.
Da usare in tutti i router che rendono template con base.html.
"""
from __future__ import annotations

_cache: dict | None = None


async def get_settings() -> dict:
    """Carica le impostazioni dal DB (con cache in memoria)."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        from database import get_db
        db = get_db()
        s = await db["impostazioni"].find_one({"_id": "global"})
        _cache = s or {}
    except Exception:
        _cache = {}
    return _cache


def invalidate_cache():
    """Da chiamare dopo ogni salvataggio impostazioni."""
    global _cache
    _cache = None
