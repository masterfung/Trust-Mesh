"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TimelineEntry, TimelineEngineState } from "@/lib/api";

const STATE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  DORMANT: { bg: "bg-zinc-500/10", text: "text-zinc-400", border: "border-zinc-500/30" },
  PENDING: { bg: "bg-amber-500/10", text: "text-amber-400", border: "border-amber-500/30" },
  ACTIVATING: { bg: "bg-blue-500/10", text: "text-blue-400", border: "border-blue-500/30" },
  ACTIVE: { bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/30" },
  DEACTIVATING: { bg: "bg-orange-500/10", text: "text-orange-400", border: "border-orange-500/30" },
  COMPLETED: { bg: "bg-green-500/10", text: "text-green-500", border: "border-green-500/30" },
  FAILED: { bg: "bg-red-500/10", text: "text-red-400", border: "border-red-500/30" },
  ARCHIVED: { bg: "bg-zinc-600/10", text: "text-zinc-500", border: "border-zinc-600/30" },
  DELETED: { bg: "bg-zinc-700/10", text: "text-zinc-600", border: "border-zinc-700/30" },
};

const CATEGORY_ICONS: Record<string, string> = {
  health: "\u2764\uFE0F",
  family: "\uD83D\uDC68\u200D\uD83D\uDC69\u200D\uD83D\uDC67",
  work: "\uD83D\uDCBC",
  personal: "\uD83D\uDC64",
  general: "\u26A1",
  home: "\uD83C\uDFE0",
  test: "\uD83E\uDDEA",
  system: "\u2699\uFE0F",
  data: "\uD83D\uDCCA",
};

