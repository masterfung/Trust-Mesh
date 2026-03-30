// propagation.zig — Capsule propagation inference, target resolution, and notification fan-out.
//
// Zig-native hot path: comptime keyword lists for category→propagation mapping,
// SQL queries for target resolution, batch INSERT for notification creation.
//
// Called directly from handlers/capsules.zig after INSERT/UPDATE, and exported
// for Python ctypes fallback via podos_infer_propagation() / podos_propagation_targets().
//
// Design: docs/design-propagation.md Phase 1

const std = @import("std");

// When imported as part of podos module, access sibling modules via parent.
// When compiled standalone for tests, this import may fail — tests use
// only the inference function which has no dependencies.
const podos = @import("main.zig");

// ── Compile-time category → propagation mapping ──

const BROADCAST_CATEGORIES = [_][]const u8{ "health", "medical" };
const NOTIFY_CATEGORIES = [_][]const u8{"family"};
const FORCED_SILENT_CATEGORIES = [_][]const u8{ "financial", "personal" };
const FORCED_SILENT_VISIBILITIES = [_][]const u8{"private"};

// ── Utility functions (shared with handlers/common.zig but local to avoid circular import) ──

fn generateUuid(buf: *[36]u8) void {
    var raw: [16]u8 = undefined;
    std.crypto.random.bytes(&raw);
    raw[6] = (raw[6] & 0x0f) | 0x40;
    raw[8] = (raw[8] & 0x3f) | 0x80;
    const hex = "0123456789abcdef";
    var i: usize = 0;
    for (raw, 0..) |byte, idx| {
        buf[i] = hex[byte >> 4];
        buf[i + 1] = hex[byte & 0x0f];
        i += 2;
        if (idx == 3 or idx == 5 or idx == 7 or idx == 9) {
            buf[i] = '-';
            i += 1;
        }
    }
}

fn formatIsoTimestamp(epoch_secs: i64, buf: *[32]u8) usize {
    // Simplified ISO 8601: YYYY-MM-DDTHH:MM:SSZ
    const epoch_u: u64 = @intCast(if (epoch_secs < 0) 0 else epoch_secs);
    const SECS_PER_DAY: u64 = 86400;
    var days = epoch_u / SECS_PER_DAY;
    const day_secs = epoch_u % SECS_PER_DAY;
    const hours = day_secs / 3600;
    const minutes = (day_secs % 3600) / 60;
    const seconds = day_secs % 60;
    // Civil date from days since epoch (simplified Euclidean algorithm)
    var y: u64 = 1970;
    while (true) {
        const is_leap: u64 = if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) 1 else 0;
        const year_days: u64 = 365 + is_leap;
        if (days < year_days) break;
        days -= year_days;
        y += 1;
    }
    const is_leap: u64 = if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) 1 else 0;
    const month_days = [12]u64{ 31, 28 + is_leap, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
    var m: usize = 0;
    while (m < 12 and days >= month_days[m]) {
        days -= month_days[m];
        m += 1;
    }
    const d = "0123456789";
    buf[0] = d[y / 1000 % 10]; buf[1] = d[y / 100 % 10]; buf[2] = d[y / 10 % 10]; buf[3] = d[y % 10];
    buf[4] = '-';
    buf[5] = d[(m + 1) / 10]; buf[6] = d[(m + 1) % 10];
    buf[7] = '-';
    buf[8] = d[(days + 1) / 10]; buf[9] = d[(days + 1) % 10];
    buf[10] = 'T';
    buf[11] = d[hours / 10]; buf[12] = d[hours % 10];
    buf[13] = ':';
    buf[14] = d[minutes / 10]; buf[15] = d[minutes % 10];
    buf[16] = ':';
    buf[17] = d[seconds / 10]; buf[18] = d[seconds % 10];
    buf[19] = 'Z';
    return 20;
}

// ═══════════════════════════════════════════
//  Propagation Inference (zero-alloc)
// ═══════════════════════════════════════════

/// Determine propagation level for a capsule.
///
/// Rules (applied in order):
///   1. Private visibility → always "silent"
///   2. Financial/personal category → always "silent"
///   3. Explicit value provided → use it
///   4. Health/medical category → "broadcast"
///   5. Family category → "notify"
///   6. Everything else → "silent"
pub fn inferPropagation(
    explicit: ?[]const u8,
    category: []const u8,
    visibility: []const u8,
) []const u8 {
    // Rule 1: forced silent for private visibility
    for (FORCED_SILENT_VISIBILITIES) |v| {
        if (std.mem.eql(u8, visibility, v)) return "silent";
    }

    // Rule 2: forced silent for financial/personal categories
    for (FORCED_SILENT_CATEGORIES) |cat| {
        if (std.mem.eql(u8, category, cat)) return "silent";
    }

    // Rule 3: explicit override
    if (explicit) |e| {
        if (e.len > 0) {
            // Validate: must be silent, notify, or broadcast
            if (std.mem.eql(u8, e, "silent") or
                std.mem.eql(u8, e, "notify") or
                std.mem.eql(u8, e, "broadcast"))
            {
                return e;
            }
            // Invalid value → fall through to category defaults
        }
    }

    // Rule 4: category defaults
    for (BROADCAST_CATEGORIES) |cat| {
        if (std.mem.eql(u8, category, cat)) return "broadcast";
    }
    for (NOTIFY_CATEGORIES) |cat| {
        if (std.mem.eql(u8, category, cat)) return "notify";
    }

    // Rule 5: default silent
    return "silent";
}

