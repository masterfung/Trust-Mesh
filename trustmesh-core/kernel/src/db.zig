// db.zig — Thin SQLite C API wrapper for PodOS kernel.
// Opens the same trustmesh.db as the Python backend (WAL mode supports concurrent readers).

const std = @import("std");
pub const c = @cImport(@cInclude("sqlite3.h"));

pub const SqliteError = error{
    CantOpen,
    ExecFailed,
    PrepareFailed,
    BindFailed,
    StepFailed,
    NullHandle,
};

// ═══════════════════════════════════════════
//  Database
// ═══════════════════════════════════════════

pub const Database = struct {
    handle: *c.sqlite3,

    /// Open a SQLite database with WAL, busy_timeout, and secure_delete.
    pub fn open(path: [*:0]const u8) SqliteError!Database {
        var db: ?*c.sqlite3 = null;
        const rc = c.sqlite3_open(path, &db);
        if (rc != c.SQLITE_OK or db == null) {
            if (db) |d| _ = c.sqlite3_close(d);
            return SqliteError.CantOpen;
        }
        var self = Database{ .handle = db.? };
        // Match pragmas from src/database.py
        self.exec("PRAGMA journal_mode=WAL") catch {};
        self.exec("PRAGMA busy_timeout=5000") catch {};
        self.exec("PRAGMA secure_delete=ON") catch {};
        return self;
    }

    pub fn close(self: *Database) void {
        _ = c.sqlite3_close(self.handle);
    }

    /// Create credential tables (vault_secrets, credential_shares,
    /// credential_ops, credential_fts). Safe to call on existing DB.
    pub fn initCredentialTables(self: *Database) SqliteError!void {
        try self.exec(
            \\CREATE TABLE IF NOT EXISTS vault_secrets (
            \\    id TEXT PRIMARY KEY,
            \\    owner_id TEXT NOT NULL,
            \\    name TEXT NOT NULL,
            \\    service TEXT NOT NULL DEFAULT '',
            \\    category TEXT NOT NULL DEFAULT '',
            \\    secret_encrypted BLOB NOT NULL,
            \\    scoped_tools TEXT NOT NULL DEFAULT '[]',
            \\    expires_at TEXT,
            \\    rotation_interval_days INTEGER,
            \\    is_active INTEGER NOT NULL DEFAULT 1,
            \\    use_count INTEGER NOT NULL DEFAULT 0,
            \\    last_used_at TEXT,
            \\    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            \\    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            \\)
        );
        try self.exec(
            \\CREATE INDEX IF NOT EXISTS idx_vault_secrets_owner
            \\    ON vault_secrets(owner_id, is_active)
        );
        try self.exec(
            \\CREATE TABLE IF NOT EXISTS credential_shares (
            \\    id TEXT PRIMARY KEY,
            \\    credential_id TEXT NOT NULL,
            \\    grantor_id TEXT NOT NULL,
            \\    grantee_id TEXT NOT NULL,
            \\    grantee_type TEXT NOT NULL CHECK(grantee_type IN ('user','network')),
            \\    expires_at TEXT NOT NULL,
            \\    max_uses INTEGER,
            \\    use_count INTEGER NOT NULL DEFAULT 0,
            \\    can_reshare INTEGER NOT NULL DEFAULT 0,
            \\    secret_reencrypted BLOB,
            \\    revoked_at TEXT,
            \\    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            \\)
        );
        try self.exec(
            \\CREATE INDEX IF NOT EXISTS idx_credential_shares_grantee
            \\    ON credential_shares(grantee_id, grantee_type)
            \\    WHERE revoked_at IS NULL
        );
        try self.exec(
            \\CREATE TABLE IF NOT EXISTS credential_ops (
            \\    id INTEGER PRIMARY KEY AUTOINCREMENT,
            \\    credential_id TEXT NOT NULL,
            \\    operation TEXT NOT NULL CHECK(operation IN (
            \\        'created','updated','used','rotated',
            \\        'shared','share_revoked','share_expired','deactivated','deleted'
            \\    )),
            \\    actor_id TEXT NOT NULL,
            \\    tool_name TEXT,
            \\    share_id TEXT,
            \\    ip_fingerprint TEXT,
            \\    decision TEXT NOT NULL DEFAULT 'allowed'
            \\        CHECK(decision IN ('allowed','denied')),
            \\    details TEXT,
            \\    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            \\)
        );
        try self.exec(
            \\CREATE INDEX IF NOT EXISTS idx_credential_ops_credential
            \\    ON credential_ops(credential_id, created_at)
        );
        try self.exec(
            \\CREATE INDEX IF NOT EXISTS idx_credential_ops_actor
            \\    ON credential_ops(actor_id, created_at)
        );
        try self.exec(
            \\CREATE VIRTUAL TABLE IF NOT EXISTS credential_fts USING fts5(
            \\    credential_id UNINDEXED,
            \\    name,
            \\    service,
            \\    category UNINDEXED,
            \\    tokenize='porter unicode61'
            \\)
        );
    }

    /// Execute a simple SQL statement (no results).
    pub fn exec(self: *Database, sql: [*:0]const u8) SqliteError!void {
        var err_msg: [*c]u8 = null;
        const rc = c.sqlite3_exec(self.handle, sql, null, null, &err_msg);
        if (err_msg != null) c.sqlite3_free(err_msg);
        if (rc != c.SQLITE_OK) return SqliteError.ExecFailed;
    }

    /// Prepare a SQL statement.
    pub fn prepare(self: *Database, sql: [*:0]const u8) SqliteError!Statement {
        var stmt: ?*c.sqlite3_stmt = null;
        const rc = c.sqlite3_prepare_v2(self.handle, sql, -1, &stmt, null);
        if (rc != c.SQLITE_OK or stmt == null) {
            const errmsg: [*c]const u8 = c.sqlite3_errmsg(self.handle);
            if (errmsg != null) {
                std.log.err("sqlite3_prepare_v2 failed: rc={d} sql={s} err={s}", .{ rc, sql, errmsg });
            } else {
                std.log.err("sqlite3_prepare_v2 failed: rc={d} sql={s}", .{ rc, sql });
            }
            return SqliteError.PrepareFailed;
        }
        return Statement{ .handle = stmt.? };
    }
};

