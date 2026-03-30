const std = @import("std");

fn addSqlite(mod: *std.Build.Module) void {
    // Bundle sqlite3 amalgamation for zero-dependency cross-platform builds.
    // Enables FTS5 full-text search. No system library needed at build or runtime.
    mod.link_libc = true; // Required for cross-compilation: lets Zig supply bundled libc headers.
    mod.addCSourceFile(.{
        .file = mod.owner.path("sqlite/sqlite3.c"),
        .flags = &.{"-DSQLITE_ENABLE_FTS5"},
    });
    mod.addSystemIncludePath(mod.owner.path("sqlite"));
}

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // ── Single "podos" module rooted at main.zig ──
    // All source files are pulled in via main.zig's pub imports.
    // Tests import this module as @import("podos").
    const podos_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    addSqlite(podos_mod);

    // ── Shared library (libpodos.dylib / libpodos.so) ──
    const lib_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    addSqlite(lib_mod);

    const lib = b.addLibrary(.{
        .linkage = .dynamic,
        .name = "podos",
        .root_module = lib_mod,
    });
    b.installArtifact(lib);

    // ── podos-server: standalone HTTP proxy executable (Phase 3) ──
    // Entry point: src/server_main.zig
    // Listens on :8000, proxies unhandled routes to Python FastAPI on :9000.
    const server_mod = b.createModule(.{
        .root_source_file = b.path("src/server_main.zig"),
        .target = target,
        .optimize = optimize,
    });
    server_mod.addImport("podos", podos_mod);
    // No addSqlite(server_mod) — server_main.zig only uses sqlite3 via podos module import.

    const server_exe = b.addExecutable(.{
        .name = "podos-server",
        .root_module = server_mod,
    });
    b.installArtifact(server_exe);

    // Shorthand: zig build server
    const server_step = b.step("server", "Build podos-server HTTP proxy binary");
    server_step.dependOn(&b.addInstallArtifact(server_exe, .{}).step);

    // ── Unit tests ──
    const test_files = [_][]const u8{
        "tests/test_types.zig",
        "tests/test_entry.zig",
        "tests/test_event.zig",
        "tests/test_cron.zig",
        "tests/test_dag.zig",
        "tests/test_resolution.zig",
        "tests/test_state.zig",
        "tests/test_log.zig",
        "tests/test_timeline.zig",
        "tests/test_fts.zig",
        "tests/test_crypto.zig",
        "tests/test_trust.zig",
        "tests/test_session.zig",
        "tests/test_rate_limit.zig",
        "tests/test_timeline_persist.zig",
        "tests/test_transit.zig",
        "tests/test_federation_auth.zig",
        "tests/test_credential.zig",
        "tests/test_credential_audit.zig",
    };

    const test_step = b.step("test", "Run all kernel tests");

    for (test_files) |test_file| {
        const test_module = b.createModule(.{
            .root_source_file = b.path(test_file),
            .target = target,
            .optimize = optimize,
        });
        test_module.addImport("podos", podos_mod);
        // No addSqlite(test_module) — tests use sqlite3 via podos module import.
        // Tests that directly import sqlite3 functions do so through podos, so one copy suffices.

        const t = b.addTest(.{ .root_module = test_module });
        const run_t = b.addRunArtifact(t);
        test_step.dependOn(&run_t.step);
    }
}
