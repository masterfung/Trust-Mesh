# PodOS Lean Core: Zig Migration Plan

> From ~500MB per pod to ~80MB. Same capabilities. 10x lighter.

---

## Table of Contents

1. [Motivation](#motivation)
2. [Current Architecture & Footprint](#current-architecture--footprint)
3. [Target Architecture](#target-architecture)
4. [Migration Phases](#migration-phases)
   - [Phase 1: SQLite + FTS5 in Zig](#phase-1-sqlite--fts5-in-zig)
   - [Phase 2: Crypto in Zig](#phase-2-crypto-in-zig)
   - [Phase 3: Zig HTTP Server](#phase-3-zig-http-server)
   - [Phase 4: Trust, Sessions, Rate Limiting in Zig](#phase-4-trust-sessions-rate-limiting-in-zig)
   - [Phase 5: Federation Client in Zig](#phase-5-federation-client-in-zig)
5. [Future Phases](#future-phases)
6. [Zig Kernel Module Map](#zig-kernel-module-map)
7. [What Stays in Python (and Why)](#what-stays-in-python-and-why)
8. [Testing Strategy](#testing-strategy)
9. [Risks & Mitigations](#risks--mitigations)
10. [Build Order Summary](#build-order-summary)

---

## Motivation

A single TrustMesh pod today runs **~500MB RSS**. For 16-pod federation, that's **~10GB** just for Python processes. The vast majority of that memory is ChromaDB (~300-500MB in-process vector DB with its `all-MiniLM-L6-v2` embedding model).

The pod's actual responsibilities — storing encrypted capsules, resolving trust, managing sessions, serving HTTP — are lightweight operations that don't need a Python runtime, an ORM, or an in-process ML model.

The Zig timeline kernel (`libpodos.dylib`, 1.4MB, 2,308 lines) already proves the pattern: compile to native code, expose a C ABI, call from Python via ctypes. This document extends that pattern to the entire pod core.

### Goals

- **~80-100MB per pod** (down from ~500MB)
- **Millisecond startup** (down from 5-10s for Python + ChromaDB)
- **Single Zig binary** for the core pod server
- **Python retained only for**: MCP protocol, Anthropic SDK, agent prompting
- **Go Citadel sidecar** (or Mighty API) for security scanning
- **Zero capability loss** — same trust model, same encryption, same federation

---

## Current Architecture & Footprint

### Per-Pod Memory Breakdown

| Component | RSS | Role |
|-----------|-----|------|
| Python interpreter + stdlib | ~40MB | Runtime |
| FastAPI + uvicorn | ~20MB | HTTP server, ASGI |
| SQLAlchemy async + aiosqlite | ~15MB | ORM, DB access |
| **ChromaDB + all-MiniLM-L6-v2** | **~300-500MB** | Vector search, embeddings |
| cryptography + argon2-cffi | ~10MB | AES-256-GCM, Ed25519, Argon2id |
| anthropic + httpx | ~10MB | LLM API client |
| Other deps (mcp, typer, pydantic, etc.) | ~15MB | Various |
| Zig kernel (libpodos.dylib) | ~2MB | Timeline engine |
| **Total** | **~400-600MB** | |

### Process Count (16-pod federation)

| Process | Count | Memory |
|---------|-------|--------|
| uvicorn (Python) | 16 | ~6-10GB total |
| Bun (Next.js UI) | 1 | ~150-200MB |
| Bun (Registry) | 1 | ~100-150MB |
| Go (Citadel) | 1 | ~50-100MB |
| **Total** | **19** | **~7-10GB** |

### Where the Bytes Go

```
ChromaDB          ████████████████████████████████████████  60-80%
Python runtime    ████████                                  10-15%
FastAPI/uvicorn   ████                                      5%
SQLAlchemy        ███                                       4%
Crypto libs       ██                                        3%
Anthropic SDK     ██                                        3%
Zig kernel        ▏                                         <1%
```

ChromaDB is the elephant. Killing it alone is a 4x improvement.

---

## Target Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  Zig Binary (:8000)                       │
│                                                          │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────┐  │
│  │  HTTP Server │ │  SQLite +   │ │  Crypto Engine    │  │
│  │             │ │  FTS5       │ │                   │  │
│  │  Routing     │ │  Raw queries│ │  AES-256-GCM      │  │
│  │  CORS        │ │  Migrations │ │  Ed25519           │  │
│  │  Static files│ │  FTS5 index │ │  Argon2id          │  │
│  │  JSON codec  │ │             │ │  SHA-256           │  │
│  │  Cookie auth │ │             │ │  Base58btc/DID     │  │
│  └──────┬──────┘ └──────┬──────┘ └───────────────────┘  │
│         │               │                                │
│  ┌──────┴──────┐ ┌──────┴──────┐ ┌───────────────────┐  │
│  │  Trust      │ │  Session    │ │  Federation       │  │
│  │  Resolver   │ │  Manager    │ │  Client           │  │
│  │             │ │             │ │                   │  │
│  │  4-level    │ │  In-memory  │ │  Peer connect     │  │
│  │  Ghost stale│ │  Cookie map │ │  Ghost lifecycle   │  │
│  │  Pool merge │ │  Rate limit │ │  Pool sync         │  │
│  │             │ │             │ │  Registry sync     │  │
│  └─────────────┘ └─────────────┘ └───────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Timeline Kernel (existing)                         │  │
│  │  Tick-tock engine, entry state machine, cron, DAG   │  │
│  └────────────────────────────────────────────────────┘  │
│                         │                                │
│                   Unix socket / pipe                      │
│                         │                                │
├─────────────────────────┼────────────────────────────────┤
│          Python Sidecar (internal, no port)               │
│                                                          │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────┐  │
│  │  MCP Server │ │  Anthropic  │ │  Agent Prompting  │  │
│  │  (stdio)    │ │  SDK        │ │                   │  │
│  │  JSON-RPC   │ │  Streaming  │ │  System prompts    │  │
│  │  Tools      │ │  Tool use   │ │  Tool dispatch     │  │
│  └─────────────┘ └─────────────┘ └───────────────────┘  │
├──────────────────────────────────────────────────────────┤
│          Go Sidecar (Citadel :3001)  OR  Mighty API      │
│                                                          │
│  Input scanning, output scanning, trust-aware patterns   │
└──────────────────────────────────────────────────────────┘
```

### Target Footprint

| Component | RSS | Notes |
|-----------|-----|-------|
| Zig binary | ~10-20MB | All HTTP, DB, crypto, trust, federation |
| Python sidecar | ~50-60MB | MCP + anthropic + httpx only |
| Go Citadel | ~50-100MB | Optional (Mighty API = zero local) |
| **Total per pod** | **~80-120MB** | **5-6x reduction** |

For 16 pods: **~1.5-2GB** instead of ~10GB.

---

## Migration Phases

### Phase 1: SQLite + FTS5 in Zig

> **Effort**: ~1-2 weeks | **Memory win**: ~400MB per pod (biggest single win)
> **New Zig files**: `kernel/src/db.zig`, `kernel/src/fts.zig`

The biggest win and the right place to start. ChromaDB is ~400MB of the ~500MB pod footprint. Replace it with FTS5 (built into SQLite) and do it in Zig from day one — this establishes `db.zig` as the foundation all later phases build on, avoiding throwaway Python-only work.

#### Why Zig (not Python-only)

Doing FTS5 in Python first would mean rewriting `embeddings.py` to use aiosqlite FTS5 queries, then rewriting it *again* in Zig when SQLite moves to the kernel. Instead:

1. **Build `db.zig` now** — SQLite C API wrapper (`@cImport("sqlite3.h")`), ~80 lines. This is the same `db.zig` needed for the full route migration later.
2. **Build `fts.zig`** — FTS5 search/upsert/delete, ~120 lines. Small, contained scope.
3. **Expose 3 C ABI functions** — `podos_fts_search`, `podos_fts_upsert`, `podos_fts_delete`
4. **Python calls Zig via ctypes** — same pattern as `timeline_bridge.py`
5. **Front-loads the hardest unknown** — if Zig + SQLite + WAL concurrent access is painful, discover it on a 200-line module, not during the full migration.

#### What Changes

| File | Change |
|------|--------|
| `kernel/src/db.zig` (new, ~80 lines) | SQLite C API wrapper: open, exec, prepare, bind, step, close |
| `kernel/src/fts.zig` (new, ~150 lines) | FTS5 search, upsert, delete with C ABI exports |
| `kernel/src/main.zig` | Add 3-5 new exports for FTS5 operations |
| `kernel/build.zig` | Link sqlite3 (`linkSystemLibrary("sqlite3")`) |
| `src/embeddings.py` (169 lines) | **Rewrite** — call Zig FFI instead of ChromaDB |
| `src/gossip.py` | Update `search_capsules()` call to use new embeddings API |
| `src/seed.py` | Replace `upsert_capsule_embedding()` with FTS5 upsert via Zig |
| `src/main.py` | Remove ChromaDB rebuild on startup; FTS5 table created by Zig |
| `src/routes/capsules.py` | Replace embedding upsert/delete calls with Zig equivalents |
| `pyproject.toml` | Remove `chromadb` dependency |

#### FTS5 Schema (created by `db.zig` on init)

```sql
-- Virtual table mirroring capsule content for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS capsule_fts USING fts5(
    capsule_id UNINDEXED,    -- FK to knowledge_capsules.id (not searchable)
    title,                    -- searchable
    content,                  -- searchable (plaintext, decrypted at index time)
    category UNINDEXED,       -- used for filtering, not searching
    tokenize='porter unicode61'  -- stemming + unicode support
);
```

#### Zig: `db.zig` — SQLite Foundation

```zig
// kernel/src/db.zig — thin wrapper around SQLite C API
// This module is reused by ALL later phases (1b, 4, 5)

const c = @cImport({
    @cInclude("sqlite3.h");
});

pub const Database = struct {
    handle: *c.sqlite3,

    pub fn open(path: [*:0]const u8) !Database {
        var db: ?*c.sqlite3 = null;
        const rc = c.sqlite3_open_v2(
            path, &db,
            c.SQLITE_OPEN_READWRITE | c.SQLITE_OPEN_CREATE | c.SQLITE_OPEN_NOMUTEX,
            null,
        );
        if (rc != c.SQLITE_OK) return error.SqliteOpenFailed;
        const handle = db.?;

        // Match existing database.py PRAGMA configuration
        _ = c.sqlite3_exec(handle, "PRAGMA journal_mode=WAL", null, null, null);
        _ = c.sqlite3_exec(handle, "PRAGMA busy_timeout=5000", null, null, null);
        _ = c.sqlite3_exec(handle, "PRAGMA secure_delete=ON", null, null, null);

        return .{ .handle = handle };
    }

    pub fn prepare(self: *Database, sql: [*:0]const u8) !Statement { ... }
    pub fn exec(self: *Database, sql: [*:0]const u8) !void { ... }
    pub fn close(self: *Database) void { c.sqlite3_close(self.handle); }
};

pub const Statement = struct {
    stmt: *c.sqlite3_stmt,
    pub fn bindText(self: *Statement, idx: c_int, text: []const u8) !void { ... }
    pub fn step(self: *Statement) !StepResult { ... }
    pub fn getText(self: *Statement, col: c_int) ?[]const u8 { ... }
    pub fn getDouble(self: *Statement, col: c_int) f64 { ... }
    pub fn reset(self: *Statement) void { ... }
    pub fn finalize(self: *Statement) void { ... }
};
```

#### Zig: `fts.zig` — FTS5 Operations

```zig
// kernel/src/fts.zig

const db_mod = @import("db.zig");

/// Initialize FTS5 virtual table (idempotent)
pub fn initFtsTable(database: *db_mod.Database) !void {
    try database.exec(
        \\CREATE VIRTUAL TABLE IF NOT EXISTS capsule_fts USING fts5(
        \\    capsule_id UNINDEXED,
        \\    title,
        \\    content,
        \\    category UNINDEXED,
        \\    tokenize='porter unicode61'
        \\);
    );
}

/// Upsert a capsule into the FTS5 index (decrypted plaintext)
pub fn upsertCapsule(
    database: *db_mod.Database,
    capsule_id: []const u8,
    title: []const u8,
    content: []const u8,
    category: []const u8,
) !void {
    // DELETE + INSERT (FTS5 doesn't support UPDATE well)
    var del = try database.prepare("DELETE FROM capsule_fts WHERE capsule_id = ?");
    defer del.finalize();
    try del.bindText(1, capsule_id);
    _ = try del.step();

    var ins = try database.prepare(
        "INSERT INTO capsule_fts(capsule_id, title, content, category) VALUES (?, ?, ?, ?)"
    );
    defer ins.finalize();
    try ins.bindText(1, capsule_id);
    try ins.bindText(2, title);
    try ins.bindText(3, content);
    try ins.bindText(4, category);
    _ = try ins.step();
}

/// BM25 search over accessible capsules
pub fn searchCapsules(
    database: *db_mod.Database,
    query: []const u8,
    accessible_ids: []const []const u8,
    top_k: u32,
    allocator: std.mem.Allocator,
) ![]SearchResult {
    // Build: SELECT capsule_id, rank FROM capsule_fts
    //        WHERE capsule_fts MATCH ? AND capsule_id IN (...)
    //        ORDER BY rank LIMIT ?
    // Return capsule IDs ranked by BM25 relevance
    ...
}

pub fn deleteCapsule(database: *db_mod.Database, capsule_id: []const u8) !void {
    var stmt = try database.prepare("DELETE FROM capsule_fts WHERE capsule_id = ?");
    defer stmt.finalize();
    try stmt.bindText(1, capsule_id);
    _ = try stmt.step();
}
```

#### C ABI Exports (in main.zig)

```zig
// ═══════════════════════════════════════════
//  DATABASE + FTS5
// ═══════════════════════════════════════════

/// Open database and create FTS5 table if needed
export fn podos_db_open(path: [*:0]const u8) callconv(.c) ?*anyopaque {
    var database = db_mod.Database.open(path) catch return null;
    fts_mod.initFtsTable(&database) catch return null;
    // Store in opaque pointer
    ...
}

export fn podos_db_close(handle: ?*anyopaque) callconv(.c) void { ... }

/// Upsert capsule into FTS5 index
export fn podos_fts_upsert(
    db_handle: ?*anyopaque,
    capsule_id: [*]const u8, id_len: u32,
    title: [*]const u8, title_len: u32,
    content: [*]const u8, content_len: u32,
    category: [*]const u8, category_len: u32,
) callconv(.c) i32 { ... }

/// Search FTS5 index — returns JSON array of {capsule_id, rank}
export fn podos_fts_search(
    db_handle: ?*anyopaque,
    query: [*]const u8, query_len: u32,
    accessible_ids_json: [*]const u8, ids_len: u32,  // JSON array of ID strings
    top_k: u32,
    out: [*]u8, out_capacity: u32, out_len: *u32,    // JSON result buffer
) callconv(.c) i32 { ... }

/// Delete capsule from FTS5 index
export fn podos_fts_delete(
    db_handle: ?*anyopaque,
    capsule_id: [*]const u8, id_len: u32,
) callconv(.c) i32 { ... }
```

#### Python Bridge Update (`embeddings.py`)

```python
"""FTS5 search via Zig kernel — replaces ChromaDB."""

import ctypes
import json
from src.timeline_bridge import _lib  # reuse existing dylib handle

_db_handle = None  # set on startup via podos_db_open()

def init_fts(db_path: str):
    """Open Zig-side SQLite + create FTS5 table."""
    global _db_handle
    _db_handle = _lib.podos_db_open(db_path.encode())
    if not _db_handle:
        raise RuntimeError("Failed to open FTS5 database")

def upsert_capsule_embedding(capsule_id: str, text: str, metadata=None, category="general"):
    """Index a capsule's decrypted content in FTS5."""
    title = (metadata or {}).get("title", "")
    rc = _lib.podos_fts_upsert(
        _db_handle,
        capsule_id.encode(), len(capsule_id),
        title.encode(), len(title),
        text.encode(), len(text),
        category.encode(), len(category),
    )
    if rc != 0:
        raise RuntimeError(f"FTS5 upsert failed: {rc}")

def search_capsules(query: str, accessible_ids: list[str], top_k=5, categories=None) -> list[str]:
    """BM25 search over accessible capsules via Zig FTS5."""
    if not accessible_ids:
        return []
    ids_json = json.dumps(accessible_ids).encode()
    out_buf = ctypes.create_string_buffer(65536)
    out_len = ctypes.c_uint32()
    rc = _lib.podos_fts_search(
        _db_handle,
        query.encode(), len(query),
        ids_json, len(ids_json),
        top_k,
        out_buf, 65536, ctypes.byref(out_len),
    )
    if rc != 0:
        return []
    results = json.loads(out_buf.raw[:out_len.value])
    return [r["capsule_id"] for r in results]

def delete_capsule_embedding(capsule_id: str, category=None):
    """Remove a capsule from the FTS5 index."""
    _lib.podos_fts_delete(_db_handle, capsule_id.encode(), len(capsule_id))
```

#### Concurrent Access: Zig + Python on Same SQLite DB

Both processes access the same `trustmesh.db` file:
- **Python (SQLAlchemy)**: Writes capsules, reads for routes (until Phase 3 migrates routes to Zig)
- **Zig (libpodos)**: Reads/writes FTS5 index, timeline engine state

This works because:
- SQLite WAL mode allows concurrent readers + one writer
- `busy_timeout=5000ms` handles write contention (both sides configured)
- FTS5 writes (upsert on capsule create) are brief and infrequent
- The Zig DB handle opens with `SQLITE_OPEN_NOMUTEX` (each connection is single-threaded)

#### Key Design Decision: Indexing Decrypted Content

FTS5 indexes **decrypted plaintext** — the search index is in the same SQLite DB as the encrypted capsules. This is the same security model as ChromaDB (which also stores plaintext embeddings in-process). The DB file is already trusted local storage.

If this is a concern for future multi-tenant scenarios, the FTS5 table could be a separate encrypted SQLite DB per user. But for single-user pods, it's equivalent to the current ChromaDB model.

#### What Gets Removed

- `chromadb` pip dependency (~300-500MB runtime memory)
- `all-MiniLM-L6-v2` sentence transformer model (~90MB on disk)
- 30-second embedding rebuild on pod startup
- Category-scoped ChromaDB collection management

#### Trade-offs

| | ChromaDB (current) | FTS5 in Zig (proposed) |
|---|---|---|
| Search type | Semantic (cosine similarity) | Keyword (BM25 ranking) |
| "headache" finds "migraine"? | Yes (embedding similarity) | No (unless both terms present) |
| Memory | ~300-500MB | ~0 (built into SQLite, managed by Zig) |
| Startup | ~30s (rebuild embeddings) | ~0 (FTS5 is persistent, Zig opens in ms) |
| Ranking quality | Better for fuzzy queries | Better for exact queries |
| LLM compensation | N/A | Claude bridges semantic gaps |
| Bonus | None | Establishes `db.zig` for all later phases |

**Mitigation for semantic gap**: Before FTS5 search, optionally expand the query using a small synonym map or ask the LLM to generate search terms. E.g., user says "headache" → search for `headache OR migraine OR cephalalgia`. This is cheap (one small LLM call or static map) and recovers most of the semantic matching.

---

### Phase 2: Crypto in Zig

> **Effort**: ~1 week | **Memory win**: ~10MB (small, but eliminates `cryptography` + `argon2-cffi` C extensions)
> **New Zig files**: `kernel/src/crypto.zig`

Port all crypto operations to Zig, exposed via C ABI. Python calls Zig for all crypto instead of the `cryptography` library.

#### Zig std.crypto Coverage

| Algorithm | Python (current) | Zig std equivalent | Notes |
|-----------|------------------|--------------------|-------|
| AES-256-GCM | `cryptography.hazmat` AESGCM | `std.crypto.aead.aes_gcm.Aes256Gcm` | Direct match |
| Ed25519 sign/verify | `cryptography.hazmat` Ed25519PrivateKey | `std.crypto.sign.Ed25519` | Direct match |
| Ed25519 keygen | `Ed25519PrivateKey.generate()` | `Ed25519.KeyPair.create(null)` | Direct match |
| SHA-256 | `hashlib.sha256` | `std.crypto.hash.sha2.Sha256` | Direct match |
| Argon2id | `argon2.low_level.hash_secret_raw` | `std.crypto.pwhash.argon2` | Direct match |
| CSPRNG | `os.urandom()` | `std.crypto.random` | Direct match |
| Base58btc | Custom Python impl (30 lines) | Port to Zig (big-int arithmetic) | Straightforward |
| Base64url | `base64.urlsafe_b64encode` | `std.base64.url_safe` | Direct match |

All algorithms have direct Zig std equivalents. No external libraries needed.

#### C ABI Exports (~15 functions)

```zig
// kernel/src/crypto.zig

// ── Key Generation ──
export fn podos_generate_aes_key(out: [*]u8) callconv(.c) void;
export fn podos_generate_ed25519_keypair(priv_out: [*]u8, pub_out: [*]u8) callconv(.c) void;
export fn podos_random_bytes(out: [*]u8, len: u32) callconv(.c) void;

// ── AES-256-GCM ──
export fn podos_encrypt(
    plaintext: [*]const u8, plaintext_len: u32,
    key: [*]const u8,
    out: [*]u8, out_len: *u32,  // nonce (12) + ciphertext + tag (16)
) callconv(.c) i32;

export fn podos_decrypt(
    data: [*]const u8, data_len: u32,  // nonce || ciphertext || tag
    key: [*]const u8,
    out: [*]u8, out_len: *u32,
) callconv(.c) i32;

// ── Ed25519 ──
export fn podos_sign_ed25519(
    message: [*]const u8, msg_len: u32,
    private_key: [*]const u8,
    signature_out: [*]u8,  // 64 bytes
) callconv(.c) i32;

export fn podos_verify_ed25519(
    message: [*]const u8, msg_len: u32,
    signature: [*]const u8,
    public_key: [*]const u8,
) callconv(.c) i32;  // 1 = valid, 0 = invalid

// ── Argon2id ──
export fn podos_derive_vault_key(
    password: [*]const u8, password_len: u32,
    salt: [*]const u8, salt_len: u32,  // pass null + 0 to auto-generate
    key_out: [*]u8,    // 32 bytes
    salt_out: [*]u8,   // 16 bytes (actual salt used)
) callconv(.c) i32;

export fn podos_hash_pin(
    pin: [*]const u8, pin_len: u32,
    out: [*]u8, out_len: *u32,  // "salt_hex$hash_hex" string
) callconv(.c) i32;

export fn podos_verify_pin(
    pin: [*]const u8, pin_len: u32,
    hash: [*]const u8, hash_len: u32,
) callconv(.c) i32;  // 1 = match, 0 = no match

// ── DID:key ──
export fn podos_public_key_to_did(
    public_key: [*]const u8,
    out: [*]u8, out_len: *u32,  // "did:key:z..." string
) callconv(.c) i32;

export fn podos_did_to_public_key(
    did: [*]const u8, did_len: u32,
    out: [*]u8,  // 32 bytes
) callconv(.c) i32;

// ── Hashing ──
export fn podos_sha256(
    data: [*]const u8, data_len: u32,
    out: [*]u8,  // 32 bytes
) callconv(.c) void;
```

#### Python Bridge Update

Update `src/crypto.py` to call Zig instead of `cryptography`:

```python
# Before: from cryptography.hazmat.primitives.ciphers.aead import AESGCM
# After:  call libpodos via ctypes

from src.timeline_bridge import _lib  # reuse existing dylib handle

def encrypt(plaintext: bytes, key: bytes) -> bytes:
    out = ctypes.create_string_buffer(12 + len(plaintext) + 16)  # nonce + ct + tag
    out_len = ctypes.c_uint32()
    rc = _lib.podos_encrypt(plaintext, len(plaintext), key, out, ctypes.byref(out_len))
    if rc != 0:
        raise RuntimeError("Encryption failed")
    return out.raw[:out_len.value]
```

#### What Gets Removed

- `cryptography` pip dependency (~10MB, C extension with OpenSSL)
- `argon2-cffi` pip dependency (~2MB, C extension)
- Custom base58btc Python implementation (30 lines → Zig)

#### Validation

- Port existing `tests/test_crypto.py` — encrypt in Zig, decrypt in Zig, verify round-trip
- Cross-validate: encrypt in Python (old), decrypt in Zig (new) and vice versa
- Ensure DID format is byte-identical between Python and Zig implementations
- UCAN tokens signed by Zig must validate against existing Python verifier

---

### Phase 3: Zig HTTP Server

> **Effort**: ~2-3 weeks | **Memory win**: Enables all subsequent phases
> **New Zig files**: `kernel/src/http.zig`, `kernel/src/router.zig`, `kernel/src/json.zig`

This is the architectural pivot. Zig takes over the HTTP port (:8000). Initially it proxies ALL requests to Python (running on an internal port or unix socket). Then routes migrate one-by-one from Python to native Zig handlers.

#### Architecture

```
Client → :8000 (Zig HTTP server)
              │
              ├── /api/query, /api/pod/a2a, /api/briefing, /api/intake
              │   └── proxy → Python sidecar (LLM-dependent routes)
              │
              ├── /api/capsules, /api/users, /api/connections, /api/networks, ...
              │   └── handled natively in Zig (after Phase 1b)
              │
              └── /* (static files)
                  └── serve built Next.js assets from disk
```

#### Implementation Options

| Option | Pros | Cons |
|--------|------|------|
| `std.http.Server` | No deps, ships with Zig | Low-level, no middleware, single-threaded event loop |
| [zap](https://github.com/zigzap/zap) (libfacil.io) | Fast, battle-tested C backend, routing built-in | External dep, C interop complexity |
| [httpz](https://github.com/karlseguin/http.zig) | Pure Zig, good API, thread pool | Smaller community |
| [jetzig](https://github.com/jetzig-project/jetzig) | Full framework (templates, ORM, etc.) | Too heavy, we want control |

**Recommendation**: Start with `std.http.Server` for control and zero deps. It's low-level but our routing needs are simple (18 prefixes, ~84 endpoints). If performance or ergonomics become an issue, swap to httpz later — the handler functions stay the same.

#### Phase 3a: Proxy Mode (~1 week)

Zig HTTP server on :8000, Python FastAPI on :9000 (internal). Zig proxies every request to Python. This validates:

- Zig can handle HTTP correctly (headers, cookies, CORS, chunked encoding)
- Cookie-based auth works through the proxy
- Streaming LLM responses proxy correctly
- Static file serving works for the frontend

```zig
// kernel/src/http.zig — simplified proxy handler
fn handleRequest(request: *std.http.Server.Request) !void {
    // Parse route
    const path = request.target;

    // Check if this route is handled natively
    if (router.findNativeHandler(path)) |handler| {
        return handler(request);
    }

    // Otherwise proxy to Python sidecar
    return proxyToPython(request);
}
```

#### Phase 3b: CORS + Cookie Middleware (~2-3 days)

```zig
// CORS middleware
fn addCorsHeaders(response: *Response) void {
    response.header("Access-Control-Allow-Origin", getAllowedOrigin());
    response.header("Access-Control-Allow-Credentials", "true");
    response.header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,PATCH,OPTIONS");
    response.header("Access-Control-Allow-Headers", "Content-Type,Authorization,X-Pool-Sync-Secret,...");
}

// Cookie extraction
fn getSessionToken(request: *Request) ?[]const u8 {
    const cookie_header = request.headers.get("cookie") orelse return null;
    // Parse "trustmesh_session=<token>" from cookie string
    return parseCookieValue(cookie_header, "trustmesh_session");
}
```

#### Phase 3c: Route Migration (ongoing, overlaps with 1b)

Routes move from Python to Zig one module at a time. Priority order:

1. **Health/status** endpoints (trivial, good first test)
2. **Auth** endpoints (login/logout — validates session management works)
3. **Capsules CRUD** (validates SQLite + crypto integration)
4. **Connections/Networks** (validates trust resolution)
5. **Federation/Pod** endpoints (validates HTTP client)
6. **LLM-dependent routes stay in Python**: `/api/query`, `/api/pod/a2a`, `/api/briefing`, `/api/intake`

#### What Gets Removed (eventually)

- FastAPI framework
- uvicorn ASGI server
- Pydantic schema validation (replaced by Zig struct parsing)
- Most of the Python route files

---

### Phase 4: Trust, Sessions, Rate Limiting in Zig

> **Effort**: ~3-5 days | **Memory win**: Negligible (these are tiny modules)
> **New Zig files**: `kernel/src/trust.zig`, `kernel/src/session.zig`, `kernel/src/rate_limit.zig`

These are simple, self-contained modules with clear logic. Small LOC, easy to port.

#### Trust Resolution (103 lines Python → ~150 lines Zig)

```zig
// kernel/src/trust.zig

pub const TrustLevel = enum { private, network, connected, public };

pub const TrustResult = struct {
    level: TrustLevel,
    shared_network_ids: []const []const u8,
};

pub fn resolveTrustLevel(
    db: *Database,
    from_user_id: []const u8,
    to_user_id: []const u8,
) !TrustResult {
    // Same user → private
    if (std.mem.eql(u8, from_user_id, to_user_id))
        return .{ .level = .private, .shared_network_ids = &.{} };

    // Shared networks → network (unless ghost is stale)
    const shared = try getSharedNetworks(db, from_user_id, to_user_id);
    if (shared.len > 0) {
        if (try isGhostStale(db, from_user_id))
            return .{ .level = .public, .shared_network_ids = &.{} };
        return .{ .level = .network, .shared_network_ids = shared };
    }

    // Accepted connection → connected
    if (try hasAcceptedConnection(db, from_user_id, to_user_id))
        return .{ .level = .connected, .shared_network_ids = &.{} };

    return .{ .level = .public, .shared_network_ids = &.{} };
}
```

#### Session Management (91 lines Python → ~120 lines Zig)

```zig
// kernel/src/session.zig

const SessionEntry = struct {
    user_id: [36]u8,
    created_at: i64,  // unix timestamp
};

var sessions = std.StringHashMap(SessionEntry).init(allocator);

pub fn createSession(user_id: []const u8) ![44]u8 {
    var token: [32]u8 = undefined;
    std.crypto.random.bytes(&token);
    const token_str = std.base64.url_safe.encode(&token);
    sessions.put(token_str, .{ .user_id = user_id, .created_at = std.time.timestamp() });
    return token_str;
}

pub fn validateSession(token: []const u8) ?[]const u8 {
    const entry = sessions.get(token) orelse return null;
    if (std.time.timestamp() - entry.created_at > SESSION_TTL) {
        _ = sessions.remove(token);
        return null;
    }
    return &entry.user_id;
}
```

#### Rate Limiting (112 lines Python → ~150 lines Zig)

```zig
// kernel/src/rate_limit.zig

const SlidingWindow = struct {
    events: std.ArrayList(i64),

    fn record(self: *SlidingWindow, alloc: Allocator) !void {
        try self.events.append(alloc, std.time.timestamp());
    }

    fn count(self: *SlidingWindow, window_seconds: i64) usize {
        const cutoff = std.time.timestamp() - window_seconds;
        // Prune and count
        ...
    }
};

var connection_windows = std.StringHashMap(SlidingWindow).init(allocator);
var query_windows = std.StringHashMap(SlidingWindow).init(allocator);

pub fn checkConnectionRate(user_id: []const u8) !struct { allowed: bool, reason: []const u8 } {
    const daily = getOrCreate(&connection_windows, "conn:" ++ user_id ++ ":day").count(86400);
    if (daily >= 10) return .{ .allowed = false, .reason = "Daily limit reached (10/day)" };
    const weekly = getOrCreate(&connection_windows, "conn:" ++ user_id ++ ":week").count(604800);
    if (weekly >= 30) return .{ .allowed = false, .reason = "Weekly limit reached (30/week)" };
    return .{ .allowed = true, .reason = "ok" };
}
```

#### What Gets Removed

- `src/trust.py` (103 lines)
- `src/auth.py` (91 lines)
- `src/rate_limit.py` (112 lines)
- FastAPI `Depends()` injection for auth → Zig middleware

---

### Phase 5: Federation Client in Zig

> **Effort**: ~2 weeks | **Memory win**: Eliminates `httpx` from Python
> **New Zig files**: `kernel/src/federation.zig`, `kernel/src/federation_auth.zig`

Federation is the most complex phase because it involves:
- Outbound HTTP to other pods (peer connect, query, pool sync)
- Signed requests (Ed25519 + nonce + timestamp)
- Ghost user lifecycle (create, lookup, cascade delete)
- Registry integration (signed registration)

#### Zig HTTP Client

```zig
// Using std.http.Client for outbound requests
const client = std.http.Client{ .allocator = allocator };
defer client.deinit();

var request = try client.open(.POST, try std.Uri.parse(peer_url ++ "/api/pod/peers"), .{
    .extra_headers = &.{
        .{ .name = "Content-Type", .value = "application/json" },
        .{ .name = "X-TrustMesh-Timestamp", .value = timestamp },
        .{ .name = "X-TrustMesh-Nonce", .value = nonce },
        .{ .name = "X-TrustMesh-Signature", .value = signature },
    },
});
try request.writer().writeAll(body_json);
try request.finish();
try request.wait();
```

#### Federation Auth (196 lines Python → ~200 lines Zig)

The signing scheme (timestamp + nonce + body → Ed25519) maps directly since Phase 2 already provides all crypto primitives.

```zig
// kernel/src/federation_auth.zig

pub fn signRequest(
    body: []const u8,
    private_key: [32]u8,
) !FederationHeaders {
    const timestamp = try std.fmt.allocPrint(allocator, "{d}", .{std.time.timestamp()});
    var nonce: [16]u8 = undefined;
    std.crypto.random.bytes(&nonce);
    const nonce_b64 = std.base64.url_safe.encode(&nonce);

    // Message: "<timestamp>\n<nonce>\n<body>"
    const message = try std.fmt.allocPrint(allocator, "{s}\n{s}\n{s}", .{ timestamp, nonce_b64, body });

    const keypair = std.crypto.sign.Ed25519.KeyPair.fromSecretKey(private_key);
    const signature = try keypair.sign(message, null);

    return .{
        .timestamp = timestamp,
        .nonce = nonce_b64,
        .signature = std.base64.url_safe.encode(&signature.toBytes()),
    };
}
```

#### Ghost User Lifecycle

Ghost user management (create, lookup, cascade delete) is DB operations + trust resolution — both already in Zig after phases 1b and 4.

#### What Gets Removed

- `src/federation.py` (510 lines)
- `src/federation_auth.py` (196 lines)
- `httpx` pip dependency (for federation — still needed for Anthropic SDK)

---

## Future Phases

These are beyond the initial 5-phase plan but complete the long-term vision:

### Phase 6: CLI in Zig

> **Effort**: ~1-2 weeks

The CLI (`src/cli.py`, 1,188 lines) is just HTTP calls + terminal formatting. Zig can do this with `std.http.Client` + `std.io.getStdOut()`. The CLI becomes a separate Zig binary (`podos-cli`) that talks to the pod's HTTP API.

Alternative: Write in Go, since Citadel is already Go and the CLI toolchain is mature (cobra, etc.).

### Phase 7: Python → MCP + Anthropic Only

> **Effort**: ~1 week (cleanup)

After all routes are native Zig, Python shrinks to:

```
anthropic          # Claude API client (streaming tool use)
mcp                # Model Context Protocol server (stdio JSON-RPC)
httpx              # HTTP client (used by anthropic SDK)
```

That's it. ~50-60MB for the Python sidecar. Everything else is Zig.

### Phase 8: Registry in Zig

The standalone `trustmesh-registry/` (Next.js 16 + better-sqlite3) is just 5 API routes + SQLite. Could fold into the Zig binary as a compilation flag (`--enable-registry`), or keep as a separate Zig binary for deployment flexibility.

### Phase 9: Static Frontend Serving

`next build` → static assets. Zig serves them from a directory. No Bun runtime in production. Development still uses `bun dev` for hot reload.

---

## Zig Kernel Module Map

After all phases, the kernel source tree:

```
kernel/src/
├── main.zig              # C ABI exports (existing 48 + new ~60)
├── types.zig             # Core types (existing)
├── entry.zig             # Entry state machine (existing)
├── event.zig             # Event queue (existing)
├── cron.zig              # Cron parser (existing)
├── dag.zig               # Dependency graph (existing)
├── resolution.zig        # Three-stream resolution (existing)
├── state.zig             # Central state (existing)
├── log.zig               # Transition log (existing)
├── timeline.zig          # Timeline engine (existing)
│
├── db.zig                # Phase 1: SQLite C API wrapper (foundation for all DB access)
├── fts.zig               # Phase 1: FTS5 search, upsert, delete
├── crypto.zig            # Phase 2: AES-GCM, Ed25519, Argon2id, DID
├── http.zig              # Phase 3: HTTP server, routing, CORS
├── router.zig            # Phase 3: Route table, path matching
├── json.zig              # Phase 3: JSON parse/serialize helpers
├── models.zig            # Phase 3+: Struct definitions for all tables (as routes migrate)
├── trust.zig             # Phase 4: Trust resolution
├── session.zig           # Phase 4: Session management, cookies
├── rate_limit.zig        # Phase 4: Sliding window rate limiter
├── federation.zig        # Phase 5: Outbound HTTP client, ghost lifecycle
└── federation_auth.zig   # Phase 5: Ed25519 request signing/verification
```

Estimated total: **~6,000-8,000 lines of Zig** (up from 2,308 current).

---

## What Stays in Python (and Why)

| Module | Lines | Why it stays |
|--------|-------|-------------|
| `agents.py` | 2,474 | Complex prompt construction, multi-turn tool use, Anthropic SDK streaming |
| `gossip.py` (partial) | ~200 | LLM orchestration (trust filtering moves to Zig, LLM call stays in Python) |
| `citadel.py` (partial) | ~100 | Heuristic fallback patterns (Go sidecar handles primary scanning) |
| `mcp_server.py` | 466 | MCP protocol (JSON-RPC over stdio, Python `mcp` library) |
| `cli.py` | 1,188 | Stays until Phase 6 (works fine against Zig HTTP server) |
| `seed.py` | 2,030 | Stays as client-side script (calls HTTP API) |

**MCP is the anchor.** The `mcp` Python library implements the full Model Context Protocol spec (stdio transport, JSON-RPC, tool registration, resource management). Reimplementing this in Zig would be ~2,000+ lines for a moving spec target. Not worth it.

**Anthropic SDK is the other anchor.** Streaming tool use with Claude requires handling SSE, partial JSON, tool call accumulation, and retry logic. The Python SDK does this well. Direct HTTP from Zig is possible but significantly more work for marginal gain.

---

## Testing Strategy

### Phase 1 (SQLite + FTS5 in Zig)

- **Zig unit tests**: `zig build test` for db.zig (open, prepare, bind, step) and fts.zig (upsert, search, delete)
- **FFI integration tests**: Python pytest calling Zig via ctypes — upsert capsule, search, verify results
- **BM25 quality tests**: Known queries → expected capsule ordering
- **Concurrent access**: Python (SQLAlchemy) writes capsule + Zig writes FTS5 index simultaneously
- **Regression**: Full gossip pipeline tests pass with FTS5 backend instead of ChromaDB
- **Key test**: Trust-filtered FTS5 search returns correct capsules for exact-match queries
- **Seed validation**: Seed script populates FTS5 index via Zig, search returns all expected capsules

### Phase 2 (Crypto)

- **Cross-validation**: Encrypt with Python (old), decrypt with Zig (new) and vice versa
- **DID round-trip**: `public_key → did:key → public_key` identical in both implementations
- **UCAN compat**: Tokens signed by Zig validate in Python verifier (and reverse)
- Zig unit tests via `zig build test` (existing pattern)

### Phase 3 (HTTP Server)

- **Proxy mode**: All existing pytest tests pass through Zig proxy → Python backend
- **Route migration**: Each migrated route gets its own Zig test + existing Python test still passes
- **CORS**: Browser-based test for preflight OPTIONS handling
- **Cookie auth**: Verify httpOnly cookie flow through Zig
- **SQLAlchemy elimination**: Routes that move to Zig use db.zig directly (no more ORM)
- **Schema compatibility**: Verify Zig raw SQL creates/reads identical data to SQLAlchemy

### Phase 4 (Trust/Sessions/Rate)

- Port existing trust tests to call Zig functions
- Session TTL and rate limit window tests
- **Ghost staleness**: Verify 24-hour timeout logic matches Python behavior

### Phase 5 (Federation)

- **Signing compat**: Zig-signed requests accepted by Python verifier (and reverse)
- **Multi-pod smoke tests**: Existing `test_multi_pod.py` passes with Zig pods
- **Ghost lifecycle**: Create, lookup, cascade delete all work from Zig

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Zig HTTP server maturity | `std.http.Server` lacks middleware, may have edge cases | Start in proxy mode; fall back to httpz/zap if needed |
| SQLite concurrent access | Zig HTTP + Python sidecar both hitting same DB | SQLite WAL mode handles this; busy_timeout=5000ms |
| Argon2id in Zig std | May not match Python argon2-cffi output byte-for-byte | Cross-validate early; both use Argon2id spec, should match with same params |
| JSON handling verbosity | Zig std.json is functional but verbose vs Python dicts | Build thin helpers in `json.zig`; accept the verbosity |
| Memory management | Zig has no GC — must track allocations | Use arena allocator per request (alloc on start, free all on response complete) |
| Zig 0.15.x breaking changes | Zig pre-1.0, APIs shift between versions | Pin to 0.15.2 (already installed), document any API quirks |
| Streaming LLM responses | Proxying SSE/chunked from Python through Zig | Test early in Phase 3a; chunked transfer encoding must pass through cleanly |
| Base58btc big-int math | Zig has no arbitrary-precision integers | Ed25519 public keys are 32 bytes (fits u256); implement fixed-width base58 |

---

## Build Order Summary

```
Phase 1: SQLite + FTS5 in Zig         ~1-2 weeks    ████████████████
  └── Kill ChromaDB (~400MB saved), establish db.zig foundation
  └── Prereqs: none — START HERE

Phase 2: Crypto in Zig                ~1 week       ████████
  └── AES-GCM, Ed25519, Argon2id, DID
  └── Prereqs: none (can parallel with Phase 1)

Phase 3: Zig HTTP Server              ~2-3 weeks    ████████████████████
  └── Proxy mode → route migration → SQLAlchemy elimination
  └── Prereqs: Phase 1 (db.zig), Phase 2 (crypto for auth routes)

Phase 4: Trust/Sessions/Rate          ~3-5 days     ████
  └── Simple logic ports
  └── Prereqs: Phase 1 (db.zig for trust queries)

Phase 5: Federation Client            ~2 weeks      ████████████████
  └── HTTP client, signing, ghosts
  └── Prereqs: Phase 2 (crypto), Phase 1 (DB), Phase 4 (trust)

─────────────────────────────────────────────────────────────
Total: ~7-9 weeks for one developer

Phase 1 + 2 in parallel:              ~2 weeks
Phase 3 after both:                   ~2-3 weeks
Phase 4 + 5 after 3:                  ~2-3 weeks
```

### Milestone Checkpoints

| After Phase | Pod Memory | Python Surface | Zig LOC |
|-------------|-----------|---------------|---------|
| Current | ~500MB | Everything | 2,308 |
| **1** | **~120MB** | Everything minus ChromaDB | ~2,550 |
| **2** | ~110MB | Minus crypto libs | ~3,050 |
| **3** | ~80-90MB | Minus FastAPI/SQLAlchemy (routes migrated) | ~5,500 |
| **4** | ~80MB | Minus auth/trust/rate | ~5,900 |
| **5** | **~80MB** | **MCP + Anthropic only** | ~6,800 |

---

## Appendix: Current Python LOC by Module

For reference, the exact scope of what's being ported or retained:

| Module | Lines | Fate |
|--------|-------|------|
| `agents.py` | 2,474 | **Stays** (Python — LLM orchestration) |
| `seed.py` | 2,030 | **Stays** (Python — HTTP client script) |
| `cli.py` | 1,188 | Stays until Phase 6 |
| `routes/*.py` (18 files) | 5,141 | **Zig** (Phase 3 + 1b) |
| `timeline_bridge.py` | 781 | Evolves (bridge to expanded Zig kernel) |
| `schemas.py` | 673 | **Zig** (structs replace Pydantic) |
| `gossip.py` | 622 | Split: search → Zig, LLM call → Python |
| `federation.py` | 510 | **Zig** (Phase 5) |
| `mcp_server.py` | 466 | **Stays** (Python — MCP protocol) |
| `model_router.py` | 433 | **Stays** (Python — LLM provider routing) |
| `main.py` | 399 | Replaced by Zig HTTP server |
| `models.py` | 343 | **Zig** (Phase 3, as routes migrate) |
| `citadel.py` | 270 | Partial: heuristics stay, sidecar calls → Zig |
| `crypto.py` | 245 | **Zig** (Phase 2) |
| `ucan.py` | 225 | **Zig** (Phase 2) |
| `seed_multi.py` | 211 | Stays (Python — HTTP client script) |
| `federation_auth.py` | 196 | **Zig** (Phase 5) |
| `embeddings.py` | 169 | **Rewritten** (Phase 1 — FTS5 via Zig FFI) |
| `rate_limit.py` | 112 | **Zig** (Phase 4) |
| `trust.py` | 103 | **Zig** (Phase 4) |
| `auth.py` | 91 | **Zig** (Phase 4) |
| `audit.py` | 73 | **Zig** (with routes) |
| `database.py` | 62 | **Zig** (Phase 1 establishes db.zig, Phase 3 completes migration) |
| `fhir.py` | 206 | **Zig** (with routes) |
| **Total** | ~16,400 | ~8,200 → Zig, ~6,200 stays Python, ~2,000 rewritten |
