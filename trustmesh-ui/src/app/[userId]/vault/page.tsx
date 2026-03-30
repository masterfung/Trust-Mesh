"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getPodUrl, getCsrfToken, type Capsule, type ContextMode, type Network } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, CapsuleTypeBadge } from "@/components/TrustBadge";
import { matchesContext } from "@/lib/context";
import { CAPSULE_TYPES, CAPSULE_TYPE_EMOJIS, TIER_FILTER_LABELS, type CapsuleType } from "@/lib/constants";
import { formatRelativeTime } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";

const TIERS = ["public", "network", "private"] as const;

const TYPE_DESCRIPTIONS: Record<string, string> = {
  memory: "Events, conversations, observations",
  skill: "Expertise, techniques, domain knowledge",
  procedure: "Step-by-step instructions for tasks",
  schedule: "Time-based info with dates",
  preference: "Personal prefs, allergies, dietary",
  contact: "People, phone numbers, relationships",
};

export default function VaultPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingCapsule, setEditingCapsule] = useState<Capsule | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [tierFilter, setTierFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [showCount, setShowCount] = useState(20);

  const { data: currentUser } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });
  const activeContext: ContextMode = (currentUser?.active_context as ContextMode) || "all";

  const { data: allCapsules, isLoading } = useQuery({
    queryKey: ["capsules", userId],
    queryFn: () => api.listCapsules(userId),
  });
  const capsules = allCapsules?.filter((c) => matchesContext(c.context, activeContext));

  const { data: networks } = useQuery({
    queryKey: ["networks", userId],
    queryFn: () => api.listNetworks(userId),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteCapsule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["capsules", userId] }),
  });

  const markReviewedMutation = useMutation({
    mutationFn: (id: string) => api.markReviewed(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["capsules", userId] }),
  });

  const autoUpdateMutation = useMutation({
    mutationFn: (id: string) => api.autoUpdateCapsule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["capsules", userId] }),
  });

  const filtered = capsules?.filter((c) => {
    if (typeFilter !== "all" && c.capsule_type !== typeFilter) return false;
    if (tierFilter !== "all" && c.tier !== tierFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return c.title.toLowerCase().includes(q) || c.content.toLowerCase().includes(q);
    }
    return true;
  });

  const visible = filtered?.slice(0, showCount);

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold">
              {currentUser?.user_type === "organization" ? "Knowledge Base" : "My Memories"}
            </h1>
            {capsules && (
              <span className="text-xs bg-card-hover text-muted-foreground px-2 py-0.5 rounded-lg font-medium">
                {capsules.length}
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm mt-0.5">
            {currentUser?.user_type === "organization"
              ? "Your organization's knowledge — encrypted and access-controlled"
              : "Your saved memories — encrypted and secure"}
          </p>
        </div>
        <button
          onClick={() => { setShowForm(!showForm); setEditingCapsule(null); }}
          className={`px-4 py-2.5 font-medium rounded-xl text-sm transition-all ${
            showForm
              ? "bg-card-hover text-muted-foreground border border-card-border"
              : "bg-accent hover:bg-accent-hover text-accent-fg hover:shadow-lg hover:shadow-accent/20"
          }`}
        >
          {showForm ? "Cancel" : "+ Save Something"}
        </button>
      </div>

      {(showForm || editingCapsule) && (
        <CapsuleForm
          userId={userId}
          networks={networks ?? []}
          capsule={editingCapsule}
          isOrg={currentUser?.user_type === "organization"}
          onDone={() => {
            setShowForm(false);
            setEditingCapsule(null);
            queryClient.invalidateQueries({ queryKey: ["capsules", userId] });
          }}
        />
      )}

      {/* Search */}
      <div className="mb-3">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setShowCount(20); }}
            placeholder="Search memories..."
            className="w-full bg-card border border-card-border rounded-xl pl-9 pr-4 py-2.5 text-sm placeholder:text-muted-foreground"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-1.5 mb-5">
        <button
          onClick={() => { setTypeFilter("all"); setShowCount(20); }}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
            typeFilter === "all" && tierFilter === "all"
              ? "bg-accent text-accent-fg"
              : "bg-card border border-card-border text-muted-foreground hover:text-foreground"
          }`}
        >
          All
        </button>
        {CAPSULE_TYPES.map((f) => (
          <button
            key={f}
            onClick={() => { setTypeFilter(typeFilter === f ? "all" : f); setShowCount(20); }}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all flex items-center gap-1 ${
              typeFilter === f
                ? "bg-accent text-accent-fg"
                : "bg-card border border-card-border text-muted-foreground hover:text-foreground hover:border-accent/30"
            }`}
          >
            <span>{CAPSULE_TYPE_EMOJIS[f]}</span>
            <span>{f}</span>
          </button>
        ))}
        <span className="w-px h-4 bg-card-border mx-1" />
        {TIERS.map((t) => (
          <button
            key={t}
            onClick={() => { setTierFilter(tierFilter === t ? "all" : t); setShowCount(20); }}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
              tierFilter === t
                ? "bg-accent text-accent-fg"
                : "bg-card border border-card-border text-muted-foreground hover:text-foreground hover:border-accent/30"
            }`}
          >
            {TIER_FILTER_LABELS[t]}
          </button>
        ))}
        {(typeFilter !== "all" || tierFilter !== "all" || search) && filtered && (
          <span className="text-[11px] text-muted-foreground ml-1">{filtered.length} result{filtered.length !== 1 ? "s" : ""}</span>
        )}
      </div>

      {/* Capsule List */}
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-card border border-card-border rounded-2xl p-4 animate-pulse">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-card-hover rounded-xl" />
                <div className="flex-1">
                  <div className="h-4 bg-card-hover rounded w-40 mb-1.5" />
                  <div className="h-3 bg-card-hover rounded w-60" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-1.5">
          {visible?.map((c: Capsule) => {
            const relTime = formatRelativeTime(c.freshness, c.last_verified_at);
            return (
              <div
                key={c.id}
                className="bg-card border border-card-border rounded-2xl overflow-hidden hover:border-card-border/80 transition-all"
              >
                {/* Collapsed row */}
                <button
                  className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-card-hover/40 transition-colors"
                  onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
                >
                  <CapsuleTypeBadge type={c.capsule_type} />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium block truncate">{c.title}</span>
                    <span className="text-[11px] text-muted-foreground truncate block leading-snug">
                      {c.content.slice(0, 90)}{c.content.length > 90 ? "..." : ""}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    <TrustBadge tier={c.tier} />
                    {c.stale_since && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20" title={c.stale_reason || "Potentially stale data"}>&#x26a0; stale</span>
                    )}
                    {c.propagation === "notify" && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400 border border-yellow-500/20" title="Notifies network on update">notify</span>
                    )}
                    {c.propagation === "broadcast" && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20" title="Broadcasts to all pods on update">broadcast</span>
                    )}
                    {c.network_names && c.network_names.length > 0 && (
                      <span className="text-[10px] text-muted-foreground/60 hidden sm:block truncate max-w-[100px]">
                        {c.network_names.join(", ")}
                      </span>
                    )}
                    {relTime && (
                      <span className="text-[10px] text-muted-foreground/50 hidden md:block whitespace-nowrap">
                        {relTime}
                      </span>
                    )}
                    <svg
                      width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                      strokeLinecap="round" strokeLinejoin="round"
                      className={`text-muted-foreground/40 transition-transform shrink-0 ${expandedId === c.id ? "rotate-180" : ""}`}
                    >
                      <polyline points="6 9 12 15 18 9"/>
                    </svg>
                  </div>
                </button>

                {/* Expanded detail */}
                {expandedId === c.id && (
                  <div className="px-4 pb-4 border-t border-card-border">
                    <p className="text-sm mt-3 whitespace-pre-wrap leading-relaxed text-muted-foreground bg-background/50 rounded-xl p-4">
                      {c.content}
                    </p>

                    {/* Stale warning banner */}
                    {c.stale_since && (
                      <div className="mt-3 flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-orange-500/10 border border-orange-500/20">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-orange-400">&#x26a0; Potentially stale</p>
                          {c.stale_reason && (
                            <p className="text-xs text-orange-400/70 mt-0.5">{c.stale_reason}</p>
                          )}
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            Since {new Date(c.stale_since).toLocaleDateString()}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            onClick={() => markReviewedMutation.mutate(c.id)}
                            disabled={markReviewedMutation.isPending}
                            className="px-3 py-1.5 text-xs bg-card text-muted-foreground rounded-lg hover:text-foreground hover:bg-card-hover transition-colors border border-card-border disabled:opacity-40"
                          >
                            Mark as reviewed
                          </button>
                          <button
                            onClick={() => autoUpdateMutation.mutate(c.id)}
                            disabled={autoUpdateMutation.isPending}
                            className="px-3 py-1.5 text-xs bg-orange-500/20 text-orange-400 rounded-lg hover:bg-orange-500/30 transition-colors border border-orange-500/30 disabled:opacity-40"
                          >
                            {autoUpdateMutation.isPending ? "Updating..." : "Auto-update"}
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Metadata row */}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-[11px] text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <span>{CAPSULE_TYPE_EMOJIS[c.capsule_type]}</span>
                        <span className="capitalize">{c.capsule_type}</span>
                      </span>
                      {relTime && (
                        <span className="flex items-center gap-1">
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                          </svg>
                          {relTime}
                        </span>
                      )}
                      {c.expires_at && (
                        <span className="text-amber-400/70">
                          Expires {new Date(c.expires_at).toLocaleDateString()}
                        </span>
                      )}
                      {c.network_names && c.network_names.length > 0 && (
                        <span>Shared with: {c.network_names.join(", ")}</span>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={() => {
                          setEditingCapsule(c);
                          setShowForm(false);
                          setExpandedId(null);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                        className="px-3 py-1.5 text-xs bg-accent/10 text-accent rounded-lg hover:bg-accent/20 transition-colors border border-accent/20"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => deleteMutation.mutate(c.id)}
                        disabled={deleteMutation.isPending}
                        className="px-3 py-1.5 text-xs bg-danger/10 text-danger rounded-lg hover:bg-danger/20 transition-colors border border-danger/20 disabled:opacity-40"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}

          {filtered && filtered.length > showCount && (
            <button
              onClick={() => setShowCount((prev) => prev + 20)}
              className="w-full py-3 text-sm text-accent hover:text-accent-hover font-medium bg-card border border-card-border rounded-2xl hover:bg-card-hover transition-all"
            >
              Show {Math.min(20, filtered.length - showCount)} more ({filtered.length - showCount} remaining)
            </button>
          )}

          {!filtered?.length && (
            <EmptyState
              variant="card"
              title={search ? `No memories match "${search}".` : "No memories match this filter."}
              action={
                !search ? (
                  <button
                    onClick={() => { setTypeFilter("all"); setTierFilter("all"); setShowForm(true); }}
                    className="text-accent text-sm hover:text-accent-hover transition-colors"
                  >
                    Save something new →
                  </button>
                ) : undefined
              }
            />
          )}
        </div>
      )}
    </div>
  );
}

/* ── Tier explanations ── */

const TIER_EXPLANATIONS: Record<string, { label: string; detail: string }> = {
  public: {
    label: "Everyone",
    detail: "Anyone who queries your agent can see this — including people outside your connections.",
  },
  network: {
    label: "Shared groups",
    detail: "Only members of the groups you select can access this memory.",
  },
  private: {
    label: "Only you",
    detail: "Only your own agent can access this. Nobody else can see it.",
  },
};

/* ── Capsule Form with AI Assist ── */

// Map org pool selection to tier + network_ids
type OrgPoolOption = "public" | "all_staff" | "leadership" | "private_org";

const ORG_POOL_OPTIONS: { key: OrgPoolOption; label: string; detail: string; emoji: string }[] = [
  { key: "public",      label: "Public",     detail: "Any external agent can query this",          emoji: "🌐" },
  { key: "all_staff",   label: "All Staff",  detail: "All connected staff members can access",     emoji: "👥" },
  { key: "leadership",  label: "Leadership", detail: "Executive team only",                         emoji: "🔒" },
  { key: "private_org", label: "Private",    detail: "Org admin only — not shared with anyone",    emoji: "🔐" },
];

function CapsuleForm({
  userId,
  networks,
  capsule,
  isOrg = false,
  onDone,
}: {
  userId: string;
  networks: Network[];
  capsule?: Capsule | null;
  isOrg?: boolean;
  onDone: () => void;
}) {
  const isEdit = !!capsule;
  const originalTier = capsule?.tier || "private";

  const [mode, setMode] = useState<"manual" | "ai">(isEdit ? "manual" : "ai");
  const [aiInput, setAiInput] = useState("");
  const [aiLoading, setAiLoading] = useState(false);

  const [type, setType] = useState(capsule?.capsule_type || "memory");
  const [title, setTitle] = useState(capsule?.title || "");
  const [content, setContent] = useState(capsule?.content || "");
  const [tier, setTier] = useState(capsule?.tier || "private");
  const [selectedNetworks, setSelectedNetworks] = useState<string[]>(capsule?.network_ids || []);
  const [propagation, setPropagation] = useState(capsule?.propagation || "silent");
  const [showVisibilityConfirm, setShowVisibilityConfirm] = useState(false);

  // Org pool selection
  const [orgPool, setOrgPool] = useState<OrgPoolOption>("private_org");
  const allStaffNetwork = networks.find((n) => n.pool_type === "org_all_staff");
  const leadershipNetwork = networks.find((n) => n.pool_type === "org_executives");

  // Derive tier + network_ids from org pool selection
  const orgTier = orgPool === "public" ? "public" : orgPool === "private_org" ? "private" : "network";
  const orgNetworkIds =
    orgPool === "all_staff" ? (allStaffNetwork ? [allStaffNetwork.id] : []) :
    orgPool === "leadership" ? (leadershipNetwork ? [leadershipNetwork.id] : []) : [];

  const tierOrder = { private: 0, network: 1, public: 2 } as Record<string, number>;
  const isWidening = (tierOrder[tier] ?? 0) > (tierOrder[originalTier] ?? 0);

  /** Let AI guess the type/title/content from a free-form description. */
  const handleAiAssist = async () => {
    if (!aiInput.trim()) return;
    setAiLoading(true);
    try {
      // Use the agent to classify and structure the input
      const csrf = getCsrfToken();
      const res = await fetch(`${getPodUrl()}/api/users/${userId}/intake`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(csrf ? { "x-csrf-token": csrf } : {}) },
        credentials: "include",
        body: JSON.stringify({
          message: `I want to save this to my vault: "${aiInput}". Please suggest: 1) The best capsule type (memory/skill/procedure/schedule/preference/contact), 2) A short title (max 60 chars), 3) The full content to save. Reply in JSON: {"type":"...","title":"...","content":"..."}`,
          conversation_history: [],
        }),
      });

      if (!res.ok) throw new Error("AI assist failed");

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No reader");

      const decoder = new TextDecoder();
      let buffer = "";
      let fullText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "text") fullText += event.data;
          } catch {}
        }
      }

      // Extract JSON from the AI response
      // Extract first JSON object from response
      const jsonStart = fullText.indexOf("{");
      const jsonEnd = fullText.lastIndexOf("}");
      const jsonMatch = jsonStart >= 0 && jsonEnd > jsonStart ? [fullText.slice(jsonStart, jsonEnd + 1)] : null;
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]);
        if (parsed.type && CAPSULE_TYPES.includes(parsed.type as CapsuleType)) setType(parsed.type as CapsuleType);
        if (parsed.title) setTitle(parsed.title);
        if (parsed.content) setContent(parsed.content);
        setMode("manual");
      } else {
        // Fallback: just pre-fill content
        setContent(aiInput);
        setMode("manual");
      }
    } catch {
      // Fallback: just pre-fill content with their text
      setContent(aiInput);
      setMode("manual");
    }
    setAiLoading(false);
  };

  const doSave = () => { mutation.mutate(); };

  const handleSave = () => {
    if (isWidening && !showVisibilityConfirm) {
      setShowVisibilityConfirm(true);
      return;
    }
    doSave();
  };

  const effectiveTier = isOrg ? orgTier : tier;
  const effectiveNetworkIds = isOrg
    ? orgNetworkIds
    : (tier === "network" ? selectedNetworks : []);

  const mutation = useMutation({
    mutationFn: () =>
      isEdit
        ? api.updateCapsule(capsule!.id, {
            capsule_type: type, title, content,
            tier: effectiveTier,
            network_ids: effectiveNetworkIds,
            propagation,
          })
        : api.createCapsule(userId, {
            capsule_type: type, title, content,
            tier: effectiveTier,
            network_ids: effectiveNetworkIds,
            propagation,
          }),
    onSuccess: onDone,
  });

  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 mb-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">{isEdit ? "Edit Memory" : "Save Something New"}</h2>
        {!isEdit && (
          <div className="flex items-center bg-card-hover rounded-lg p-0.5">
            <button
              onClick={() => setMode("ai")}
              className={`px-2.5 py-1 text-xs rounded-md transition-all ${mode === "ai" ? "bg-accent/20 text-accent font-medium" : "text-muted-foreground hover:text-foreground"}`}
            >
              ✨ AI Assist
            </button>
            <button
              onClick={() => setMode("manual")}
              className={`px-2.5 py-1 text-xs rounded-md transition-all ${mode === "manual" ? "bg-card text-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
            >
              Manual
            </button>
          </div>
        )}
      </div>

      {/* AI Assist mode */}
      {mode === "ai" && !isEdit && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">Describe what you want to save — your agent will figure out how to categorize it.</p>
          <textarea
            value={aiInput}
            onChange={(e) => setAiInput(e.target.value)}
            rows={3}
            placeholder="e.g. My blood type is A+ and I'm allergic to penicillin..."
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm resize-y placeholder:text-muted-foreground focus:outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <button
              onClick={handleAiAssist}
              disabled={!aiInput.trim() || aiLoading}
              className="flex-1 bg-accent hover:bg-accent-hover text-accent-fg font-semibold py-2.5 rounded-xl text-sm disabled:opacity-40 transition-all flex items-center justify-center gap-2"
            >
              {aiLoading ? (
                <>
                  <Spinner />
                  Thinking...
                </>
              ) : (
                <>✨ Let AI categorize this</>
              )}
            </button>
            <button
              onClick={() => setMode("manual")}
              className="px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground bg-card-hover rounded-xl transition-all"
            >
              Fill manually
            </button>
          </div>
        </div>
      )}

      {/* Manual mode */}
      {mode === "manual" && (
        <>
          {/* Type Selection */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-muted-foreground mb-2">Memory type</label>
            <div className="grid grid-cols-3 gap-1.5">
              {CAPSULE_TYPES.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setType(t)}
                  className={`p-2.5 rounded-xl text-left transition-all ${
                    type === t
                      ? "bg-accent/10 border-2 border-accent"
                      : "bg-card-hover border-2 border-transparent hover:border-card-border"
                  }`}
                >
                  <span className="text-base block mb-1">{CAPSULE_TYPE_EMOJIS[t]}</span>
                  <span className="text-xs font-medium block capitalize">{t}</span>
                  <span className="text-[9px] text-muted-foreground leading-tight block">{TYPE_DESCRIPTIONS[t]}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Sharing Level — org pool selector or person tier selector */}
          {isOrg ? (
            <div className="mb-4">
              <label className="block text-xs font-medium text-muted-foreground mb-2">Visibility / Access</label>
              <div className="grid grid-cols-2 gap-1.5">
                {ORG_POOL_OPTIONS.map((opt) => (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => setOrgPool(opt.key)}
                    className={`p-2.5 rounded-xl text-left transition-all ${
                      orgPool === opt.key
                        ? "bg-accent/10 border-2 border-accent"
                        : "bg-card-hover border-2 border-transparent hover:border-card-border"
                    }`}
                  >
                    <span className="text-base block mb-0.5">{opt.emoji}</span>
                    <span className="text-xs font-medium block">{opt.label}</span>
                    <span className="text-[9px] text-muted-foreground leading-tight block">{opt.detail}</span>
                  </button>
                ))}
              </div>
              {orgPool === "all_staff" && !allStaffNetwork && (
                <p className="text-[11px] text-amber-400 mt-2">No All Staff pool found — will save as private.</p>
              )}
              {orgPool === "leadership" && !leadershipNetwork && (
                <p className="text-[11px] text-amber-400 mt-2">No Leadership pool found — will save as private.</p>
              )}
            </div>
          ) : (
            <div className="mb-4">
              <label className="block text-xs font-medium text-muted-foreground mb-2">Who can see this?</label>
              <div className="grid grid-cols-3 gap-1.5">
                {TIERS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => { setTier(t); setShowVisibilityConfirm(false); }}
                    className={`p-2.5 rounded-xl text-center transition-all ${
                      tier === t
                        ? "bg-accent/10 border-2 border-accent"
                        : "bg-card-hover border-2 border-transparent hover:border-card-border"
                    }`}
                  >
                    <TrustBadge tier={t} />
                    <span className="text-[10px] text-muted-foreground block mt-1.5 font-medium">
                      {TIER_EXPLANATIONS[t]?.label}
                    </span>
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground mt-2 leading-relaxed">
                {TIER_EXPLANATIONS[tier]?.detail}
              </p>
            </div>
          )}

          {/* Title */}
          <div className="mb-3">
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., House Plumbing Layout"
              className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:border-accent"
            />
          </div>

          {/* Content */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">Content</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              placeholder="What do you want to remember?"
              className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm resize-y placeholder:text-muted-foreground focus:outline-none focus:border-accent"
            />
          </div>

          {/* Network Selection (person only — org uses pool selector above) */}
          {!isOrg && tier === "network" && (
            <div className="mb-4">
              <label className="block text-xs font-medium text-muted-foreground mb-2">Share with groups</label>
              {networks.length === 0 ? (
                <p className="text-xs text-muted-foreground">Create a group first to share memories.</p>
              ) : (
                <div className="flex gap-2 flex-wrap">
                  {networks.map((n) => (
                    <label key={n.id} className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs cursor-pointer transition-all ${
                      selectedNetworks.includes(n.id) ? "bg-accent/10 border border-accent/30 text-accent" : "bg-card-hover border border-transparent hover:border-card-border"
                    }`}>
                      <input
                        type="checkbox"
                        checked={selectedNetworks.includes(n.id)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedNetworks([...selectedNetworks, n.id]);
                          } else {
                            setSelectedNetworks(selectedNetworks.filter((id) => id !== n.id));
                          }
                        }}
                        className="rounded accent-accent"
                      />
                      {n.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Propagation selector — shown when sharing with networks */}
          {(tier === "network" || tier === "public") && selectedNetworks.length > 0 && (
            <div className="mb-4">
              <label className="block text-xs font-medium text-muted-foreground mb-2">
                When this capsule changes
              </label>
              <div className="flex gap-2">
                {(["silent", "notify", "broadcast"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setPropagation(mode)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                      propagation === mode
                        ? mode === "broadcast"
                          ? "bg-red-500/15 text-red-400 border border-red-500/30"
                          : mode === "notify"
                          ? "bg-yellow-500/15 text-yellow-400 border border-yellow-500/30"
                          : "bg-card-hover text-foreground border border-card-border"
                        : "bg-card-hover/50 text-muted-foreground border border-transparent hover:border-card-border"
                    }`}
                  >
                    {mode === "silent" && "Don't notify"}
                    {mode === "notify" && "Notify network"}
                    {mode === "broadcast" && "Broadcast to all pods"}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-muted-foreground/60 mt-1">
                {propagation === "silent" && "Network members discover changes on their next query."}
                {propagation === "notify" && "Network members get a notification when you update this."}
                {propagation === "broadcast" && "All pods in the network get pushed a notification instantly."}
              </p>
            </div>
          )}

          {/* Visibility widening confirmation */}
          {showVisibilityConfirm && isWidening && (
            <div className="mb-4 rounded-xl border border-warning/30 bg-warning/5 p-4 space-y-2">
              <p className="text-sm font-medium">
                {tier === "public" ? "Make this memory visible to everyone?" : "Share this with groups?"}
              </p>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {tier === "public"
                  ? "Anyone who queries your agent — including strangers — will be able to see this."
                  : "Group members can access this through their agents."}
              </p>
              <div className="flex gap-2 pt-1">
                <button
                  onClick={doSave}
                  disabled={mutation.isPending}
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-accent hover:bg-accent-hover text-accent-fg transition-colors disabled:opacity-40"
                >
                  {mutation.isPending ? "Saving..." : "Yes, save"}
                </button>
                <button
                  onClick={() => setShowVisibilityConfirm(false)}
                  className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {!showVisibilityConfirm && (
            <button
              onClick={handleSave}
              disabled={!title.trim() || !content.trim() || mutation.isPending}
              className="w-full bg-accent hover:bg-accent-hover text-accent-fg font-semibold py-3 rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/20"
            >
              {mutation.isPending ? (
                <span className="flex items-center justify-center gap-2">
                  <Spinner />
                  Saving...
                </span>
              ) : isEdit ? "Save Changes" : isOrg ? "Save to Knowledge Base" : "Save Memory"}
            </button>
          )}

          {mutation.isError && (
            <p className="text-xs text-danger mt-2">{(mutation.error as Error).message}</p>
          )}
        </>
      )}
    </div>
  );
}
