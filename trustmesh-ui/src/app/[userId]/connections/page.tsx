"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User, type ContextMode, type Connection, type ConnectionRequest, type Network } from "@/lib/api";
import { useParams } from "next/navigation";
import { matchesContext } from "@/lib/context";
import { RelationshipBadge } from "@/components/TrustBadge";
import { ProfilePreview } from "@/components/ProfilePreview";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

export default function ConnectionsPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showConnect, setShowConnect] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<Connection | null>(null);

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
  const { data: networks } = useQuery({
    queryKey: ["networks", userId],
    queryFn: () => api.listNetworks(userId),
  });

  const connectedIds = new Set(connections?.map((c: Connection) => c.peer?.id).filter(Boolean));
  const unconnected = allUsers?.filter((u: User) => u.id !== userId && !connectedIds.has(u.id)) ?? [];

  const acceptMutation = useMutation({
    mutationFn: ({ requestId, toLabel }: { requestId: string; toLabel?: string }) =>
      api.updateConnectionRequest(requestId, "accepted", toLabel),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections", userId] });
      queryClient.invalidateQueries({ queryKey: ["connection-requests", userId] });
    },
  });

  const declineMutation = useMutation({
    mutationFn: (requestId: string) => api.updateConnectionRequest(requestId, "declined"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connection-requests", userId] }),
  });

  const disconnectMutation = useMutation({
    mutationFn: (connectionId: string) => api.deleteConnection(connectionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections", userId] });
      queryClient.invalidateQueries({ queryKey: ["networks", userId] });
    },
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
              <PendingRequestCard
                key={r.id}
                request={r}
                networks={networks}
                onAccept={(toLabel?: string) => acceptMutation.mutate({ requestId: r.id, toLabel })}
                onDecline={() => declineMutation.mutate(r.id)}
                isPending={acceptMutation.isPending || declineMutation.isPending}
              />
            ))}
          </div>
        </div>
      )}

      {/* Send Connection Request */}
      {showConnect && unconnected.length > 0 && (
        <SendConnectionForm userId={userId} unconnected={unconnected} networks={networks} onDone={() => {
          setShowConnect(false);
          queryClient.invalidateQueries({ queryKey: ["connections", userId] });
        }} />
      )}

      {/* Current Connections */}
      <h2 className="text-sm font-semibold mb-3 text-muted-foreground">Connected ({connections?.length ?? 0})</h2>
      <div className="space-y-2">
        {connections?.map((c: Connection) => (
          <div key={c.id} className="bg-card border border-card-border rounded-2xl p-4 flex items-center gap-3 group hover:bg-card-hover transition-colors">
            <div className="w-11 h-11 rounded-xl bg-accent flex items-center justify-center text-accent-fg font-bold">
              {c.peer?.display_name?.[0] || "?"}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold">{c.peer?.display_name}</p>
                {c.peer?.user_type === "organization" && (
                  <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold uppercase">Org</span>
                )}
                {c.peer?.user_type === "government" && (
                  <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-semibold uppercase">Gov</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground truncate">
                @{c.peer?.username}
                {c.peer?.profile_data?.occupation?.title && <> &middot; {c.peer.profile_data.occupation.title}</>}
                {c.my_label && <> &middot; {c.my_label}</>}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {c.relationship_type && <RelationshipBadge type={c.relationship_type} />}
              <span className="inline-flex items-center gap-1 text-xs text-success bg-success/10 px-2.5 py-1 rounded-lg font-medium border border-success/20">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                Connected
              </span>
              <button
                onClick={() => setDisconnectTarget(c)}
                disabled={disconnectMutation.isPending}
                className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-muted-foreground hover:text-danger hover:bg-danger/10 transition-all"
                title="Disconnect"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>
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

      {/* Disconnect Confirmation */}
      <ConfirmDialog
        open={!!disconnectTarget}
        onCancel={() => setDisconnectTarget(null)}
        onConfirm={() => {
          if (disconnectTarget) {
            disconnectMutation.mutate(disconnectTarget.id);
            setDisconnectTarget(null);
          }
        }}
        title={`Disconnect from ${disconnectTarget?.peer?.display_name}?`}
        description="This will remove the trust connection between you. They will no longer have connected-level access to your knowledge, and you'll lose access to theirs."
        confirmLabel="Disconnect"
        variant="danger"
        loading={disconnectMutation.isPending}
      />
    </div>
  );
}

/* ── Pending Request with Profile Preview ── */

function PendingRequestCard({
  request,
  networks,
  onAccept,
  onDecline,
  isPending,
}: {
  request: ConnectionRequest;
  networks?: Network[];
  onAccept: (toLabel?: string) => void;
  onDecline: () => void;
  isPending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [toLabel, setToLabel] = useState("");
  const from = request.from_user;

  return (
    <div className="bg-card border border-warning/20 rounded-2xl overflow-hidden">
      <button
        className="w-full p-4 flex items-center gap-3 text-left hover:bg-card-hover/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="w-10 h-10 rounded-xl bg-warning/15 flex items-center justify-center text-warning font-bold text-sm">
          {from?.display_name?.[0] || "?"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{from?.display_name || "Unknown"}</span>
            <span className="text-xs text-muted-foreground">@{from?.username}</span>
            {request.relationship_type && <RelationshipBadge type={request.relationship_type} />}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            {request.message && (
              <p className="text-xs text-muted-foreground truncate">&ldquo;{request.message}&rdquo;</p>
            )}
            {request.from_label && (
              <span className="text-[10px] text-accent shrink-0">They call you: {request.from_label}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {(request.mutual_connections || request.mutual_networks) ? (
            <span className="text-[10px] text-muted-foreground">
              {request.mutual_connections ? `${request.mutual_connections} mutual` : ""}
              {request.mutual_connections && request.mutual_networks ? " · " : ""}
              {request.mutual_networks ? `${request.mutual_networks} shared` : ""}
            </span>
          ) : null}
          <svg
            width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round"
            className={`text-muted-foreground transition-transform ${expanded ? "rotate-180" : ""}`}
          >
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-card-border">
          {from && (
            <div className="mt-3 mb-3">
              <ProfilePreview user={from} networks={networks} />
            </div>
          )}
          {request.message && (
            <div className="p-3 bg-card-hover/50 rounded-xl mb-3">
              <p className="text-[11px] text-muted-foreground uppercase font-semibold mb-1">Message</p>
              <p className="text-sm">{request.message}</p>
            </div>
          )}
          <div className="mb-3">
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Your label for them (optional)</label>
            <input
              type="text"
              value={toLabel}
              onChange={(e) => setToLabel(e.target.value)}
              placeholder={request.relationship_type === "family" ? "e.g. brother, cousin" : request.relationship_type === "work" ? "e.g. colleague, manager" : "e.g. friend, neighbor"}
              className="w-full bg-background border border-card-border rounded-lg px-3 py-1.5 text-xs placeholder:text-muted-foreground"
            />
          </div>
          <p className="text-[11px] text-muted-foreground mb-3">
            Accepting this request will create a mutual trust connection. You&apos;ll be able to share knowledge through shared networks.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => onAccept(toLabel || undefined)}
              disabled={isPending}
              className="flex-1 px-4 py-2.5 text-sm font-medium bg-success/10 text-success rounded-xl hover:bg-success/20 transition-colors border border-success/20 disabled:opacity-40"
            >
              Accept
            </button>
            <button
              onClick={onDecline}
              disabled={isPending}
              className="flex-1 px-4 py-2.5 text-sm font-medium bg-danger/10 text-danger rounded-xl hover:bg-danger/20 transition-colors border border-danger/20 disabled:opacity-40"
            >
              Decline
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const RELATIONSHIP_TYPES = ["family", "friend", "work", "healthcare", "neighbor", "emergency", "other"] as const;
const LABEL_SUGGESTIONS: Record<string, string[]> = {
  family: ["spouse", "parent", "child", "son", "daughter", "sibling", "grandparent", "in-law"],
  friend: ["close friend", "childhood friend"],
  work: ["boss", "manager", "direct report", "colleague", "mentor"],
  healthcare: ["doctor", "nurse", "therapist", "caregiver"],
  neighbor: ["next door"],
  emergency: ["ICE contact", "medical proxy"],
  other: [],
};

function SendConnectionForm({
  userId,
  unconnected,
  networks,
  onDone,
}: {
  userId: string;
  unconnected: User[];
  networks?: Network[];
  onDone: () => void;
}) {
  const [targetId, setTargetId] = useState("");
  const [message, setMessage] = useState("");
  const [relType, setRelType] = useState("");
  const [fromLabel, setFromLabel] = useState("");
  const selectedUser = unconnected.find((u) => u.id === targetId);

  const mutation = useMutation({
    mutationFn: () => api.sendConnectionRequest(userId, targetId, message, relType || undefined, fromLabel || undefined),
    onSuccess: onDone,
  });

  const suggestions = relType ? LABEL_SUGGESTIONS[relType] || [] : [];

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
      {selectedUser && (
        <div className="mb-4">
          <ProfilePreview user={selectedUser} networks={networks} />
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">Relationship type</label>
          <select
            value={relType}
            onChange={(e) => { setRelType(e.target.value); setFromLabel(""); }}
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm"
          >
            <option value="">None</option>
            {RELATIONSHIP_TYPES.map((t) => (
              <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">Your label for them</label>
          <input
            type="text"
            value={fromLabel}
            onChange={(e) => setFromLabel(e.target.value)}
            placeholder={suggestions[0] || "e.g. friend, boss"}
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground"
          />
          {suggestions.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setFromLabel(s)}
                  className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                    fromLabel === s
                      ? "bg-accent/15 text-accent border-accent/25"
                      : "bg-card-hover text-muted-foreground border-card-border hover:border-accent/30"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
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
