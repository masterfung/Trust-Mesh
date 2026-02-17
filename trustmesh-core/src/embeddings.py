"""FTS5 full-text search for capsule retrieval — replaces ChromaDB with Zig kernel.

Uses SQLite FTS5 (BM25 keyword search) via libpodos for fast, low-memory capsule search.
The Zig kernel opens the same trustmesh.db as a second WAL-mode connection.
"""

import ctypes
import json
import os
from ctypes import c_uint32

_db_handle = None


def _get_lib():
    """Get the loaded libpodos library."""
    from src.timeline_bridge import _get_lib as _tl_get_lib
    return _tl_get_lib()


def init_fts(db_path: str | None = None) -> None:
    """Open the Zig-side SQLite connection and create the FTS5 table.

    Called once on startup. Opens the same trustmesh.db the Python side uses.
    """
    global _db_handle
    if _db_handle is not None:
        return  # Already initialized

    if db_path is None:
        db_path = os.getenv("TRUSTMESH_DB", "./trustmesh.db")

    lib = _get_lib()
    path_bytes = db_path.encode("utf-8")
    _db_handle = lib.podos_db_open(path_bytes, len(path_bytes))
    if not _db_handle:
        raise RuntimeError(f"Failed to open FTS5 database at {db_path}")


def _ensure_init():
    """Ensure FTS is initialized (lazy init for backward compat)."""
    if _db_handle is None:
        init_fts()


def upsert_capsule_embedding(
    capsule_id: str, text: str, metadata: dict | None = None, category: str = "general"
):
    """Index a capsule's text in the FTS5 table.

    Same signature as the old ChromaDB version for drop-in replacement.
    """
    _ensure_init()
    lib = _get_lib()

    # Extract title from "Title: content" format if present, else use full text
    title = ""
    content = text
    if ": " in text:
        parts = text.split(": ", 1)
        title = parts[0]
        content = parts[1]

    id_b = capsule_id.encode("utf-8")
    title_b = title.encode("utf-8")
    content_b = content.encode("utf-8")
    cat_b = (category or "general").encode("utf-8")

    rc = lib.podos_fts_upsert(
        _db_handle,
        id_b, len(id_b),
        title_b, len(title_b),
        content_b, len(content_b),
        cat_b, len(cat_b),
    )
    if rc < 0:
        raise RuntimeError(f"FTS5 upsert failed for {capsule_id}: {rc}")


def delete_capsule_embedding(capsule_id: str, category: str | None = None):
    """Remove a capsule from the FTS5 index.

    Category is ignored (FTS5 uses one flat table), but kept for API compat.
    """
    _ensure_init()
    lib = _get_lib()
    id_b = capsule_id.encode("utf-8")
    rc = lib.podos_fts_delete(_db_handle, id_b, len(id_b))
    if rc < 0:
        raise RuntimeError(f"FTS5 delete failed for {capsule_id}: {rc}")


def move_capsule_embedding(
    capsule_id: str, text: str, metadata: dict | None = None,
    old_category: str = "general", new_category: str = "general",
):
    """Move a capsule embedding — just re-upsert (FTS5 uses one flat table)."""
    upsert_capsule_embedding(capsule_id, text, metadata, new_category)


def search_capsules(
    query: str,
    accessible_ids: list[str],
    top_k: int = 5,
    categories: list[str] | None = None,
) -> list[str]:
    """Full-text search over accessible capsules using FTS5 BM25 ranking.

    Returns capsule IDs ranked by relevance to the query.
    Categories parameter is accepted for API compat but not used for filtering
    (FTS5 searches all capsules; trust filtering is via accessible_ids).
    """
    if not accessible_ids or not query or not query.strip():
        return []

    _ensure_init()
    lib = _get_lib()

    # Prepare the query for FTS5 MATCH — escape special chars
    safe_query = _sanitize_fts_query(query)
    if not safe_query:
        return []

    query_b = safe_query.encode("utf-8")
    ids_json = json.dumps(accessible_ids).encode("utf-8")

    # Allocate output buffer (16KB should be plenty)
    out_buf = ctypes.create_string_buffer(16384)
    out_len = c_uint32(0)

    rc = lib.podos_fts_search(
        _db_handle,
        query_b, len(query_b),
        ids_json, len(ids_json),
        top_k,
        out_buf, 16384,
        ctypes.byref(out_len),
    )

    if rc < 0:
        # Search failed (e.g., malformed query) — return empty rather than crash
        return []

    # Parse JSON result: [{"id":"...","rank":-1.23}, ...]
    result_json = out_buf.raw[:out_len.value].decode("utf-8")
    try:
        results = json.loads(result_json)
    except json.JSONDecodeError:
        return []

    return [r["id"] for r in results if "id" in r]


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5 MATCH syntax.

    FTS5 uses a query language where some characters are special.
    We convert the user query into a safe OR-joined keyword search.
    """
    # Split into words, strip non-alphanumeric (keep unicode letters)
    import re
    words = re.findall(r'\w+', query, re.UNICODE)
    if not words:
        return ""
    # Join with OR for broader matching (any word matches)
    return " OR ".join(words)


def reset_collections():
    """Reset the FTS5 table (for testing/seeding)."""
    _ensure_init()
    lib = _get_lib()
    rc = lib.podos_fts_reset(_db_handle)
    if rc < 0:
        raise RuntimeError(f"FTS5 reset failed: {rc}")


# Backward-compat alias
reset_collection = reset_collections


def close_fts():
    """Close the Zig-side DB connection. Called on shutdown."""
    global _db_handle
    if _db_handle is not None:
        lib = _get_lib()
        lib.podos_db_close(_db_handle)
        _db_handle = None
