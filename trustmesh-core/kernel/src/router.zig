// router.zig — Route dispatch table for the Zig HTTP server.
// Maps (method, path_prefix) → native handler fn or proxy.
//
// Route matching is prefix-based and checked in registration order.
// The first matching entry wins. Unmatched routes fall through to the proxy.

const std = @import("std");
const http = @import("http.zig");

// Handler function signature
pub const HandlerFn = *const fn (ctx: *http.RequestContext) anyerror!void;

const RouteEntry = struct {
    method: std.http.Method,
    // Exact match if exact=true, prefix match otherwise
    path: []const u8,
    exact: bool,
    handler: HandlerFn,
};

// Static route table — registered at startup.
// We keep a fixed-size array to avoid allocator dependency at global scope.
const MAX_ROUTES = 96;
var routes: [MAX_ROUTES]RouteEntry = undefined;
var route_count: usize = 0;

/// Register a native handler for an exact path.
pub fn addExact(method: std.http.Method, path: []const u8, handler: HandlerFn) void {
    if (route_count >= MAX_ROUTES) return;
    routes[route_count] = .{
        .method = method,
        .path = path,
        .exact = true,
        .handler = handler,
    };
    route_count += 1;
}

/// Register a native handler for a path prefix.
pub fn addPrefix(method: std.http.Method, prefix: []const u8, handler: HandlerFn) void {
    if (route_count >= MAX_ROUTES) return;
    routes[route_count] = .{
        .method = method,
        .path = prefix,
        .exact = false,
        .handler = handler,
    };
    route_count += 1;
}

/// Find a native handler for (method, path). Returns null → proxy to Python.
/// OPTIONS always returns null so CORS preflight is handled at the http layer.
pub fn findHandler(method: std.http.Method, path: []const u8) ?HandlerFn {
    if (method == .OPTIONS) return null;
    for (routes[0..route_count]) |entry| {
        if (entry.method != method) continue;
        if (entry.exact) {
            if (std.mem.eql(u8, entry.path, path)) return entry.handler;
        } else {
            if (std.mem.startsWith(u8, path, entry.path)) return entry.handler;
        }
    }
    return null;
}

/// Reset all routes (test helper).
pub fn reset() void {
    route_count = 0;
}
