"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Capsule, type Network } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, CapsuleTypeBadge } from "@/components/TrustBadge";

const CAPSULE_TYPES = ["memory", "skill", "procedure", "schedule", "preference", "contact"];
const TIERS = ["public", "network", "private"];

export default function VaultPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

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

  const filtered = filter === "all"
    ? capsules
    : capsules?.filter((c) => c.capsule_type === filter || c.tier === filter);

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Knowledge Vault</h1>
          <p className="text-muted text-sm">Your encrypted knowledge capsules</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-accent text-black font-medium rounded-lg text-sm hover:bg-accent-dim transition-colors"
        >
          {showForm ? "Cancel" : "+ Add Capsule"}
        </button>
      </div>

      {showForm && (
        <CapsuleForm
          userId={userId}
          networks={networks ?? []}
          onDone={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["capsules", userId] });
          }}
        />
      )}

      {/* Filters */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {["all", ...CAPSULE_TYPES, ...TIERS].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === f
                ? "bg-accent text-black"
                : "bg-card border border-card-border text-muted hover:text-foreground"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-muted animate-pulse">Loading vault...</div>
      ) : (
        <div className="space-y-2">
          {filtered?.map((c: Capsule) => (
            <div
              key={c.id}
              className="bg-card border border-card-border rounded-lg overflow-hidden"
            >
              <button
                className="w-full flex items-center gap-3 p-3 text-left hover:bg-card-border/20 transition-colors"
                onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
              >
                <CapsuleTypeBadge type={c.capsule_type} />
                <span className="text-sm font-medium flex-1">{c.title}</span>
                <TrustBadge tier={c.tier} />
                <span className="text-xs text-muted">{expandedId === c.id ? "^" : "v"}</span>
              </button>
              {expandedId === c.id && (
                <div className="px-3 pb-3 border-t border-card-border">
                  <p className="text-sm mt-3 whitespace-pre-wrap">{c.content}</p>
                  <div className="flex items-center gap-4 mt-3 text-xs text-muted">
                    <span>Type: {c.capsule_type}</span>
                    <span>Freshness: {c.freshness}</span>
                    {c.network_ids.length > 0 && (
                      <span>
                        Networks: {c.network_ids.map((nid) => {
                          const net = networks?.find((n) => n.id === nid);
                          return net?.name || nid;
                        }).join(", ")}
                      </span>
                    )}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => deleteMutation.mutate(c.id)}
                      className="px-3 py-1 text-xs bg-danger/10 text-danger rounded hover:bg-danger/20 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
          {!filtered?.length && (
            <p className="text-muted text-sm text-center py-8">No capsules match this filter.</p>
          )}
        </div>
      )}
    </div>
  );
}

function CapsuleForm({
  userId,
  networks,
  onDone,
}: {
  userId: string;
  networks: Network[];
  onDone: () => void;
}) {
  const [type, setType] = useState("memory");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tier, setTier] = useState("private");
  const [selectedNetworks, setSelectedNetworks] = useState<string[]>([]);

  const mutation = useMutation({
    mutationFn: () =>
      api.createCapsule(userId, {
        capsule_type: type,
        title,
        content,
        tier,
        network_ids: tier === "network" ? selectedNetworks : [],
      }),
    onSuccess: onDone,
  });

  return (
    <div className="bg-card border border-card-border rounded-lg p-4 mb-6">
      <h2 className="text-sm font-semibold mb-4">Add Knowledge Capsule</h2>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-xs text-muted mb-1">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
          >
            {CAPSULE_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Trust Tier</label>
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value)}
            className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
          >
            {TIERS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="mb-3">
        <label className="block text-xs text-muted mb-1">Title</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g., House Plumbing Layout"
          className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
        />
      </div>

      <div className="mb-3">
        <label className="block text-xs text-muted mb-1">Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={4}
          placeholder="The knowledge your agent will hold and share..."
          className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm resize-y"
        />
      </div>

      {tier === "network" && (
        <div className="mb-3">
          <label className="block text-xs text-muted mb-1">Share to Networks</label>
          <div className="flex gap-2 flex-wrap">
            {networks.map((n) => (
              <label key={n.id} className="flex items-center gap-1.5 text-sm">
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
                  className="rounded"
                />
                {n.name}
              </label>
            ))}
          </div>
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={!title.trim() || !content.trim() || mutation.isPending}
        className="w-full bg-accent text-black font-medium py-2 rounded-lg text-sm hover:bg-accent-dim disabled:opacity-50 transition-colors"
      >
        {mutation.isPending ? "Encrypting & storing..." : "Add to Vault"}
      </button>
    </div>
  );
}
