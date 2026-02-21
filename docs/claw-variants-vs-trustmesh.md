# Claw Variants vs TrustMesh: Deep Architecture Comparison

## Overview

Three systems, three languages, one vision: personal AI that works for you.

| System | Language | LoC | Binary/Runtime | Test Count | Focus |
|--------|----------|-----|----------------|------------|-------|
| **NullClaw** | Zig 0.15.2 | ~19K (132 files) | 678 KB (ReleaseSmall), <1MB RSS | 2,738 | Lean native agent, vtable polymorphism, sub-MB footprint |
| **ZeroClaw** | Rust 2021 | ~104K (35 modules) | 3.4 MB (release), <5MB RSS | ~2,000+ | Production async agent, trait-driven, hardware integration |
| **TrustMesh** | Python + Zig | ~8K Python + ~12K Zig | 1.4 MB dylib + Python runtime | 842 | Trust-aware vault, federation, gossip protocol |

**The key insight**: Claw variants are the **brain, hands, and voice** (LLM provider dispatch + sandboxed tool execution + multi-channel messaging). TrustMesh is the **memory, identity, and social fabric** (encrypted vault + trust networks + pod federation + agent discovery). They don't compete — they complete each other.

---

## 1. What Each System Actually Does (From the Source)

### NullClaw (Zig) — "The Lean Agent"

Built for minimal footprint with zero runtime dependencies beyond libc and SQLite. The entire agent compiles to a single 678 KB binary.

**Module breakdown** (from `src/`):
- `providers/` (14 files) — vtable-based LLM dispatch for 22+ providers via `StaticStringMap` of 40+ provider URLs
- `security/` (14 files) — sandbox backends, secret scrubbing, command policy (76 tests, 1119 lines), audit
- `tools/` (36 files) — shell, file ops, git, browser, memory, http, cron, delegate, hardware
- `channels/` (19 files) — CLI, Telegram, Discord, Slack, WhatsApp, Signal, Matrix, IRC, etc.
- `memory/` (13 files, 178K total) — sqlite.zig (54K), lucid.zig (29K), embeddings.zig (26K), cache.zig (24K), chunker.zig (19K), markdown.zig (17K), vector.zig (12K), hygiene.zig (10K), snapshot.zig (7K), none.zig (4K)
- `agent/` (6 files) — orchestration loop, context window, planner

**Build optimization** (`build.zig`):
- Strip symbols, dead dylib stripping, macOS `strip -x` for local symbols
- Platform detection for SQLite paths (Homebrew vs system)
- Result: 678 KB static binary, <1 MB peak RSS

### ZeroClaw (Rust) — "The Production Agent"

Full async runtime on Tokio with the broadest provider/channel/tool coverage and firmware targets for embedded hardware.

**Module breakdown** (from `src/`):
- `providers/` — 14 provider modules (Anthropic, OpenAI, Gemini, Ollama, OpenRouter, Copilot, Bedrock, GLM/Zhipu, + 6 OpenAI-compatible wrappers covering 30+ providers)
- `channels/` (20,726 lines) — 18 channel implementations: CLI, Telegram (2965), Discord (955), Slack (349), WhatsApp Cloud (1138), WhatsApp Web (525) + storage (1345), iMessage (982), Signal (910), Matrix (1043), IRC (1021), Email/IMAP (968), DingTalk (382), Lark (1271), LinQ (793), Mattermost (918), QQ (508)
- `tools/` (~14,500 lines) — 30+ tools: shell, file_read, file_write, git_operations, browser, screenshot, web_search, http_request, cron (6 tools), memory (3 tools), delegate, composio (1000+ OAuth apps), pushover, hardware (3 tools), schedule, proxy_config, image_info, browser_open, schema
- `security/` — sandbox trait + 5 backends, secret store (ChaCha20-Poly1305), pairing, policy
- `memory/` — SQLite + FTS5 hybrid search, PostgreSQL, Markdown files, Lucid bridge, embeddings
- `firmware/` — 5 targets: ESP32, ESP32-UI, Nucleo (STM32F401RE), Arduino, UNO-Q-Bridge
- `observability/` — Prometheus metrics, OpenTelemetry traces, console observer
- `python/` — `zeroclaw-tools` LangGraph companion package

**Build optimization** (`Cargo.toml`):
- `opt-level = "z"`, `lto = "thin"`, `strip = true`, single codegen unit
- Result: 3.4 MB release binary, <5 MB RAM

### TrustMesh — "The Trust Layer"

The missing piece: encrypted personal data vault with trust-aware access control and peer-to-peer federation. Not an agent runtime — it's what makes agent runtimes trustworthy.

**Module breakdown**:
- `src/` (Python) — gossip.py (query engine), agents.py (Sonnet 4.5 + 15 tools), crypto.py (AES-256-GCM, Argon2id, ed25519), trust.py, citadel.py (AI security), federation.py, ucan.py, cli.py, mcp_server.py
- `kernel/src/` (Zig) — types.zig, entry.zig, event.zig, cron.zig, dag.zig, resolution.zig, state.zig, timeline.zig, crypto.zig, session.zig, rate_limit.zig, trust.zig, transit.zig, fts.zig, db.zig, federation.zig, federation_auth.zig, http.zig, router.zig, server_main.zig, main.zig (78 C ABI exports)
- `trustmesh-ui/` — Next.js 16, D3.js trust graph, pod switcher
- `trustmesh-registry/` — Next.js 16, SQLite, DID/ed25519 verification, agent discovery

