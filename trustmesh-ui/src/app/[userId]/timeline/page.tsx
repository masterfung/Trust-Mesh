"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { TimelineEntry, TimelineEngineState, AgentTask } from "@/lib/api";
import { CATEGORY_ICONS } from "@/lib/constants";

/* ─── Cron builder helpers ─── */

function buildCronFromSchedule(scheduleType: string, time: string, intervalValue: number, intervalUnit: string): string {
  if (scheduleType === "daily") {
    const [h, m] = time.split(":").map(Number);
    return `${m} ${h} * * *`;
  }
  if (scheduleType === "weekdays") {
    const [h, m] = time.split(":").map(Number);
    return `${m} ${h} * * 1-5`;
  }
  if (scheduleType === "weekly") {
    const [h, m] = time.split(":").map(Number);
    return `${m} ${h} * * 1`;
  }
  if (scheduleType === "interval") {
    if (intervalUnit === "minutes") return `*/${intervalValue} * * * *`;
    if (intervalUnit === "hours") return `0 */${intervalValue} * * *`;
  }
  return "0 9 * * *";
}

function describeCronFriendly(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return `Scheduled: ${cron}`;
  const [min, hour, , , dow] = parts;

  // Every N minutes
  if (min.startsWith("*/") && hour === "*") {
    const n = min.slice(2);
    return `Every ${n} minute${n === "1" ? "" : "s"}`;
  }
  // Every N hours
  if (min === "0" && hour.startsWith("*/")) {
    const n = hour.slice(2);
    return `Every ${n} hour${n === "1" ? "" : "s"}`;
  }
  // Every hour on the hour
  if (min === "0" && hour === "*") return "Every hour";
  // Specific time
  if (hour !== "*" && min !== "*") {
    const h = parseInt(hour);
    const m = parseInt(min);
    const ampm = h >= 12 ? "pm" : "am";
    const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
    const mStr = m.toString().padStart(2, "0");
    if (dow === "1-5") return `Weekdays at ${h12}:${mStr}${ampm}`;
    if (dow === "1") return `Every Monday at ${h12}:${mStr}${ampm}`;
    return `Daily at ${h12}:${mStr}${ampm}`;
  }
  return `Scheduled: ${cron}`;
}

function describeEntry(e: TimelineEntry): string {
  if (e.trigger_kind === "cron" && e.trigger_detail) {
    return describeCronFriendly(e.trigger_detail);
  }
  if (e.trigger_kind === "event" && e.trigger_detail) {
    const eventMap: Record<string, string> = {
      "capsule.created.health": "Triggers when a health memory is added",
      "capsule.created": "Triggers when any new memory is added",
      "capsule.updated": "Triggers when a memory is updated",
      "memory.sweep_completed": "Triggers after memory sweep finishes",
    };
    return eventMap[e.trigger_detail] || `Listens for "${e.trigger_detail}" events`;
  }
  if (e.trigger_kind === "absence" && e.trigger_detail) {
    return `Alerts if "${e.trigger_detail}" hasn't happened within the deadline`;
  }
  if (e.hook_summary === "PIPELINE") return "Runs an automated processing pipeline";
  if (e.hook_summary === "AGENT_TASK") return "Hands off to your AI agent";
  if (e.hook_summary === "NOTIFY") return "Sends you a notification";
  if (e.entry_type_name === "DATA") return "Stores results from other pipeline steps";
  return "Manual — activate when needed";
}

/* ─── State styling ─── */

