"""ChromaDB vector store for semantic capsule retrieval — category-scoped collections."""

import re

import chromadb

_client: chromadb.ClientAPI | None = None
_collections: dict[str, chromadb.Collection] = {}


def get_client() -> chromadb.ClientAPI:
    """Get or create the ChromaDB client (persistent, in-process)."""
    global _client
    if _client is None:
        _client = chromadb.Client()  # In-memory for hackathon; swap to PersistentClient for prod
    return _client


def _sanitize_category(category: str) -> str:
    """Normalize category to a valid ChromaDB collection name suffix."""
    if not category:
        return "general"
    # Lowercase, keep only alphanum and underscores
    sanitized = re.sub(r"[^a-z0-9_]", "_", category.lower()).strip("_")
    return sanitized or "general"


def get_collection(category: str = "general") -> chromadb.Collection:
    """Get or create a category-scoped collection."""
    suffix = _sanitize_category(category)
    name = f"trustmesh_{suffix}"
    if name not in _collections:
        client = get_client()
        _collections[name] = client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collections[name]


def upsert_capsule_embedding(
    capsule_id: str, text: str, metadata: dict | None = None, category: str = "general"
):
    """Embed and store a capsule's text in the category-scoped ChromaDB collection.

    ChromaDB uses its default embedding function (all-MiniLM-L6-v2)
    which runs locally — no API calls needed.
    """
    collection = get_collection(category)
    meta = metadata or {}
    # ChromaDB only accepts str/int/float/bool values in metadata
    clean_meta = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}
    collection.upsert(ids=[capsule_id], documents=[text], metadatas=[clean_meta])


def delete_capsule_embedding(capsule_id: str, category: str | None = None):
    """Remove a capsule from the vector store.

    If category is given, delete from that specific collection.
    If None, try all cached collections.
    """
    if category is not None:
        collection = get_collection(category)
        try:
            collection.delete(ids=[capsule_id])
        except Exception:
            pass
    else:
        for collection in _collections.values():
            try:
                collection.delete(ids=[capsule_id])
            except Exception:
                pass


def move_capsule_embedding(
    capsule_id: str, text: str, metadata: dict | None = None,
    old_category: str = "general", new_category: str = "general",
):
    """Move a capsule embedding from one category collection to another."""
    if _sanitize_category(old_category) == _sanitize_category(new_category):
        # Same collection — just upsert in place
        upsert_capsule_embedding(capsule_id, text, metadata, new_category)
        return
    # Upsert to new collection first, then delete from old
    upsert_capsule_embedding(capsule_id, text, metadata, new_category)
    delete_capsule_embedding(capsule_id, old_category)


def search_capsules(
    query: str,
    accessible_ids: list[str],
    top_k: int = 5,
    categories: list[str] | None = None,
) -> list[str]:
    """Semantic search over accessible capsules, optionally scoped to categories.

    Returns capsule IDs ranked by relevance to the query.
    """
    if not accessible_ids:
        return []

    accessible_set = set(accessible_ids)

    # Determine which collections to search
    if categories:
        collections_to_search = [get_collection(cat) for cat in categories]
    elif _collections:
        collections_to_search = list(_collections.values())
    else:
        # No cached collections — create/get the default one
        collections_to_search = [get_collection("general")]

    all_results: list[tuple[str, float]] = []

    for collection in collections_to_search:
        try:
            where_filter = (
                {"capsule_id": {"$in": accessible_ids}}
                if len(accessible_ids) > 1
                else {"capsule_id": accessible_ids[0]}
            )
            results = collection.query(
                query_texts=[query],
                where=where_filter,
                n_results=min(top_k, len(accessible_ids)),
            )
        except Exception:
            try:
                results = collection.query(query_texts=[query], n_results=top_k * 2)
            except Exception:
                continue

        if results and results["ids"] and results["ids"][0]:
            distances = results.get("distances", [[]])[0]
            for i, cid in enumerate(results["ids"][0]):
                if cid in accessible_set:
                    dist = distances[i] if i < len(distances) else 1.0
                    all_results.append((cid, dist))

    # Sort by distance (lower = more similar for cosine), deduplicate
    all_results.sort(key=lambda x: x[1])
    seen = set()
    final = []
    for cid, _ in all_results:
        if cid not in seen:
            seen.add(cid)
            final.append(cid)
            if len(final) >= top_k:
                break

    return final


def reset_collections():
    """Reset all collections (for testing/seeding)."""
    global _collections
    client = get_client()
    for name in list(_collections.keys()):
        try:
            client.delete_collection(name)
        except Exception:
            pass
    _collections.clear()


# Backward-compat alias
reset_collection = reset_collections