---

## 2. Architecture Patterns — Side by Side

### 2.1 Core Abstraction: How Each System Does Polymorphism

**ZeroClaw** uses Rust's `async_trait` with default method implementations. The Provider trait has 12 methods — only `chat_with_system` is required. Everything else has a sensible default:

```rust
// src/providers/traits.rs (903 lines)
#[async_trait]
pub trait Provider: Send + Sync {
    fn capabilities(&self) -> ProviderCapabilities { ProviderCapabilities::default() }
    fn convert_tools(&self, tools: &[ToolSpec]) -> ToolsPayload {
        // Default: prompt-guided via XML tags (works with any provider)
        ToolsPayload::PromptGuided(build_tool_instructions_text(tools))
    }
    async fn chat_with_system(&self, system: Option<&str>, message: &str,
        model: &str, temperature: f64) -> anyhow::Result<String>;  // REQUIRED
    async fn chat(&self, request: ChatRequest<'_>, model: &str,
        temperature: f64) -> anyhow::Result<ChatResponse> { /* default impl */ }
    fn supports_native_tools(&self) -> bool { self.capabilities().native_tool_calling }
    fn supports_streaming(&self) -> bool { false }
    async fn warmup(&self) -> anyhow::Result<()> { Ok(()) }
    // ... 5 more methods
}
```

The `ToolsPayload` enum handles per-provider tool format differences:
```rust
pub enum ToolsPayload {
    Gemini(Vec<serde_json::Value>),     // Google's format
    Anthropic(Vec<serde_json::Value>),  // Anthropic's format
    OpenAI(Vec<serde_json::Value>),     // OpenAI's format
    PromptGuided(String),               // Fallback: XML in system prompt
}
```

**NullClaw** uses Zig vtable structs with optional function pointer slots. The Provider vtable has 5 required + 4 optional slots:

```zig
// src/providers/root.zig (1657 lines)
pub const Provider = struct {
    ptr: *anyopaque,
    vtable: *const VTable,

    pub const VTable = struct {
        // Required — every provider must implement these:
        chatWithSystem: *const fn(ptr: *anyopaque, alloc: Allocator,
            system: ?[]const u8, message: []const u8, model: []const u8,
            temperature: f64) anyerror![]const u8,
        chat: *const fn(ptr: *anyopaque, alloc: Allocator,
            request: ChatRequest, model: []const u8, temperature: f64) anyerror!ChatResponse,
        supportsNativeTools: *const fn(ptr: *anyopaque) bool,
        getName: *const fn(ptr: *anyopaque) []const u8,
        deinit: *const fn(ptr: *anyopaque) void,

        // Optional — null means "not supported":
        warmup: ?*const fn(ptr: *anyopaque) void = null,
        chat_with_tools: ?*const fn(...) anyerror!ChatResponse = null,
        supports_streaming: ?*const fn(ptr: *anyopaque) bool = null,
        stream_chat: ?*const fn(...) anyerror!StreamChatResult = null,
    };

    // Convenience: falls back to blocking chat + synthetic stream chunks
    pub fn streamChat(self: Provider, ...) anyerror!StreamChatResult {
        if (self.vtable.stream_chat) |f| return f(self.ptr, ...);
        // Fallback: call chat() and wrap result as single chunk
        const response = try self.vtable.chat(self.ptr, ...);
        return StreamChatResult.fromComplete(response);
    }
};
```

Compile-time interface enforcement:
```zig
pub fn assertProviderInterface(comptime T: type) void {
    if (!@hasDecl(T, "provider")) {
        @compileError(@typeName(T) ++ " missing provider() method");
    }
}
```

**TrustMesh** uses Python classes for the application layer and Zig C ABI exports for the kernel. The boundary is clean: Python owns HTTP/business logic, Zig owns crypto/search/state:

```python
# Python side: class-based with async
class ModelRouter:
    async def complete(self, messages, model, sensitivity="standard"): ...

class TimelineEngine:
    def tick(self) -> int: ...  # Calls podos_timeline_tick() via ctypes
    def create_entry(self, ...) -> str: ...  # Fluent EntryBuilder
```

```zig
// Zig kernel: flat C ABI exports (78 total)
export fn podos_timeline_tick(engine: *TimelineEngine) callconv(.c) i32 { ... }
export fn podos_fts_search(query: [*]const u8, ...) callconv(.c) i32 { ... }
export fn podos_crypto_aes_gcm_encrypt(key: [*]const u8, ...) callconv(.c) i32 { ... }
export fn podos_transit_store_key(user_id: [*]const u8, ...) callconv(.c) i32 { ... }
```

### 2.2 All Trait/Vtable Interfaces Compared