const STATE_STYLE: Record<string, { dot: string; label: string; bg: string; border: string }> = {
  DORMANT:      { dot: "bg-zinc-500",               label: "Sleeping",     bg: "bg-zinc-500/5",    border: "border-card-border" },
  PENDING:      { dot: "bg-amber-500",               label: "Waiting",      bg: "bg-amber-500/5",   border: "border-amber-500/20" },
  ACTIVATING:   { dot: "bg-blue-500 animate-pulse",  label: "Starting",     bg: "bg-blue-500/5",    border: "border-blue-500/20" },
  ACTIVE:       { dot: "bg-emerald-500 animate-pulse",label: "Running",     bg: "bg-emerald-500/5", border: "border-emerald-500/20" },
  DEACTIVATING: { dot: "bg-orange-500",              label: "Winding down", bg: "bg-orange-500/5",  border: "border-orange-500/20" },
  COMPLETED:    { dot: "bg-green-600",               label: "Done",         bg: "bg-green-500/5",   border: "border-green-500/20" },
  FAILED:       { dot: "bg-red-500",                 label: "Failed",       bg: "bg-red-500/5",     border: "border-red-500/20" },
  ARCHIVED:     { dot: "bg-zinc-600",                label: "Archived",     bg: "bg-zinc-600/5",    border: "border-card-border" },
};


/* ─── Components ─── */