// ═══════════════════════════════════════════
//  Statement
// ═══════════════════════════════════════════

pub const Statement = struct {
    handle: *c.sqlite3_stmt,

    pub fn bindText(self: *Statement, col: c_int, text: [*]const u8, len: c_int) SqliteError!void {
        // Use SQLITE_STATIC (null) — safe because we always step() right after bind,
        // and the caller's data outlives the step call.
        const rc = c.sqlite3_bind_text(self.handle, col, text, len, null);
        if (rc != c.SQLITE_OK) return SqliteError.BindFailed;
    }

    pub fn bindInt(self: *Statement, col: c_int, val: c_int) SqliteError!void {
        const rc = c.sqlite3_bind_int(self.handle, col, val);
        if (rc != c.SQLITE_OK) return SqliteError.BindFailed;
    }

    pub fn bindInt64(self: *Statement, col: c_int, val: i64) SqliteError!void {
        const rc = c.sqlite3_bind_int64(self.handle, col, val);
        if (rc != c.SQLITE_OK) return SqliteError.BindFailed;
    }

    pub fn bindBlob(self: *Statement, col: c_int, data: [*]const u8, len: c_int) SqliteError!void {
        // Use SQLITE_STATIC (null) — safe because we always step() right after bind.
        const rc = c.sqlite3_bind_blob(self.handle, col, data, len, null);
        if (rc != c.SQLITE_OK) return SqliteError.BindFailed;
    }

    /// Step the statement. Returns true if there's a row (SQLITE_ROW), false if done.
    pub fn step(self: *Statement) SqliteError!bool {
        const rc = c.sqlite3_step(self.handle);
        if (rc == c.SQLITE_ROW) return true;
        if (rc == c.SQLITE_DONE) return false;
        std.log.err("sqlite3_step failed: rc={d}", .{rc});
        return SqliteError.StepFailed;
    }

    pub fn getText(self: *Statement, col: c_int) ?[*:0]const u8 {
        return c.sqlite3_column_text(self.handle, col);
    }

    pub fn getDouble(self: *Statement, col: c_int) f64 {
        return c.sqlite3_column_double(self.handle, col);
    }

    /// Read a BLOB column. Returns null if the column is NULL.
    /// The returned slice points into SQLite-managed memory valid until the next step/finalize.
    pub fn getBlob(self: *Statement, col: c_int) ?[]const u8 {
        const ptr: ?[*]const u8 = @ptrCast(c.sqlite3_column_blob(self.handle, col));
        if (ptr == null) return null;
        const len = c.sqlite3_column_bytes(self.handle, col);
        if (len <= 0) return null;
        return ptr.?[0..@intCast(len)];
    }

    pub fn getInt(self: *Statement, col: c_int) c_int {
        return c.sqlite3_column_int(self.handle, col);
    }

    pub fn getInt64(self: *Statement, col: c_int) i64 {
        return c.sqlite3_column_int64(self.handle, col);
    }

    pub fn reset(self: *Statement) void {
        _ = c.sqlite3_reset(self.handle);
        _ = c.sqlite3_clear_bindings(self.handle);
    }

    pub fn finalize(self: *Statement) void {
        _ = c.sqlite3_finalize(self.handle);
    }
};
