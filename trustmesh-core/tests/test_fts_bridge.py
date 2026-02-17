"""Tests for FTS5 Python ↔ Zig FFI bridge.

Tests the embeddings module (which calls libpodos FTS5 via ctypes)
to verify upsert, search, delete, reset, and trust filtering.
"""

import pytest

from src.timeline_bridge import is_available

# Skip entire module if libpodos is not built
pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="libpodos not built — run: cd kernel && zig build",
)


@pytest.fixture(autouse=True)
def fts_temp_db(tmp_path):
    """Set up a temp DB for each test and initialize FTS."""
    import src.embeddings as emb

    # Reset module state
    emb._db_handle = None

    db_path = str(tmp_path / "test_fts.db")
    emb.init_fts(db_path)
    yield db_path

    # Cleanup
    emb.close_fts()


# ═══════════════════════════════════════════
#  Basic CRUD
# ═══════════════════════════════════════════

def test_upsert_and_search():
    """Upsert a capsule and find it via search."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-001", "Heart Medication: take lisinopril 10mg daily", category="health")
    results = search_capsules("lisinopril", ["cap-001"], top_k=5)
    assert "cap-001" in results


def test_search_no_match():
    """Search for a term not in any capsule returns empty."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-002", "Guitar Practice: learn Stairway to Heaven", category="hobby")
    results = search_capsules("medication", ["cap-002"], top_k=5)
    assert results == []


def test_delete_removes_from_search():
    """Deleted capsule no longer appears in search."""
    from src.embeddings import delete_capsule_embedding, search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-del", "Important: findable content here", category="general")
    results = search_capsules("findable", ["cap-del"], top_k=5)
    assert "cap-del" in results

    delete_capsule_embedding("cap-del")
    results = search_capsules("findable", ["cap-del"], top_k=5)
    assert "cap-del" not in results


def test_upsert_overwrites():
    """Second upsert replaces the content (not duplicates)."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-upd", "Version One: content about cats", category="general")
    upsert_capsule_embedding("cap-upd", "Version Two: content about dogs", category="general")

    # Old content gone
    results = search_capsules("cats", ["cap-upd"], top_k=5)
    assert "cap-upd" not in results

    # New content found
    results = search_capsules("dogs", ["cap-upd"], top_k=5)
    assert "cap-upd" in results


def test_reset_clears_all():
    """reset_collections wipes the FTS5 table."""
    from src.embeddings import reset_collections, search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-rst", "Reset Test: findable data", category="general")
    results = search_capsules("findable", ["cap-rst"], top_k=5)
    assert "cap-rst" in results

    reset_collections()
    results = search_capsules("findable", ["cap-rst"], top_k=5)
    assert results == []


# ═══════════════════════════════════════════
#  Trust filtering (accessible_ids)
# ═══════════════════════════════════════════

def test_accessible_ids_filtering():
    """Only capsules in accessible_ids are returned."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("private-1", "Secret: private health data about surgery", category="health")
    upsert_capsule_embedding("public-1", "Public: general health tips for everyone", category="health")

    # Only public-1 accessible
    results = search_capsules("health", ["public-1"], top_k=5)
    assert "public-1" in results
    assert "private-1" not in results

    # Both accessible
    results = search_capsules("health", ["private-1", "public-1"], top_k=5)
    assert "private-1" in results
    assert "public-1" in results


def test_empty_accessible_ids():
    """Empty accessible_ids returns empty results."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-e", "Title: some content", category="general")
    results = search_capsules("content", [], top_k=5)
    assert results == []


def test_empty_query():
    """Empty query returns empty results."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-eq", "Title: content here", category="general")
    results = search_capsules("", ["cap-eq"], top_k=5)
    assert results == []


# ═══════════════════════════════════════════
#  BM25 ranking quality
# ═══════════════════════════════════════════

def test_bm25_ranking():
    """Capsule with more keyword occurrences ranks higher."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    # Cap with "heart" in title AND content (should rank higher)
    upsert_capsule_embedding("heart-heavy", "Heart Health: heart rate monitoring shows normal heart rhythm", category="health")
    # Cap with "heart" only once in content
    upsert_capsule_embedding("heart-light", "Daily Vitals: blood pressure and heart rate checked", category="health")

    results = search_capsules("heart", ["heart-heavy", "heart-light"], top_k=5)
    assert len(results) == 2
    assert results[0] == "heart-heavy"  # Should rank first


def test_top_k_limits_results():
    """top_k parameter limits number of results returned."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    for i in range(5):
        upsert_capsule_embedding(f"cap-tk-{i}", f"Test Item {i}: searchable test content", category="general")

    all_ids = [f"cap-tk-{i}" for i in range(5)]
    results = search_capsules("test", all_ids, top_k=2)
    assert len(results) == 2


# ═══════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════

def test_move_capsule():
    """move_capsule_embedding re-indexes with new content."""
    from src.embeddings import move_capsule_embedding, search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-mv", "Old: original content about cats", category="old")
    move_capsule_embedding("cap-mv", "New: updated content about dogs", None, "old", "new")

    results = search_capsules("dogs", ["cap-mv"], top_k=5)
    assert "cap-mv" in results

    results = search_capsules("cats", ["cap-mv"], top_k=5)
    assert "cap-mv" not in results


def test_special_characters_in_query():
    """Special characters in search query don't crash."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-sp", "Special: content with (parens) and 'quotes'", category="general")
    # These shouldn't crash even though they contain FTS5 special chars
    results = search_capsules("content (parens)", ["cap-sp"], top_k=5)
    assert isinstance(results, list)


def test_porter_stemming():
    """FTS5 porter stemmer matches word forms."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-stem", "Running: she runs every morning for exercise", category="fitness")
    results = search_capsules("running", ["cap-stem"], top_k=5)
    assert "cap-stem" in results


def test_multiple_word_query():
    """Multi-word query matches capsules with any of the words."""
    from src.embeddings import search_capsules, upsert_capsule_embedding

    upsert_capsule_embedding("cap-mw1", "Health: blood pressure monitoring", category="health")
    upsert_capsule_embedding("cap-mw2", "Fitness: morning exercise routine", category="fitness")

    # "pressure exercise" should match both (OR search)
    results = search_capsules("pressure exercise", ["cap-mw1", "cap-mw2"], top_k=5)
    assert len(results) == 2
