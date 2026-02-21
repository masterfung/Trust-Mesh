// server_main.zig — PodOS standalone HTTP server entry point.
//
// Listens on :8000, proxies unhandled routes to Python FastAPI on :9000.
// Routes migrate here one group at a time (Phase 3b/3c).
//
// Environment variables read at startup:
//   PODOS_PORT           Public port (default: 8000)
//   PODOS_PYTHON_PORT    Python backend port (default: 9000)
//   PODOS_DB_PATH        SQLite DB path (default: ./trustmesh.db)
//   PODOS_PROXY_SECRET   Shared secret for proxy→Python auth (C2)

const std = @import("std");
const podos = @import("podos");
// http, router, auth_handler are in the same module as server_main (root module)
const http_mod = @import("http.zig");
const router = @import("router.zig");
const common_handler = @import("handlers/common.zig");
const auth_handler = @import("handlers/auth.zig");
const cred_handler = @import("handlers/credentials.zig");
const onboard_handler = @import("handlers/onboard.zig");
const memory_handler = @import("handlers/memory.zig");
const notifications_handler = @import("handlers/notifications.zig");
const audit_handler = @import("handlers/audit.zig");
const pin_handler = @import("handlers/pin.zig");
const users_handler = @import("handlers/users.zig");
const connections_handler = @import("handlers/connections.zig");
const capsules_handler = @import("handlers/capsules.zig");

// ── Globals ──
var _gpa = std.heap.GeneralPurposeAllocator(.{}){};

fn getEnvU16(allocator: std.mem.Allocator, name: []const u8, default: u16) u16 {
    const val = std.process.getEnvVarOwned(allocator, name) catch return default;
    defer allocator.free(val);
    return std.fmt.parseInt(u16, val, 10) catch default;
}

fn getEnvStr(allocator: std.mem.Allocator, name: []const u8, default_val: []const u8) []const u8 {
    return std.process.getEnvVarOwned(allocator, name) catch return default_val;
}

