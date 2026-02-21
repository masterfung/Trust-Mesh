// json.zig — Thin JSON helpers for the Zig HTTP server.
// Wraps std.json with convenience functions for common patterns:
// - Parsing request bodies into typed structs
// - Serializing typed structs + ad-hoc error objects to []u8

const std = @import("std");
const Allocator = std.mem.Allocator;

pub const JsonError = error{
    ParseFailed,
    SerializeFailed,
    OutOfMemory,
};

/// Parse a JSON slice into type T. Caller owns the returned ParseResult and must call .deinit().
pub fn parse(comptime T: type, allocator: Allocator, data: []const u8) JsonError!std.json.Parsed(T) {
    return std.json.parseFromSlice(T, allocator, data, .{
        .ignore_unknown_fields = true,
        .allocate = .alloc_always,
    }) catch return JsonError.ParseFailed;
}

/// Serialize value to a newly allocated []u8. Caller must free.
pub fn stringify(val: anytype, allocator: Allocator) JsonError![]u8 {
    return std.json.Stringify.valueAlloc(allocator, val, .{}) catch return JsonError.SerializeFailed;
}

/// Serialize value to a fixed-size buffer. Returns bytes written.
pub fn stringifyBuf(val: anytype, buf: []u8) JsonError!usize {
    var writer: std.io.Writer = .fixed(buf);
    std.json.Stringify.value(val, .{}, &writer) catch return JsonError.SerializeFailed;
    return writer.end;
}

/// Convenience: produce {"error":"<msg>"} in a fixed buffer.
/// msg is treated as a trusted error message (not user input) but escaped for safety.
pub fn errorJson(buf: []u8, msg: []const u8) []const u8 {
    var esc_buf: [256]u8 = undefined;
    const esc_len = escapeJsonString(msg, &esc_buf) catch return "{\"error\":\"internal\"}";
    const result = std.fmt.bufPrint(buf, "{{\"error\":\"{s}\"}}", .{esc_buf[0..esc_len]}) catch return "{\"error\":\"internal\"}";
    return result;
}

/// Convenience: produce {"status":"<val>"} in a fixed buffer.
pub fn statusJson(buf: []u8, val: []const u8) []const u8 {
    const result = std.fmt.bufPrint(buf, "{{\"status\":\"{s}\"}}", .{val}) catch return "{\"status\":\"ok\"}";
    return result;
}

// ═══════════════════════════════════════════
//  JSON STRING ESCAPING
// ═══════════════════════════════════════════

/// Escape a string for safe inclusion as a JSON string value.
/// Escapes: " → \", \ → \\, control chars → \uXXXX.
/// Returns bytes written, or error if buffer too small.
pub fn escapeJsonString(input: []const u8, out: []u8) !usize {
    var pos: usize = 0;
    for (input) |ch| {
        const needed: usize = switch (ch) {
            '"', '\\' => 2,
            '\n' => 2,
            '\r' => 2,
            '\t' => 2,
            0x08 => 2, // backspace
            0x0C => 2, // form feed
            else => if (ch < 0x20) @as(usize, 6) else 1,
        };
        if (pos + needed > out.len) return error.BufferTooSmall;
        switch (ch) {
            '"' => {
                out[pos] = '\\';
                out[pos + 1] = '"';
                pos += 2;
            },
            '\\' => {
                out[pos] = '\\';
                out[pos + 1] = '\\';
                pos += 2;
            },
            '\n' => {
                out[pos] = '\\';
                out[pos + 1] = 'n';
                pos += 2;
            },
            '\r' => {
                out[pos] = '\\';
                out[pos + 1] = 'r';
                pos += 2;
            },
            '\t' => {
                out[pos] = '\\';
                out[pos + 1] = 't';
                pos += 2;
            },
            0x08 => {
                out[pos] = '\\';
                out[pos + 1] = 'b';
                pos += 2;
            },
            0x0C => {
                out[pos] = '\\';
                out[pos + 1] = 'f';
                pos += 2;
            },
            else => {
                if (ch < 0x20) {
                    // Control character → \u00XX
                    const hex = "0123456789abcdef";
                    out[pos] = '\\';
                    out[pos + 1] = 'u';
                    out[pos + 2] = '0';
                    out[pos + 3] = '0';
                    out[pos + 4] = hex[ch >> 4];
                    out[pos + 5] = hex[ch & 0x0f];
                    pos += 6;
                } else {
                    out[pos] = ch;
                    pos += 1;
                }
            },
        }
    }
    return pos;
}
