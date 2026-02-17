// db.zig — Thin SQLite C API wrapper for PodOS kernel.
// Opens the same trustmesh.db as the Python backend (WAL mode supports concurrent readers).

const std = @import("std");
const c = @cImport(@cInclude("sqlite3.h"));

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
        if (rc != c.SQLITE_OK or stmt == null) return SqliteError.PrepareFailed;
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

    /// Step the statement. Returns true if there's a row (SQLITE_ROW), false if done.
    pub fn step(self: *Statement) SqliteError!bool {
        const rc = c.sqlite3_step(self.handle);
        if (rc == c.SQLITE_ROW) return true;
        if (rc == c.SQLITE_DONE) return false;
        return SqliteError.StepFailed;
    }

    pub fn getText(self: *Statement, col: c_int) ?[*:0]const u8 {
        return c.sqlite3_column_text(self.handle, col);
    }

    pub fn getDouble(self: *Statement, col: c_int) f64 {
        return c.sqlite3_column_double(self.handle, col);
    }

    pub fn getInt(self: *Statement, col: c_int) c_int {
        return c.sqlite3_column_int(self.handle, col);
    }

    pub fn reset(self: *Statement) void {
        _ = c.sqlite3_reset(self.handle);
        _ = c.sqlite3_clear_bindings(self.handle);
    }

    pub fn finalize(self: *Statement) void {
        _ = c.sqlite3_finalize(self.handle);
    }
};
