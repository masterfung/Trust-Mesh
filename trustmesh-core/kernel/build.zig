const std = @import("std");

fn addSqlite(mod: *std.Build.Module) void {
    // macOS Homebrew keg-only sqlite paths
    mod.addSystemIncludePath(.{ .cwd_relative = "/opt/homebrew/opt/sqlite/include" });
    mod.addLibraryPath(.{ .cwd_relative = "/opt/homebrew/opt/sqlite/lib" });
    mod.linkSystemLibrary("sqlite3", .{});
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
    };

    const test_step = b.step("test", "Run all kernel tests");

    for (test_files) |test_file| {
        const test_module = b.createModule(.{
            .root_source_file = b.path(test_file),
            .target = target,
            .optimize = optimize,
        });
        test_module.addImport("podos", podos_mod);
        addSqlite(test_module);

        const t = b.addTest(.{ .root_module = test_module });
        const run_t = b.addRunArtifact(t);
        test_step.dependOn(&run_t.step);
    }
}