function Heartbeat({ state }: { state: TimelineEngineState }) {
  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="relative">
            <div className={`w-3.5 h-3.5 rounded-full ${state.is_running ? "bg-emerald-500" : "bg-red-500"}`} />
            {state.is_running && (
              <div className="absolute inset-0 w-3.5 h-3.5 rounded-full bg-emerald-500 animate-ping opacity-30" />
            )}
          </div>
          <div>
            <h2 className="text-base font-semibold">
              {state.is_running ? "Agent is active" : "Engine stopped"}
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {state.is_running
                ? `${state.active_count} running · ${state.dormant_count} scheduled · checked ${state.tick_count} times`
                : "The timeline engine is not running"}
            </p>
          </div>
        </div>
        {state.signal_count > 0 && (
          <span className="px-2.5 py-1 text-xs rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30">
            {state.signal_count} alert{state.signal_count !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      {state.signals.length > 0 && (
        <div className="mt-4 space-y-2">
          {state.signals.map((s, i) => (
            <div key={i} className={`text-sm p-3 rounded-xl ${s.severity === "error" ? "bg-red-500/10 text-red-300" : "bg-amber-500/10 text-amber-300"}`}>
              {s.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EntryCard({ entry, onComplete }: { entry: TimelineEntry; onComplete: (id: string) => void }) {
  const st = STATE_STYLE[entry.state_name] || STATE_STYLE.DORMANT;
  const icon = CATEGORY_ICONS[entry.category] || CATEGORY_ICONS.general;
  const canComplete = ["ACTIVE", "DEACTIVATING"].includes(entry.state_name);
  const description = describeEntry(entry);
  const importancePct = Math.round(entry.salience * 100);

  return (
    <div className={`${st.bg} border ${st.border} rounded-xl p-4 hover:opacity-90 transition-all group`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="text-lg mt-0.5 shrink-0">{icon}</span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-semibold">{entry.label}</h3>
              <div className="flex items-center gap-1">
                <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                <span className="text-[10px] text-muted-foreground">{st.label}</span>
              </div>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
            <div className="flex items-center gap-3 mt-1.5 flex-wrap">
              {entry.trigger_kind === "cron" && (
                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/70">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                  </svg>
                  {description}
                </span>
              )}
              {importancePct > 0 && (
                <span className="text-[10px] text-muted-foreground/60">
                  {importancePct >= 70 ? "🔴" : importancePct >= 40 ? "🟡" : "🟢"} {importancePct}% priority
                </span>
              )}
              {entry.dep_count > 0 && (
                <span className="text-[10px] text-muted-foreground/60">
                  Waits for {entry.dep_count} step{entry.dep_count !== 1 ? "s" : ""}
                </span>
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

/* ─── Schedule Builder ─── */

type ScheduleType = "daily" | "weekdays" | "weekly" | "interval";

function ScheduleBuilder({
  value,
  onChange,
}: {
  value: string;
  onChange: (cron: string) => void;
}) {
  const [scheduleType, setScheduleType] = useState<ScheduleType>("daily");
  const [time, setTime] = useState("09:00");
  const [intervalValue, setIntervalValue] = useState(30);
  const [intervalUnit, setIntervalUnit] = useState("minutes");

  const updateCron = (type: ScheduleType, t: string, iv: number, iu: string) => {
    onChange(buildCronFromSchedule(type, t, iv, iu));
  };

  const SCHEDULE_OPTIONS: { key: ScheduleType; label: string; desc: string }[] = [
    { key: "daily", label: "Daily", desc: "Same time every day" },
    { key: "weekdays", label: "Weekdays", desc: "Mon–Fri only" },
    { key: "weekly", label: "Weekly", desc: "Once a week" },
    { key: "interval", label: "Interval", desc: "Repeat every X" },
  ];

  return (
    <div className="space-y-3">
      {/* Schedule type picker */}
      <div className="grid grid-cols-4 gap-2">
        {SCHEDULE_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => {
              setScheduleType(opt.key);
              updateCron(opt.key, time, intervalValue, intervalUnit);
            }}
            className={`p-2.5 rounded-xl border text-center transition-all ${
              scheduleType === opt.key
                ? "bg-accent/10 border-accent text-accent"
                : "border-card-border text-muted-foreground hover:text-foreground hover:border-accent/30"
            }`}
          >
            <p className="text-xs font-medium">{opt.label}</p>
            <p className="text-[9px] opacity-70 mt-0.5">{opt.desc}</p>
          </button>
        ))}
      </div>

      {/* Time picker (for daily/weekdays/weekly) */}
      {scheduleType !== "interval" && (
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">
            {scheduleType === "weekly" ? "Every Monday at" : "Run at"}
          </label>
          <input
            type="time"
            value={time}
            onChange={(e) => {
              setTime(e.target.value);
              updateCron(scheduleType, e.target.value, intervalValue, intervalUnit);
            }}
            className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
          />
        </div>
      )}

      {/* Interval picker */}
      {scheduleType === "interval" && (
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Repeat every</label>
          <div className="flex gap-2">
            <input
              type="number"
              min="1"
              max={intervalUnit === "minutes" ? 59 : 23}
              value={intervalValue}
              onChange={(e) => {
                const v = Math.max(1, parseInt(e.target.value) || 1);
                setIntervalValue(v);
                updateCron(scheduleType, time, v, intervalUnit);
              }}
              className="flex-1 px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
            />
            <select
              value={intervalUnit}
              onChange={(e) => {
                setIntervalUnit(e.target.value);
                updateCron(scheduleType, time, intervalValue, e.target.value);
              }}
              className="px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
            >
              <option value="minutes">minutes</option>
              <option value="hours">hours</option>
            </select>
          </div>
        </div>
      )}

      {/* Preview */}
      {value && (
        <div className="flex items-center gap-2 px-3 py-2 bg-accent/5 rounded-xl border border-accent/15">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent shrink-0">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          <p className="text-xs text-accent">{describeCronFriendly(value)}</p>
        </div>
      )}
    </div>
  );
}

/* ─── Event Picker ─── */

const EVENT_OPTIONS = [
  { value: "capsule.created.health", label: "Health memory added", desc: "When a new health memory is saved to your vault" },
  { value: "capsule.created", label: "Any memory added", desc: "When any new memory is saved" },
  { value: "capsule.updated", label: "Memory updated", desc: "When any memory is edited" },
  { value: "memory.sweep_completed", label: "Memory sweep done", desc: "After the automated memory review finishes" },
];

/* ─── Create Form ─── */

function CreateForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("general");
  const [importance, setImportance] = useState(50); // 0-100 instead of 0-1
  const [triggerKind, setTriggerKind] = useState("manual");
  const [cronValue, setCronValue] = useState("0 9 * * *");
  const [eventValue, setEventValue] = useState("capsule.created.health");
  const [delayMinutes, setDelayMinutes] = useState(60);
  const [delayUnit, setDelayUnit] = useState("minutes");
  const [showTooltip, setShowTooltip] = useState(false);

  const getDelayMs = () => {
    const multipliers: Record<string, number> = { minutes: 60000, hours: 3600000, days: 86400000 };
    return delayMinutes * (multipliers[delayUnit] || 60000);
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const salience = importance / 100;
      const payload: Parameters<typeof api.createTimelineEntry>[0] = { label, category, salience };
      if (triggerKind === "cron") {
        payload.activation_trigger = { kind: "time", cron: cronValue };
      } else if (triggerKind === "event") {
        payload.activation_trigger = { kind: "event", event_type: eventValue };
      } else if (triggerKind === "time") {
        payload.activation_trigger = { kind: "time", at_ms: Date.now() + getDelayMs() };
      }
      return api.createTimelineEntry(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeline-entries"] });
      queryClient.invalidateQueries({ queryKey: ["timeline-state"] });
      onClose();
    },
  });

  const TRIGGER_OPTIONS = [
    { key: "manual", icon: "👆", label: "Manual", desc: "You or your agent activates it" },
    { key: "cron", icon: "📅", label: "Scheduled", desc: "Runs on a recurring schedule" },
    { key: "event", icon: "⚡", label: "On Event", desc: "Reacts to something happening" },
    { key: "time", icon: "⏱️", label: "After Delay", desc: "One-time, fires after a wait" },
  ];

  const IMPORTANCE_LEVELS = [
    { max: 33, label: "Low — nice to have", color: "text-green-400" },
    { max: 66, label: "Normal — handle in order", color: "text-yellow-400" },
    { max: 100, label: "High — prioritize first", color: "text-red-400" },
  ];
  const importanceLevel = IMPORTANCE_LEVELS.find(l => importance <= l.max) || IMPORTANCE_LEVELS[2];

  return (
    <div className="bg-card border border-accent/30 rounded-2xl p-5 mb-6">
      <h2 className="text-sm font-semibold mb-1">What should your agent track?</h2>
      <p className="text-xs text-muted-foreground mb-4">
        Create a task or reminder. Your agent will run it based on the trigger you set.
      </p>

      <div className="space-y-4">
        {/* Label */}
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">What is it?</label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g., Check Rose's medication"
            className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
          />
        </div>

        {/* Category + Importance */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
            >
              {Object.entries(CATEGORY_ICONS).filter(([k]) => !k.startsWith("system")).map(([cat, ico]) => (
                <option key={cat} value={cat}>{ico} {cat.charAt(0).toUpperCase() + cat.slice(1)}</option>
              ))}
            </select>
          </div>
          <div>
            <div className="flex items-center gap-1 mb-1">
              <label className="text-xs font-medium text-muted-foreground">
                Importance: {importance}%
              </label>
              <button
                type="button"
                onMouseEnter={() => setShowTooltip(true)}
                onMouseLeave={() => setShowTooltip(false)}
                className="relative text-muted-foreground/40 hover:text-muted-foreground transition-colors"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                {showTooltip && (
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 bg-card border border-card-border rounded-lg text-[10px] text-muted-foreground z-10 text-left shadow-lg">
                    When your agent has multiple tasks waiting, higher importance ones run first.
                  </div>
                )}
              </button>
            </div>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={importance}
              onChange={(e) => setImportance(parseInt(e.target.value))}
              className="w-full mt-1.5"
            />
            <p className={`text-[10px] mt-1 ${importanceLevel.color}`}>{importanceLevel.label}</p>
          </div>
        </div>

        {/* Trigger type */}
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-2 block">When should it run?</label>
          <div className="grid grid-cols-2 gap-2 mb-3">
            {TRIGGER_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                type="button"
                onClick={() => setTriggerKind(opt.key)}
                className={`p-3 rounded-xl border text-left transition-all ${
                  triggerKind === opt.key
                    ? "bg-accent/10 border-accent"
                    : "border-card-border text-muted-foreground hover:text-foreground hover:border-accent/30"
                }`}
              >
                <p className="text-sm">{opt.icon}</p>
                <p className={`text-xs font-medium mt-1 ${triggerKind === opt.key ? "text-accent" : ""}`}>{opt.label}</p>
                <p className="text-[10px] text-muted-foreground/70 mt-0.5">{opt.desc}</p>
              </button>
            ))}
          </div>

          {/* Scheduled: friendly schedule builder */}
          {triggerKind === "cron" && (
            <ScheduleBuilder value={cronValue} onChange={setCronValue} />
          )}

          {/* On Event: dropdown */}
          {triggerKind === "event" && (
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground block">Which event triggers this?</label>
              <div className="space-y-1.5">
                {EVENT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setEventValue(opt.value)}
                    className={`w-full p-3 rounded-xl border text-left transition-all ${
                      eventValue === opt.value
                        ? "bg-accent/10 border-accent"
                        : "border-card-border hover:border-accent/30"
                    }`}
                  >
                    <p className={`text-xs font-medium ${eventValue === opt.value ? "text-accent" : ""}`}>{opt.label}</p>
                    <p className="text-[10px] text-muted-foreground/70 mt-0.5">{opt.desc}</p>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* After Delay: number + unit */}
          {triggerKind === "time" && (
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">Run once after</label>
              <div className="flex gap-2">
                <input
                  type="number"
                  min="1"
                  max={delayUnit === "minutes" ? 1440 : delayUnit === "hours" ? 168 : 365}
                  value={delayMinutes}
                  onChange={(e) => setDelayMinutes(Math.max(1, parseInt(e.target.value) || 1))}
                  className="flex-1 px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
                />
                <select
                  value={delayUnit}
                  onChange={(e) => setDelayUnit(e.target.value)}
                  className="px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
                >
                  <option value="minutes">minutes</option>
                  <option value="hours">hours</option>
                  <option value="days">days</option>
                </select>
              </div>
              <p className="text-[10px] text-muted-foreground/60 mt-1">
                Fires once, {delayMinutes} {delayUnit} from now
              </p>
            </div>
          )}
        </div>
      </div>

      {createMutation.isError && (
        <p className="text-xs text-danger mt-3">{(createMutation.error as Error).message}</p>
      )}

      <div className="flex justify-end gap-2 mt-5">
        <button
          onClick={onClose}
          className="px-3 py-2 text-xs rounded-xl border border-card-border hover:bg-card-hover transition-all"
        >
          Cancel
        </button>
        <button
          onClick={() => createMutation.mutate()}
          disabled={!label.trim() || createMutation.isPending}
          className="px-4 py-2 text-xs font-medium rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-50"
        >
          {createMutation.isPending ? "Creating..." : "Create Entry"}
        </button>
      </div>
    </div>
  );
}

/* ─── Agent Task Card ─── */

const TASK_STATUS_STYLE: Record<string, { dot: string; label: string }> = {
  pending:    { dot: "bg-amber-500", label: "Pending" },
  running:    { dot: "bg-blue-500 animate-pulse", label: "Running" },
  completed:  { dot: "bg-emerald-500", label: "Done" },
  failed:     { dot: "bg-red-500", label: "Failed" },
};

function AgentTaskCard({ task }: { task: AgentTask }) {
  const st = TASK_STATUS_STYLE[task.status] || TASK_STATUS_STYLE.pending;
  const icon = CATEGORY_ICONS[task.task_type] || "🤖";
  const timeAgo = getTimeAgo(task.created_at);

  return (
    <div className="bg-card border border-card-border rounded-xl p-4 hover:opacity-90 transition-all">
      <div className="flex items-start gap-3 min-w-0">
        <span className="text-lg mt-0.5 shrink-0">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold">{task.title}</h3>
            <div className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
              <span className="text-[10px] text-muted-foreground">{st.label}</span>
            </div>
          </div>
          {task.description && (
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{task.description}</p>
          )}
          <div className="flex items-center gap-3 mt-1.5 flex-wrap">
            <span className="text-[10px] text-muted-foreground/60">{timeAgo}</span>
            {task.source_message && (
              <span className="text-[10px] text-muted-foreground/50 truncate max-w-[200px]">
                from: &quot;{task.source_message}&quot;
              </span>
            )}
          </div>
          {task.result && task.status === "completed" && (
            <p className="text-xs text-emerald-400/80 mt-1.5 line-clamp-2">{task.result}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function getTimeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/* ─── Main Page ─── */

export default function TimelinePage() {
  const { userId } = useParams<{ userId: string }>();
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

  // Agent tasks created during conversations (via create_task tool)
  const { data: agentTasks } = useQuery({
    queryKey: ["agent-tasks", userId],
    queryFn: () => api.listTasks(userId),
    enabled: !!userId,
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
            Tasks and reminders your agent watches and runs for you.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => tickMutation.mutate()}
            disabled={tickMutation.isPending || unavailable}
            className="px-3 py-2 text-xs font-medium rounded-xl border border-card-border hover:bg-card-hover transition-all disabled:opacity-50"
            title="Force the engine to evaluate all entries right now"
          >
            {tickMutation.isPending ? "Checking..." : "Force Check"}
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            disabled={unavailable}
            className="px-4 py-2 text-xs font-semibold rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-50"
          >
            {showCreate ? "Cancel" : "+ New Task"}
          </button>
        </div>
      </div>

      {/* Engine Heartbeat */}
      {stateLoading && !engineState ? (
        <div className="bg-card border border-card-border rounded-2xl p-5 mb-6 animate-pulse">
          <div className="h-5 bg-card-hover rounded w-48 mb-2" />
          <div className="h-4 bg-card-hover rounded w-80" />
        </div>
      ) : engineState ? (
        <Heartbeat state={engineState} />
      ) : (
        <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
          <p className="text-muted-foreground text-sm">
            Timeline engine not available.{" "}
            <code className="text-xs bg-card-hover px-1.5 py-0.5 rounded">cd kernel && zig build</code>
          </p>
        </div>
      )}

      {/* Create Form */}
      {showCreate && <CreateForm onClose={() => setShowCreate(false)} />}

      {/* View Tabs */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-1 bg-card border border-card-border rounded-xl p-1">
          {([
            { key: "active", label: "Active Now", count: grouped.active.length },
            { key: "scheduled", label: "Scheduled", count: grouped.scheduled.length },
            { key: "all", label: "All", count: entries?.length || 0 },
          ] as const).map(({ key, label, count }) => (
            <button
              key={key}
              onClick={() => setView(key)}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-all ${
                view === key ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
              }`}
            >
              {label}
              <span className="ml-1 text-[10px] opacity-60">{count}</span>
            </button>
          ))}
        </div>
        {engineState?.is_running && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Live
          </div>
        )}
      </div>

      {/* Entry Cards */}
      {entriesLoading && !entries ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
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
            {view === "active" ? "Nothing running right now — your agent is waiting for triggers."
              : view === "scheduled" ? "No scheduled tasks yet. Create one to get started."
              : "No tasks yet. Hit \"+ New Task\" to create one."}
          </p>
          {view !== "active" && (
            <button onClick={() => setShowCreate(true)} className="mt-3 text-accent text-sm hover:text-accent-hover">
              Create a task →
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {shown.map((entry) => (
            <EntryCard key={entry.id} entry={entry} onComplete={(id) => completeMutation.mutate(id)} />
          ))}
        </div>
      )}

      {/* Agent Tasks — tasks created by the agent during conversations */}
      {agentTasks && agentTasks.length > 0 && (
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-muted-foreground mb-3 flex items-center gap-2">
            Agent Tasks
            <span className="px-1.5 py-0.5 rounded bg-card-hover text-[10px] font-medium">{agentTasks.length}</span>
          </h2>
          <div className="space-y-2">
            {agentTasks.map((task) => (
              <AgentTaskCard key={task.id} task={task} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state when both timeline and agent tasks are empty */}
      {unavailable && (!agentTasks || agentTasks.length === 0) && (
        <div className="bg-card border border-card-border rounded-2xl p-8 text-center mt-6">
          <p className="text-muted-foreground text-sm">
            No scheduled tasks yet. Tasks created by your agent during conversations will appear here.
          </p>
        </div>
      )}
    </div>
  );
}
