"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Network, type User, type Connection, type NetworkInviteListItem } from "@/lib/api";
import { useParams } from "next/navigation";

const NETWORK_TYPES = ["family", "team", "friends", "custom"];
const NETWORK_TYPE_CONFIG: Record<string, { icon: string; color: string }> = {
  family: { icon: "\u{1F3E0}", color: "bg-blue-500/15 text-blue-400 border-blue-500/25" },
  team: { icon: "\u{1F4BC}", color: "bg-amber-500/15 text-amber-400 border-amber-500/25" },
  friends: { icon: "\u{1F465}", color: "bg-green-500/15 text-green-400 border-green-500/25" },
  custom: { icon: "\u{2699}\u{FE0F}", color: "bg-orange-500/15 text-orange-400 border-orange-500/25" },
};

const JOIN_POLICIES = ["open", "request_to_join", "invite_only"];

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
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Networks</h1>
            {networks && (
              <span className="text-xs bg-card-hover text-muted-foreground px-2.5 py-1 rounded-lg font-medium">
                {networks.length} networks
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm">Trust groups for sharing knowledge capsules. Ask your agent to discover public groups!</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className={`px-4 py-2.5 font-medium rounded-xl text-sm transition-all ${
            showForm
              ? "bg-card-hover text-muted-foreground border border-card-border"
              : "bg-accent hover:bg-accent-hover text-accent-fg hover:shadow-lg hover:shadow-accent/20"
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

      {/* My Networks */}
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
                            <div className="w-8 h-8 rounded-xl bg-accent flex items-center justify-center text-accent-fg text-xs font-bold">
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

                    {n.owner_id === userId && (
                      <InviteByEmail networkId={n.id} />
                    )}

                    {n.owner_id === userId && (
                      <JoinRequestsManager
                        networkId={n.id}
                        onChanged={() => queryClient.invalidateQueries({ queryKey: ["networks", userId] })}
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

/* ── Network Form ── */

function NetworkForm({ userId, onDone }: { userId: string; onDone: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("custom");
  const [description, setDescription] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [joinPolicy, setJoinPolicy] = useState("request_to_join");

  const mutation = useMutation({
    mutationFn: () =>
      api.createNetwork({
        name,
        description,
        network_type: type,
        owner_id: userId,
        is_public: isPublic,
        join_policy: joinPolicy,
      }),
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

      {/* Public / Discoverable */}
      <div className="mb-4">
        <label className="flex items-center gap-3 cursor-pointer group">
          <div className="relative">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-9 h-5 bg-card-hover border border-card-border rounded-full peer-checked:bg-accent peer-checked:border-accent transition-colors" />
            <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-transform peer-checked:translate-x-4" />
          </div>
          <div>
            <span className="text-sm font-medium block">Public Network</span>
            <span className="text-[11px] text-muted">Allow others to discover and request to join this network</span>
          </div>
        </label>
      </div>

      {/* Join Policy (only visible when public) */}
      {isPublic && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">Join Policy</label>
          <div className="grid grid-cols-3 gap-2">
            {JOIN_POLICIES.map((policy) => (
              <button
                key={policy}
                type="button"
                onClick={() => setJoinPolicy(policy)}
                className={`px-3 py-2.5 rounded-xl text-center text-xs font-medium capitalize transition-all ${
                  joinPolicy === policy
                    ? "bg-accent/10 border-2 border-accent text-accent"
                    : "bg-card-hover border-2 border-transparent hover:border-card-border text-muted-foreground"
                }`}
              >
                {policy === "invite_only" ? "Invite Only" : policy === "request_to_join" ? "Request to Join" : "Open"}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-muted mt-1.5">
            {joinPolicy === "open" && "Anyone can join instantly without approval."}
            {joinPolicy === "request_to_join" && "Join requests must be approved by the network owner."}
            {joinPolicy === "invite_only" && "Only the owner can invite new members."}
          </p>
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={!name.trim() || mutation.isPending}
        className="w-full bg-accent hover:bg-accent-hover text-accent-fg font-semibold py-3 rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/20"
      >
        {mutation.isPending ? "Creating..." : "Create Network"}
      </button>
    </div>
  );
}

/* ── Add Member ── */

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

/* ── Invite by Email ── */

function InviteByEmail({ networkId }: { networkId: string }) {
  const [showInvite, setShowInvite] = useState(false);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: invites } = useQuery({
    queryKey: ["invites", networkId],
    queryFn: () => api.listInvites(networkId),
    enabled: showInvite,
  });

  const sendMutation = useMutation({
    mutationFn: () => api.sendInvite(networkId, email, message),
    onSuccess: (data) => {
      setSent(data.status === "sent" ? "Email sent!" : "Invite link created (email not configured).");
      setEmail("");
      setMessage("");
      queryClient.invalidateQueries({ queryKey: ["invites", networkId] });
      setTimeout(() => setSent(null), 4000);
    },
    onError: (err: Error) => {
      setSent(`Error: ${err.message}`);
      setTimeout(() => setSent(null), 4000);
    },
  });

  return (
    <div className="mt-4 pt-4 border-t border-card-border">
      <button
        onClick={() => setShowInvite(!showInvite)}
        className="flex items-center gap-2 text-xs font-semibold text-accent hover:text-accent-hover transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
          <polyline points="22,6 12,13 2,6"/>
        </svg>
        {showInvite ? "Hide Invite" : "Invite by Email"}
      </button>

      {showInvite && (
        <div className="mt-3 space-y-3">
          <div className="flex gap-2">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="friend@example.com"
              className="flex-1 bg-background border border-card-border rounded-xl px-3 py-2 text-sm placeholder:text-muted"
            />
            <button
              onClick={() => sendMutation.mutate()}
              disabled={!email.trim() || sendMutation.isPending}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-accent-fg text-xs font-semibold rounded-xl disabled:opacity-40 transition-all"
            >
              {sendMutation.isPending ? "Sending..." : "Send Invite"}
            </button>
          </div>
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Personal message (optional)"
            className="w-full bg-background border border-card-border rounded-xl px-3 py-2 text-sm placeholder:text-muted"
          />

          {sent && (
            <p className={`text-xs font-medium ${sent.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
              {sent}
            </p>
          )}

          {invites && invites.length > 0 && (
            <div className="mt-2">
              <h4 className="text-[11px] font-semibold text-muted mb-1.5">Sent Invites</h4>
              <div className="space-y-1">
                {invites.map((inv: NetworkInviteListItem) => (
                  <div key={inv.id} className="flex items-center justify-between text-xs py-1.5 px-2 rounded-lg bg-card-hover/50">
                    <span className="text-muted-foreground truncate">{inv.email}</span>
                    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                      inv.status === "accepted"
                        ? "bg-green-500/15 text-green-400"
                        : inv.status === "pending"
                          ? "bg-yellow-500/15 text-yellow-400"
                          : "bg-red-500/15 text-red-400"
                    }`}>
                      {inv.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Join Requests Manager (for network owners) ── */

function JoinRequestsManager({ networkId, onChanged }: { networkId: string; onChanged: () => void }) {
  const queryClient = useQueryClient();

  const { data: requests } = useQuery({
    queryKey: ["join-requests", networkId],
    queryFn: () => api.listJoinRequests(networkId),
  });

  const reviewMutation = useMutation({
    mutationFn: ({ requestId, status }: { requestId: string; status: "approved" | "declined" }) =>
      api.reviewJoinRequest(networkId, requestId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["join-requests", networkId] });
      onChanged();
    },
  });

  if (!requests || requests.length === 0) return null;

  return (
    <div className="mt-4 pt-4 border-t border-card-border">
      <h3 className="text-xs font-semibold text-muted mb-2 flex items-center gap-1.5">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-amber-400">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        Pending Join Requests
        <span className="text-[10px] bg-amber-500/15 text-amber-400 px-1.5 py-0.5 rounded-full font-semibold">{requests.length}</span>
      </h3>
      <div className="space-y-2">
        {requests.map((req) => (
          <div key={req.id} className="flex items-center justify-between py-2 px-3 rounded-xl bg-card-hover/50 border border-card-border">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center text-white text-xs font-bold">
                {req.user?.display_name?.[0] ?? "?"}
              </div>
              <div>
                <span className="text-sm font-medium block">{req.user?.display_name ?? "Unknown"}</span>
                {req.message && (
                  <span className="text-[11px] text-muted block truncate max-w-[200px]">&ldquo;{req.message}&rdquo;</span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => reviewMutation.mutate({ requestId: req.id, status: "approved" })}
                disabled={reviewMutation.isPending}
                className="px-3 py-1.5 text-[11px] font-semibold bg-green-500/15 text-green-400 rounded-lg hover:bg-green-500/25 transition-colors border border-green-500/20"
              >
                Approve
              </button>
              <button
                onClick={() => reviewMutation.mutate({ requestId: req.id, status: "declined" })}
                disabled={reviewMutation.isPending}
                className="px-3 py-1.5 text-[11px] font-semibold bg-red-500/15 text-red-400 rounded-lg hover:bg-red-500/25 transition-colors border border-red-500/20"
              >
                Decline
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
