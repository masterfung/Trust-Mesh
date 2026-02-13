"use client";

const TIER_STYLES: Record<string, string> = {
  public: "bg-warning/15 text-warning border-warning/25",
  network: "bg-accent/15 text-accent border-accent/25",
  private: "bg-danger/15 text-danger border-danger/25",
};

const TIER_ICONS: Record<string, React.ReactNode> = {
  public: (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
    </svg>
  ),
  network: (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
      <path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
    </svg>
  ),
  private: (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
    </svg>
  ),
};

const TIER_LABELS: Record<string, string> = {
  public: "Public",
  network: "Network",
  private: "Private",
};

export function TrustBadge({ tier }: { tier: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold border ${TIER_STYLES[tier] || "bg-muted/15 text-muted border-muted/25"}`}
    >
      {TIER_ICONS[tier]}
      {TIER_LABELS[tier] || tier}
    </span>
  );
}

const TYPE_CONFIG: Record<string, { icon: string; color: string; bg: string }> = {
  memory: { icon: "💭", color: "text-amber-400", bg: "bg-amber-500/15 border-amber-500/25" },
  skill: { icon: "⚡", color: "text-blue-400", bg: "bg-blue-500/15 border-blue-500/25" },
  procedure: { icon: "📋", color: "text-red-400", bg: "bg-red-500/15 border-red-500/25" },
  schedule: { icon: "📅", color: "text-green-400", bg: "bg-green-500/15 border-green-500/25" },
  preference: { icon: "⭐", color: "text-yellow-400", bg: "bg-yellow-500/15 border-yellow-500/25" },
  contact: { icon: "👤", color: "text-orange-400", bg: "bg-orange-500/15 border-orange-500/25" },
};

export function CapsuleTypeBadge({ type }: { type: string }) {
  const config = TYPE_CONFIG[type] || { icon: "?", color: "text-muted", bg: "bg-muted/15 border-muted/25" };
  return (
    <span
      className={`inline-flex items-center justify-center w-7 h-7 rounded-lg text-xs border ${config.bg}`}
      title={type}
    >
      {config.icon}
    </span>
  );
}

const DECISION_STYLES: Record<string, string> = {
  allowed: "bg-success/15 text-success border-success/25",
  denied: "bg-danger/15 text-danger border-danger/25",
  redacted: "bg-warning/15 text-warning border-warning/25",
};

export function DecisionBadge({ decision }: { decision: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold border ${DECISION_STYLES[decision] || "bg-muted/15 text-muted border-muted/25"}`}>
      {decision === "allowed" ? "✓" : decision === "denied" ? "✗" : "~"} {decision.toUpperCase()}
    </span>
  );
}
