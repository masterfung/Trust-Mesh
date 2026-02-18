"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TimelineEntry, TimelineEngineState } from "@/lib/api";

/* ─── Human-readable descriptions for trigger/hook combos ─── */

function describeEntry(e: TimelineEntry): string {
  if (e.trigger_kind === "cron" && e.trigger_detail) {
    return describeCron(e.trigger_detail, e.label);
  }
  if (e.trigger_kind === "event" && e.trigger_detail) {
    return describeEvent(e.trigger_detail);
  }
  if (e.trigger_kind === "absence" && e.trigger_detail) {
    return `Alerts if "${e.trigger_detail}" hasn't happened within the deadline`;
  }
  if (e.hook_summary === "PIPELINE") {
    return "Runs an automated processing pipeline when triggered";
  }
  if (e.hook_summary === "AGENT_TASK") {
    return "Hands off to your AI agent for intelligent action";
  }
  if (e.hook_summary === "NOTIFY") {
    return "Sends a notification when conditions are met";
  }
  if (e.entry_type_name === "DATA") {
    return "Stores results from other pipeline steps";
  }
  return "Waiting to be activated";
}

function describeCron(cron: string, label: string): string {
  // Parse common cron patterns into English
  const parts = cron.split(" ");
  if (parts.length === 5) {
    const [min, hour, , , ] = parts;
    if (hour !== "*" && min !== "*") {
      const h = parseInt(hour);
      const m = parseInt(min);
      const ampm = h >= 12 ? "pm" : "am";
      const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
      return `Runs daily at ${h12}:${m.toString().padStart(2, "0")}${ampm}`;
    }
    if (min === "0" && hour === "*") {
      return "Runs every hour, on the hour";
    }
    if (min.startsWith("*/")) {
      return `Runs every ${min.slice(2)} minutes`;
    }
  }
  return `Scheduled: ${cron}`;
}

function describeEvent(eventType: string): string {
  const eventMap: Record<string, string> = {
    "capsule.created.health": "Triggers when a new health capsule is added to the vault",
    "capsule.created": "Triggers when any new capsule is added",
    "capsule.updated": "Triggers when a capsule is updated",
    "memory.sweep_completed": "Triggers after the memory sweep finishes",
    "data.updated": "Triggers when data changes",
  };
  return eventMap[eventType] || `Listens for "${eventType}" events`;
}

/* ─── State styling ─── */

const STATE_STYLE: Record<string, { dot: string; label: string; bg: string }> = {
  DORMANT: { dot: "bg-zinc-500", label: "Sleeping", bg: "bg-zinc-500/5" },
  PENDING: { dot: "bg-amber-500", label: "Waiting", bg: "bg-amber-500/5" },
  ACTIVATING: { dot: "bg-blue-500 animate-pulse", label: "Starting up", bg: "bg-blue-500/5" },
  ACTIVE: { dot: "bg-emerald-500 animate-pulse", label: "Running", bg: "bg-emerald-500/5" },
  DEACTIVATING: { dot: "bg-orange-500", label: "Winding down", bg: "bg-orange-500/5" },
  COMPLETED: { dot: "bg-green-600", label: "Done", bg: "bg-green-500/5" },
  FAILED: { dot: "bg-red-500", label: "Failed", bg: "bg-red-500/5" },
  ARCHIVED: { dot: "bg-zinc-600", label: "Archived", bg: "bg-zinc-600/5" },
};

const CATEGORY_ICONS: Record<string, string> = {
  health: "\u2764\uFE0F", family: "\uD83D\uDC68\u200D\uD83D\uDC69\u200D\uD83D\uDC67", work: "\uD83D\uDCBC",
  personal: "\uD83D\uDC64", general: "\u26A1", home: "\uD83C\uDFE0", test: "\uD83E\uDDEA",
  system: "\u2699\uFE0F", "system.metrics": "\uD83D\uDCC8", data: "\uD83D\uDCCA",
};

const VIS_LABELS: Record<string, string> = {
  PRIVATE: "Only you", INTERNAL: "Shared with networks", OPEN: "Public",
};

/* ─── Components ─── */