| Interface | ZeroClaw (Rust traits) | NullClaw (Zig vtables) | TrustMesh |
|-----------|----------------------|----------------------|-----------|
| **Provider/LLM** | `trait Provider` (12 methods, 6 required) | `Provider` vtable (5 required + 4 optional) | `ModelRouter` class + TEE routing |
| **Channel/Messaging** | `trait Channel` (10 methods, draft updates) | `Channel` vtable (6 slots) | N/A — not an agent runtime |
| **Tool/Action** | `trait Tool` (4 required + JSON Schema) | `Tool` vtable (4 slots) | 15 agent tools in `agents.py` |
| **Sandbox/Isolation** | `trait Sandbox` (4 required, 5 backends) | `Sandbox` vtable (4 slots, 5 backends) | N/A — no shell execution |
| **Memory/Storage** | `trait Memory` (7 required, 5 backends) | SQLite module (FTS5 + embeddings) | Zig FTS5 + SQLAlchemy |
| **Observer/Telemetry** | `trait Observer` (4 methods, Prometheus+OTEL) | N/A | N/A |
| **Runtime/Platform** | `trait RuntimeAdapter` (6 methods) | N/A | N/A |
| **Peripheral/Hardware** | `trait Peripheral` (5 required, 5 firmware targets) | I2C/SPI stubs | N/A |

### 2.3 Provider Discovery and Factory Patterns

Both claw variants auto-detect providers from API key prefixes:

**NullClaw** (`root.zig` — `detectProviderByApiKey()`):
```zig
const ApiKeyPrefix = struct { prefix: []const u8, provider: ProviderKind };
const api_key_prefixes = [_]ApiKeyPrefix{
    .{ .prefix = "sk-ant-", .provider = .anthropic },
    .{ .prefix = "sk-or-",  .provider = .openrouter },
    .{ .prefix = "sk-",     .provider = .openai },
    .{ .prefix = "gsk_",    .provider = .groq },
    .{ .prefix = "xai-",    .provider = .xai },
    .{ .prefix = "pplx-",   .provider = .perplexity },
    .{ .prefix = "AKIA",    .provider = .bedrock },
    .{ .prefix = "AIza",    .provider = .gemini },
};
```

Provider URL lookup via `StaticStringMap` (40+ entries in `compatibleProviderUrl()`):
```zig
// Venice, Groq, Mistral, xAI, DeepSeek, Together, Fireworks, Perplexity,
// Cohere, NVIDIA NIM, LM Studio, etc. — all routed through OpenAI-compatible adapter
const map = std.StaticStringMap([]const u8).initComptime(.{
    .{ "venice",    "https://api.venice.ai/api/v1" },
    .{ "groq",      "https://api.groq.com/openai/v1" },
    .{ "deepseek",  "https://api.deepseek.com/v1" },
    // ... 37 more entries
});
```

API key resolution is 3-level: explicit arg > provider-specific env var > generic `API_KEY`:
```zig
pub fn resolveApiKey(allocator: Allocator, provider_name: []const u8, api_key: ?[]const u8) !?[]u8 {
    if (api_key) |key| return try allocator.dupe(u8, key);
    // Try ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
    if (envForProvider(provider_name)) |env_key| {
        if (std.posix.getenv(env_key)) |val| return try allocator.dupe(u8, val);
    }
    // Fallback to generic
    if (std.posix.getenv("API_KEY")) |val| return try allocator.dupe(u8, val);
    return null;
}
```

**ZeroClaw** — similar pattern in Rust with `From<&Config>` trait implementations per provider.

**TrustMesh** — no provider factory (not an agent runtime). LLM routing via `model_router.py` with sensitivity-based TEE dispatch:
- Standard queries → Anthropic (Sonnet 4.5, Haiku 4.5)
- Sensitive queries → TEE models (Tinfoil, Redpill — Kimi K2.5, Llama 70B in secure enclaves)

---

## 3. The ReliableProvider Pattern (ZeroClaw's Crown Jewel)

`src/providers/reliable.rs` — 1507 lines, 50+ tests. This is the most adoptable pattern for TrustMesh.

### Three-Level Failover Strategy

```
Outer loop:  Model fallback chain (gpt-4 → gpt-4-turbo → claude-opus)
Middle loop: Provider priority chain (openai → anthropic → ollama)
Inner loop:  Retry with exponential backoff (attempt 1 → 2 → 3)
```

The struct:
```rust
pub struct ReliableProvider {
    providers: Vec<(String, Box<dyn Provider>)>,  // Priority-ordered
    max_retries: u32,                              // Default: 3
    base_backoff_ms: u64,                          // Default: 1000, doubles per retry, cap 10s
    api_keys: Vec<String>,                         // Round-robin on rate limits
    key_index: AtomicUsize,                        // Atomic rotation counter
    model_fallbacks: HashMap<String, Vec<String>>, // e.g. "gpt-4" → ["gpt-4-turbo", "gpt-3.5-turbo"]
}
```

### Error Classification (the critical piece)

