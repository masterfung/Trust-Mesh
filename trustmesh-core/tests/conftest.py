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
