// PodOS Timeline Kernel — Entry struct and state machine
// An Entry is the core unit of the timeline: a stateful pointer with lifecycle.

const std = @import("std");
const types = @import("types.zig");

// ── Sub-structures ──

pub const Ref = struct {
    ref_type: types.RefType = .none,
    uri: [types.MAX_REF_URI_LEN]u8 = .{0} ** types.MAX_REF_URI_LEN,
    uri_len: u16 = 0,

    pub fn getUri(self: *const Ref) []const u8 {
        return self.uri[0..self.uri_len];
    }
};

pub const TimeTrigger = struct {
    at: types.Timestamp = 0, // fire at exact ms (0 = not set)
    cron_pattern: [types.MAX_CRON_LEN]u8 = .{0} ** types.MAX_CRON_LEN,
    cron_len: u8 = 0,
    relative_offset_ms: i64 = 0, // offset from anchor (negative = before)
};

pub const EventTriggerMatch = struct {
    source_filter: types.EventSource = .system,
    type_pattern: [types.MAX_EVENT_TYPE_LEN]u8 = .{0} ** types.MAX_EVENT_TYPE_LEN,
    type_pattern_len: u8 = 0,

    pub fn getTypePattern(self: *const EventTriggerMatch) []const u8 {
        return self.type_pattern[0..self.type_pattern_len];
    }
};

pub const AbsenceTrigger = struct {
    expected_event_type: [types.MAX_EVENT_TYPE_LEN]u8 = .{0} ** types.MAX_EVENT_TYPE_LEN,
    expected_event_type_len: u8 = 0,
    expected_by: types.Timestamp = 0, // deadline — fire if not received by then
    last_checked_at: types.Timestamp = 0,
    fired: bool = false,
};

/// Unified trigger: wraps all trigger variants.
/// Kind determines which sub-struct is active.
pub const Trigger = struct {
    kind: types.TriggerKind = .manual,
    time: TimeTrigger = .{},
    event_match: EventTriggerMatch = .{},
    absence: AbsenceTrigger = .{},
};

pub const Dependency = struct {
    entry_id: types.EntryId = types.ZERO_ID,
    required_state: types.EntryState = .active, // dep must be at least this state
    is_hard: bool = true, // hard = blocks, soft = warns
};

pub const Hook = struct {
    action_kind: types.HookActionKind = .notify,
    phase: HookPhase = .pre,
    prompt: [types.MAX_HOOK_PROMPT_LEN]u8 = .{0} ** types.MAX_HOOK_PROMPT_LEN,
    prompt_len: u16 = 0,
    timeout_ms: u32 = 30_000, // default 30s
    max_retries: u8 = 0, // 0 = no retry
    retry_backoff_ms: u32 = 1_000, // base backoff (exponential)

    // Runtime state (managed by engine, not set by creator)
    status: types.HookStatus = .pending,
    attempts: u8 = 0,
    last_attempt_at: types.Timestamp = 0,

    pub const HookPhase = enum(u1) {
        pre = 0,
        post = 1,
    };

    pub fn getPrompt(self: *const Hook) []const u8 {
        return self.prompt[0..self.prompt_len];
    }

    pub fn resetForRetry(self: *Hook) void {
        self.status = .retrying;
        self.attempts += 1;
    }

    pub fn isExhausted(self: *const Hook) bool {
        return self.attempts > self.max_retries;
    }

    pub fn backoffMs(self: *const Hook) u32 {
        // Exponential backoff: base * 2^attempts, capped at 5 min
        const exp: u5 = @intCast(@min(self.attempts, 16));
        const backoff = self.retry_backoff_ms * (@as(u32, 1) << exp);
        return @min(backoff, 300_000);
    }
};

// ── The Entry ──

