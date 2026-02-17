// PodOS Timeline Kernel — Core types
// All enums backed by u8 for C ABI compatibility.
// All identifiers are fixed-size byte arrays (no heap allocation).

const std = @import("std");

// ── Identifiers ──

pub const EntryId = [16]u8; // UUID as 16 raw bytes
pub const TimelineId = [16]u8;
pub const StreamId = [16]u8;

pub const ZERO_ID: EntryId = .{0} ** 16;

pub fn ids_equal(a: EntryId, b: EntryId) bool {
    return std.mem.eql(u8, &a, &b);
}

pub fn is_zero_id(id: EntryId) bool {
    return ids_equal(id, ZERO_ID);
}

// ── Visibility (resolution priority encoded in enum value) ──

pub const Visibility = enum(u8) {
    open = 1, // lowest priority — public stream
    internal = 2, // middle — pool stream
    private = 3, // highest — always wins

    pub fn overrides(self: Visibility, other: Visibility) bool {
        return @intFromEnum(self) > @intFromEnum(other);
    }
};

// ── Entry State Machine ──

pub const EntryState = enum(u8) {
    dormant = 0, // exists but not yet relevant
    pending = 1, // trigger fired, checking deps
    activating = 2, // deps met, pre-hooks firing
    active = 3, // live — agent sees this
    deactivating = 4, // deactivation trigger fired, post-hooks firing
    completed = 5, // normal end
    failed = 6, // hook or dep failed
    archived = 7, // kept for history
    deleted = 8, // terminal — gone
};

/// Valid state transitions. Terminal state (deleted) has no outgoing edges.
/// Failed can retry → pending.
pub fn validTransition(from: EntryState, to: EntryState) bool {
    return switch (from) {
        .dormant => to == .pending or to == .deleted,
        .pending => to == .activating or to == .failed or to == .deleted,
        .activating => to == .active or to == .failed,
        .active => to == .deactivating or to == .failed,
        .deactivating => to == .completed or to == .archived or to == .failed,
        .completed => to == .archived or to == .deleted,
        .failed => to == .archived or to == .deleted or to == .pending, // retry
        .archived => to == .deleted,
        .deleted => false, // terminal
    };
}

pub fn isTerminal(s: EntryState) bool {
    return s == .deleted;
}

pub fn isLive(s: EntryState) bool {
    return s == .active or s == .activating or s == .pending;
}

// ── Trigger Types ──

pub const TriggerKind = enum(u8) {
    time = 0, // fire at datetime or cron
    event = 1, // fire on matching event
    condition = 2, // fire when predicate is true (evaluated by host)
    dependency = 3, // fire when deps are satisfied (implicit)
    absence = 4, // fire when expected thing DOESN'T happen by deadline
    manual = 5, // fire on explicit command
};

// ── Entry Types ──

pub const EntryType = enum(u8) {
    event = 0,
    idea = 1,
    data = 2,
    reminder = 3,
    hook = 4,
    milestone = 5,
    task = 6,
    signal = 7,
    mount = 8, // mount point to external system
    computed = 9, // derived from other entries
};

// ── Hook Action Types ──

pub const HookActionKind = enum(u8) {
    agent_task = 0, // dispatch to LLM agent
    notify = 1, // push notification to human
    mutate_entry = 2, // change another entry's state
    create_entry = 3, // spawn a new entry
    vault_op = 4, // modify capsule in vault
    integration = 5, // call external system (MCP, webhook)
    sync = 6, // push to federation
    pipeline = 7, // sequential chain of actions
};

// ── Hook Status (runtime state, managed by engine) ──

pub const HookStatus = enum(u8) {
    pending = 0, // not yet fired
    running = 1, // dispatched to host, awaiting result
    completed = 2, // host reported success
    failed = 3, // host reported failure or timeout
    retrying = 4, // waiting for backoff before retry
    exhausted = 5, // all retries spent — entry fails
};

// ── Event Sources ──

pub const EventSource = enum(u8) {
    system = 0, // internal (tick, startup, shutdown)
    user = 1, // human action
    agent = 2, // agent output
    integration = 3, // external system (email, SaaS, MCP)
    federation = 4, // peer pod message
    timeline = 5, // entry state transition
    public_stream = 6, // registry public timeline
};

// ── Stream Layer ──

pub const StreamLayer = enum(u8) {
    public = 1, // lowest priority (matches Visibility.open)
    pool = 2, // middle (matches Visibility.internal)
    pod = 3, // highest priority (matches Visibility.private)
};

// ── Reference Types ──

pub const RefType = enum(u8) {
    none = 0,
    capsule = 1, // vault capsule
    saas = 2, // external SaaS data (Google Calendar, etc.)
    storage = 3, // file/object storage
    pool = 4, // reference to a pool
    timeline_entry = 5, // reference to another entry
    url = 6, // generic URL
    webhook = 7, // webhook endpoint
    compute = 8, // computation result
};

// ── Timestamps ──
// Unix milliseconds (i64 handles dates well past year 9999)

pub const Timestamp = i64;

pub fn nowMs() Timestamp {
    return std.time.milliTimestamp();
}

// ── Constants ──

pub const MAX_REF_URI_LEN = 256;
pub const MAX_CATEGORY_LEN = 32;
pub const MAX_TAG_LEN = 32;
pub const MAX_TAGS = 8;
pub const MAX_DEPS = 16;
pub const MAX_HOOKS = 8;
pub const MAX_HOOK_PROMPT_LEN = 512;
pub const MAX_LABEL_LEN = 128;
pub const MAX_CREATOR_ID_LEN = 36;
pub const MAX_CRON_LEN = 64;
pub const MAX_EVENT_TYPE_LEN = 64;
pub const MAX_POD_URL_LEN = 128;