pub fn main() !void {
    defer _ = _gpa.deinit();
    const allocator = _gpa.allocator();

    // ── Parse config from environment ──
    const listen_port = getEnvU16(allocator, "PODOS_PORT", 8000);
    const python_port = getEnvU16(allocator, "PODOS_PYTHON_PORT", 9000);
    const db_path_str = getEnvStr(allocator, "PODOS_DB_PATH", "./trustmesh.db");
    defer if (!std.mem.eql(u8, db_path_str, "./trustmesh.db")) allocator.free(db_path_str);

    std.log.info("Starting PodOS HTTP server", .{});
    std.log.info("  Public port:  :{d}", .{listen_port});
    std.log.info("  Python proxy: 127.0.0.1:{d}", .{python_port});

    // ── Init Zig subsystems via internal module functions ──

    // Session store
    var sess_store = podos.session.SessionStore.init(allocator);
    defer sess_store.deinit();

    // Rate limiter
    var rate_limiter = podos.rate_limit.RateLimiter.init(allocator);
    defer rate_limiter.deinit();

    // Transit keyring
    var transit_engine = podos.transit.TransitEngine.init(allocator);
    defer transit_engine.deinit();

    // Federation auth nonce cache (accessed through podos module)
    podos.federation_auth.initNonceCache(allocator);
    defer podos.federation_auth.deinitNonceCache();

    // DB
    const db_path_z = try allocator.dupeZ(u8, db_path_str);
    defer allocator.free(db_path_z);
    var database = try podos.db.Database.open(db_path_z);
    defer database.close();
    // Create credential tables (idempotent — safe on existing DB)
    database.initCredentialTables() catch |err| {
        std.log.warn("initCredentialTables failed: {}", .{err});
    };
    std.log.info("  DB: {s}", .{db_path_str});

    // ── Give proxy layer access to session store (for X-Verified-User-Id injection) ──
    http_mod.setSessionStore(&sess_store);

    // ── Common handler utilities (shared session store for requireAuth) ──
    common_handler.setSessionStore(&sess_store);

    // ── Register native route handlers ──
    // Phase 3b: Auth routes (login, logout, me)
    auth_handler.setDatabase(&database);
    auth_handler.setSessionStore(&sess_store);
    auth_handler.setTransitEngine(&transit_engine);
    auth_handler.registerRoutes();

    // Phase 7: Credential store routes
    cred_handler.setDatabase(&database);
    cred_handler.setTransitEngine(&transit_engine);
    cred_handler.setSessionStore(&sess_store);
    cred_handler.registerRoutes();

    // Onboard routes (pod initialization)
    onboard_handler.setDatabase(&database);
    onboard_handler.setSessionStore(&sess_store);
    onboard_handler.setTransitEngine(&transit_engine);
    onboard_handler.setRateLimiter(&rate_limiter);
    onboard_handler.registerRoutes();

    // Memory API routes (ZeroClaw/NullClaw backend)
    memory_handler.setDatabase(&database);
    memory_handler.setSessionStore(&sess_store);
    memory_handler.setTransitEngine(&transit_engine);
    memory_handler.setRateLimiter(&rate_limiter);
    memory_handler.registerRoutes();

    // Notifications (polling hot path)
    notifications_handler.setDatabase(&database);
    notifications_handler.registerRoutes();

    // Audit log reads
    audit_handler.setDatabase(&database);
    audit_handler.registerRoutes();

    // PIN management
    pin_handler.setDatabase(&database);
    pin_handler.setRateLimiter(&rate_limiter);
    pin_handler.registerRoutes();

    // User reads (page load hot path)
    users_handler.setDatabase(&database);
    users_handler.registerRoutes();

    // Connection reads (dashboard hot path)
    connections_handler.setDatabase(&database);
    connections_handler.registerRoutes();

    // Capsule CRUD (vault hot path)
    capsules_handler.setDatabase(&database);
    capsules_handler.setTransitEngine(&transit_engine);
    capsules_handler.registerRoutes();

    // ── Start HTTP server ──
    // C2: Read proxy shared secret from environment
    const proxy_secret = getEnvStr(allocator, "PODOS_PROXY_SECRET", "");
    if (proxy_secret.len > 0) {
        std.log.info("  Proxy secret: configured ({d} bytes)", .{proxy_secret.len});
    } else {
        std.log.warn("  Proxy secret: NOT SET (Python backend unprotected)", .{});
    }

    const config = http_mod.Config{
        .listen_port = listen_port,
        .python_port = python_port,
        .python_host = "127.0.0.1",
        .proxy_secret = proxy_secret,
    };

    var http_server = http_mod.Server.init(config);

    // Handle SIGINT/SIGTERM for clean shutdown
    const SigContext = struct {
        var srv: ?*http_mod.Server = null;
        fn handle(sig: c_int) callconv(.c) void {
            _ = sig;
            std.log.info("Shutdown signal received", .{});
            if (srv) |s| s.stop();
        }
    };
    SigContext.srv = &http_server;
    // sigaction is void-returning in 0.15.2, use sigemptyset() for mask
    const sigact = std.posix.Sigaction{
        .handler = .{ .handler = SigContext.handle },
        .mask = std.posix.sigemptyset(),
        .flags = 0,
    };
    std.posix.sigaction(std.posix.SIG.INT, &sigact, null);
    std.posix.sigaction(std.posix.SIG.TERM, &sigact, null);

    // Run server blocking in main thread
    std.log.info("Listening on :{d} (proxy → :{d})", .{ listen_port, python_port });

    const addr = try std.net.Address.parseIp4("0.0.0.0", listen_port);
    var listener = try addr.listen(.{ .reuse_address = true });
    defer listener.deinit();

    // Connection semaphore: cap concurrent connections at 256
    const MAX_CONCURRENT: usize = 256;
    var active_connections = std.atomic.Value(usize).init(0);

    while (!http_server._stop.load(.acquire)) {
        const conn = listener.accept() catch |err| switch (err) {
            error.WouldBlock => continue,
            else => {
                std.log.warn("Accept error: {}", .{err});
                continue;
            },
        };

        // Reject if at capacity
        const current = active_connections.load(.acquire);
        if (current >= MAX_CONCURRENT) {
            std.log.warn("Max connections reached ({d}), rejecting", .{MAX_CONCURRENT});
            conn.stream.close();
            continue;
        }

        const t = std.Thread.spawn(.{}, struct {
            fn run(c: std.net.Server.Connection, cfg: *const http_mod.Config, counter: *std.atomic.Value(usize)) void {
                _ = counter.fetchAdd(1, .monotonic);
                defer _ = counter.fetchSub(1, .monotonic);
                http_mod.handleConnection(c, cfg);
            }
        }.run, .{ conn, &http_server.config, &active_connections }) catch |err| {
            std.log.warn("Failed to spawn handler thread: {}", .{err});
            conn.stream.close();
            continue;
        };
        t.detach();
    }

    std.log.info("PodOS HTTP server stopped.", .{});
}
