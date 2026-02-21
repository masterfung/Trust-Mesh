"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api, AuditLogEntry } from "@/lib/api";

function timeAgo(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

function eventTypeColor(type: string): string {
  switch (type) {
    case "emergency": return "bg-danger/20 text-danger border-danger/30";
    case "query": return "bg-sky-500/20 text-sky-400 border-sky-500/30";
    case "auth": return "bg-warning/20 text-warning border-warning/30";
    case "capsule": return "bg-accent/20 text-accent border-accent/30";
    default: return "bg-muted/20 text-muted-foreground border-muted/30";
  }
}

function decisionColor(decision: string): string {
  switch (decision) {
    case "allowed": return "text-success";
    case "denied": return "text-danger";
    default: return "text-muted-foreground";
  }
}

function EventIcon({ type }: { type: string }) {
  const cls = "w-5 h-5";
  switch (type) {
    case "emergency":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          <line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      );
    case "query":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      );
    case "auth":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
        </svg>
      );
    default:
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      );
  }
}

const TABS = [
  { key: "all", label: "All Events" },
  { key: "emergency", label: "Emergency" },
  { key: "query", label: "Queries" },
] as const;

type TabKey = typeof TABS[number]["key"];

export default function AuditPage() {
  const params = useParams();
  const userId = params.userId as string;
  const [activeTab, setActiveTab] = useState<TabKey>("all");

  const { data: logs, isLoading } = useQuery({
    queryKey: ["auditLogs", userId, activeTab],
    queryFn: () =>
      activeTab === "emergency"
        ? api.listEmergencyLogs(userId)
        : activeTab === "all"
          ? api.listAuditLogs(userId)
          : api.listAuditLogs(userId, activeTab),
  });

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">Activity Log</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Security events, emergency access, and data sharing history
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-card/50 rounded-xl border border-card-border w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.key
                ? "bg-accent text-accent-fg shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
            }`}
          >
            {tab.label}
            {tab.key === "emergency" && (
              <span className="ml-1.5 inline-flex items-center justify-center w-2 h-2 rounded-full bg-danger" />
            )}
          </button>
        ))}
      </div>

      {/* Timeline */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <div className="text-muted-foreground animate-pulse">Loading activity...</div>
        </div>
      ) : !logs || logs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground mb-3">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            <path d="M9 12l2 2 4-4"/>
          </svg>
          <p className="text-muted-foreground font-medium">No activity yet</p>
          <p className="text-sm text-muted-foreground mt-1">Security events will appear here as they occur</p>
        </div>
      ) : (
        <div className="space-y-3">
          {logs.map((entry: AuditLogEntry) => (
            <AuditCard key={entry.id} entry={entry} userId={userId} />
          ))}
        </div>
      )}
    </div>
  );
}

function AuditCard({ entry, userId }: { entry: AuditLogEntry; userId: string }) {
  const isEmergency = entry.event_type === "emergency";
  const isActor = entry.actor_user_id === userId;

  return (
    <div
      className={`rounded-2xl border p-4 transition-all ${
        isEmergency
          ? "bg-danger/5 border-danger/20 shadow-sm shadow-danger/10"
          : "bg-card/50 border-card-border hover:border-card-border-hover"
      }`}
    >
      <div className="flex gap-3">
        {/* Icon */}
        <div className={`mt-0.5 p-2 rounded-xl border ${eventTypeColor(entry.event_type)}`}>
          <EventIcon type={entry.event_type} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Header row */}
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-foreground">
                {formatAction(entry.action)}
              </p>
              {entry.actor_institution && (
                <p className="text-xs text-muted-foreground mt-0.5">
                  by {entry.actor_institution}
                  {entry.actor_role && <span className="ml-1 text-muted-foreground">({entry.actor_role})</span>}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className={`text-xs font-semibold ${decisionColor(entry.decision)}`}>
                {entry.decision.toUpperCase()}
              </span>
              <span className="text-[10px] text-muted-foreground">{timeAgo(entry.created_at)}</span>
            </div>
          </div>

          {/* Details */}
          <div className="mt-2 space-y-1.5">
            {entry.reason && (
              <p className="text-xs text-muted-foreground">
                <span className="text-muted-foreground">Reason:</span> {entry.reason}
              </p>
            )}
            {entry.case_id && (
              <p className="text-xs text-muted-foreground">
                <span className="text-muted-foreground">Case ID:</span> {entry.case_id}
              </p>
            )}
            {entry.categories_accessed.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Categories:</span>
                {entry.categories_accessed.map((cat) => (
                  <span key={cat} className="text-[10px] px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">
                    {cat}
                  </span>
                ))}
              </div>
            )}
            {entry.capsule_ids_accessed.length > 0 && (
              <p className="text-[10px] text-muted-foreground">
                {entry.capsule_ids_accessed.length} {entry.capsule_ids_accessed.length !== 1 ? "memories" : "memory"} accessed
              </p>
            )}
            {entry.details && "practitioner_name" in entry.details && (
              <p className="text-xs text-muted-foreground">
                <span className="text-muted-foreground">Practitioner:</span> {String(entry.details.practitioner_name)}
              </p>
            )}
            {entry.token_role && (
              <p className="text-xs text-muted-foreground">
                <span className="text-muted-foreground">Token role:</span> {entry.token_role}
                {entry.token_expires_at && (
                  <span className="ml-2 text-muted-foreground">
                    expires {new Date(entry.token_expires_at).toLocaleString()}
                  </span>
                )}
              </p>
            )}
          </div>

          {/* Direction indicator + FHIR link */}
          <div className="mt-2 flex items-center gap-2">
            <span className={`text-[10px] px-2 py-0.5 rounded-full ${
              isActor
                ? "bg-sky-500/10 text-sky-400 border border-sky-500/20"
                : "bg-warning/10 text-warning border border-warning/20"
            }`}>
              {isActor ? "You initiated" : "Your data accessed"}
            </span>
            {entry.action === "emergency_data_access" && entry.decision === "allowed" && (
              <a
                href={`/emergency/${entry.id}/fhir`}
                className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 hover:bg-purple-500/20 transition-colors"
              >
                View FHIR Bundle
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatAction(action: string): string {
  const map: Record<string, string> = {
    emergency_token_issued: "Emergency Token Issued",
    emergency_data_access: "Emergency Data Access",
    emergency_access_denied: "Emergency Access Denied",
    cross_query: "Cross-Agent Query",
  };
  return map[action] || action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