```rust
fn is_non_retryable(err: &anyhow::Error) -> bool {
    let msg = err.to_string().to_lowercase();
    // HTTP 4xx except 429 and 408
    if msg.contains("status: 4") && !msg.contains("status: 429") && !msg.contains("status: 408") {
        return true;
    }
    // Auth failures, model not found, content policy
    msg.contains("invalid api key") || msg.contains("authentication failed")
        || msg.contains("model not found") || msg.contains("content policy")
}

fn is_rate_limited(err: &anyhow::Error) -> bool {
    let msg = err.to_string().to_lowercase();
    msg.contains("status: 429") || msg.contains("too many requests")
        || msg.contains("rate limit")
}

fn is_context_window_exceeded(err: &anyhow::Error) -> bool {
    // Fast-fail: skip ALL retries and fallbacks — prompt is too long
    let msg = err.to_string().to_lowercase();
    msg.contains("context window") || msg.contains("maximum context length")
        || msg.contains("token limit")
}

fn is_non_retryable_rate_limit(err: &anyhow::Error) -> bool {
    // Business errors: can't retry because it's a plan/billing issue
    let msg = err.to_string().to_lowercase();
    msg.contains("plan does not include") || msg.contains("insufficient balance")
        || msg.contains("quota exceeded")
}
```

### Retry-After Parsing

```rust
fn parse_retry_after_ms(err: &anyhow::Error) -> Option<u64> {
    let msg = err.to_string();
    // Look for "Retry-After: N" or "retry after Ns" or "try again in N seconds"
    for pattern in &["retry-after:", "retry after ", "try again in "] {
        if let Some(pos) = msg.to_lowercase().find(pattern) {
            let after = &msg[pos + pattern.len()..];
            if let Ok(secs) = after.trim().split_whitespace().next()
                .and_then(|s| s.trim_end_matches('s').parse::<f64>().ok()) {
                return Some((secs * 1000.0).min(30_000.0) as u64);  // Cap at 30s
            }
        }
    }
    None
}
```

### API Key Rotation

On 429 errors, rotate to the next API key before retrying:
```rust
fn rotate_key(&self) -> &str {
    if self.api_keys.is_empty() { return ""; }
    let idx = self.key_index.fetch_add(1, Ordering::Relaxed) % self.api_keys.len();
    &self.api_keys[idx]
}
```

### Structured Error Reporting

When all attempts fail, the error message shows exactly what happened:
```
All providers/models failed. Attempts:
  provider=openai model=gpt-4 attempt 1/3: rate_limited (retry_after=5000ms)
  provider=openai model=gpt-4 attempt 2/3: rate_limited (retry_after=5000ms)
  provider=openai model=gpt-4 attempt 3/3: rate_limited
  provider=openai model=gpt-4-turbo attempt 1/3: non_retryable; error=model not found
  provider=anthropic model=claude-opus attempt 1/3: success
```

### What TrustMesh Should Adopt

Port this to `model_router.py` for:
- **Federation retries**: cross-pod queries failing due to network issues
- **TEE failover**: Tinfoil down → Redpill → standard Anthropic (with sensitivity downgrade warning)
- **Multi-key rotation**: multiple API keys for high-throughput pods

---

## 4. Security — Deep Comparison

### 4.1 Encryption at Rest

| Feature | ZeroClaw | NullClaw | TrustMesh |
|---------|----------|----------|-----------|
| **Algorithm** | ChaCha20-Poly1305 | ChaCha20-Poly1305 | AES-256-GCM |
| **Key storage** | `~/.zeroclaw/.secret_key` (0600) | File-based (0600) | Zig transit engine (never on disk after init) |
| **Key derivation** | CSPRNG (256-bit random) | CSPRNG | Argon2id (password → key) |
| **What's encrypted** | API keys in config, OAuth tokens | API keys in config | ALL vault capsule content, ed25519 private keys |
| **Nonce** | 12-byte random per encrypt | 12-byte random | 12-byte random per capsule |
| **Migration** | XOR → ChaCha20 auto-upgrade | N/A | N/A |
| **Memory protection** | N/A | N/A | `secureZero` on secret material, keys in Zig memory only |

**TrustMesh's edge**: Vault keys never exist in Python memory. The transit engine (`transit.zig`) stores keys in Zig heap, encrypts/decrypts via C ABI calls. Even if the Python process is compromised, vault keys aren't accessible.

### 4.2 Secret Scrubbing

All three systems now scrub secrets from tool/API output before it reaches the LLM.

**NullClaw** (`root.zig` — `scrubSecretPatterns()`, 12 prefixes):
```zig
const prefixes = [_][]const u8{
    "sk-", "xoxb-", "xoxp-", "ghp_", "gho_", "ghs_", "ghu_",
    "glpat-", "AKIA", "pypi-", "npm_", "shpat_",
};
// + key=value patterns (9 keywords: api_key, token, password, secret, etc.)
// + Bearer token detection
// + Output truncation: 10K char max via scrubToolOutput()
// + API error truncation: 200 char max via sanitizeApiError()
```

**ZeroClaw** (`secrets.rs` — `redact()`, similar approach):
- First 4 chars preserved + `[REDACTED]` for debugging
- ChaCha20-Poly1305 encrypted storage for config secrets
- Environment sanitization in shell tool (only `PATH`, `HOME`, `TERM`, `LANG`, `USER`, `SHELL`, `TMPDIR`)