function Heartbeat({ state }: { state: TimelineEngineState }) {
  return (
    <div className="bg-card border border-card-border rounded-2xl p-6 mb-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="relative">
            <div className={`w-4 h-4 rounded-full ${state.is_running ? "bg-emerald-500" : "bg-red-500"}`} />
            {state.is_running && (
              <div className="absolute inset-0 w-4 h-4 rounded-full bg-emerald-500 animate-ping opacity-30" />
            )}
          </div>
          <div>
            <h2 className="text-lg font-semibold">
              {state.is_running ? "Your agent is awake" : "Engine stopped"}
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              {state.is_running
                ? `Checked in ${state.tick_count} times \u00B7 Managing ${state.active_count} active tasks, ${state.dormant_count} scheduled`
                : "The timeline engine is not running"}
            </p>
          </div>
        </div>
        {state.signal_count > 0 && (
          <span className="px-3 py-1 text-xs rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30">
            {state.signal_count} alert{state.signal_count !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      {state.signals.length > 0 && (
        <div className="mt-4 space-y-2">
          {state.signals.map((s, i) => (
            <div key={i} className={`text-sm p-3 rounded-xl ${
              s.severity === "error" ? "bg-red-500/10 text-red-300" : "bg-amber-500/10 text-amber-300"
            }`}>
              {s.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PipelineView({ entries }: { entries: TimelineEntry[] }) {
  // Find entries that form a pipeline (have dependencies or are CME-related)
  const pipelineEntries = entries.filter(e =>
    e.dep_count > 0 ||
    e.hook_summary === "PIPELINE" ||
    e.label.toLowerCase().includes("sweep") ||
    e.label.toLowerCase().includes("consolidat") ||
    e.label.toLowerCase().includes("forgetting") ||
    e.label.toLowerCase().includes("sla") ||
    e.label.toLowerCase().includes("results")
  );

  if (pipelineEntries.length === 0) return null;

  return (
    <div className="bg-card border border-card-border rounded-2xl p-6 mb-6">
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-4">
        Memory Pipeline
      </h2>
      <p className="text-sm text-muted-foreground mb-4">
        Your agent automatically maintains your knowledge vault through this pipeline.
        Each step feeds into the next.
      </p>
      <div className="flex items-center gap-2 overflow-x-auto pb-2">
        {pipelineEntries.map((entry, i) => {
          const st = STATE_STYLE[entry.state_name] || STATE_STYLE.DORMANT;
          return (
            <div key={entry.id} className="flex items-center gap-2 shrink-0">
              <div className={`${st.bg} border border-card-border rounded-xl p-3 min-w-[160px]`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-2 h-2 rounded-full ${st.dot}`} />
                  <span className="text-xs font-medium text-muted-foreground">{st.label}</span>
                </div>
                <p className="text-sm font-medium">{entry.label}</p>
                {entry.hook_summary && (
                  <p className="text-[10px] text-muted-foreground mt-1">
                    {entry.hook_summary === "PIPELINE" ? "Automated" :
                     entry.hook_summary === "AGENT_TASK" ? "AI-driven" : "Notifies you"}
                  </p>
                )}
              </div>
              {i < pipelineEntries.length - 1 && (
                <svg className="w-5 h-5 text-muted-foreground/40 shrink-0" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
                </svg>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EntryCard({ entry, onComplete }: { entry: TimelineEntry; onComplete: (id: string) => void }) {
  const st = STATE_STYLE[entry.state_name] || STATE_STYLE.DORMANT;
  const icon = CATEGORY_ICONS[entry.category] || CATEGORY_ICONS.general;
  const canComplete = ["ACTIVE", "DEACTIVATING"].includes(entry.state_name);
  const description = describeEntry(entry);
  const vis = VIS_LABELS[entry.visibility_name] || "Private";

  return (
    <div className={`${st.bg} border border-card-border rounded-xl p-4 hover:border-card-border/80 transition-all group`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="text-xl mt-0.5 shrink-0">{icon}</span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-semibold">{entry.label}</h3>
              <div className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${st.dot}`} />
                <span className="text-xs text-muted-foreground">{st.label}</span>
              </div>
            </div>
            <p className="text-xs text-muted-foreground mt-1">{description}</p>
            <div className="flex items-center gap-3 mt-2 text-[10px] text-muted-foreground/60">
              <span>{entry.entry_type_name}</span>
              <span>&middot;</span>
              <span>{vis}</span>
              {entry.dep_count > 0 && (
                <>
                  <span>&middot;</span>
                  <span>Depends on {entry.dep_count} other step{entry.dep_count !== 1 ? "s" : ""}</span>
                </>
              )}
            </div>
          </div>
        </div>
        {canComplete && (
          <button
            onClick={() => onComplete(entry.id)}
            className="opacity-0 group-hover:opacity-100 shrink-0 text-xs px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20 transition-all"
          >
            Mark done
          </button>
        )}
      </div>
    </div>
  );
}

/* ─── Create Form ─── */

function CreateForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("general");
  const [salience, setSalience] = useState(0.5);
  const [triggerKind, setTriggerKind] = useState("manual");
  const [triggerDetail, setTriggerDetail] = useState("");

  const createMutation = useMutation({
    mutationFn: () => {
      const payload: Parameters<typeof api.createTimelineEntry>[0] = { label, category, salience };
      if (triggerKind === "cron" && triggerDetail) {
        payload.activation_trigger = { kind: "time", cron: triggerDetail };
      } else if (triggerKind === "event" && triggerDetail) {
        payload.activation_trigger = { kind: "event", event_type: triggerDetail };
      } else if (triggerKind === "time" && triggerDetail) {
        payload.activation_trigger = { kind: "time", at_ms: Date.now() + parseInt(triggerDetail) * 60000 };
      }
      return api.createTimelineEntry(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeline-entries"] });
      queryClient.invalidateQueries({ queryKey: ["timeline-state"] });
      onClose();
    },
  });

  const triggerHelp: Record<string, string> = {
    manual: "You'll activate this yourself, or your agent can do it from chat.",
    cron: "Runs on a schedule. Examples: '0 9 * * *' = every day at 9am, '*/30 * * * *' = every 30 min.",
    event: "Reacts to something happening. Example: 'capsule.created.health' = when a health capsule is added.",
    time: "One-time trigger after a delay. Enter minutes from now.",
  };

  return (
    <div className="bg-card border border-accent/30 rounded-2xl p-6 mb-6">
      <h2 className="text-base font-semibold mb-1">What should your agent track?</h2>
      <p className="text-sm text-muted-foreground mb-4">
        Create a timeline entry. Your agent will manage it based on the trigger you set.
      </p>

      <div className="space-y-4">
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">What is it?</label>
          <input type="text" value={label} onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g., Remind me to check Rose's medication"
            className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent">
              {Object.entries(CATEGORY_ICONS).filter(([k]) => !k.startsWith("system")).map(([cat, ico]) => (
                <option key={cat} value={cat}>{ico} {cat}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Priority: {Math.round(salience * 100)}%
            </label>
            <input type="range" min="0" max="1" step="0.05" value={salience}
              onChange={(e) => setSalience(parseFloat(e.target.value))} className="w-full mt-2" />
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">When should it run?</label>
          <div className="grid grid-cols-4 gap-2 mb-2">
            {(["manual", "cron", "event", "time"] as const).map((k) => (
              <button key={k} onClick={() => { setTriggerKind(k); setTriggerDetail(""); }}
                className={`px-3 py-2 text-xs rounded-xl border transition-all ${
                  triggerKind === k ? "bg-accent/10 border-accent text-accent" : "border-card-border text-muted-foreground hover:text-foreground"
                }`}>
                {k === "manual" ? "Manual" : k === "cron" ? "Scheduled" : k === "event" ? "On Event" : "After Delay"}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mb-2">{triggerHelp[triggerKind]}</p>
          {triggerKind !== "manual" && (
            <input type="text" value={triggerDetail} onChange={(e) => setTriggerDetail(e.target.value)}
              placeholder={
                triggerKind === "cron" ? "0 9 * * *" : triggerKind === "event" ? "capsule.created.health" : "60"
              }
              className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent" />
          )}
        </div>
      </div>

      <div className="flex justify-end gap-2 mt-5">
        <button onClick={onClose}
          className="px-3 py-2 text-xs rounded-xl border border-card-border hover:bg-card-hover transition-all">Cancel</button>
        <button onClick={() => createMutation.mutate()} disabled={!label || createMutation.isPending}
          className="px-4 py-2 text-xs font-medium rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-50">
          {createMutation.isPending ? "Creating..." : "Create Entry"}
        </button>
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

export default function TimelinePage() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<"active" | "scheduled" | "all">("active");
  const [showCreate, setShowCreate] = useState(false);

  const { data: engineState, isLoading: stateLoading, error: stateError } = useQuery({
    queryKey: ["timeline-state"],
    queryFn: () => api.getTimelineState(),
    refetchInterval: 5000,
    retry: false,
  });

  const { data: entries, isLoading: entriesLoading } = useQuery({
    queryKey: ["timeline-entries"],
    queryFn: () => api.listTimelineEntries(),
    refetchInterval: 5000,
    retry: false,
  });

  const tickMutation = useMutation({
    mutationFn: () => api.tickTimeline(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeline-state"] });
      queryClient.invalidateQueries({ queryKey: ["timeline-entries"] });
    },
  });

  const completeMutation = useMutation({
    mutationFn: async (entryId: string) => {
      try { await api.transitionTimelineEntry(entryId, 4); } catch { /* may already be deactivating */ }
      return api.transitionTimelineEntry(entryId, 5);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeline-entries"] });
      queryClient.invalidateQueries({ queryKey: ["timeline-state"] });
    },
  });

  const unavailable = !!(stateError && !engineState);

  // Group entries by state for better comprehension
  const grouped = useMemo(() => {
    if (!entries) return { active: [], scheduled: [], done: [] };
    const sorted = [...entries].sort((a, b) => b.salience - a.salience);
    return {
      active: sorted.filter(e => ["ACTIVE", "ACTIVATING", "DEACTIVATING", "PENDING"].includes(e.state_name)),
      scheduled: sorted.filter(e => e.state_name === "DORMANT"),
      done: sorted.filter(e => ["COMPLETED", "ARCHIVED", "FAILED"].includes(e.state_name)),
    };
  }, [entries]);

  const shown = view === "active" ? grouped.active
    : view === "scheduled" ? grouped.scheduled
    : [...grouped.active, ...grouped.scheduled, ...grouped.done];

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Timeline</h1>
          <p className="text-muted-foreground text-sm mt-1">
            What your agent is doing, has done, and will do next.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => tickMutation.mutate()} disabled={tickMutation.isPending || unavailable}
            className="px-3 py-2 text-xs font-medium rounded-xl border border-card-border hover:bg-card-hover transition-all disabled:opacity-50"
            title="Force the engine to evaluate all entries right now">
            {tickMutation.isPending ? "Checking..." : "Force Check"}
          </button>
          <button onClick={() => setShowCreate(!showCreate)} disabled={unavailable}
            className="px-4 py-2 text-xs font-medium rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-50">
            + New Entry
          </button>
        </div>
      </div>

      {/* Engine Heartbeat */}
      {stateLoading && !engineState ? (
        <div className="bg-card border border-card-border rounded-2xl p-6 mb-6 animate-pulse">
          <div className="h-5 bg-card-hover rounded w-48 mb-2" />
          <div className="h-4 bg-card-hover rounded w-80" />
        </div>
      ) : engineState ? (
        <Heartbeat state={engineState} />
      ) : (
        <div className="bg-card border border-card-border rounded-2xl p-6 mb-6">
          <p className="text-muted-foreground text-sm">Timeline engine not available. Build: <code className="text-xs bg-card-hover px-1.5 py-0.5 rounded">cd kernel && zig build</code></p>
        </div>
      )}

      {/* Create Form */}
      {showCreate && <CreateForm onClose={() => setShowCreate(false)} />}

      {/* Pipeline View — only show if CME entries exist */}
      {entries && <PipelineView entries={entries} />}

      {/* View Tabs */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-1 bg-card border border-card-border rounded-xl p-1">
          {([
            { key: "active", label: "Active Now", count: grouped.active.length },
            { key: "scheduled", label: "Scheduled", count: grouped.scheduled.length },
            { key: "all", label: "All", count: entries?.length || 0 },
          ] as const).map(({ key, label, count }) => (
            <button key={key} onClick={() => setView(key)}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-all ${
                view === key ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
              }`}>
              {label}
              <span className="ml-1.5 text-[10px] opacity-60">{count}</span>
            </button>
          ))}
        </div>
        {engineState?.is_running && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Live — updates every 5s
          </div>
        )}
      </div>

      {/* Entry Cards */}
      {entriesLoading && !entries ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-card border border-card-border rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-card-hover rounded w-48 mb-2" />
              <div className="h-3 bg-card-hover rounded w-72" />
            </div>
          ))}
        </div>
      ) : unavailable ? (
        <div className="bg-card border border-card-border rounded-2xl p-8 text-center">
          <p className="text-muted-foreground text-sm">Timeline engine not available</p>
        </div>
      ) : shown.length === 0 ? (
        <div className="bg-card border border-card-border rounded-2xl p-8 text-center">
          <p className="text-muted-foreground text-sm">
            {view === "active" ? "Nothing active right now. Your agent is waiting for triggers."
              : view === "scheduled" ? "No scheduled entries. Create one to get started."
              : "No entries yet."}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {shown.map((entry) => (
            <EntryCard key={entry.id} entry={entry} onComplete={(id) => completeMutation.mutate(id)} />
          ))}
        </div>
      )}

      {/* How it works explanation */}
      {entries && entries.length > 0 && (
        <div className="mt-8 bg-card border border-card-border rounded-2xl p-6">
          <h3 className="text-sm font-semibold mb-2">How does this work?</h3>
          <div className="text-xs text-muted-foreground space-y-2">
            <p>
              The timeline engine is a real Zig program running inside your pod. Every 5 seconds, it:
            </p>
            <ol className="list-decimal pl-4 space-y-1">
              <li><strong className="text-foreground/80">Checks schedules</strong> — evaluates cron expressions and time triggers</li>
              <li><strong className="text-foreground/80">Listens for events</strong> — capsule creates, updates, and custom signals wake sleeping entries</li>
              <li><strong className="text-foreground/80">Resolves dependencies</strong> — pipeline steps only run when their prerequisites complete</li>
              <li><strong className="text-foreground/80">Dispatches work</strong> — hands off to your AI agent, runs pipelines, or sends notifications</li>
            </ol>
            <p className="mt-2">
              Try it: go to <strong className="text-foreground/80">Ask Agents</strong> and say
              &ldquo;remind me to check Rose&rsquo;s medication tomorrow at 9am&rdquo; — your agent will create a timeline entry that actually fires.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
