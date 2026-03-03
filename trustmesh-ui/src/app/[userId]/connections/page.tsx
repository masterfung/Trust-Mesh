"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User, type ContextMode, type Connection, type ConnectionRequest, type Network } from "@/lib/api";
import { useParams } from "next/navigation";
import { matchesContext } from "@/lib/context";
import { RelationshipBadge } from "@/components/TrustBadge";
import { ProfilePreview } from "@/components/ProfilePreview";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TrustGraph } from "@/components/TrustGraph";
import { RELATIONSHIP_TYPES } from "@/lib/constants";

type ViewMode = "list" | "graph";

export default function ConnectionsPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showConnect, setShowConnect] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<Connection | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("list");

  const { data: currentUser } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });
  const activeContext: ContextMode = (currentUser?.active_context as ContextMode) || "all";

  const { data: allConnections, isLoading: connectionsLoading } = useQuery({
    queryKey: ["connections", userId],
    queryFn: () => api.listConnections(userId),
  });
  const connections = allConnections?.filter((c) => matchesContext(c.context, activeContext));

  const { data: requests } = useQuery({
    queryKey: ["connection-requests", userId],
    queryFn: () => api.listConnectionRequests(userId),
  });

  const { data: allUsers, isLoading: usersLoading } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
  });

  const { data: networks } = useQuery({
    queryKey: ["networks", userId],
    queryFn: () => api.listNetworks(userId),
  });

  const { data: graphData } = useQuery({
    queryKey: ["user-graph", userId],
    queryFn: () => api.getUserGraph(userId),
    enabled: viewMode === "graph",
  });

  const connectedIds = new Set(connections?.map((c: Connection) => c.peer?.id).filter(Boolean));
  // Also exclude pending request targets
  const pendingIds = new Set(requests?.map((r) => r.from_user?.id).filter(Boolean));
  const unconnected = allUsers?.filter(
    (u: User) => u.id !== userId && !connectedIds.has(u.id) && !pendingIds.has(u.id)
  ) ?? [];

  const acceptMutation = useMutation({
    mutationFn: ({ requestId, toLabel }: { requestId: string; toLabel?: string }) =>
      api.updateConnectionRequest(requestId, "accepted", toLabel),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections", userId] });
      queryClient.invalidateQueries({ queryKey: ["connection-requests", userId] });
      queryClient.invalidateQueries({ queryKey: ["user-graph", userId] });
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
      queryClient.invalidateQueries({ queryKey: ["user-graph", userId] });
    },
  });

  const handleConnectDone = useCallback(() => {
    setShowConnect(false);
    queryClient.invalidateQueries({ queryKey: ["connections", userId] });
    queryClient.invalidateQueries({ queryKey: ["user-graph", userId] });
  }, [queryClient, userId]);

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">People</h1>
          <p className="text-muted-foreground text-sm">
            {connections?.length
              ? `${connections.length} trusted connection${connections.length !== 1 ? "s" : ""}`
              : "People you trust and share knowledge with"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex items-center bg-card border border-card-border rounded-xl p-1">
            <button
              onClick={() => setViewMode("list")}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-all ${
                viewMode === "list" ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"
              }`}
              title="List view"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>
                <line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>
              </svg>
            </button>
            <button
              onClick={() => setViewMode("graph")}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-all ${
                viewMode === "graph" ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"
              }`}
              title="Graph view"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="2"/><circle cx="4" cy="6" r="2"/><circle cx="20" cy="6" r="2"/>
                <circle cx="4" cy="18" r="2"/><circle cx="20" cy="18" r="2"/>
                <line x1="6" y1="6" x2="10" y2="11"/><line x1="18" y1="6" x2="14" y2="11"/>
                <line x1="6" y1="18" x2="10" y2="13"/><line x1="18" y1="18" x2="14" y2="13"/>
              </svg>
            </button>
          </div>

          <button
            onClick={() => setShowConnect(!showConnect)}
            className={`px-4 py-2 font-medium rounded-xl text-sm transition-all ${
              showConnect
                ? "bg-card-hover text-muted-foreground border border-card-border"
                : "bg-accent hover:bg-accent-hover text-accent-fg hover:shadow-lg hover:shadow-accent/20"
            }`}
          >
            {showConnect ? "Cancel" : "+ Connect"}
          </button>
        </div>
      </div>

      {/* Pending Requests */}
      {requests && requests.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
            <h2 className="text-sm font-semibold text-warning">
              {requests.length} pending request{requests.length !== 1 ? "s" : ""}
            </h2>
          </div>
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

      {/* Send Connection Request Form */}
      {showConnect && (
        <SendConnectionForm
          userId={userId}
          unconnected={unconnected}
          networks={networks}
          isLoading={usersLoading || connectionsLoading}
          onDone={handleConnectDone}
        />
      )}

      {/* Graph View */}
      {viewMode === "graph" && (
        <div className="mb-6">
          {graphData ? (
            <div className="bg-card border border-card-border rounded-2xl overflow-hidden">
              <div className="px-4 py-3 border-b border-card-border flex items-center justify-between">
                <p className="text-sm font-medium">Trust Network</p>
                <p className="text-xs text-muted-foreground">Drag to explore · Click a node for details</p>
              </div>
              <div className="h-[400px]">
                <TrustGraph data={graphData} />
              </div>
            </div>
          ) : (
            <div className="bg-card border border-card-border rounded-2xl p-8 text-center animate-pulse">
              <p className="text-muted-foreground text-sm">Loading trust network...</p>
            </div>
          )}
        </div>
      )}

      {/* List View */}
      {viewMode === "list" && (
        <>
          {/* Section header */}
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-muted-foreground">
              Connected
              <span className="ml-1.5 text-xs font-normal">({connections?.length ?? 0})</span>
            </h2>
          </div>

          <div className="space-y-2">
            {connectionsLoading && !allConnections ? (
              // Skeleton loader
              <div className="space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="bg-card border border-card-border rounded-2xl p-4 animate-pulse">
                    <div className="flex items-center gap-3">
                      <div className="w-11 h-11 rounded-xl bg-card-hover" />
                      <div className="flex-1">
                        <div className="h-4 bg-card-hover rounded w-32 mb-1.5" />
                        <div className="h-3 bg-card-hover rounded w-48" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : connections?.length ? (
              connections.map((c: Connection) => (
                <div
                  key={c.id}
                  className="bg-card border border-card-border rounded-2xl p-4 flex items-center gap-3 group hover:bg-card-hover transition-colors"
                >
                  {/* Avatar */}
                  <div className="w-11 h-11 rounded-xl bg-accent/15 flex items-center justify-center text-accent font-bold text-base shrink-0">
                    {c.peer?.display_name?.[0]?.toUpperCase() || "?"}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-semibold">{c.peer?.display_name}</p>
                      {c.peer?.user_type === "organization" && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold uppercase tracking-wide">Org</span>
                      )}
                      {c.peer?.user_type === "government" && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-semibold uppercase tracking-wide">Gov</span>
                      )}
                      {c.relationship_type && <RelationshipBadge type={c.relationship_type} />}
                    </div>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">
                      {c.peer?.profile_data?.occupation?.title
                        ? c.peer.profile_data.occupation.title
                        : c.peer?.username
                        ? `@${c.peer.username}`
                        : "No info available"}
                      {c.my_label && <span className="text-accent/70"> · {c.my_label}</span>}
                    </p>
                  </div>

                  {/* Status + actions */}
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="inline-flex items-center gap-1 text-[11px] text-success bg-success/10 px-2 py-0.5 rounded-lg font-medium border border-success/20">
                      <span className="w-1.5 h-1.5 rounded-full bg-success" />
                      Trusted
                    </span>
                    <button
                      onClick={() => setDisconnectTarget(c)}
                      disabled={disconnectMutation.isPending}
                      className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-muted-foreground hover:text-danger hover:bg-danger/10 transition-all"
                      title="Remove connection"
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                      </svg>
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-12 bg-card border border-card-border rounded-2xl">
                <div className="w-12 h-12 rounded-2xl bg-card-hover flex items-center justify-center mx-auto mb-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                  </svg>
                </div>
                <p className="text-muted-foreground text-sm mb-3">No connections yet.</p>
                <button
                  onClick={() => setShowConnect(true)}
                  className="text-accent text-sm hover:text-accent-hover transition-colors"
                >
                  Send your first connection request →
                </button>
              </div>
            )}
          </div>
        </>
      )}

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
        title={`Remove ${disconnectTarget?.peer?.display_name}?`}
        description="This will remove the trust connection. They'll lose connected-level access to your knowledge, and you'll lose access to theirs."
        confirmLabel="Remove"
        variant="danger"
        loading={disconnectMutation.isPending}
      />
    </div>
  );
}

