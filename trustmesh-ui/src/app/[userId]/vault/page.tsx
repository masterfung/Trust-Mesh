"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Capsule, type ContextMode, type Network } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, CapsuleTypeBadge } from "@/components/TrustBadge";
import { matchesContext } from "@/lib/context";

const CAPSULE_TYPES = ["memory", "skill", "procedure", "schedule", "preference", "contact"];
const TIERS = ["public", "network", "private"];
const TIER_FILTER_LABELS: Record<string, string> = { public: "everyone", network: "shared", private: "only me" };

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
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">My Memories</h1>
            {capsules && (
              <span className="text-xs bg-card-hover text-muted-foreground px-2.5 py-1 rounded-lg font-medium">
                {capsules.length} memories
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm">Your saved memories &mdash; encrypted and secure</p>
        </div>
        <button
          onClick={() => { setShowForm(!showForm); setEditingCapsule(null); }}
          className={`px-4 py-2.5 font-medium rounded-xl text-sm transition-all ${
            showForm
              ? "bg-card-hover text-muted-foreground border border-card-border"
              : "bg-accent hover:bg-accent-hover text-accent-fg hover:shadow-lg hover:shadow-accent/20"
          }`}
        >
          {showForm ? "Cancel" : "+ Save Something New"}
        </button>
      </div>

      {(showForm || editingCapsule) && (
        <CapsuleForm
          userId={userId}
          networks={networks ?? []}
          capsule={editingCapsule}
          onDone={() => {
            setShowForm(false);
            setEditingCapsule(null);
            queryClient.invalidateQueries({ queryKey: ["capsules", userId] });
          }}
        />
      )}

      {/* Search */}
      <div className="mb-4">
        <input
          type="text"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setShowCount(20); }}
          placeholder="Search memories..."
          className="w-full bg-card border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground"
        />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-5">
        {["all", ...CAPSULE_TYPES].map((f) => (
          <button
            key={f}
            onClick={() => { setTypeFilter(f); setShowCount(20); }}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
              typeFilter === f
                ? "bg-accent text-accent-fg shadow-sm"
                : "bg-card border border-card-border text-muted-foreground hover:text-foreground hover:border-accent/30"
            }`}
          >
            {f}
          </button>
        ))}
        <span className="w-px h-4 bg-card-border mx-1" />
        {TIERS.map((t) => (
          <button
            key={t}
            onClick={() => { setTierFilter(tierFilter === t ? "all" : t); setShowCount(20); }}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
              tierFilter === t
                ? "bg-accent text-accent-fg shadow-sm"
                : "bg-card border border-card-border text-muted-foreground hover:text-foreground hover:border-accent/30"
            }`}
          >
            {TIER_FILTER_LABELS[t] || t}
          </button>
        ))}
        {(typeFilter !== "all" || tierFilter !== "all" || search) && filtered && (
          <span className="text-[11px] text-muted-foreground ml-2">{filtered.length} results</span>
        )}
      </div>

      {/* Capsule List */}
      {isLoading ? (
        <div className="text-muted-foreground animate-pulse text-center py-12">Loading memories...</div>
      ) : (
        <div className="space-y-2">
          {visible?.map((c: Capsule) => (
            <div
              key={c.id}
              className="bg-card border border-card-border rounded-2xl overflow-hidden hover:border-card-border transition-all"
            >
              <button
                className="w-full flex items-center gap-3 p-4 text-left hover:bg-card-hover/50 transition-colors"
                onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
              >
                <CapsuleTypeBadge type={c.capsule_type} />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium block truncate">{c.title}</span>
                  <span className="text-[11px] text-muted-foreground truncate block">{c.content.slice(0, 80)}{c.content.length > 80 ? "..." : ""}</span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <TrustBadge tier={c.tier} />
                  {c.network_names && c.network_names.length > 0 && (
                    <span className="text-[10px] text-muted-foreground truncate max-w-[120px]">
                      {c.network_names.join(", ")}
                    </span>
                  )}
                </div>
                <svg
                  width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round"
                  className={`text-muted-foreground transition-transform shrink-0 ${expandedId === c.id ? "rotate-180" : ""}`}
                >
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </button>
              {expandedId === c.id && (
                <div className="px-4 pb-4 border-t border-card-border">
                  <p className="text-sm mt-4 whitespace-pre-wrap leading-relaxed text-muted-foreground bg-background rounded-xl p-4">{c.content}</p>
                  <div className="flex items-center gap-4 mt-3 text-[11px] text-muted-foreground">
                    <span>Type: {c.capsule_type}</span>
                    <span>Last updated: {c.freshness}</span>
                    {c.expires_at && <span>Expires: {new Date(c.expires_at).toLocaleDateString()}</span>}
                    {c.network_names && c.network_names.length > 0 && (
                      <span>Shared with: {c.network_names.join(", ")}</span>
                    )}
                  </div>
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
                      className="px-3 py-1.5 text-xs bg-danger/10 text-danger rounded-lg hover:bg-danger/20 transition-colors border border-danger/20"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Show more button */}
          {filtered && filtered.length > showCount && (
            <button
              onClick={() => setShowCount((prev) => prev + 20)}
              className="w-full py-3 text-sm text-accent hover:text-accent-hover font-medium bg-card border border-card-border rounded-2xl hover:bg-card-hover transition-all"
            >
              Show more ({filtered.length - showCount} remaining)
            </button>
          )}

          {!filtered?.length && (
            <div className="text-center py-12">
              <p className="text-muted-foreground text-sm">
                {search ? "No memories match your search." : "No memories match this filter."}
              </p>
              {!search && (
                <button
                  onClick={() => { setTypeFilter("all"); setTierFilter("all"); setShowForm(true); }}
                  className="mt-3 text-accent text-sm hover:text-accent-hover transition-colors"
                >
                  Add your first memory &rarr;
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const TIER_EXPLANATIONS: Record<string, { label: string; detail: string }> = {
  public: {
    label: "Visible to everyone",
    detail: "Anyone who queries your agent can see this — including strangers and cross-pod requests.",
  },
  network: {
    label: "Shared with groups",
    detail: "Only members of the groups you select below can see this memory.",
  },
  private: {
    label: "Only you",
    detail: "Only your own agent can access this. No one else — not even connections — can see it.",
  },
};

function CapsuleForm({
  userId,
  networks,
  capsule,
  onDone,
}: {
  userId: string;
  networks: Network[];
  capsule?: Capsule | null;
  onDone: () => void;
}) {
  const isEdit = !!capsule;
  const originalTier = capsule?.tier || "private";
  const [type, setType] = useState(capsule?.capsule_type || "memory");
  const [title, setTitle] = useState(capsule?.title || "");
  const [content, setContent] = useState(capsule?.content || "");
  const [tier, setTier] = useState(capsule?.tier || "private");
  const [selectedNetworks, setSelectedNetworks] = useState<string[]>(capsule?.network_ids || []);
  const [showVisibilityConfirm, setShowVisibilityConfirm] = useState(false);

  // Track if visibility is being widened (more public than before)
  const tierOrder = { private: 0, network: 1, public: 2 } as Record<string, number>;
  const isWidening = (tierOrder[tier] ?? 0) > (tierOrder[originalTier] ?? 0);

  const doSave = () => {
    mutation.mutate();
  };

  const handleSave = () => {
    // If widening visibility, show confirmation first
    if (isWidening && !showVisibilityConfirm) {
      setShowVisibilityConfirm(true);
      return;
    }
    doSave();
  };

  const mutation = useMutation({
    mutationFn: () =>
      isEdit
        ? api.updateCapsule(capsule!.id, {
            capsule_type: type,
            title,
            content,
            tier,
            network_ids: tier === "network" ? selectedNetworks : [],
          })
        : api.createCapsule(userId, {
            capsule_type: type,
            title,
            content,
            tier,
            network_ids: tier === "network" ? selectedNetworks : [],
          }),
    onSuccess: onDone,
  });

  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
      <h2 className="text-base font-semibold mb-1">{isEdit ? "Edit Memory" : "Save Something New"}</h2>
      <p className="text-xs text-muted-foreground mb-5">{isEdit ? `Editing "${capsule!.title}" — changes are saved automatically.` : "Your AI assistant will use this when answering questions."}</p>

      {/* Type Selection */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-2">Type</label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {CAPSULE_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setType(t)}
              className={`p-3 rounded-xl text-left transition-all ${
                type === t
                  ? "bg-accent/10 border-2 border-accent"
                  : "bg-card-hover border-2 border-transparent hover:border-card-border"
              }`}
            >
              <CapsuleTypeBadge type={t} />
              <span className="text-sm font-medium block mt-1 capitalize">{t}</span>
              <span className="text-[10px] text-muted-foreground">{TYPE_DESCRIPTIONS[t]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Sharing Level */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-2">Sharing Level</label>
        <div className="flex gap-2">
          {TIERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => { setTier(t); setShowVisibilityConfirm(false); }}
              className={`flex-1 p-3 rounded-xl text-center transition-all ${
                tier === t
                  ? "bg-accent/10 border-2 border-accent"
                  : "bg-card-hover border-2 border-transparent hover:border-card-border"
              }`}
            >
              <TrustBadge tier={t} />
              <span className="text-[10px] text-muted-foreground block mt-1.5">
                {TIER_EXPLANATIONS[t]?.label || t}
              </span>
            </button>
          ))}
        </div>
        {/* Tier detail explanation */}
        <p className="text-[11px] text-muted-foreground mt-2 leading-relaxed">
          {TIER_EXPLANATIONS[tier]?.detail}
        </p>
      </div>

      {/* Title */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Title</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g., House Plumbing Layout"
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground"
        />
      </div>

      {/* Content */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={5}
          placeholder="What do you want to remember?"
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm resize-y placeholder:text-muted-foreground"
        />
      </div>

      {/* Network Selection */}
      {tier === "network" && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-muted-foreground mb-2">Share to Networks</label>
          <div className="flex gap-2 flex-wrap">
            {networks.map((n) => (
              <label key={n.id} className={`flex items-center gap-2 px-3 py-2 rounded-xl text-sm cursor-pointer transition-all ${
                selectedNetworks.includes(n.id) ? "bg-accent/10 border border-accent/30" : "bg-card-hover border border-transparent"
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
            {!networks.length && (
              <p className="text-xs text-muted-foreground">Create a group first to share memories.</p>
            )}
          </div>
        </div>
      )}

      {/* Visibility widening confirmation */}
      {showVisibilityConfirm && isWidening && (
        <div className="mb-4 rounded-xl border border-warning/30 bg-warning/5 p-4 space-y-2">
          <p className="text-sm font-medium">
            {tier === "public" ? "Make this memory public?" : "Share this memory with groups?"}
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {tier === "public"
              ? "This memory will be visible to anyone who queries your agent — including people outside your connections and pools. This cannot be undone without manually changing it back."
              : "This memory will be visible to members of the selected groups. They can access it through their agents."}
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
              Go back
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
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              Saving...
            </span>
          ) : isEdit ? "Save Changes" : "Save Memory"}
        </button>
      )}

      {mutation.isError && (
        <p className="text-xs text-danger mt-2">{(mutation.error as Error).message}</p>
      )}
    </div>
  );
}
