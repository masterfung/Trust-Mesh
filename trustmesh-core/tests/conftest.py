"""Shared test configuration — runs before any test module is collected."""

import os

import pytest_asyncio

# Disable CSRF middleware in tests so that POST/PUT/DELETE requests
# don't need to juggle double-submit cookies.
os.environ["TRUSTMESH_DISABLE_CSRF"] = "1"

# Enable dev mode in tests so session cookies are not marked Secure
# (test clients use http:// not https://, so Secure cookies won't be sent back).
os.environ["TRUSTMESH_DEV_MODE"] = "1"


@pytest_asyncio.fixture(autouse=True)
async def _close_citadel_client_after_test():
    """Close the global httpx citadel client after each test.

    The singleton stays open across tests and leaves pending asyncio connection-
    cleanup tasks on the closing event loop, causing 'Event loop is closed'
    errors in the next test's teardown.  Explicitly aclose()-ing it here lets
    all cleanup tasks finish while the test's loop is still running.
    """
    yield
    try:
        from src.citadel import close_citadel_client
        await close_citadel_client()
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def _clear_transit_keys_after_test():
    """Reset the Zig transit engine after each test.

    The transit engine is a process-level singleton with MAX_USERS=256 capacity.
    Tests that call transit_bridge.store_key() directly (bypassing vault_keys)
    don't track keys in vault_keys._user_ids, so vault_keys.clear() alone is
    insufficient. Full deinit/reinit guarantees a clean engine for every test
    regardless of which code path stored the keys.

    podos_transit_init() is idempotent (no-op if already initialized), so
    calling deinit+reinit here is safe across all test orderings.
    """
    yield
    try:
        from src import transit_bridge
        from src.main import vault_keys
        # Clear Python-side tracking
        vault_keys._user_ids.clear()
        transit_bridge._initialized = False
        # Deinit the Zig engine (secureZero all keys, free engine)
        try:
            lib = transit_bridge._get_lib()
            lib.podos_transit_deinit()
        except Exception:
            pass
    except Exception:
        pass
