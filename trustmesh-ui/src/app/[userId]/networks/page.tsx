"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Network, type User, type Connection } from "@/lib/api";
import { useParams } from "next/navigation";

const NETWORK_TYPES = ["family", "team", "friends", "custom"];
const NETWORK_TYPE_CONFIG: Record<string, { icon: string; color: string }> = {
  family: { icon: "🏠", color: "bg-blue-500/15 text-blue-400 border-blue-500/25" },
  team: { icon: "💼", color: "bg-purple-500/15 text-purple-400 border-purple-500/25" },
  friends: { icon: "👥", color: "bg-green-500/15 text-green-400 border-green-500/25" },
  custom: { icon: "⚙️", color: "bg-orange-500/15 text-orange-400 border-orange-500/25" },
};

export default function NetworksPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: networks, isLoading } = useQuery({
    queryKey: ["networks", userId],
    queryFn: () => api.listNetworks(userId),
  });
  const { data: connections } = useQuery({
    queryKey: ["connections", userId],
    queryFn: () => api.listConnections(userId),
  });

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Networks</h1>
          <p className="text-muted-foreground text-sm">Trust groups for sharing knowledge capsules</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className={`px-4 py-2.5 font-medium rounded-xl text-sm transition-all ${
            showForm
              ? "bg-card-hover text-muted-foreground border border-card-border"
              : "bg-accent hover:bg-accent-hover text-white hover:shadow-lg hover:shadow-accent/20"
          }`}
        >
          {showForm ? "Cancel" : "+ Create Network"}
        </button>
      </div>

      {showForm && (
        <NetworkForm
          userId={userId}
          onDone={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["networks", userId] });
          }}
        />
      )}

      {isLoading ? (
        <div className="text-muted animate-pulse text-center py-12">Loading networks...</div>
      ) : (
        <div className="space-y-3">
          {networks?.map((n: Network) => {
            const config = NETWORK_TYPE_CONFIG[n.network_type] || NETWORK_TYPE_CONFIG.custom;
            return (
              <div key={n.id} className="bg-card border border-card-border rounded-2xl overflow-hidden">
                <button
                  className="w-full flex items-center gap-4 p-4 text-left hover:bg-card-hover/50 transition-colors"
                  onClick={() => setExpandedId(expandedId === n.id ? null : n.id)}
                >
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg border ${config.color}`}>
                    {config.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-semibold block">{n.name}</span>
                    <span className="text-[11px] text-muted capitalize">{n.network_type}</span>
                  </div>
                  <span className="text-xs text-muted-foreground bg-card-hover px-2.5 py-1 rounded-lg">{n.members.length} members</span>
                  <svg
                    width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round"
                    className={`text-muted transition-transform ${expandedId === n.id ? "rotate-180" : ""}`}
                  >
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>
                {expandedId === n.id && (
                  <div className="px-4 pb-4 border-t border-card-border">
                    {n.description && (
                      <p className="text-xs text-muted-foreground mt-3 mb-3">{n.description}</p>
                    )}
                    <h3 className="text-xs font-semibold text-muted mt-3 mb-2">Members</h3>
                    <div className="space-y-1.5">
                      {n.members.map((m: User) => (
                        <div key={m.id} className="flex items-center justify-between py-2 px-3 rounded-xl hover:bg-card-hover transition-colors">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center text-white text-xs font-bold">
                              {m.display_name[0]}
                            </div>
                            <div>
                              <span className="text-sm font-medium">{m.display_name}</span>
                              <span className="text-[11px] text-muted block">@{m.username}</span>
                            </div>
                          </div>
                          {m.id === n.owner_id && (
                            <span className="text-[10px] text-accent bg-accent/10 px-2 py-0.5 rounded-full font-medium">Owner</span>
                          )}
                        </div>
                      ))}
                    </div>

                    {n.owner_id === userId && connections && connections.length > 0 && (
                      <AddMemberToNetwork
                        networkId={n.id}
                        currentMembers={n.members}
                        connections={connections}
                        onAdded={() => queryClient.invalidateQueries({ queryKey: ["networks", userId] })}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {!networks?.length && (
            <div className="text-center py-12">
              <p className="text-muted text-sm">No networks yet.</p>
              <button
                onClick={() => setShowForm(true)}
                className="mt-3 text-accent text-sm hover:text-accent-hover transition-colors"
              >
                Create your first network &rarr;
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NetworkForm({ userId, onDone }: { userId: string; onDone: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("custom");
  const [description, setDescription] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      api.createNetwork({ name, description, network_type: type, owner_id: userId }),
    onSuccess: onDone,
  });

  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
      <h2 className="text-base font-semibold mb-4">Create Network</h2>

      {/* Type Selection */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-2">Type</label>
        <div className="grid grid-cols-4 gap-2">
          {NETWORK_TYPES.map((t) => {
            const config = NETWORK_TYPE_CONFIG[t];
            return (
              <button
                key={t}
                type="button"
                onClick={() => setType(t)}
                className={`p-3 rounded-xl text-center transition-all ${
                  type === t
                    ? "bg-accent/10 border-2 border-accent"
                    : "bg-card-hover border-2 border-transparent hover:border-card-border"
                }`}
              >
                <span className="text-lg block">{config.icon}</span>
                <span className="text-xs font-medium capitalize block mt-1">{t}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g., The Johnsons"
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted"
        />
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Description (optional)</label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What is this network for?"
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted"
        />
      </div>

      <button
        onClick={() => mutation.mutate()}
        disabled={!name.trim() || mutation.isPending}
        className="w-full bg-accent hover:bg-accent-hover text-white font-semibold py-3 rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/20"
      >
        {mutation.isPending ? "Creating..." : "Create Network"}
      </button>
    </div>
  );
}

function AddMemberToNetwork({
  networkId,
  currentMembers,
  connections,
  onAdded,
}: {
  networkId: string;
  currentMembers: User[];
  connections: Connection[];
  onAdded: () => void;
}) {
  const memberIds = new Set(currentMembers.map((m) => m.id));
  const eligible = connections
    .filter((c) => c.peer && !memberIds.has(c.peer.id))
    .map((c) => c.peer!);

  const mutation = useMutation({
    mutationFn: (uid: string) => api.addNetworkMember(networkId, uid),
    onSuccess: onAdded,
  });

  if (!eligible.length) return null;

  return (
    <div className="mt-4 pt-4 border-t border-card-border">
      <h3 className="text-xs font-semibold text-muted mb-2">Add Connected User</h3>
      <div className="flex gap-2 flex-wrap">
        {eligible.map((u) => (
          <button
            key={u.id}
            onClick={() => mutation.mutate(u.id)}
            disabled={mutation.isPending}
            className="px-3 py-1.5 text-xs bg-accent/10 text-accent rounded-xl hover:bg-accent/20 transition-colors border border-accent/20 font-medium"
          >
            + {u.display_name}
          </button>
        ))}
      </div>
    </div>
  );
}
