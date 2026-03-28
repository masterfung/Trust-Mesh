// sensitivity.zig — Pre-flight sensitivity detection at the channel boundary.
//
// Zero-allocation hot path: text is lowercased into a stack buffer,
// then checked against compile-time keyword and relationship-type lists.
//
// Called directly by channels.zig (no ctypes overhead) and exported for
// Python ctypes fallback via podos_preflight_sensitivity().

const std = @import("std");

// ── Compile-time constants (mirror agents.py SENSITIVE_KEYWORDS) ──

const SENSITIVE_KEYWORDS = [_][]const u8{
    "medical",        "health",         "diagnosis",      "prescription",
    "medication",     "blood pressure", "dialysis",       "surgery",
    "therapy",        "treatment",      "financial",      "bank",
    "account number", "ssn",            "social security","credit card",
    "tax",            "salary",         "income",         "investment",
    "insurance",      "policy number",  "claim",
};

const SENSITIVE_RELATIONSHIP_TYPES = [_][]const u8{
    "healthcare",
    "legal",
    "financial",
};

// ── Max text to lowercase (stack-allocated, no heap) ──
const MAX_TEXT_LEN: usize = 32 * 1024; // 32KB

/// Lowercase `src` into `dst` (truncates at `dst.len`). Returns bytes written.
fn toLower(src: []const u8, dst: []u8) usize {
    const n = @min(src.len, dst.len);
    for (src[0..n], 0..) |ch, i| {
        dst[i] = std.ascii.toLower(ch);
    }
    return n;
}

// ═══════════════════════════════════════════
//  Core function (called from channels.zig)
// ═══════════════════════════════════════════

/// Returns true if text or relationship_type indicate sensitive content.
/// No heap allocation — text is lowercased into a 32KB stack buffer.
pub fn preflightSensitivity(text: []const u8, relationship_type: ?[]const u8) bool {
    // Check relationship type first (cheapest)
    if (relationship_type) |rt| {
        var rt_lower_buf: [64]u8 = undefined;
        const rt_lower_len = toLower(rt, &rt_lower_buf);
        const rt_lower = rt_lower_buf[0..rt_lower_len];
        for (SENSITIVE_RELATIONSHIP_TYPES) |srt| {
            if (std.mem.eql(u8, rt_lower, srt)) return true;
        }
    }

    // Lowercase text into stack buffer
    var lower_buf: [MAX_TEXT_LEN]u8 = undefined;
    const lower_len = toLower(text, &lower_buf);
    const lower = lower_buf[0..lower_len];

    // Keyword scan
    for (SENSITIVE_KEYWORDS) |kw| {
        if (std.mem.indexOf(u8, lower, kw) != null) return true;
    }

    return false;
}

// ═══════════════════════════════════════════
//  C ABI shim (exported by main.zig — do not export here)
// ═══════════════════════════════════════════

/// Returns 1 if sensitive, 0 if standard.
/// main.zig re-exports this as `export fn podos_preflight_sensitivity` for Python ctypes.
pub fn podos_preflight_sensitivity(
    text_ptr: [*]const u8,
    text_len: usize,
    rel_type_ptr: ?[*]const u8,
    rel_type_len: usize,
) callconv(.c) u8 {
    const text = text_ptr[0..text_len];
    const rel_type: ?[]const u8 = if (rel_type_ptr) |p| p[0..rel_type_len] else null;
    return if (preflightSensitivity(text, rel_type)) 1 else 0;
}
