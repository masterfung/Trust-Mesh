"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Network, type User, type Connection } from "@/lib/api";
import { useParams } from "next/navigation";

const NETWORK_TYPES = ["family", "team", "friends", "custom"];

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
    <div className="max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Networks</h1>
          <p className="text-muted text-sm">Groups for sharing knowledge capsules</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-accent text-black font-medium rounded-lg text-sm hover:bg-accent-dim transition-colors"
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
        <div className="text-muted animate-pulse">Loading networks...</div>
      ) : (
        <div className="space-y-3">
          {networks?.map((n: Network) => (
            <div key={n.id} className="bg-card border border-card-border rounded-lg overflow-hidden">
              <button
                className="w-full flex items-center justify-between p-4 text-left hover:bg-card-border/20 transition-colors"
                onClick={() => setExpandedId(expandedId === n.id ? null : n.id)}
              >
                <div>
                  <span className="text-sm font-semibold">{n.name}</span>
                  <span className="ml-2 text-xs text-muted">{n.network_type}</span>
                </div>
                <span className="text-xs text-muted">{n.members.length} members</span>
              </button>
              {expandedId === n.id && (
                <div className="px-4 pb-4 border-t border-card-border">
                  <h3 className="text-xs text-muted mt-3 mb-2">Members</h3>
                  <div className="space-y-1">
                    {n.members.map((m: User) => (
                      <div key={m.id} className="flex items-center justify-between py-1">
                        <div className="flex items-center gap-2">
                          <div className="w-6 h-6 rounded-full bg-accent-dim flex items-center justify-center text-white text-xs font-bold">
                            {m.display_name[0]}
                          </div>
                          <span className="text-sm">{m.display_name}</span>
                        </div>
                        {m.id === n.owner_id && (
                          <span className="text-xs text-accent">Owner</span>
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
          ))}
          {!networks?.length && (
            <p className="text-muted text-sm text-center py-8">No networks yet. Create one to start sharing.</p>
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
    <div className="bg-card border border-card-border rounded-lg p-4 mb-6">
      <h2 className="text-sm font-semibold mb-3">Create Network</h2>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-xs text-muted mb-1">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., The Johnsons"
            className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
          >
            {NETWORK_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="mb-3">
        <label className="block text-xs text-muted mb-1">Description</label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What is this network for?"
          className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
        />
      </div>
      <button
        onClick={() => mutation.mutate()}
        disabled={!name.trim() || mutation.isPending}
        className="w-full bg-accent text-black font-medium py-2 rounded-lg text-sm hover:bg-accent-dim disabled:opacity-50 transition-colors"
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
    <div className="mt-3 pt-3 border-t border-card-border">
      <h3 className="text-xs text-muted mb-2">Add Connected User</h3>
      <div className="flex gap-2 flex-wrap">
        {eligible.map((u) => (
          <button
            key={u.id}
            onClick={() => mutation.mutate(u.id)}
            disabled={mutation.isPending}
            className="px-3 py-1 text-xs bg-accent/10 text-accent rounded hover:bg-accent/20 transition-colors"
          >
            + {u.display_name}
          </button>
        ))}
      </div>
    </div>
  );
}
