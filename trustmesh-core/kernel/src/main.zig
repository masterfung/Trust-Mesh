// PodOS Timeline Kernel — C ABI exports
// This is the entry point for the shared library (libpodos.dylib/.so).
// Python loads this via ctypes and calls exported functions.

pub const types = @import("types.zig");
pub const entry = @import("entry.zig");
pub const event = @import("event.zig");
pub const cron = @import("cron.zig");
pub const dag = @import("dag.zig");
pub const resolution = @import("resolution.zig");
pub const state = @import("state.zig");
pub const log = @import("log.zig");
pub const timeline = @import("timeline.zig");

// ── C ABI Exports (Phase 1.9) ──
// Will be populated after all subsystems are implemented.

export fn podos_version() callconv(.c) u32 {
    return 1; // v0.0.1
}