/* ── Pending Request Card ── */

function PendingRequestCard({
  request, networks, onAccept, onDecline, isPending,
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
    <div className="bg-card border border-warning/25 rounded-2xl overflow-hidden">
      <button
        className="w-full p-4 flex items-center gap-3 text-left hover:bg-card-hover/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="w-10 h-10 rounded-xl bg-warning/15 flex items-center justify-center text-warning font-bold text-sm shrink-0">
          {from?.display_name?.[0]?.toUpperCase() || "?"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold">{from?.display_name || "Unknown"}</span>
            {from?.username && <span className="text-xs text-muted-foreground">@{from.username}</span>}
            {request.relationship_type && <RelationshipBadge type={request.relationship_type} />}
          </div>
          {request.message && (
            <p className="text-xs text-muted-foreground truncate mt-0.5">&ldquo;{request.message}&rdquo;</p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {(request.mutual_connections || request.mutual_networks) ? (
            <div className="text-right">
              {request.mutual_connections ? (
                <p className="text-[10px] text-muted-foreground">{request.mutual_connections} mutual</p>
              ) : null}
              {request.mutual_networks ? (
                <p className="text-[10px] text-muted-foreground">{request.mutual_networks} shared groups</p>
              ) : null}
            </div>
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
              <p className="text-[10px] text-muted-foreground uppercase font-semibold mb-1">Their message</p>
              <p className="text-sm">{request.message}</p>
            </div>
          )}
          {request.from_label && (
            <p className="text-xs text-accent mb-3">They&apos;re calling you: <strong>{request.from_label}</strong></p>
          )}
          <div className="mb-3">
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              Your nickname for them <span className="text-muted-foreground/50">(optional)</span>
            </label>
            <input
              type="text"
              value={toLabel}
              onChange={(e) => setToLabel(e.target.value)}
              placeholder={
                request.relationship_type === "family" ? "e.g. brother, cousin" :
                request.relationship_type === "work" ? "e.g. colleague, manager" :
                "e.g. friend, neighbor"
              }
              className="w-full bg-background border border-card-border rounded-lg px-3 py-1.5 text-xs placeholder:text-muted-foreground"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => onAccept(toLabel || undefined)}
              disabled={isPending}
              className="flex-1 px-4 py-2.5 text-sm font-semibold bg-success/10 text-success rounded-xl hover:bg-success/20 transition-colors border border-success/20 disabled:opacity-40"
            >
              Accept
            </button>
            <button
              onClick={onDecline}
              disabled={isPending}
              className="px-4 py-2.5 text-sm font-medium bg-card-hover text-muted-foreground rounded-xl hover:bg-danger/10 hover:text-danger transition-colors border border-card-border disabled:opacity-40"
            >
              Decline
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Send Connection Form ── */

const LABEL_SUGGESTIONS: Record<string, string[]> = {
  family: ["spouse", "parent", "child", "sibling", "grandparent", "in-law"],
  friend: ["close friend", "childhood friend"],
  work: ["boss", "manager", "colleague", "mentor"],
  healthcare: ["doctor", "nurse", "therapist", "caregiver"],
  neighbor: ["next door"],
  emergency: ["ICE contact", "medical proxy"],
  other: [],
};

function SendConnectionForm({
  userId, unconnected, networks, isLoading, onDone,
}: {
  userId: string;
  unconnected: User[];
  networks?: Network[];
  isLoading?: boolean;
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
    <div className="bg-card border border-accent/20 rounded-2xl p-5 mb-6">
      <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
          <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
          <line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>
        </svg>
        Send Connection Request
      </h2>

      {isLoading ? (
        <div className="py-6 text-center">
          <p className="text-sm text-muted-foreground">Loading people...</p>
        </div>
      ) : unconnected.length === 0 ? (
        <div className="py-6 text-center">
          <p className="text-sm text-muted-foreground">You&apos;re already connected with everyone on this pod.</p>
        </div>
      ) : (
        <>
          <div className="mb-4">
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">Who do you want to connect with?</label>
            <select
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm"
            >
              <option value="">Select a person...</option>
              {unconnected.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name}{u.username ? ` (@${u.username})` : ""}
                  {u.profile_data?.occupation?.title ? ` — ${u.profile_data.occupation.title}` : ""}
                </option>
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
              <label className="block text-xs font-medium text-muted-foreground mb-1.5">Relationship</label>
              <select
                value={relType}
                onChange={(e) => { setRelType(e.target.value); setFromLabel(""); }}
                className="w-full bg-background border border-card-border rounded-xl px-3 py-2.5 text-sm"
              >
                <option value="">Not specified</option>
                {RELATIONSHIP_TYPES.map((t) => (
                  <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1.5">Your nickname for them</label>
              <input
                type="text"
                value={fromLabel}
                onChange={(e) => setFromLabel(e.target.value)}
                placeholder={suggestions[0] || "e.g. best friend"}
                className="w-full bg-background border border-card-border rounded-xl px-3 py-2.5 text-sm placeholder:text-muted-foreground"
              />
              {suggestions.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setFromLabel(s)}
                      className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                        fromLabel === s ? "bg-accent/15 text-accent border-accent/25" : "bg-card-hover text-muted-foreground border-card-border hover:border-accent/30"
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
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">
              Personal message <span className="text-muted-foreground/50">(optional)</span>
            </label>
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Hi, I'd like to connect..."
              className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground"
            />
          </div>

          {mutation.isError && (
            <p className="text-xs text-danger mb-3">{(mutation.error as Error).message}</p>
          )}

          <button
            onClick={() => mutation.mutate()}
            disabled={!targetId || mutation.isPending}
            className="w-full bg-accent hover:bg-accent-hover text-accent-fg font-semibold py-3 rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/20"
          >
            {mutation.isPending ? "Sending..." : "Send Request"}
          </button>
        </>
      )}
    </div>
  );
}