// ═══════════════════════════════════════════
//  Target Resolution (SQL query)
// ═══════════════════════════════════════════

/// A notification target — either a local user or a remote pod.
pub const PropagationTarget = struct {
    user_id: [36]u8,
    is_remote: bool,
    /// For remote users: the pod URL (null-terminated in buffer).
    /// For local users: empty.
    pod_url_buf: [512]u8 = undefined,
    pod_url_len: usize = 0,
};

/// Resolve all users who should be notified about a capsule update.
/// Returns targets via the provided slice (caller-allocated).
/// Returns the number of targets written.
///
/// SQL: SELECT DISTINCT u.id, u.is_remote, u.remote_pod_url
///      FROM capsule_network_access cna
///      JOIN network_memberships nm ON nm.network_id = cna.network_id
///      JOIN users u ON u.id = nm.user_id
///      WHERE cna.capsule_id = ? AND u.id != ?
pub fn resolveTargets(
    database: *podos.db.Database,
    capsule_id: []const u8,
    owner_id: []const u8,
    targets: []PropagationTarget,
) !usize {
    var stmt = database.prepare(
        "SELECT DISTINCT u.id, u.is_remote, u.remote_pod_url " ++
            "FROM capsule_network_access cna " ++
            "JOIN network_memberships nm ON nm.network_id = cna.network_id " ++
            "JOIN users u ON u.id = nm.user_id " ++
            "WHERE cna.capsule_id = ? AND u.id != ?",
    ) catch return error.DbError;
    defer stmt.finalize();

    stmt.bindText(1, capsule_id.ptr, @intCast(capsule_id.len)) catch return error.DbError;
    stmt.bindText(2, owner_id.ptr, @intCast(owner_id.len)) catch return error.DbError;

    var count: usize = 0;
    while (true) {
        const rc = stmt.step() catch return error.DbError;
        if (rc != .row) break;
        if (count >= targets.len) break; // buffer full

        const uid = stmt.columnText(0);
        const is_remote_val = stmt.columnInt(1);
        const pod_url = stmt.columnText(2);

        var target = &targets[count];
        // Copy user_id
        if (uid.len >= 36) {
            @memcpy(&target.user_id, uid[0..36]);
        } else {
            @memset(&target.user_id, 0);
            @memcpy(target.user_id[0..uid.len], uid);
        }
        target.is_remote = is_remote_val != 0;

        // Copy pod_url for remote users
        if (target.is_remote and pod_url.len > 0) {
            const copy_len = @min(pod_url.len, target.pod_url_buf.len);
            @memcpy(target.pod_url_buf[0..copy_len], pod_url[0..copy_len]);
            target.pod_url_len = copy_len;
        } else {
            target.pod_url_len = 0;
        }

        count += 1;
    }

    return count;
}

// ═══════════════════════════════════════════
//  Notification Batch Insert
// ═══════════════════════════════════════════

/// Create notification records for local (non-remote) targets.
/// Returns the number of notifications created.
pub fn createNotifications(
    database: *podos.db.Database,
    targets: []const PropagationTarget,
    target_count: usize,
    capsule_id: []const u8,
    title: []const u8,
    body: []const u8,
) !u32 {
    var created: u32 = 0;

    // Timestamp for all notifications
    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    for (targets[0..target_count]) |target| {
        if (target.is_remote) continue; // Skip remote — Python handles HTTP push

        var notif_id_buf: [36]u8 = undefined;
        generateUuid(&notif_id_buf);

        var stmt = database.prepare(
            "INSERT INTO notifications " ++
                "(id, user_id, notification_type, title, body, is_read, related_id, created_at) " ++
                "VALUES (?, ?, 'capsule_updated', ?, ?, 0, ?, ?)",
        ) catch return error.DbError;
        defer stmt.finalize();

        stmt.bindText(1, &notif_id_buf, 36) catch return error.DbError;
        stmt.bindText(2, &target.user_id, 36) catch return error.DbError;
        stmt.bindText(3, title.ptr, @intCast(title.len)) catch return error.DbError;
        stmt.bindText(4, body.ptr, @intCast(body.len)) catch return error.DbError;
        stmt.bindText(5, capsule_id.ptr, @intCast(capsule_id.len)) catch return error.DbError;
        stmt.bindText(6, ts.ptr, @intCast(ts.len)) catch return error.DbError;

        _ = stmt.step() catch continue; // Best-effort per notification
        created += 1;
    }

    return created;
}

// ═══════════════════════════════════════════
//  C ABI Exports (for Python ctypes bridge)
// ═══════════════════════════════════════════

