"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Network, type User, type Connection, type NetworkInviteListItem, type ContextMode } from "@/lib/api";
import { useParams } from "next/navigation";
import { matchesContext } from "@/lib/context";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

const CAPSULE_CATEGORIES = ["health", "home", "work", "personal", "family", "general"];
const NETWORK_TYPES = ["family", "team", "friends", "custom"];
const NETWORK_TYPE_CONFIG: Record<string, { icon: string; color: string }> = {
  family: { icon: "\u{1F3E0}", color: "bg-blue-500/15 text-blue-400 border-blue-500/25" },
  team: { icon: "\u{1F4BC}", color: "bg-amber-500/15 text-amber-400 border-amber-500/25" },
  friends: { icon: "\u{1F465}", color: "bg-green-500/15 text-green-400 border-green-500/25" },
  custom: { icon: "\u{2699}\u{FE0F}", color: "bg-orange-500/15 text-orange-400 border-orange-500/25" },
};

const POOL_TYPES = ["standard", "category_scoped", "public_registry"];
const POOL_TYPE_CONFIG: Record<string, { label: string; color: string; description: string }> = {
  standard: { label: "Standard", color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25", description: "All shared capsules visible to members" },
  category_scoped: { label: "Category Scoped", color: "bg-purple-500/15 text-purple-400 border-purple-500/25", description: "Only capsules in selected categories are visible" },
  public_registry: { label: "Public Registry", color: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25", description: "Open discovery — anyone can find this pool" },
};

const JOIN_POLICIES = ["open", "request_to_join", "invite_only"];

export default function NetworksPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: currentUser } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });
  const activeContext = (currentUser?.active_context as ContextMode) || "all";

  const { data: allNetworks, isLoading } = useQuery({
    queryKey: ["networks", userId],
    queryFn: () => api.listNetworks(userId),
  });
  const { data: connections } = useQuery({
    queryKey: ["connections", userId],
    queryFn: () => api.listConnections(userId),
  });

  // Filter networks by active context mode (DRY: shared matchesContext utility)
  const networks = allNetworks?.filter((n) => matchesContext(n.context, activeContext));
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
          connections={connections || []}
          onDone={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["networks", userId] });
          }}
        />
      )}

      {/* My Networks */}
      {isLoading ? (
        <div className="text-muted-foreground animate-pulse text-center py-12">Loading networks...</div>
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
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-[11px] text-muted-foreground capitalize">{n.network_type}</span>
                      {n.pool_type && n.pool_type !== "standard" && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border ${POOL_TYPE_CONFIG[n.pool_type]?.color || POOL_TYPE_CONFIG.standard.color}`}>
                          {POOL_TYPE_CONFIG[n.pool_type]?.label || n.pool_type}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="text-xs text-muted-foreground bg-card-hover px-2.5 py-1 rounded-lg">{n.members.length} members</span>
                  {n.expires_at && (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium border ${
                      new Date(n.expires_at) < new Date()
                        ? "bg-red-500/15 text-red-400 border-red-500/25"
                        : "bg-amber-500/15 text-amber-400 border-amber-500/25"
                    }`}>
                      {new Date(n.expires_at) < new Date()
                        ? "Expired"
                        : `Expires ${new Date(n.expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`}
                    </span>
                  )}
                  <svg
                    width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round"
                    className={`text-muted-foreground transition-transform ${expandedId === n.id ? "rotate-180" : ""}`}
                  >
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>
                {expandedId === n.id && (
                  <div className="px-4 pb-4 border-t border-card-border">
                    {n.description && (
                      <p className="text-xs text-muted-foreground mt-3 mb-3">{n.description}</p>
                    )}
                    {/* Pool info */}
                    {n.pool_type && n.pool_type !== "standard" && (
                      <div className="mt-3 mb-3 flex items-center gap-2 flex-wrap">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium border ${POOL_TYPE_CONFIG[n.pool_type]?.color || ""}`}>
                          {POOL_TYPE_CONFIG[n.pool_type]?.label}
                        </span>
                        {n.shared_categories?.map((cat) => (
                          <span key={cat} className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">
                            {cat}
                          </span>
                        ))}
                      </div>
                    )}
                    <h3 className="text-xs font-semibold text-muted-foreground mt-3 mb-2">Members ({n.members.length})</h3>
                    <div className="space-y-1.5">
                      {n.members.map((m: User) => (
                        <NetworkMemberRow
                          key={m.id}
                          member={m}
                          isOwner={m.id === n.owner_id}
                          canRemove={n.owner_id === userId && m.id !== userId}
                          networkId={n.id}
                          onRemoved={() => queryClient.invalidateQueries({ queryKey: ["networks", userId] })}
                        />
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
                      <ShareInviteLink networkId={n.id} />
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
              <p className="text-muted-foreground text-sm">No networks yet.</p>
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

function NetworkForm({ userId, connections, onDone }: { userId: string; connections: Connection[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("custom");
  const [description, setDescription] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [joinPolicy, setJoinPolicy] = useState("request_to_join");
  const [poolType, setPoolType] = useState("standard");
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedMembers, setSelectedMembers] = useState<string[]>([]);
  const [expiresAt, setExpiresAt] = useState("");
  const [showPublicConfirm, setShowPublicConfirm] = useState(false);

  const toggleCategory = (cat: string) => {
    setCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const toggleMember = (memberId: string) => {
    setSelectedMembers((prev) =>
      prev.includes(memberId) ? prev.filter((id) => id !== memberId) : [...prev, memberId]
    );
  };

  // Filter out ghost users from eligible members
  const eligibleMembers = connections
    .filter((c) => c.peer && !c.peer.username.startsWith("remote:"))
    .map((c) => c.peer!);

  const mutation = useMutation({
    mutationFn: () =>
      api.createNetwork({
        name,
        description,
        network_type: type,
        owner_id: userId,
        is_public: isPublic || poolType === "public_registry",
        join_policy: poolType === "public_registry" ? "open" : joinPolicy,
        pool_type: poolType,
        shared_categories: poolType === "category_scoped" ? categories : undefined,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
        initial_member_ids: selectedMembers.length > 0 ? selectedMembers : undefined,
      }),
    onSuccess: onDone,
  });

  const handleCreate = () => {
    if (poolType === "public_registry") {
      setShowPublicConfirm(true);
    } else {
      mutation.mutate();
    }
  };

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
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground"
        />
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Description (optional)</label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What is this network for?"
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground"
        />
      </div>

      {/* Pool Type Selection */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-2">Pool Type</label>
        <div className="grid grid-cols-3 gap-2">
          {POOL_TYPES.map((pt) => {
            const config = POOL_TYPE_CONFIG[pt];
            return (
              <button
                key={pt}
                type="button"
                onClick={() => setPoolType(pt)}
                className={`p-2.5 rounded-xl text-center transition-all ${
                  poolType === pt
                    ? "bg-accent/10 border-2 border-accent"
                    : "bg-card-hover border-2 border-transparent hover:border-card-border"
                }`}
              >
                <span className="text-xs font-medium block">{config.label}</span>
                <span className="text-[10px] text-muted-foreground block mt-0.5">{config.description}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Category checkboxes (only for category_scoped) */}
      {poolType === "category_scoped" && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-muted-foreground mb-2">Shared Categories</label>
          <div className="flex gap-2 flex-wrap">
            {CAPSULE_CATEGORIES.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => toggleCategory(cat)}
                className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all border ${
                  categories.includes(cat)
                    ? "bg-purple-500/20 text-purple-300 border-purple-500/40"
                    : "bg-card-hover text-muted-foreground border-card-border hover:border-purple-500/30"
                }`}
              >
                {categories.includes(cat) ? "\u2713 " : ""}{cat}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground mt-1.5">Members will only see capsules in these categories.</p>
        </div>
      )}

      {/* Add Members */}
      {eligibleMembers.length > 0 && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-muted-foreground mb-2">Add Members</label>
          <div className="flex gap-2 flex-wrap">
            {eligibleMembers.map((u) => (
              <button
                key={u.id}
                type="button"
                onClick={() => toggleMember(u.id)}
                className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all border ${
                  selectedMembers.includes(u.id)
                    ? "bg-accent/20 text-accent border-accent/40"
                    : "bg-card-hover text-muted-foreground border-card-border hover:border-accent/30"
                }`}
              >
                {selectedMembers.includes(u.id) ? "\u2713 " : "+ "}{u.display_name}
              </button>
            ))}
          </div>
          {selectedMembers.length > 0 && (
            <p className="text-[11px] text-muted-foreground mt-1.5">{selectedMembers.length} member{selectedMembers.length !== 1 ? "s" : ""} will be added on creation.</p>
          )}
        </div>
      )}

      {/* Expiry date picker */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-muted-foreground mb-1.5">Pool Duration (optional)</label>
        <input
          type="datetime-local"
          value={expiresAt}
          onChange={(e) => setExpiresAt(e.target.value)}
          className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm text-foreground [color-scheme:dark]"
        />
        <p className="text-[11px] text-muted-foreground mt-1">Network will become inactive after this date.</p>
        {expiresAt && (
          <button
            type="button"
            onClick={() => setExpiresAt("")}
            className="text-[11px] text-red-400 hover:text-red-300 mt-1 transition-colors"
          >
            Clear expiry
          </button>
        )}
      </div>

      {/* Public / Discoverable */}
      {poolType !== "public_registry" && (
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
            <span className="text-[11px] text-muted-foreground">Allow others to discover and request to join this network</span>
          </div>
        </label>
      </div>
      )}

      {/* Join Policy (only visible when public, not for public_registry which is always open) */}
      {isPublic && poolType !== "public_registry" && (
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
          <p className="text-[11px] text-muted-foreground mt-1.5">
            {joinPolicy === "open" && "Anyone can join instantly without approval."}
            {joinPolicy === "request_to_join" && "Join requests must be approved by the network owner."}
            {joinPolicy === "invite_only" && "Only the owner can invite new members."}
          </p>
        </div>
      )}

      <button
        onClick={handleCreate}
        disabled={!name.trim() || mutation.isPending}
        className="w-full bg-accent hover:bg-accent-hover text-accent-fg font-semibold py-3 rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/20"
      >
        {mutation.isPending ? "Creating..." : "Create Network"}
      </button>

      {/* Public Registry confirmation dialog */}
      <ConfirmDialog
        open={showPublicConfirm}
        onCancel={() => setShowPublicConfirm(false)}
        onConfirm={() => {
          setShowPublicConfirm(false);
          mutation.mutate();
        }}
        title="Make this network publicly discoverable?"
        description="Public Registry networks are visible to anyone on the TrustMesh network. Members and shared capsules will be discoverable by external agents."
        confirmLabel="Create Public Network"
        variant="default"
        loading={mutation.isPending}
      />
    </div>
  );
}

/* ── Network Member Row ── */

function NetworkMemberRow({
  member,
  isOwner,
  canRemove,
  networkId,
  onRemoved,
}: {
  member: User;
  isOwner: boolean;
  canRemove: boolean;
  networkId: string;
  onRemoved: () => void;
}) {
  const [showConfirm, setShowConfirm] = useState(false);
  const removeMutation = useMutation({
    mutationFn: () => api.removeNetworkMember(networkId, member.id),
    onSuccess: onRemoved,
  });

  return (
    <>
      <div className="flex items-center justify-between py-2 px-3 rounded-xl hover:bg-card-hover transition-colors group">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-accent flex items-center justify-center text-accent-fg text-xs font-bold">
            {member.display_name[0]}
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium">{member.display_name}</span>
              {member.user_type === "organization" && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold uppercase">Org</span>
              )}
              {member.user_type === "government" && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-semibold uppercase">Gov</span>
              )}
            </div>
            <span className="text-[11px] text-muted-foreground block">@{member.username}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isOwner && (
            <span className="text-[10px] text-accent bg-accent/10 px-2 py-0.5 rounded-full font-medium">Owner</span>
          )}
          {canRemove && (
            <button
              onClick={() => setShowConfirm(true)}
              disabled={removeMutation.isPending}
              className="opacity-0 group-hover:opacity-100 p-1 rounded-lg text-muted-foreground hover:text-danger hover:bg-danger/10 transition-all"
              title="Remove member"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={showConfirm}
        onCancel={() => setShowConfirm(false)}
        onConfirm={() => {
          removeMutation.mutate();
          setShowConfirm(false);
        }}
        title={`Remove ${member.display_name}?`}
        description={`This will remove them from this network. They will lose shared-level access to capsules shared with this group.`}
        confirmLabel="Remove"
        variant="danger"
        loading={removeMutation.isPending}
      />
    </>
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
  const [confirmUser, setConfirmUser] = useState<User | null>(null);
  const memberIds = new Set(currentMembers.map((m) => m.id));
  const eligible = connections
    .filter((c) => c.peer && !memberIds.has(c.peer.id))
    .map((c) => c.peer!);

  const mutation = useMutation({
    mutationFn: (uid: string) => api.addNetworkMember(networkId, uid),
    onSuccess: () => {
      setConfirmUser(null);
      onAdded();
    },
  });

  if (!eligible.length) return null;

  return (
    <>
      <div className="mt-4 pt-4 border-t border-card-border">
        <h3 className="text-xs font-semibold text-muted-foreground mb-2">Add Connected User</h3>
        <div className="flex gap-2 flex-wrap">
          {eligible.map((u) => (
            <button
              key={u.id}
              onClick={() => setConfirmUser(u)}
              disabled={mutation.isPending}
              className="px-3 py-1.5 text-xs bg-accent/10 text-accent rounded-xl hover:bg-accent/20 transition-colors border border-accent/20 font-medium"
            >
              + {u.display_name}
            </button>
          ))}
        </div>
      </div>
      <ConfirmDialog
        open={!!confirmUser}
        onCancel={() => setConfirmUser(null)}
        onConfirm={() => {
          if (confirmUser) mutation.mutate(confirmUser.id);
        }}
        title={`Add ${confirmUser?.display_name}?`}
        description={`This will give ${confirmUser?.display_name} access to all capsules shared with this network.`}
        confirmLabel="Add Member"
        variant="default"
        loading={mutation.isPending}
      />
    </>
  );
}

/* ── Share Invite Link ── */

function ShareInviteLink({ networkId }: { networkId: string }) {
  const [showInvite, setShowInvite] = useState(false);
  const [generatedLink, setGeneratedLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: invites } = useQuery({
    queryKey: ["invites", networkId],
    queryFn: () => api.listInvites(networkId),
    enabled: showInvite,
  });

  const generateMutation = useMutation({
    mutationFn: () => api.sendInvite(networkId, "", ""),
    onSuccess: (data) => {
      const link = `${window.location.origin}/invite/${data.token}`;
      setGeneratedLink(link);
      queryClient.invalidateQueries({ queryKey: ["invites", networkId] });
    },
    onError: (err: Error) => {
      setStatus(`Error: ${err.message}`);
      setTimeout(() => setStatus(null), 4000);
    },
  });

  const copyLink = async () => {
    if (!generatedLink) return;
    try {
      await navigator.clipboard.writeText(generatedLink);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setStatus("Could not copy — select and copy manually");
      setTimeout(() => setStatus(null), 3000);
    }
  };

  return (
    <div className="mt-4 pt-4 border-t border-card-border">
      <button
        onClick={() => setShowInvite(!showInvite)}
        className="flex items-center gap-2 text-xs font-semibold text-accent hover:text-accent-hover transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
        </svg>
        {showInvite ? "Hide Invite" : "Share Invite Link"}
      </button>

      {showInvite && (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-muted-foreground">Generate a one-time invite link to share via text, email, or any messaging app.</p>

          {!generatedLink ? (
            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="w-full px-4 py-2.5 bg-accent hover:bg-accent-hover text-accent-fg text-sm font-semibold rounded-xl disabled:opacity-40 transition-all hover:shadow-lg hover:shadow-accent/20"
            >
              {generateMutation.isPending ? "Generating..." : "Generate Invite Link"}
            </button>
          ) : (
            <div className="space-y-2">
              <div className="flex gap-2">
                <input
                  readOnly
                  value={generatedLink}
                  className="flex-1 bg-background border border-card-border rounded-xl px-3 py-2 text-xs text-muted-foreground font-mono select-all"
                  onClick={(e) => (e.target as HTMLInputElement).select()}
                />
                <button
                  onClick={copyLink}
                  className={`px-4 py-2 text-xs font-semibold rounded-xl transition-all ${
                    copied
                      ? "bg-success/15 text-success border border-success/20"
                      : "bg-accent hover:bg-accent-hover text-accent-fg"
                  }`}
                >
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>
              <button
                onClick={() => {
                  setGeneratedLink(null);
                  generateMutation.mutate();
                }}
                disabled={generateMutation.isPending}
                className="text-xs text-muted-foreground hover:text-accent transition-colors"
              >
                Generate another link
              </button>
            </div>
          )}

          {status && (
            <p className={`text-xs font-medium ${status.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
              {status}
            </p>
          )}

          {invites && invites.length > 0 && (
            <div className="mt-2">
              <h4 className="text-[11px] font-semibold text-muted-foreground mb-1.5">Sent Invites ({invites.length})</h4>
              <div className="space-y-1">
                {invites.map((inv: NetworkInviteListItem) => (
                  <div key={inv.id} className="flex items-center justify-between text-xs py-1.5 px-2 rounded-lg bg-card-hover/50">
                    <span className="text-muted-foreground truncate">
                      {inv.email || "Link invite"}
                    </span>
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
      <h3 className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
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
                  <span className="text-[11px] text-muted-foreground block truncate max-w-[200px]">&ldquo;{req.message}&rdquo;</span>
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
