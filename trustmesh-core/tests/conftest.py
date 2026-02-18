"""Shared test configuration — runs before any test module is collected."""

import os

# Disable CSRF middleware in tests so that POST/PUT/DELETE requests
# don't need to juggle double-submit cookies.
os.environ["TRUSTMESH_DISABLE_CSRF"] = "1"

# Enable dev mode in tests so session cookies are not marked Secure
# (test clients use http:// not https://, so Secure cookies won't be sent back).
os.environ["TRUSTMESH_DEV_MODE"] = "1"
