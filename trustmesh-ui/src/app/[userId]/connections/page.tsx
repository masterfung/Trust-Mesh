"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User, type ContextMode, type Connection, type ConnectionRequest } from "@/lib/api";
import { useParams } from "next/navigation";
import { matchesContext } from "@/lib/context";

export default function ConnectionsPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showConnect, setShowConnect] = useState(false);

  const { data: currentUser } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });
  const activeContext: ContextMode = (currentUser?.active_context as ContextMode) || "all";

  const { data: allConnections } = useQuery({
    queryKey: ["connections", userId],
    queryFn: () => api.listConnections(userId),
  });
  const connections = allConnections?.filter((c) => matchesContext(c.context, activeContext));
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
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Connections</h1>
          <p className="text-muted-foreground text-sm">People you trust and share knowledge with</p>
        </div>
        <button
          onClick={() => setShowConnect(!showConnect)}
          className={`px-4 py-2.5 font-medium rounded-xl text-sm transition-all ${
            showConnect
              ? "bg-card-hover text-muted-foreground border border-card-border"
              : "bg-accent hover:bg-accent-hover text-accent-fg hover:shadow-lg hover:shadow-accent/20"
          }`}
        >
          {showConnect ? "Cancel" : "+ Connect"}
        </button>
      </div>

      {/* Pending Requests */}
      {requests && requests.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-warning mb-3 flex items-center gap-2">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            Pending Requests ({requests.length})
          </h2>
          <div className="space-y-2">
            {requests.map((r: ConnectionRequest) => (
              <div key={r.id} className="bg-card border border-warning/20 rounded-2xl p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-warning/15 flex items-center justify-center text-warning font-bold text-sm">
                    {r.from_user?.display_name?.[0] || "?"}
                  </div>
                  <div>
                    <span className="text-sm font-semibold">
                      {r.from_user?.display_name || "Unknown"}
                    </span>
                    {r.message && (
                      <p className="text-xs text-muted-foreground mt-0.5">&ldquo;{r.message}&rdquo;</p>
                    )}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => acceptMutation.mutate(r.id)}
                    className="px-4 py-2 text-xs font-medium bg-success/10 text-success rounded-xl hover:bg-success/20 transition-colors border border-success/20"
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => declineMutation.mutate(r.id)}
                    className="px-4 py-2 text-xs font-medium bg-danger/10 text-danger rounded-xl hover:bg-danger/20 transition-colors border border-danger/20"
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
      <h2 className="text-sm font-semibold mb-3 text-muted-foreground">Connected ({connections?.length ?? 0})</h2>
      <div className="space-y-2">
        {connections?.map((c: Connection) => (
          <div key={c.id} className="bg-card border border-card-border rounded-2xl p-4 flex items-center gap-3 hover:bg-card-hover transition-colors">
            <div className="w-11 h-11 rounded-xl bg-accent flex items-center justify-center text-accent-fg font-bold">
              {c.peer?.display_name?.[0] || "?"}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold">{c.peer?.display_name}</p>
              <p className="text-xs text-muted-foreground truncate">@{c.peer?.username} &middot; {c.peer?.bio}</p>
            </div>
            <span className="inline-flex items-center gap-1 text-xs text-success bg-success/10 px-2.5 py-1 rounded-lg font-medium border border-success/20">
              <span className="w-1.5 h-1.5 rounded-full bg-success" />
              Connected
            </span>
          </div>
        ))}
        {!connections?.length && (
          <div className="text-center py-12">
            <p className="text-muted-foreground text-sm">No connections yet.</p>
            <button
              onClick={() => setShowConnect(true)}
              className="mt-3 text-accent text-sm hover:text-accent-hover transition-colors"
            >
              Send your first connection request &rarr;
            </button>
          </div>
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
    <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
      <h2 className="text-base font-semibold mb-4">Send Connection Request</h2>
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Connect with</label>
        <select
          value={targetId}
          onChange={(e) => setTargetId(e.target.value)}
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm"
        >
          <option value="">Select a person...</option>
          {unconnected.map((u) => (
            <option key={u.id} value={u.id}>{u.display_name} (@{u.username})</option>
          ))}
        </select>
      </div>
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Message (optional)</label>
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Hi, I'd like to connect..."
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground"
        />
      </div>
      <button
        onClick={() => mutation.mutate()}
        disabled={!targetId || mutation.isPending}
        className="w-full bg-accent hover:bg-accent-hover text-accent-fg font-semibold py-3 rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/20"
      >
        {mutation.isPending ? "Sending..." : "Send Request"}
      </button>
    </div>
  );
}