pub const Entry = struct {
    // Identity
    id: types.EntryId = types.ZERO_ID,
    timeline_id: types.TimelineId = types.ZERO_ID,
    creator_id: [types.MAX_CREATOR_ID_LEN]u8 = .{0} ** types.MAX_CREATOR_ID_LEN,
    creator_id_len: u8 = 0,

    // Human-readable label
    label: [types.MAX_LABEL_LEN]u8 = .{0} ** types.MAX_LABEL_LEN,
    label_len: u8 = 0,

    // Reference (pointer to external state)
    ref: Ref = .{},

    // State
    state: types.EntryState = .dormant,
    previous_state: types.EntryState = .dormant,

    // Time binding
    anchor: types.Timestamp = 0, // 0 = unanchored
    window_start: types.Timestamp = 0, // 0 = no window
    window_end: types.Timestamp = 0, // 0 = no window

    // Triggers
    activation_trigger: Trigger = .{},
    deactivation_trigger: Trigger = .{},

    // Dependencies
    deps: [types.MAX_DEPS]Dependency = [_]Dependency{.{}} ** types.MAX_DEPS,
    dep_count: u8 = 0,

    // Hooks
    hooks: [types.MAX_HOOKS]Hook = [_]Hook{.{}} ** types.MAX_HOOKS,
    hook_count: u8 = 0,

    // Visibility & classification
    visibility: types.Visibility = .private,
    stream_layer: types.StreamLayer = .pod,
    entry_type: types.EntryType = .event,
    category: [types.MAX_CATEGORY_LEN]u8 = .{0} ** types.MAX_CATEGORY_LEN,
    category_len: u8 = 0,
    salience: f32 = 0.5, // current, after resolution
    original_salience: f32 = 0.5, // before resolution

    // Tags (for public stream filtering)
    tags: [types.MAX_TAGS][types.MAX_TAG_LEN]u8 = [_][types.MAX_TAG_LEN]u8{.{0} ** types.MAX_TAG_LEN} ** types.MAX_TAGS,
    tag_lengths: [types.MAX_TAGS]u8 = .{0} ** types.MAX_TAGS,
    tag_count: u8 = 0,

    // Sync & ordering
    logical_clock: u64 = 0,
    next_cron_at: i64 = 0, // cached next cron fire time (ms); 0 = unset

    // Metadata
    created_at: types.Timestamp = 0,
    last_transition_at: types.Timestamp = 0,
    tick_activated: u64 = 0,
    tick_deactivated: u64 = 0,
    cascade_depth: u8 = 0, // hook chain depth (0 = root)

    // Shadow tracking
    is_shadow: bool = false,
    shadow_source_pod: [types.MAX_POD_URL_LEN]u8 = .{0} ** types.MAX_POD_URL_LEN,
    shadow_source_pod_len: u8 = 0,
    shadow_source_entry_id: types.EntryId = types.ZERO_ID,

    // Flags
    is_deleted: bool = false,
    needs_confirmation: bool = false, // visibility upgrade pending (EC-3)
    missed_while_offline: bool = false, // activated+deactivated offline (EC-1)

    // ── Accessor methods ──

    pub fn getLabel(self: *const Entry) []const u8 {
        return self.label[0..self.label_len];
    }

    pub fn getCategory(self: *const Entry) []const u8 {
        return self.category[0..self.category_len];
    }

    pub fn getTag(self: *const Entry, index: u8) []const u8 {
        if (index >= self.tag_count) return "";
        return self.tags[index][0..self.tag_lengths[index]];
    }

    // ── State machine ──

    pub fn transition(self: *Entry, to: types.EntryState) !void {
        if (!types.validTransition(self.state, to)) return error.InvalidTransition;
        self.previous_state = self.state;
        self.state = to;
        self.last_transition_at = types.nowMs();
    }

    pub fn isActive(self: *const Entry) bool {
        return self.state == .active;
    }

    pub fn isTerminal(self: *const Entry) bool {
        return types.isTerminal(self.state);
    }

    pub fn isLive(self: *const Entry) bool {
        return types.isLive(self.state);
    }

    /// Check if a time trigger should fire now.
    pub fn shouldActivateByTime(self: *const Entry, now: types.Timestamp) bool {
        if (self.state != .dormant) return false;
        if (self.activation_trigger.kind != .time) return false;

        const t = &self.activation_trigger.time;

        // Exact time trigger
        if (t.at > 0 and t.at <= now) return true;

        // Window start trigger
        if (self.window_start > 0 and self.window_start <= now) return true;

        // Relative offset from anchor
        if (self.anchor > 0 and t.relative_offset_ms != 0) {
            const fire_at = self.anchor + t.relative_offset_ms;
            if (fire_at <= now) return true;
        }

        // Cron is checked separately (needs cron.zig)
        return false;
    }

    /// Check if entry has expired its window.
    pub fn isWindowExpired(self: *const Entry, now: types.Timestamp) bool {
        if (self.window_end == 0) return false; // no window end = never expires
        return now > self.window_end;
    }

    /// Check if entry is within its time window.
    pub fn isWithinWindow(self: *const Entry, now: types.Timestamp) bool {
        if (self.window_start > 0 and now < self.window_start) return false;
        if (self.window_end > 0 and now > self.window_end) return false;
        return true;
    }

    /// Check if absence trigger should fire (deadline passed, event not received).
    pub fn shouldFireAbsence(self: *const Entry, now: types.Timestamp) bool {
        if (self.state != .dormant) return false;
        if (self.activation_trigger.kind != .absence) return false;

        const a = &self.activation_trigger.absence;
        if (a.fired) return false; // already fired
        if (a.expected_by == 0) return false;
        return now >= a.expected_by;
    }

    /// Reset salience to original (un-shadow after conflict resolution changes).
    pub fn resetSalience(self: *Entry) void {
        self.salience = self.original_salience;
    }

    /// Check if all hooks have completed (for pre-hook gating).
    pub fn allHooksCompleted(self: *const Entry, phase: Hook.HookPhase) bool {
        for (self.hooks[0..self.hook_count]) |hook| {
            if (hook.phase == phase) {
                if (hook.status != .completed and hook.status != .exhausted) return false;
            }
        }
        return true;
    }

    /// Check if any hook has exhausted its retries.
    pub fn anyHookExhausted(self: *const Entry) bool {
        for (self.hooks[0..self.hook_count]) |hook| {
            if (hook.status == .exhausted) return true;
        }
        return false;
    }

    /// Set a tag by index.
    pub fn setTag(self: *Entry, tag: []const u8) !void {
        if (self.tag_count >= types.MAX_TAGS) return error.TooManyTags;
        const len: u8 = @intCast(@min(tag.len, types.MAX_TAG_LEN));
        @memcpy(self.tags[self.tag_count][0..len], tag[0..len]);
        self.tag_lengths[self.tag_count] = len;
        self.tag_count += 1;
    }

    /// Check if entry has a specific tag.
    pub fn hasTag(self: *const Entry, tag: []const u8) bool {
        for (0..self.tag_count) |i| {
            const t = self.tags[i][0..self.tag_lengths[i]];
            if (std.mem.eql(u8, t, tag)) return true;
        }
        return false;
    }

    /// Set the label.
    pub fn setLabel(self: *Entry, lbl: []const u8) void {
        const len: u8 = @intCast(@min(lbl.len, types.MAX_LABEL_LEN));
        @memcpy(self.label[0..len], lbl[0..len]);
        self.label_len = len;
    }

    /// Set the category.
    pub fn setCategory(self: *Entry, cat: []const u8) void {
        const len: u8 = @intCast(@min(cat.len, types.MAX_CATEGORY_LEN));
        @memcpy(self.category[0..len], cat[0..len]);
        self.category_len = len;
    }
};