**TrustMesh** (`citadel.py` — `scrub_secret_prefixes()`, 27 prefixes):
```python
SECRET_PREFIXES = [
    "sk-", "xoxb-", "xoxp-", "ghp_", "gho_", "ghs_", "ghu_", "glpat-",
    "AKIA", "pypi-", "npm_", "shpat_", "whsec_",
    "sk_live_", "sk_test_", "pk_live_", "pk_test_",  # Stripe
    "rk_live_", "rk_test_",                           # Stripe restricted
    "SG.",                                              # SendGrid
    "xapp-",                                            # Slack app
    "dop_v1_",                                          # DigitalOcean
    "snyk-",                                            # Snyk
    "sq0csp-",                                          # Square
    "EAACEdEose0cBA",                                   # Facebook
]
# + key=value patterns (14 key names)
# + Bearer token detection
# + 10K char tool output truncation
# 61 tests — all passing
```

### 4.3 Sandbox Backends

| Backend | ZeroClaw | NullClaw | TrustMesh |
|---------|----------|----------|-----------|
| **Landlock** (Linux 5.13+ LSM) | `landlock` crate, feature-gated | Comptime platform check, native syscalls | N/A |
| **Firejail** (SUID sandbox) | Runtime probe | `--noprofile --private=workspace` | N/A |
| **Bubblewrap** (user namespaces) | Feature-gated | Always compiled | N/A |
| **Docker** (container) | `--network none --read-only --memory` limits | Similar flags | N/A |
| **Noop** (no isolation) | Fallback | Fallback | N/A |
| **Auto-detection** | Best-available probe | Manual selection | N/A |

**Linux priority**: Landlock > Firejail > Bubblewrap > Docker > Noop
**macOS priority**: Docker > Noop (ZeroClaw), Docker > Noop (NullClaw)

### 4.4 Command Injection Protection

**NullClaw** (`policy.zig` — 1119 lines, 76 tests):

High-risk command blocklist:
```zig
const high_risk_commands = [_][]const u8{
    "rm", "mkfs", "dd", "shutdown", "reboot", "halt", "poweroff",
    "sudo", "su", "chown", "chmod", "useradd", "userdel", "usermod", "passwd",
    "mount", "umount", "iptables", "ufw", "firewall-cmd",
    "curl", "wget", "nc", "ncat", "netcat", "scp", "ssh", "ftp", "telnet",
};
```