function StateBadge({ state }: { state: string }) {
  const colors = STATE_COLORS[state] || STATE_COLORS.DORMANT;
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium border ${colors.bg} ${colors.text} ${colors.border}`}>
      {state}
    </span>
  );
}

function SalienceBar({ salience }: { salience: number }) {
  const pct = Math.round(salience * 100);
  const color = salience >= 0.9 ? "bg-red-500" : salience >= 0.7 ? "bg-amber-500" : salience >= 0.5 ? "bg-blue-500" : "bg-zinc-500";
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 bg-card-hover rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-muted-foreground w-7 text-right">{pct}%</span>
    </div>
  );
}

function EngineStatePanel({ state, isLoading }: { state?: TimelineEngineState; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className="bg-card border border-card-border rounded-2xl p-5 mb-6 animate-pulse">
        <div className="h-4 bg-card-hover rounded w-32 mb-4" />
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <div key={i} className="h-16 bg-card-hover rounded-xl" />)}
        </div>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
        <p className="text-muted-foreground text-sm">Timeline engine not available. Build the kernel: <code className="text-xs bg-card-hover px-1.5 py-0.5 rounded">cd kernel && zig build</code></p>
      </div>
    );
  }

  const counts = [
    { label: "Active", value: state.active_count, color: "text-emerald-400", bg: "bg-emerald-500/10" },
    { label: "Pending", value: state.pending_count, color: "text-amber-400", bg: "bg-amber-500/10" },
    { label: "Dormant", value: state.dormant_count, color: "text-zinc-400", bg: "bg-zinc-500/10" },
    { label: "Failed", value: state.failed_count, color: "text-red-400", bg: "bg-red-500/10" },
  ];

  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold">Engine State</h2>
          <div className={`flex items-center gap-1.5 text-xs font-medium ${state.is_running ? "text-emerald-400" : "text-red-400"}`}>
            <span className={`w-2 h-2 rounded-full ${state.is_running ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
            {state.is_running ? "Running" : "Stopped"}
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span>Tick #{state.tick_count}</span>
          <span>{state.total_count} entries</span>
          {state.signal_count > 0 && (
            <span className="text-amber-400">{state.signal_count} signals</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {counts.map((c) => (
          <div key={c.label} className={`${c.bg} rounded-xl p-3 text-center`}>
            <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">{c.label}</div>
          </div>
        ))}
      </div>

      {state.signals.length > 0 && (
        <div className="mt-4 space-y-2">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Signals</h3>
          {state.signals.map((s, i) => (
            <div key={i} className={`flex items-start gap-2 text-xs p-2 rounded-lg ${
              s.severity === "warning" ? "bg-amber-500/10 text-amber-400" :
              s.severity === "error" ? "bg-red-500/10 text-red-400" :
              "bg-blue-500/10 text-blue-400"
            }`}>
              <span className="font-medium uppercase text-[10px]">{s.severity}</span>
              <span className="text-foreground/80">{s.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EntryRow({ entry, onComplete }: { entry: TimelineEntry; onComplete: (id: string) => void }) {
  const icon = CATEGORY_ICONS[entry.category] || CATEGORY_ICONS.general;
  const canComplete = ["ACTIVE", "DEACTIVATING"].includes(entry.state_name);

  return (
    <div className="flex items-center gap-4 py-3 px-4 rounded-xl hover:bg-card-hover/50 transition-colors group">
      <span className="text-base shrink-0" title={entry.category}>{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">{entry.label}</span>
          <StateBadge state={entry.state_name} />
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-[10px] text-muted-foreground">{entry.category}</span>
          <span className="text-[10px] text-muted-foreground font-mono">{entry.id.slice(0, 8)}</span>
        </div>
      </div>
      <SalienceBar salience={entry.salience} />
      {canComplete && (
        <button
          onClick={() => onComplete(entry.id)}
          className="opacity-0 group-hover:opacity-100 text-[10px] px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20 transition-all"
        >
          Complete
        </button>
      )}
    </div>
  );
}

export default function TimelinePage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<string>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newCategory, setNewCategory] = useState("general");
  const [newSalience, setNewSalience] = useState(0.5);

  // Fetch engine state — auto-refresh every 5 seconds
  const { data: engineState, isLoading: stateLoading, error: stateError } = useQuery({
    queryKey: ["timeline-state"],
    queryFn: () => api.getTimelineState(),
    refetchInterval: 5000,
    retry: false,
  });

  // Fetch entries — auto-refresh every 5 seconds
  const { data: entries, isLoading: entriesLoading } = useQuery({
    queryKey: ["timeline-entries"],
    queryFn: () => api.listTimelineEntries(),
    refetchInterval: 5000,
    retry: false,
  });

  // Manual tick
  const tickMutation = useMutation({
    mutationFn: () => api.tickTimeline(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeline-state"] });
      queryClient.invalidateQueries({ queryKey: ["timeline-entries"] });
    },
  });

  // Create entry
  const createMutation = useMutation({
    mutationFn: () => api.createTimelineEntry({
      label: newLabel,
      category: newCategory,
      salience: newSalience,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeline-entries"] });
      queryClient.invalidateQueries({ queryKey: ["timeline-state"] });
      setNewLabel("");
      setShowCreate(false);
    },
  });

  // Complete entry (transition to DEACTIVATING then COMPLETED)
  const completeMutation = useMutation({
    mutationFn: async (entryId: string) => {
      // Try DEACTIVATING first, then COMPLETED
      try { await api.transitionTimelineEntry(entryId, 4); } catch { /* might already be deactivating */ }
      return api.transitionTimelineEntry(entryId, 5);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeline-entries"] });
      queryClient.invalidateQueries({ queryKey: ["timeline-state"] });
    },
  });

  // Filter entries
  const filteredEntries = entries?.filter((e) => {
    if (filter === "all") return true;
    return e.state_name.toLowerCase() === filter;
  }) || [];

  // Sort by salience (highest first)
  const sortedEntries = [...filteredEntries].sort((a, b) => b.salience - a.salience);

  const unavailable = !!(stateError && !engineState);

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Timeline</h1>
            {entries && (
              <span className="text-xs bg-card-hover text-muted-foreground px-2.5 py-1 rounded-lg font-medium">
                {entries.length} entries
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm mt-1">PodOS temporal engine — the heartbeat of your agent</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => tickMutation.mutate()}
            disabled={tickMutation.isPending || unavailable}
            className="px-3 py-2 text-xs font-medium rounded-xl border border-card-border hover:bg-card-hover transition-all disabled:opacity-50"
          >
            {tickMutation.isPending ? "Ticking..." : "Manual Tick"}
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            disabled={unavailable}
            className="px-4 py-2 text-xs font-medium rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-50"
          >
            + New Entry
          </button>
        </div>
      </div>

      {/* Engine State */}
      <EngineStatePanel state={engineState} isLoading={stateLoading && !unavailable} />

      {/* Create Entry Form */}
      {showCreate && (
        <div className="bg-card border border-accent/30 rounded-2xl p-5 mb-6">
          <h2 className="text-sm font-semibold mb-4">Create Timeline Entry</h2>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Label</label>
              <input
                type="text"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="e.g., Check medication refill"
                className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Category</label>
              <select
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
              >
                {Object.keys(CATEGORY_ICONS).map((cat) => (
                  <option key={cat} value={cat}>{CATEGORY_ICONS[cat]} {cat}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">
                Salience: {Math.round(newSalience * 100)}%
              </label>
              <input
                type="range"
                min="0" max="1" step="0.05"
                value={newSalience}
                onChange={(e) => setNewSalience(parseFloat(e.target.value))}
                className="w-full mt-1.5"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowCreate(false)}
              className="px-3 py-2 text-xs rounded-xl border border-card-border hover:bg-card-hover transition-all"
            >
              Cancel
            </button>
            <button
              onClick={() => createMutation.mutate()}
              disabled={!newLabel || createMutation.isPending}
              className="px-4 py-2 text-xs font-medium rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-50"
            >
              {createMutation.isPending ? "Creating..." : "Create"}
            </button>
          </div>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex items-center gap-1 mb-4 bg-card border border-card-border rounded-xl p-1 w-fit">
        {["all", "active", "pending", "dormant", "failed", "completed"].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-all ${
              filter === f
                ? "bg-accent/10 text-accent"
                : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
            {f !== "all" && entries && (
              <span className="ml-1 text-[10px] opacity-60">
                {entries.filter((e) => e.state_name.toLowerCase() === f).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Entries List */}
      <div className="bg-card border border-card-border rounded-2xl overflow-hidden">
        {entriesLoading && !entries ? (
          <div className="p-8 text-center text-muted-foreground animate-pulse text-sm">Loading entries...</div>
        ) : unavailable ? (
          <div className="p-8 text-center">
            <p className="text-muted-foreground text-sm">Timeline engine not available</p>
            <p className="text-muted-foreground/60 text-xs mt-1">Build the kernel: <code className="bg-card-hover px-1.5 py-0.5 rounded">cd trustmesh-core/kernel && zig build</code></p>
          </div>
        ) : sortedEntries.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-muted-foreground text-sm">No entries match this filter</p>
          </div>
        ) : (
          <div className="divide-y divide-card-border">
            {sortedEntries.map((entry) => (
              <EntryRow
                key={entry.id}
                entry={entry}
                onComplete={(id) => completeMutation.mutate(id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Heartbeat indicator */}
      {engineState?.is_running && (
        <div className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span>Auto-refreshing every 5s &middot; Tick #{engineState.tick_count}</span>
        </div>
      )}
    </div>
  );
}
