"""ChromaDB vector store for semantic capsule retrieval."""

import chromadb

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None

COLLECTION_NAME = "trustmesh_capsules"


def get_client() -> chromadb.ClientAPI:
    """Get or create the ChromaDB client (persistent, in-process)."""
    global _client
    if _client is None:
        _client = chromadb.Client()  # In-memory for hackathon; swap to PersistentClient for prod
    return _client


def get_collection() -> chromadb.Collection:
    """Get or create the capsules collection."""
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def upsert_capsule_embedding(capsule_id: str, text: str, metadata: dict | None = None):
    """Embed and store a capsule's text in ChromaDB.

    ChromaDB uses its default embedding function (all-MiniLM-L6-v2)
    which runs locally — no API calls needed.
    """
    collection = get_collection()
    meta = metadata or {}
    # ChromaDB only accepts str/int/float/bool values in metadata
    clean_meta = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}
    collection.upsert(ids=[capsule_id], documents=[text], metadatas=[clean_meta])


def delete_capsule_embedding(capsule_id: str):
    """Remove a capsule from the vector store."""
    collection = get_collection()
    try:
        collection.delete(ids=[capsule_id])
    except Exception:
        pass  # Ignore if not found


def search_capsules(
    query: str,
    accessible_ids: list[str],
    top_k: int = 5,
) -> list[str]:
    """Semantic search over accessible capsules.

    Returns capsule IDs ranked by relevance to the query.
    """
    if not accessible_ids:
        return []

    collection = get_collection()
    try:
        # Always filter by accessible_ids to enforce trust boundaries
        where_filter = {"capsule_id": {"$in": accessible_ids}} if len(accessible_ids) > 1 else {"capsule_id": accessible_ids[0]}
        results = collection.query(
            query_texts=[query],
            where=where_filter,
            n_results=min(top_k, len(accessible_ids)),
        )
    except Exception:
        # Fallback: if filtering fails, query all and filter post-hoc
        results = collection.query(query_texts=[query], n_results=top_k * 2)

    if not results or not results["ids"] or not results["ids"][0]:
        return []

    # Filter to accessible IDs only
    accessible_set = set(accessible_ids)
    return [cid for cid in results["ids"][0] if cid in accessible_set][:top_k]


def reset_collection():
    """Reset the collection (for testing/seeding)."""
    global _collection
    client = get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _collection = None
