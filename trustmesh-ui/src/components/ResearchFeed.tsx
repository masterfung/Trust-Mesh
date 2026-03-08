"use client";

import { useEffect, useRef, useState } from "react";

export interface ResearchEvent {
  type: "research_started" | "research_step" | "research_done" | "research_parallel_started";
  label?: string;
  url?: string;
  step?: string;
  success?: boolean;
  summary?: string;
  error?: string;
  tasks?: string[];
  count?: number;
  podUrl: string;
  timestamp: number;
}

const POD_COLORS: Record<string, string> = {
  "9001": "text-cyan-400",
  "9002": "text-amber-400",
  "9004": "text-violet-400",
  "9000": "text-emerald-400",
};

const POD_BG: Record<string, string> = {
  "9001": "bg-cyan-500/10 border-cyan-500/20",
  "9002": "bg-amber-500/10 border-amber-500/20",
  "9004": "bg-violet-500/10 border-violet-500/20",
  "9000": "bg-emerald-500/10 border-emerald-500/20",
};

function getPodPort(podUrl: string): string {
  return podUrl.match(/:(\d+)/)?.[1] ?? "9000";
}

function EventRow({ event }: { event: ResearchEvent }) {
  const port = getPodPort(event.podUrl);
  const colorClass = POD_COLORS[port] ?? "text-muted-foreground";
  const isInProgress = event.type === "research_started" || event.type === "research_step";
  const isDone = event.type === "research_done";

  let icon = "↗";
  if (event.type === "research_step") icon = "→";
  if (isDone && event.success) icon = "✓";
  if (isDone && !event.success) icon = "✗";
  if (event.type === "research_parallel_started") icon = "⇉";

  const label = event.label || event.url?.slice(0, 40) || "...";
  const detail =
    event.type === "research_step"
      ? event.step
      : event.type === "research_done"
        ? event.success
          ? event.summary?.slice(0, 80)
          : `Error: ${event.error?.slice(0, 60)}`
        : event.type === "research_parallel_started"
          ? `${event.count} sites in parallel`
          : "";

  return (
    <div className="flex items-start gap-2 text-[11px] py-0.5 group">
      <span className={`font-mono font-bold shrink-0 ${colorClass}`}>{icon}</span>
      <span className={`font-medium shrink-0 ${colorClass}`}>{label}</span>
      {detail && (
        <span className="text-muted-foreground truncate">{detail}</span>
      )}
      {isInProgress && (
        <span className="shrink-0 ml-auto">
          <svg className="animate-spin w-3 h-3 text-muted-foreground" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </span>
      )}
      <span className="shrink-0 ml-auto text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
        :{port}
      </span>
    </div>
  );
}

interface ResearchFeedProps {
  /** Pod base URLs to subscribe to, e.g. ["http://localhost:9001", "http://localhost:9002"] */
  podUrls: string[];
  /** Whether the feed should be shown */
  visible: boolean;
}

export function ResearchFeed({ podUrls, visible }: ResearchFeedProps) {
  const [events, setEvents] = useState<ResearchEvent[]>([]);
  const [hasActivity, setHasActivity] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const sourcesRef = useRef<EventSource[]>([]);

  useEffect(() => {
    // Close existing connections
    sourcesRef.current.forEach((s) => s.close());
    sourcesRef.current = [];

    if (!visible || podUrls.length === 0) return;

    const sources = podUrls.map((podUrl) => {
      const src = new EventSource(`${podUrl}/api/research/feed`, { withCredentials: true });
      src.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as Omit<ResearchEvent, "podUrl" | "timestamp">;
          setEvents((prev) => {
            const newEvent: ResearchEvent = {
              ...event,
              podUrl,
              timestamp: Date.now(),
            };
            // Keep last 50 events
            const updated = [newEvent, ...prev].slice(0, 50);
            return updated;
          });
          setHasActivity(true);
        } catch {
          // ignore malformed
        }
      };
      src.onerror = () => {
        // SSE reconnects automatically — no action needed
      };
      return src;
    });

    sourcesRef.current = sources;
    return () => {
      sources.forEach((s) => s.close());
    };
  }, [podUrls, visible]);

  // Auto-scroll to top when new events arrive
  useEffect(() => {
    if (feedRef.current && events.length > 0) {
      feedRef.current.scrollTop = 0;
    }
  }, [events.length]);

  if (!visible || (!hasActivity && events.length === 0)) return null;

  const activeCount = events.filter(
    (e) => e.type === "research_started" || e.type === "research_step"
  ).length;

  return (
    <div className="mb-6 rounded-xl border border-card-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-card-border bg-card-hover">
        <div className="flex items-center gap-1.5">
          {activeCount > 0 && (
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
          )}
          <span className="text-xs font-semibold text-foreground">Research Feed</span>
        </div>
        {activeCount > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-400 border border-cyan-500/20 font-medium">
            {activeCount} active
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {podUrls.map((url) => {
            const port = getPodPort(url);
            const bgClass = POD_BG[port] ?? "bg-muted/10 border-card-border";
            return (
              <span
                key={url}
                className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${bgClass} ${POD_COLORS[port] ?? "text-muted-foreground"}`}
              >
                :{port}
              </span>
            );
          })}
        </div>
        {events.length > 0 && (
          <button
            onClick={() => { setEvents([]); setHasActivity(false); }}
            className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            Clear
          </button>
        )}
      </div>

      {/* Event list */}
      <div
        ref={feedRef}
        className="px-4 py-3 max-h-48 overflow-y-auto space-y-0.5 font-mono"
      >
        {events.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">Waiting for research activity...</p>
        ) : (
          events.map((event, i) => <EventRow key={i} event={event} />)
        )}
      </div>
    </div>
  );
}