Injection vector blocking:
- Backtick `` ` `` and `$(` subshell — blocked
- `${` variable expansion — blocked
- Process substitution `<(` and `>(` — blocked
- Output redirect `>` — blocked
- Background `&` (but allows `&&`) — smart single-ampersand detection
- `tee` bypass (writes to arbitrary files, evading redirect blocks) — blocked
- `find -exec` and `find -ok` — blocked
- Git argument injection (`--exec=`, `--upload-pack=`, `--pager=`, `-c`) — blocked

**ZeroClaw** — similar `SecurityPolicy` with 3 autonomy levels (ReadOnly, Supervised, Full), forbidden paths (14 system dirs + 4 sensitive dotfiles), workspace-only enforcement with symlink escape detection.

**TrustMesh** — no shell execution (not an agent runtime). Security focus is on trust boundaries and prompt injection defense via Citadel.

### 4.5 AI Security (TrustMesh's Unique Strength)

| Feature | ZeroClaw | NullClaw | TrustMesh |
|---------|----------|----------|-----------|
| **Prompt injection defense** | Tool output truncation | Tool output truncation | Citadel sidecar (Go, ML+heuristic) + Python fallback |
| **Output scanning** | Secret scrubbing only | Secret scrubbing only | Trust-level-aware pattern matching (6 soft-leak categories) |
| **Information boundaries** | N/A | N/A | 3-tier trust: public/network/private |
| **Query classification** | N/A | N/A | Citadel scans BOTH input questions AND output answers |
| **Context minimization** | N/A | N/A | Public queries get stripped capsule metadata |
| **Red-team tested** | N/A | N/A | 50 adversarial tests in test_citadel_redteam.py |

### 4.6 Authentication

| Feature | ZeroClaw | NullClaw | TrustMesh |
|---------|----------|----------|-----------|
| **Gateway auth** | 6-digit pairing code → bearer token | 6-digit pairing code → SHA-256 token | N/A |
| **Session auth** | Bearer token (hashed in RwLock) | Bearer token (hashed) | httpOnly cookie + SHA-256 fingerprint (UA+IP) |
| **Session security** | N/A | N/A | Rotation on login, 10 cap/user, 1hr sliding timeout |
| **CSRF** | N/A | N/A | Double-submit cookie on POST/PUT/DELETE |
| **Federation auth** | N/A | N/A | ed25519 signed headers + nonce replay protection |
| **Delegation auth** | N/A | N/A | UCAN tokens (role-scoped, time-limited, ed25519) |
| **Brute force** | 5-attempt lockout | 5-attempt global lockout | Per-user + per-DID rate limiting |

---

## 5. Memory Systems Compared

### NullClaw's Memory (178K LoC across 13 files)

The most sophisticated memory system of the three, built entirely in Zig:

**Schema** (`memory/sqlite.zig` — 54K lines, 200+ tests):
```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'core', session_id TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE memories_fts USING fts5(
    key, content, content=memories, content_rowid=rowid
);
-- FTS5 sync triggers (insert, delete, update)
CREATE TABLE memory_embeddings (
    memory_key TEXT PRIMARY KEY, embedding BLOB NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY (memory_key) REFERENCES memories(key) ON DELETE CASCADE
);
```

5 memory categories: `core`, `working`, `episodic`, `semantic`, `procedural`

Memory hygiene: auto-archive after 90 days, purge after 180 days

### ZeroClaw's Memory (5 backends)

**SQLite hybrid search** (`memory/sqlite.rs` — ~800 lines):
```rust
pub fn hybrid_merge(
    vector_results: &[(String, f32)],   // Cosine similarity [0, 1]
    keyword_results: &[(String, f32)],  // BM25 (normalized to [0, 1])
    vector_weight: f32,                 // Default: 0.7
    keyword_weight: f32,                // Default: 0.3
    limit: usize,
) -> Vec<ScoredResult> { /* union merge + weighted score + sort */ }
```

Backends: SQLite + FTS5 (default), PostgreSQL + pgvector, Markdown files, Lucid bridge (external), None (no-op)

Embedding providers: OpenAI API, custom OpenAI-compatible URL, None (keyword-only)

LRU embedding cache (`embedding_cache` table) to avoid recomputing.

### TrustMesh's Memory (Encrypted Vault + FTS5)

**Fundamentally different**: TrustMesh's "memory" is an encrypted vault with trust-gated access:

```
Capsule lifecycle:
1. User creates capsule → content encrypted with AES-256-GCM via transit.zig
2. FTS5 index updated in Zig kernel (title + content, porter stemming)
3. Capsule stored in SQLite (encrypted blob)
4. Query arrives → trust level computed → FTS5 search within accessible capsule IDs
5. Results decrypted in transit.zig → returned to caller
```

Key difference from claw memory:
- **Claw memory** = agent's working memory (what it learned during conversations)
- **TrustMesh vault** = YOUR personal data (health records, financial docs, family info)
- **Claw memory** has no access control — it's single-user
- **TrustMesh vault** has 3-tier trust: private (you only), network (trusted circles), public (anyone)

---

## 6. What TrustMesh Has That Claw Doesn't

### 6.1 Encrypted Personal Vault
Every piece of your data encrypted with YOUR key (AES-256-GCM). Keys live in Zig memory (transit engine) — never touch Python, never touch disk unencrypted. Vault key derived from your password via Argon2id. Your AI can search your vault, but only with your permission and only data your trust level permits.

### 6.2 Trust Networks
You control who sees what: **Private** (only you), **Network** (trusted circles), **Public** (anyone). Trust computed from connections AND network pool membership. Ghost users enable cross-pod trust without exposing your full identity. Pool-based trust: join a "Family Health" pool, members see your shared health data — nothing else.

### 6.3 Gossip Protocol (Trust-Aware Query Resolution)
When someone asks your agent a question, trust level determines accessible data. Citadel scans both the question (injection defense) AND the answer (leak prevention). Public queries get minimal context with stripped metadata. Private queries get full vault access.

### 6.4 Pod Federation
Every person/organization runs their own pod (single-command deployment). Pods discover each other via registry, connect peer-to-peer. Pools enable group trust without centralized authority. Cross-pod queries use federation auth (ed25519 signed headers + nonce replay protection + DID spoofing prevention).

### 6.5 DID Identity + UCAN Authorization
ed25519 keypair generates a decentralized identifier (DID). UCAN tokens: cryptographically signed, role-scoped, time-limited. Emergency access: paramedic gets time-limited token for critical health data. Agent cards (A2A protocol) make your agent discoverable.

### 6.6 PodOS Timeline Kernel
Temporal execution engine in Zig: schedule, trigger, coordinate. Cron expressions, event reactors, entry state machines (dormant→pending→active→completed). Tick-tock cycle: evaluate (frozen) then commit (atomic). Three-stream resolution: private > internal > open priority.

### 6.7 TEE Model Routing
Sensitive queries routed to Trusted Execution Environments (Tinfoil, Redpill). TEE models run in hardware-isolated enclaves — not even the cloud provider can see your data. Standard queries use Anthropic (Sonnet 4.5, Haiku 4.5).

---

## 7. What Claw Has That TrustMesh Should Learn From

### 7.1 Secret Prefix Scrubbing — ADOPTED
**Status**: Complete. 27 prefixes in `citadel.py`, 61 tests passing.
TrustMesh now scrubs tool output before LLM sees it AND before returning to callers. Defense-in-depth with Citadel output scanning.

### 7.2 ReliableProvider Pattern — TO ADOPT
Port ZeroClaw's three-level failover to `model_router.py`:
- Error classification (retryable vs permanent vs rate-limited vs context-exceeded)
- Exponential backoff with Retry-After parsing
- Multi-key rotation for high-throughput pods
- Model fallback chains for TEE routing (Tinfoil → Redpill → standard)
- Structured error aggregation for debugging

### 7.3 Vtable Pattern — PARTIALLY ADOPTED
TrustMesh's Zig kernel already uses vtable-like patterns internally. The C ABI boundary is similar to NullClaw's approach. Consider adopting for transport abstraction (Direct HTTP / Tunnel / Relay).

### 7.4 Channel Architecture — DON'T DUPLICATE
ZeroClaw's 18-channel, 20K-line messaging system is mature and battle-tested. TrustMesh shouldn't rebuild this. Instead, TrustMesh should be the vault/trust backend that claw agents connect to via MCP.

### 7.5 Sandbox Architecture — LEARN FOR FUTURE
If TrustMesh ever adds tool execution, adopt the 5-backend sandbox model with auto-detection. For now, TrustMesh has no shell tools, so this is informational.

### 7.6 Observability — TO ADOPT
Add basic metrics to TrustMesh pods: request latency, federation sync health, trust resolution time, vault operations count. ZeroClaw's Observer trait (Prometheus + OTEL) is the reference.

### 7.7 Hardware Integration — FUTURE VISION
ZeroClaw's Peripheral trait + 5 firmware targets opens paths for:
- Smart home pod: TrustMesh vault + claw hardware control
- Health monitoring: sensor data → encrypted capsules
- Edge computing: local inference + vault + federation

### 7.8 Draft Update Pattern for Streaming
ZeroClaw channels support progressive message edits: `send_draft()` → `update_draft()` → `finalize_draft()`. TrustMesh's agent could adopt this for streaming responses to the web UI.

---

## 8. The Integration Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                           YOUR DEVICE                                     │
│                                                                           │
│  ┌──────────────────────────┐    ┌─────────────────────────────────────┐  │
│  │   CLAW AGENT              │    │   TRUSTMESH POD                     │  │
│  │   (ZeroClaw or NullClaw)  │    │   (Your Personal Vault)             │  │
│  │                            │    │                                     │  │
│  │  Brain:                    │    │  Memory:                            │  │
│  │  - 22+ LLM Providers      │◄──►│  - Encrypted Vault (AES-256-GCM)   │  │
│  │  - ReliableProvider        │MCP │  - FTS5 Search (Zig kernel)        │  │
│  │  - Model Routing           │    │  - Timeline Engine                  │  │
│  │                            │    │                                     │  │
│  │  Hands:                    │    │  Identity:                          │  │
│  │  - 30+ Tools (sandboxed)   │    │  - DID (ed25519)                   │  │
│  │  - 5 Sandbox Backends      │    │  - UCAN Tokens                     │  │
│  │  - Hardware Peripherals    │    │  - Session Auth + Fingerprint      │  │
│  │                            │    │                                     │  │
│  │  Voice:                    │    │  Social Fabric:                     │  │
│  │  - 18 Messaging Channels   │    │  - Trust Networks (3-tier)         │  │
│  │  - Draft Update Streaming  │    │  - Pod Federation (P2P)            │  │
│  │  - Allowlist Security      │    │  - Ghost Users (cross-pod)         │  │
│  │                            │    │  - Gossip Protocol                  │  │
│  │  Security:                 │    │                                     │  │
│  │  - Secret Scrubbing        │    │  Security:                          │  │
│  │  - Command Injection Guard │    │  - Citadel AI Security             │  │
│  │  - Env Sanitization        │    │  - Trust-Aware Output Scanning     │  │
│  │  - ChaCha20-Poly1305       │    │  - TEE Model Routing               │  │
│  └──────────────────────────┘    │  - Federation Auth (ed25519+nonce)  │  │
│           │                       └─────────────────────────────────────┘  │
│           │                              │                                 │
│           ▼                              ▼                                 │
│  ┌──────────────────────┐    ┌─────────────────────────────────────────┐  │
│  │ Telegram / Discord    │    │ Peer Pods (Family, Doctor, Work)        │  │
│  │ WhatsApp / Signal     │    │ Trust Pools (Health Team, Legal)        │  │
│  │ iMessage / Matrix     │    │ Public Registry (Agent Discovery)       │  │
│  │ Slack / IRC / Email   │    │ A2A Protocol (Agent-to-Agent)           │  │
│  │ Hardware (ESP32/RPi)  │    │ TEE Enclaves (Tinfoil, Redpill)        │  │
│  └──────────────────────┘    └─────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

**Connection**: MCP protocol (Model Context Protocol). TrustMesh already has an MCP server (`src/mcp_server.py`). A claw agent connects via stdio JSON-RPC, gains access to vault search, trust queries, timeline operations, and federation — all through the trust layer.

---

## 9. Value Proposition (For Everyday People)

### What TrustMesh Gives You

**Your AI, Your Rules, Your Data.**

Think of TrustMesh as a personal safe that your AI assistant uses. Everything your AI knows about you — your health records, family conversations, financial information, work documents — is locked in YOUR safe, encrypted with YOUR key, on YOUR device.

**Three things that set TrustMesh apart:**

1. **Your data stays yours.** Not on OpenAI's servers. Not on Google's cloud. In your encrypted vault, on your device. When your AI needs to answer a question, it unlocks just what it needs, answers, and locks it back up. The encryption keys never leave Zig memory — even the Python process can't see them.

2. **You control who knows what.** Your doctor's AI can ask yours about your medications — and get an answer. A stranger's AI asking the same question gets nothing. You set the trust levels: family, healthcare team, work colleagues, public. Each circle sees only what you've shared with them. Citadel security scans every question AND every answer to prevent information leaks.

3. **Your AI talks to other AIs — safely.** Your AI can coordinate with your spouse's AI about dinner plans, your doctor's AI about appointments, your accountant's AI about tax documents. All through encrypted, trust-verified, DID-authenticated channels. No platform middleman. Every cross-pod message is signed with ed25519 and protected against replay attacks.

### Real-World Scenarios

**Health**: Your doctor asks their AI about your medications. Their AI contacts yours through a verified trust connection. Your AI checks trust level (doctor = healthcare team = network trust), decrypts your health capsules, and shares the medication list. Financial data, family conversations, work documents — invisible. Citadel scans the response to ensure no accidental data leaks.

**Emergency**: A paramedic scans your emergency QR code. Their AI gets a time-limited UCAN token (role: paramedic, expires: 1 hour). Your AI shares allergies, blood type, and current medications — nothing else. After the token expires, access is permanently revoked.

**Family**: Your mom's AI reminds yours about Sunday dinner. Your AI checks the timeline kernel, sees a conflict, and suggests Tuesday instead — all through encrypted pod-to-pod communication. Nobody else can see this exchange.

**Work**: Your company runs an organization pod. When you join, your personal pod connects to the company pool. You share work-relevant documents with colleagues automatically. When you leave the company, you disconnect — your personal data stays yours, ghost users are cleaned up, and the company loses access to everything you didn't explicitly share.

### What Claw Agents Add to This

A claw agent (ZeroClaw or NullClaw) connected to your TrustMesh pod gives you the full picture:

- **Claw** handles talking to you (18 messaging channels), acting for you (30+ sandboxed tools), thinking for you (22+ LLM providers with failover)
- **TrustMesh** handles remembering for you (encrypted vault), trusting for you (3-tier networks), and coordinating for you (pod federation + timeline)

Together: a personal AI that can talk on WhatsApp, search your medical records, check your calendar, coordinate with your doctor's AI, and never leak a single piece of data to anyone you haven't explicitly trusted.

---

## 10. Adoption Status

| Pattern | Source | Status | Details |
|---------|--------|--------|---------|
| Secret prefix scrubbing | NullClaw | **COMPLETE** | 27 prefixes, 61 tests, integrated in agents.py |
| ReliableProvider | ZeroClaw | **PLANNED** | Port to model_router.py for TEE failover |
| Vtable pattern | NullClaw | **PARTIAL** | Used in Zig kernel, consider for transport |
| Observability | ZeroClaw | **PLANNED** | Prometheus metrics for pod health |
| Channel system | ZeroClaw | **LEARN** | Don't duplicate — connect via MCP |
| Sandbox system | Both | **LEARN** | Adopt if TrustMesh adds tool execution |
| Hardware/firmware | ZeroClaw | **FUTURE** | Smart home, health sensors, edge pods |
| Draft streaming | ZeroClaw | **FUTURE** | Progressive UI updates for agent responses |
| Hybrid search merge | Both | **ADOPTED** | FTS5 in Zig kernel, trust-filtered |
| Env sanitization | NullClaw | **LEARN** | Shell tool safe-env pattern |

---

## Appendix A: Trait/Vtable Reference

### ZeroClaw — 8 Core Traits

| Trait | File | Methods | Purpose |
|-------|------|---------|---------|
| `Provider` | `providers/traits.rs` (903 LoC) | 12 (6 required, 6 default) | LLM inference |
| `Channel` | `channels/traits.rs` (221 LoC) | 10 (3 required, 7 default) | Messaging platforms |
| `Tool` | `tools/traits.rs` (121 LoC) | 4 (4 required) | Agent capabilities |
| `Sandbox` | `security/traits.rs` (119 LoC) | 4 (4 required) | OS-level isolation |
| `Memory` | `memory/traits.rs` (133 LoC) | 7 (7 required) | Knowledge persistence |
| `Observer` | `observability/traits.rs` (199 LoC) | 4 (2 required, 2 default) | Telemetry |
| `RuntimeAdapter` | `runtime/traits.rs` (143 LoC) | 6 (5 required, 1 default) | Platform abstraction |
| `Peripheral` | `peripherals/traits.rs` (76 LoC) | 5 (5 required) | Hardware I/O |

### NullClaw — 5 Vtable Interfaces

| Vtable | File | Slots | Purpose |
|--------|------|-------|---------|
| `Provider` | `providers/root.zig` (1657 LoC) | 9 (5 required + 4 optional) | LLM inference |
| `Channel` | `channels/root.zig` | 6 | Messaging platforms |
| `Tool` | `tools/root.zig` | 4 | Agent capabilities |
| `Sandbox` | `security/sandbox.zig` | 4 | OS-level isolation |
| `Memory` | `memory/root.zig` | 5 | Knowledge persistence |

### TrustMesh — Zig C ABI Exports (78 total)

| Module | Exports | Purpose |
|--------|---------|---------|
| Crypto | 14 | AES-GCM, Argon2id, Ed25519, SHA-256, DID |
| Session | 9 | Session store, validation, fingerprinting |
| Rate Limit | 7 | Per-user/DID rate limiting |
| Trust | 1 | Trust level resolution |
| Timeline | 17 | Temporal execution engine |
| FTS | 6 | Full-text search (SQLite FTS5) |
| DB | 2 | SQLite lifecycle |
| Federation Auth | 4 | Ed25519 sign/verify for cross-pod |
| Transit | 4 | Vault key storage, encrypt/decrypt |
| HTTP/Router | 14 | Zig HTTP proxy, auth handlers |
| **Total** | **78** | |
