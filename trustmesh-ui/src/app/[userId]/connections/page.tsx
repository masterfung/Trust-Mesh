"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User, type Connection, type ConnectionRequest } from "@/lib/api";
import { useParams } from "next/navigation";

export default function ConnectionsPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showConnect, setShowConnect] = useState(false);

  const { data: connections } = useQuery({
    queryKey: ["connections", userId],
    queryFn: () => api.listConnections(userId),
  });
  const { data: requests } = useQuery({
    queryKey: ["connection-requests", userId],
    queryFn: () => api.listConnectionRequests(userId),
  });
  const { data: allUsers } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
  });

  const connectedIds = new Set(connections?.map((c: Connection) => c.peer?.id).filter(Boolean));
  const unconnected = allUsers?.filter((u: User) => u.id !== userId && !connectedIds.has(u.id)) ?? [];

  const acceptMutation = useMutation({
    mutationFn: (requestId: string) => api.updateConnectionRequest(requestId, "accepted"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections", userId] });
      queryClient.invalidateQueries({ queryKey: ["connection-requests", userId] });
    },
  });

  const declineMutation = useMutation({
    mutationFn: (requestId: string) => api.updateConnectionRequest(requestId, "declined"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connection-requests", userId] }),
  });

  return (
    <div className="max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Connections</h1>
          <p className="text-muted text-sm">People you trust and share knowledge with</p>
        </div>
        <button
          onClick={() => setShowConnect(!showConnect)}
          className="px-4 py-2 bg-accent text-black font-medium rounded-lg text-sm hover:bg-accent-dim transition-colors"
        >
          {showConnect ? "Cancel" : "+ Connect"}
        </button>
      </div>

      {/* Pending Requests */}
      {requests && requests.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-warning mb-3">
            Pending Requests ({requests.length})
          </h2>
          <div className="space-y-2">
            {requests.map((r: ConnectionRequest) => (
              <div key={r.id} className="bg-card border border-warning/30 rounded-lg p-3 flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium">
                    {r.from_user?.display_name || "Unknown"}
                  </span>
                  {r.message && (
                    <p className="text-xs text-muted mt-0.5">&ldquo;{r.message}&rdquo;</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => acceptMutation.mutate(r.id)}
                    className="px-3 py-1 text-xs bg-success/10 text-success rounded hover:bg-success/20 transition-colors"
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => declineMutation.mutate(r.id)}
                    className="px-3 py-1 text-xs bg-danger/10 text-danger rounded hover:bg-danger/20 transition-colors"
                  >
                    Decline
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Send Connection Request */}
      {showConnect && unconnected.length > 0 && (
        <SendConnectionForm userId={userId} unconnected={unconnected} onDone={() => {
          setShowConnect(false);
          queryClient.invalidateQueries({ queryKey: ["connections", userId] });
        }} />
      )}

      {/* Current Connections */}
      <h2 className="text-sm font-semibold mb-3">Connected ({connections?.length ?? 0})</h2>
      <div className="space-y-2">
        {connections?.map((c: Connection) => (
          <div key={c.id} className="bg-card border border-card-border rounded-lg p-3 flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-accent-dim flex items-center justify-center text-white font-bold">
              {c.peer?.display_name?.[0] || "?"}
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">{c.peer?.display_name}</p>
              <p className="text-xs text-muted">@{c.peer?.username} &middot; {c.peer?.bio}</p>
            </div>
            <span className="text-xs text-success">Connected</span>
          </div>
        ))}
        {!connections?.length && (
          <p className="text-muted text-sm text-center py-8">No connections yet.</p>
        )}
      </div>
    </div>
  );
}

function SendConnectionForm({
  userId,
  unconnected,
  onDone,
}: {
  userId: string;
  unconnected: User[];
  onDone: () => void;
}) {
  const [targetId, setTargetId] = useState("");
  const [message, setMessage] = useState("");

  const mutation = useMutation({
    mutationFn: () => api.sendConnectionRequest(userId, targetId, message),
    onSuccess: onDone,
  });

  return (
    <div className="bg-card border border-card-border rounded-lg p-4 mb-6">
      <h2 className="text-sm font-semibold mb-3">Send Connection Request</h2>
      <div className="mb-3">
        <label className="block text-xs text-muted mb-1">Connect with</label>
        <select
          value={targetId}
          onChange={(e) => setTargetId(e.target.value)}
          className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
        >
          <option value="">Select a person...</option>
          {unconnected.map((u) => (
            <option key={u.id} value={u.id}>{u.display_name} (@{u.username})</option>
          ))}
        </select>
      </div>
      <div className="mb-3">
        <label className="block text-xs text-muted mb-1">Message (optional)</label>
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Hi, I'd like to connect..."
          className="w-full bg-background border border-card-border rounded px-2 py-1.5 text-sm"
        />
      </div>
      <button
        onClick={() => mutation.mutate()}
        disabled={!targetId || mutation.isPending}
        className="w-full bg-accent text-black font-medium py-2 rounded-lg text-sm hover:bg-accent-dim disabled:opacity-50 transition-colors"
      >
        {mutation.isPending ? "Sending..." : "Send Request"}
      </button>
    </div>
  );
}