/// Infer propagation mode. Returns pointer to static string ("silent", "notify", or "broadcast").
/// Python reads the result via ctypes c_char_p.
pub fn podos_infer_propagation_export(
    explicit_ptr: ?[*]const u8,
    explicit_len: usize,
    category_ptr: [*]const u8,
    category_len: usize,
    visibility_ptr: [*]const u8,
    visibility_len: usize,
) callconv(.c) [*]const u8 {
    const explicit: ?[]const u8 = if (explicit_ptr) |p| p[0..explicit_len] else null;
    const category = category_ptr[0..category_len];
    const visibility = visibility_ptr[0..visibility_len];
    const result = inferPropagation(explicit, category, visibility);
    return result.ptr;
}

/// Resolve propagation targets into a caller-provided buffer.
/// Returns count of targets, or -1 on error.
/// Each target is 36 bytes (user_id) + 1 byte (is_remote) + 2 bytes (pod_url_len) + pod_url_len bytes.
pub fn podos_propagation_targets_export(
    db_handle: *podos.db.Database,
    capsule_id_ptr: [*]const u8,
    capsule_id_len: usize,
    owner_id_ptr: [*]const u8,
    owner_id_len: usize,
    out_buf: [*]u8,
    out_buf_len: usize,
) callconv(.c) c_int {
    const capsule_id = capsule_id_ptr[0..capsule_id_len];
    const owner_id = owner_id_ptr[0..owner_id_len];

    // Allocate targets on stack (max 256 targets)
    var targets: [256]PropagationTarget = undefined;

    const count = resolveTargets(db_handle, capsule_id, owner_id, &targets) catch return -1;

    // Pack into output buffer: for each target:
    //   36 bytes user_id + 1 byte is_remote + 2 bytes pod_url_len (LE) + pod_url bytes
    var offset: usize = 0;
    for (targets[0..count]) |target| {
        const entry_size = 36 + 1 + 2 + target.pod_url_len;
        if (offset + entry_size > out_buf_len) break;

        @memcpy(out_buf[offset .. offset + 36], &target.user_id);
        offset += 36;
        out_buf[offset] = if (target.is_remote) 1 else 0;
        offset += 1;
        const url_len_u16: u16 = @intCast(target.pod_url_len);
        out_buf[offset] = @truncate(url_len_u16);
        out_buf[offset + 1] = @truncate(url_len_u16 >> 8);
        offset += 2;
        if (target.pod_url_len > 0) {
            @memcpy(out_buf[offset .. offset + target.pod_url_len], target.pod_url_buf[0..target.pod_url_len]);
            offset += target.pod_url_len;
        }
    }

    return @intCast(count);
}

/// Create notification records for local targets. Returns count created, or -1 on error.
pub fn podos_create_notifications_export(
    db_handle: *podos.db.Database,
    capsule_id_ptr: [*]const u8,
    capsule_id_len: usize,
    owner_id_ptr: [*]const u8,
    owner_id_len: usize,
    title_ptr: [*]const u8,
    title_len: usize,
    body_ptr: [*]const u8,
    body_len: usize,
) callconv(.c) c_int {
    const capsule_id = capsule_id_ptr[0..capsule_id_len];
    const owner_id = owner_id_ptr[0..owner_id_len];
    const title = title_ptr[0..title_len];
    const body = body_ptr[0..body_len];

    // Resolve targets first
    var targets: [256]PropagationTarget = undefined;
    const count = resolveTargets(db_handle, capsule_id, owner_id, &targets) catch return -1;

    // Create notifications for local users only
    const created = createNotifications(db_handle, &targets, count, capsule_id, title, body) catch return -1;
    return @intCast(created);
}

// ═══════════════════════════════════════════
//  Tests
// ═══════════════════════════════════════════

test "inferPropagation: private always silent" {
    try std.testing.expectEqualStrings("silent", inferPropagation("broadcast", "health", "private"));
}

test "inferPropagation: financial always silent" {
    try std.testing.expectEqualStrings("silent", inferPropagation("notify", "financial", "internal"));
}

test "inferPropagation: personal always silent" {
    try std.testing.expectEqualStrings("silent", inferPropagation("broadcast", "personal", "open"));
}

test "inferPropagation: explicit override" {
    try std.testing.expectEqualStrings("broadcast", inferPropagation("broadcast", "general", "open"));
}

test "inferPropagation: health default broadcast" {
    try std.testing.expectEqualStrings("broadcast", inferPropagation(null, "health", "internal"));
}

test "inferPropagation: family default notify" {
    try std.testing.expectEqualStrings("notify", inferPropagation(null, "family", "internal"));
}

test "inferPropagation: work default silent" {
    try std.testing.expectEqualStrings("silent", inferPropagation(null, "work", "internal"));
}

test "inferPropagation: empty explicit uses category default" {
    try std.testing.expectEqualStrings("broadcast", inferPropagation("", "health", "internal"));
}

test "inferPropagation: invalid explicit falls through" {
    try std.testing.expectEqualStrings("notify", inferPropagation("scream", "family", "internal"));
}
