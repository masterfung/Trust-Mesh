"use client";

const TIER_STYLES: Record<string, string> = {
  public: "bg-trust-public text-black",
  network: "bg-trust-network text-black",
  private: "bg-trust-private text-white",
};

const TIER_LABELS: Record<string, string> = {
  public: "Public",
  network: "Network",
  private: "Private",
};

export function TrustBadge({ tier }: { tier: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${TIER_STYLES[tier] || "bg-muted text-black"}`}
    >
      {TIER_LABELS[tier] || tier}
    </span>
  );
}

const TYPE_ICONS: Record<string, string> = {
  memory: "M",
  skill: "S",
  procedure: "P",
  schedule: "C",
  preference: "R",
  contact: "K",
};

const TYPE_COLORS: Record<string, string> = {
  memory: "bg-purple-500",
  skill: "bg-blue-500",
  procedure: "bg-red-500",
  schedule: "bg-green-500",
  preference: "bg-yellow-500",
  contact: "bg-orange-500",
};

export function CapsuleTypeBadge({ type }: { type: string }) {
  return (
    <span
      className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold text-white ${TYPE_COLORS[type] || "bg-gray-500"}`}
      title={type}
    >
      {TYPE_ICONS[type] || "?"}
    </span>
  );
}

const DECISION_STYLES: Record<string, string> = {
  allowed: "text-success",
  denied: "text-danger",
  redacted: "text-warning",
};

export function DecisionBadge({ decision }: { decision: string }) {
  return (
    <span className={`font-semibold text-sm ${DECISION_STYLES[decision] || "text-muted"}`}>
      {decision.toUpperCase()}
    </span>
  );
}
