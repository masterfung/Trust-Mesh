"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Capsule, type Network } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, CapsuleTypeBadge } from "@/components/TrustBadge";

const CAPSULE_TYPES = ["memory", "skill", "procedure", "schedule", "preference", "contact"];
const TIERS = ["public", "network", "private"];

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

  const { data: capsules, isLoading } = useQuery({
    queryKey: ["capsules", userId],
    queryFn: () => api.listCapsules(userId),
  });
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
            <h1 className="text-2xl font-bold">Knowledge Vault</h1>
            {capsules && (
              <span className="text-xs bg-card-hover text-muted-foreground px-2.5 py-1 rounded-lg font-medium">
                {capsules.length} capsules
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm">Your encrypted knowledge capsules &mdash; AES-256-GCM protected</p>
        </div>
        <button
          onClick={() => { setShowForm(!showForm); setEditingCapsule(null); }}
          className={`px-4 py-2.5 font-medium rounded-xl text-sm transition-all ${
            showForm
              ? "bg-card-hover text-muted-foreground border border-card-border"
              : "bg-accent hover:bg-accent-hover text-accent-fg hover:shadow-lg hover:shadow-accent/20"
          }`}
        >
          {showForm ? "Cancel" : "+ Add Capsule"}
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
          placeholder="Search capsules..."
          className="w-full bg-card border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted"
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
            {t}
          </button>
        ))}
        {(typeFilter !== "all" || tierFilter !== "all" || search) && filtered && (
          <span className="text-[11px] text-muted ml-2">{filtered.length} results</span>
        )}
      </div>

      {/* Capsule List */}
      {isLoading ? (
        <div className="text-muted animate-pulse text-center py-12">Loading vault...</div>
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
                  <span className="text-[11px] text-muted truncate block">{c.content.slice(0, 80)}{c.content.length > 80 ? "..." : ""}</span>
                </div>
                <TrustBadge tier={c.tier} />
                <svg
                  width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round"
                  className={`text-muted transition-transform shrink-0 ${expandedId === c.id ? "rotate-180" : ""}`}
                >
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </button>
              {expandedId === c.id && (
                <div className="px-4 pb-4 border-t border-card-border">
                  <p className="text-sm mt-4 whitespace-pre-wrap leading-relaxed text-muted-foreground bg-background rounded-xl p-4">{c.content}</p>
                  <div className="flex items-center gap-4 mt-3 text-[11px] text-muted">
                    <span>Type: {c.capsule_type}</span>
                    <span>Freshness: {c.freshness}</span>
                    {c.expires_at && <span>Expires: {new Date(c.expires_at).toLocaleDateString()}</span>}
                    {c.network_ids.length > 0 && (
                      <span>
                        Networks: {c.network_ids.map((nid) => {
                          const net = networks?.find((n) => n.id === nid);
                          return net?.name || nid.slice(0, 8);
                        }).join(", ")}
                      </span>
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
              <p className="text-muted text-sm">
                {search ? "No capsules match your search." : "No capsules match this filter."}
              </p>
              {!search && (
                <button
                  onClick={() => { setTypeFilter("all"); setTierFilter("all"); setShowForm(true); }}
                  className="mt-3 text-accent text-sm hover:text-accent-hover transition-colors"
                >
                  Add your first capsule &rarr;
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

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
  const [type, setType] = useState(capsule?.capsule_type || "memory");
  const [title, setTitle] = useState(capsule?.title || "");
  const [content, setContent] = useState(capsule?.content || "");
  const [tier, setTier] = useState(capsule?.tier || "private");
  const [selectedNetworks, setSelectedNetworks] = useState<string[]>(capsule?.network_ids || []);

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
      <h2 className="text-base font-semibold mb-1">{isEdit ? "Edit Capsule" : "Add Knowledge Capsule"}</h2>
      <p className="text-xs text-muted mb-5">{isEdit ? `Editing "${capsule!.title}" — changes are re-encrypted automatically.` : "Your agent will use this knowledge when responding to queries."}</p>

      {/* Type Selection */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-2">Capsule Type</label>
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
              <span className="text-[10px] text-muted">{TYPE_DESCRIPTIONS[t]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Trust Tier */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-2">Trust Tier</label>
        <div className="flex gap-2">
          {TIERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTier(t)}
              className={`flex-1 p-3 rounded-xl text-center transition-all ${
                tier === t
                  ? "bg-accent/10 border-2 border-accent"
                  : "bg-card-hover border-2 border-transparent hover:border-card-border"
              }`}
            >
              <TrustBadge tier={t} />
              <span className="text-[10px] text-muted block mt-1.5">
                {t === "public" ? "Anyone can see" : t === "network" ? "Network members" : "Only you"}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Title */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Title</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g., House Plumbing Layout"
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted"
        />
      </div>

      {/* Content */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={5}
          placeholder="The knowledge your agent will hold and share..."
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm resize-y placeholder:text-muted"
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
              <p className="text-xs text-muted">Create a network first to share capsules.</p>
            )}
          </div>
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={!title.trim() || !content.trim() || mutation.isPending}
        className="w-full bg-accent hover:bg-accent-hover text-accent-fg font-semibold py-3 rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/20"
      >
        {mutation.isPending ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            {isEdit ? "Saving..." : "Encrypting & storing..."}
          </span>
        ) : isEdit ? "Save Changes" : "Add to Vault"}
      </button>
    </div>
  );
}
