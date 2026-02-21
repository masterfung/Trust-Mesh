"use client";

import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type PeerPod, type Network, type User } from "@/lib/api";
import { useParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Box, User as UserIcon, Globe, Lock, Network as NetworkIcon,
  Copy, Check, Wifi, WifiOff, Plus, X, Loader2, Users, Radio,
  ExternalLink, Clock, Info,
} from "lucide-react";

// ── Shared helpers ──

function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <div className={cn("rounded-lg bg-accent flex items-center justify-center text-accent-fg font-bold text-xs shrink-0", className)}>
      {name?.[0]?.toUpperCase() || "?"}
    </div>
  );
}

function StatusDot({ status }: { status: "active" | "unreachable" | "pending" | string }) {
  const color = status === "active" ? "bg-success" : status === "unreachable" ? "bg-danger" : "bg-warning";
  return <span className={cn("w-2 h-2 rounded-full shrink-0", color)} />;
}

function relativeTime(ts: string | null): string | null {
  if (!ts) return null;
  const mins = Math.floor((Date.now() - new Date(ts).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const ENTITY_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  person: "secondary",
  organization: "default",
  government: "outline",
};

const POOL_LABELS: Record<string, string> = {
  standard: "Open Sharing",
  category_scoped: "Topic-Based",
  public_registry: "Public",
};

// ── Page ──

export default function PodPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();

  const { data: currentUser } = useQuery({ queryKey: ["user", userId], queryFn: () => api.getUser(userId) });
  const { data: podInfo } = useQuery({ queryKey: ["pod-info"], queryFn: () => api.getPodInfo() });
  const { data: peersData } = useQuery({ queryKey: ["pod-peers"], queryFn: () => api.listPeers() });
  const { data: agentCard } = useQuery({ queryKey: ["agent-card", userId], queryFn: () => api.getAgentCard(userId), enabled: !!userId });
  const { data: networks } = useQuery({ queryKey: ["networks", userId], queryFn: () => api.listNetworks(userId), enabled: !!userId });

  const peers = peersData?.peers || [];
  const pools = networks || [];
  const activePeers = peers.filter((p) => p.status === "active").length;
  const ghostCount = pools.reduce((s, n) => s + n.members.filter((m: User) => m.username?.startsWith("remote:")).length, 0);

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">Settings</h1>
            <Badge variant="outline" className="gap-1.5 text-success border-success/30">
              <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
              Online
            </Badge>
          </div>
          <p className="text-muted-foreground text-sm mt-0.5">Your identity, groups, and connected organizations.</p>
        </div>
        {/* Quick stats */}
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <span>{activePeers}/{peers.length} peers</span>
          <span className="text-border">|</span>
          <span>{pools.length} pools</span>
          <span className="text-border">|</span>
          <span>{ghostCount} remote</span>
        </div>
      </div>

      {/* Tabbed content */}
      <Tabs defaultValue="identity">
        <TabsList variant="line" className="mb-4 w-full justify-start">
          <TabsTrigger value="identity"><Box className="size-4" /> Identity</TabsTrigger>
          <TabsTrigger value="pools"><Users className="size-4" /> Pools <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">{pools.length}</Badge></TabsTrigger>
          <TabsTrigger value="peers"><Radio className="size-4" /> Peers <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">{peers.length}</Badge></TabsTrigger>
        </TabsList>

        <TabsContent value="identity" className="space-y-4">
          <PodIdentityCard podInfo={podInfo} />
          <AgentIdentityCard userId={userId} currentUser={currentUser} agentCard={agentCard} podInfo={podInfo} />
          <DiscoverableToggle userId={userId} currentUser={currentUser} queryClient={queryClient} />
        </TabsContent>

        <TabsContent value="pools">
          <TrustPools pools={pools} userId={userId} />
        </TabsContent>

        <TabsContent value="peers">
          <PeerManagement peers={peers} queryClient={queryClient} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Identity Tab ──

function PodIdentityCard({ podInfo }: { podInfo?: { pod_name: string; pod_url: string; protocol: string; agent_count: number } }) {
  if (!podInfo) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <Loader2 className="size-5 animate-spin text-muted-foreground mx-auto mb-2" />
          <p className="text-xs text-muted-foreground">Loading pod info...</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm"><Box className="size-4 text-accent" /> Pod</CardTitle>
        <CardDescription>Your local pod instance running on this device.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg bg-muted/30 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1">Name</p>
            <p className="text-sm font-semibold">{podInfo.pod_name}</p>
          </div>
          <div className="rounded-lg bg-muted/30 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1">Agents</p>
            <p className="text-sm font-semibold">{podInfo.agent_count} registered</p>
          </div>
          <div className="col-span-2 rounded-lg bg-muted/30 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1">URL</p>
            <code className="text-xs font-mono text-muted-foreground">{podInfo.pod_url}</code>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function AgentIdentityCard({ userId, currentUser, agentCard, podInfo }: {
  userId: string;
  currentUser?: { display_name: string; user_type?: string; bio: string; username?: string | null };
  agentCard?: { name: string; description: string; skills: { id: string; name: string; description: string }[] } | null;
  podInfo?: { agents?: { owner_username: string; did: string }[] };
}) {
  const [copied, setCopied] = useState(false);
  const myAgent = podInfo?.agents?.find((a) => currentUser && a.owner_username === currentUser.username);
  const did = myAgent?.did;

  const copyDid = () => {
    if (!did) return;
    navigator.clipboard.writeText(did);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!currentUser) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <Loader2 className="size-5 animate-spin text-muted-foreground mx-auto mb-2" />
          <p className="text-xs text-muted-foreground">Loading agent identity...</p>
        </CardContent>
      </Card>
    );
  }

  const entityType = currentUser.user_type || "person";
  const variant = ENTITY_VARIANT[entityType] || "secondary";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <UserIcon className="size-4 text-accent" />
          Your Agent
          <Badge variant={variant} className="capitalize text-[10px]">{entityType}</Badge>
        </CardTitle>
        <CardDescription>Your AI assistant&apos;s identity on the network.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {did && (
          <div className="rounded-lg bg-muted/30 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1.5">Decentralized Identifier (DID)</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs font-mono truncate text-muted-foreground">{did}</code>
              <button onClick={copyDid} className="p-1.5 rounded-md hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground shrink-0">
                {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
              </button>
            </div>
          </div>
        )}
        {agentCard && (
          <div className="rounded-lg bg-muted/30 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1.5">Agent Card</p>
            <p className="text-sm font-medium">{agentCard.name}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{agentCard.description}</p>
            {agentCard.skills?.length > 0 && (
              <div className="mt-2 flex gap-1.5 flex-wrap">
                {agentCard.skills.map((s) => (
                  <Badge key={s.id} variant="outline" className="text-[10px]">{s.name}</Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DiscoverableToggle({ userId, currentUser, queryClient }: {
  userId: string;
  currentUser?: { is_discoverable?: boolean; username?: string | null; user_type?: string };
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const isDiscoverable = currentUser?.is_discoverable ?? false;
  const currentHandle = currentUser?.username || null;
  const entityType = currentUser?.user_type || "person";
  const isOrgOrGov = entityType === "organization" || entityType === "government";
  const [showConfirm, setShowConfirm] = useState(false);
  const [handle, setHandle] = useState("");
  const [handleStatus, setHandleStatus] = useState<{ available?: boolean; reason?: string; checking?: boolean } | null>(null);
  const checkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Validate handle format locally
  const formatError = handle.length > 0 && !/^[a-z0-9_-]{2,50}$/.test(handle)
    ? handle.length < 2 ? "At least 2 characters" : "Only lowercase letters, numbers, _ and -"
    : null;

  // Debounced handle availability check
  useEffect(() => {
    if (!handle || handle.length < 2 || formatError) {
      setHandleStatus(null);
      return;
    }
    setHandleStatus({ checking: true });
    if (checkTimerRef.current) clearTimeout(checkTimerRef.current);
    checkTimerRef.current = setTimeout(async () => {
      try {
        const res = await api.checkHandle(userId, handle);
        setHandleStatus({ available: res.available, reason: res.reason });
      } catch {
        setHandleStatus({ available: false, reason: "Could not check availability" });
      }
    }, 400);
    return () => { if (checkTimerRef.current) clearTimeout(checkTimerRef.current); };
  }, [handle, userId, formatError]);

  // Go private mutation
  const goPrivate = useMutation({
    mutationFn: () => api.updateUser(userId, { is_discoverable: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user", userId] });
      setShowConfirm(false);
    },
  });

  // Claim handle mutation (Go Live)
  const claimHandle = useMutation({
    mutationFn: () => api.claimHandle(userId, handle),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user", userId] });
      setShowConfirm(false);
      setHandle("");
      setHandleStatus(null);
    },
  });

  const isPending = goPrivate.isPending || claimHandle.isPending;

  const registryUrl = typeof window !== "undefined"
    ? (localStorage.getItem("trustmesh_registry_url") || "http://localhost:8100")
    : "http://localhost:8100";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          {isDiscoverable ? <Globe className="size-4 text-success" /> : <Lock className="size-4 text-muted-foreground" />}
          Visibility
        </CardTitle>
        <CardDescription>
          Control whether your agent profile appears in the public registry.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Current status banner */}
        <div className={cn(
          "rounded-lg p-4",
          isDiscoverable ? "bg-success/5 border border-success/20" : "bg-muted/30 border border-border"
        )}>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">
                {isDiscoverable ? (
                  <>Live{currentHandle && <span className="text-accent ml-1.5">@{currentHandle}</span>}</>
                ) : "Private"}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {isDiscoverable
                  ? "Anyone can find your agent in the public registry and send queries."
                  : "Your agent is hidden from the public registry. Only people you connect with directly or share a pool with can reach you."}
              </p>
            </div>
            <label className="relative cursor-pointer shrink-0 ml-4">
              <input type="checkbox" checked={isDiscoverable} onChange={() => setShowConfirm(true)} disabled={isPending} className="sr-only peer" />
              <div className="w-11 h-6 bg-muted rounded-full peer-checked:bg-success transition-colors" />
              <div className="absolute left-0.5 top-0.5 w-5 h-5 bg-white rounded-full shadow-sm transition-transform peer-checked:translate-x-5" />
            </label>
          </div>

          {/* Registry preview link when live */}
          {isDiscoverable && (
            <a
              href={registryUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 mt-3 text-xs text-accent hover:text-accent-hover transition-colors"
            >
              <ExternalLink className="size-3" />
              View your profile in the public registry
            </a>
          )}
        </div>

        {/* Explainer: what private means */}
        {!isDiscoverable && !showConfirm && (
          <div className="space-y-2 text-xs text-muted-foreground">
            <p className="font-medium text-foreground text-sm">What can people see?</p>
            <div className="grid gap-2">
              <div className="flex items-start gap-2">
                <Check className="size-3.5 text-success shrink-0 mt-0.5" />
                <span><span className="font-medium text-foreground">Connections</span> — people you&apos;ve connected with can query your agent</span>
              </div>
              <div className="flex items-start gap-2">
                <Check className="size-3.5 text-success shrink-0 mt-0.5" />
                <span><span className="font-medium text-foreground">Pool members</span> — people in your shared groups can see pool-scoped info</span>
              </div>
              <div className="flex items-start gap-2">
                <X className="size-3.5 text-danger shrink-0 mt-0.5" />
                <span><span className="font-medium text-foreground">Public registry</span> — your agent will not appear in search results</span>
              </div>
              <div className="flex items-start gap-2">
                <X className="size-3.5 text-danger shrink-0 mt-0.5" />
                <span><span className="font-medium text-foreground">Strangers</span> — cannot find or query your agent at all</span>
              </div>
            </div>
          </div>
        )}

        {/* Go Private confirmation */}
        {showConfirm && isDiscoverable && (
          <div className="rounded-lg border border-warning/30 bg-warning/5 p-4 space-y-3">
            <p className="text-sm font-medium">Go private?</p>
            <p className="text-xs text-muted-foreground">
              Your agent will be removed from the public registry immediately. Existing connections and pool memberships are not affected.
            </p>
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Clock className="size-3 shrink-0" />
              Removal takes effect instantly &mdash; your profile disappears from the registry within seconds.
            </div>
            <div className="flex gap-2">
              <button onClick={() => goPrivate.mutate()} disabled={isPending}
                className="px-3 py-1.5 text-sm font-medium rounded-md bg-muted hover:bg-muted/80 text-foreground transition-colors">
                {goPrivate.isPending ? "Updating..." : "Go Private"}
              </button>
              <button onClick={() => setShowConfirm(false)}
                className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Go Live — claim a handle */}
        {showConfirm && !isDiscoverable && (
          <div className="rounded-lg border border-accent/30 bg-accent/5 p-4 space-y-4">
            <div>
              <p className="text-sm font-medium">Go Live &mdash; Pick Your Handle</p>
              <p className="text-xs text-muted-foreground mt-1">
                Choose a unique public handle. Anyone can find you as <span className="text-accent font-medium">@{handle || "yourname"}</span> in the registry.
              </p>
            </div>

            <div>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-accent font-medium text-sm">@</span>
                <input
                  type="text"
                  value={handle}
                  onChange={(e) => setHandle(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
                  placeholder="yourname"
                  maxLength={50}
                  className={cn(
                    "w-full bg-background border rounded-lg pl-7 pr-10 py-2.5 text-sm font-mono transition-colors",
                    formatError ? "border-danger/50" :
                    handleStatus?.available === true ? "border-success/50" :
                    handleStatus?.available === false ? "border-danger/50" :
                    "border-border"
                  )}
                  autoFocus
                />
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  {handleStatus?.checking && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                  {handleStatus?.available === true && !handleStatus.checking && <Check className="size-4 text-success" />}
                  {handleStatus?.available === false && !handleStatus.checking && <X className="size-4 text-danger" />}
                </div>
              </div>
              <div className="mt-1.5 min-h-[18px]">
                {formatError && <p className="text-[11px] text-danger">{formatError}</p>}
                {!formatError && handleStatus?.available === true && <p className="text-[11px] text-success">@{handle} is available</p>}
                {!formatError && handleStatus?.available === false && <p className="text-[11px] text-danger">{handleStatus.reason || "Not available"}</p>}
                {!formatError && !handleStatus && handle.length >= 2 && <p className="text-[11px] text-muted-foreground">Checking...</p>}
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => claimHandle.mutate()}
                disabled={isPending || !handleStatus?.available || !!formatError}
                className="px-4 py-2 text-sm font-medium rounded-md bg-accent hover:bg-accent-hover text-accent-fg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {claimHandle.isPending ? "Claiming..." : `Claim @${handle || "..."}`}
              </button>
              <button
                onClick={() => { setShowConfirm(false); setHandle(""); setHandleStatus(null); }}
                className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
            </div>
            {claimHandle.isError && <p className="text-xs text-danger">{(claimHandle.error as Error).message}</p>}

            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Clock className="size-3 shrink-0" />
              Your profile appears in the registry instantly after claiming your handle.
            </div>
          </div>
        )}

        {/* How discovery works */}
        <div className="rounded-lg bg-muted/20 p-3 space-y-2">
          <p className="text-xs font-medium text-foreground flex items-center gap-1.5">
            <Info className="size-3.5 text-muted-foreground" />
            How discovery works
          </p>
          <div className="text-[11px] text-muted-foreground space-y-1.5 leading-relaxed">
            <p>
              The <a href={registryUrl} target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover underline underline-offset-2">public registry</a> is
              a searchable directory of all live agents across the network. Other pods can browse it to find agents to connect with.
            </p>
            <p>
              {isOrgOrGov ? (
                <>
                  <span className="font-medium text-foreground capitalize">{entityType}</span> accounts are listed in the registry by default
                  because they provide services that others need to discover. You can still go private, but this means your services
                  won&apos;t appear in search results.
                </>
              ) : (
                <>
                  <span className="font-medium text-foreground">People</span> start private by default &mdash; you choose when to go live.
                  Organizations and government entities are discoverable by default since they provide services others need to find.
                </>
              )}
            </p>
            <p>
              <span className="font-medium text-foreground">Propagation:</span> Changes are instant. Going live registers
              your profile immediately. Going private sends a delete to the registry &mdash; your profile is removed within seconds.
              Pods also re-sync with the registry on every startup.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Pools Tab ──

function TrustPools({ pools, userId }: { pools: Network[]; userId: string }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (!pools.length) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <CardDescription>No trust pools yet. Create a network to start sharing.</CardDescription>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {pools.map((pool) => {
        const local = pool.members.filter((m) => !m.username?.startsWith("remote:"));
        const remote = pool.members.filter((m) => m.username?.startsWith("remote:"));
        const poolType = pool.pool_type || "standard";
        const isExpanded = expandedId === pool.id;
        const cats: string[] = pool.shared_categories || [];

        return (
          <Card key={pool.id} className="gap-0 py-0 overflow-hidden">
            <button
              className="w-full flex items-center gap-3 p-4 text-left hover:bg-muted/30 transition-colors"
              onClick={() => setExpandedId(isExpanded ? null : pool.id)}
            >
              <NetworkIcon className="size-4 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium truncate">{pool.name}</span>
                  {pool.owner_id === userId && <Badge variant="outline" className="text-[10px] text-accent border-accent/30">Owner</Badge>}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <Badge variant="secondary" className="text-[10px]">{POOL_LABELS[poolType] || poolType}</Badge>
                  {cats.slice(0, 2).map((c) => <Badge key={c} variant="outline" className="text-[10px]">{c}</Badge>)}
                  {cats.length > 2 && <span className="text-[10px] text-muted-foreground">+{cats.length - 2}</span>}
                </div>
              </div>
              <span className="text-xs text-muted-foreground tabular-nums">{local.length} local</span>
              {remote.length > 0 && <span className="text-xs text-muted-foreground tabular-nums">{remote.length} remote</span>}
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={cn("text-muted-foreground transition-transform", isExpanded && "rotate-180")}>
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {isExpanded && (
              <div className="px-4 pb-4 border-t border-border space-y-3">
                {pool.description && <p className="text-xs text-muted-foreground pt-3">{pool.description}</p>}

                {local.length > 0 && (
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-1.5">Local</h4>
                    <div className="flex gap-1.5 flex-wrap">
                      {local.map((m) => (
                        <span key={m.id} className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-md bg-muted/30">
                          <Avatar name={m.display_name} className="w-5 h-5 text-[10px]" />
                          {m.display_name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {remote.length > 0 && (
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-1.5">Remote</h4>
                    <div className="flex gap-1.5 flex-wrap">
                      {remote.map((m) => {
                        const host = m.username?.replace("remote:", "").split("@")[1] || "?";
                        const name = m.display_name || m.username?.replace("remote:", "").split("@")[0] || "?";
                        return (
                          <span key={m.id} className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-md bg-muted/20 text-muted-foreground">
                            <Avatar name={name} className="w-5 h-5 text-[10px] bg-muted" />
                            {name}
                            <span className="text-[10px] opacity-60">@{host}</span>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

// ── Peers Tab ──

function PeerManagement({ peers, queryClient }: { peers: PeerPod[]; queryClient: ReturnType<typeof useQueryClient> }) {
  const [showAdd, setShowAdd] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [pinging, setPinging] = useState<Record<string, boolean>>({});

  const addPeer = useMutation({
    mutationFn: () => api.addPeer(newUrl.trim()),
    onSuccess: () => { setNewUrl(""); setShowAdd(false); queryClient.invalidateQueries({ queryKey: ["pod-peers"] }); },
  });

  const removePeer = useMutation({
    mutationFn: (id: string) => api.removePeer(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["pod-peers"] }); queryClient.invalidateQueries({ queryKey: ["networks"] }); },
  });

  const pingPeer = async (id: string) => {
    setPinging((p) => ({ ...p, [id]: true }));
    try { await api.pingPeer(id); queryClient.invalidateQueries({ queryKey: ["pod-peers"] }); } catch {}
    setPinging((p) => ({ ...p, [id]: false }));
  };

  return (
    <div className="space-y-3">
      {/* Add peer */}
      <div className="flex justify-end">
        <button
          onClick={() => setShowAdd(!showAdd)}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors",
            showAdd ? "bg-muted text-muted-foreground" : "bg-accent text-accent-fg hover:bg-accent-hover"
          )}
        >
          {showAdd ? <><X className="size-3" /> Cancel</> : <><Plus className="size-3" /> Connect Pod</>}
        </button>
      </div>

      {showAdd && (
        <Card className="gap-0 py-0">
          <CardContent className="py-4">
            <label className="text-xs text-muted-foreground block mb-1.5">Pod URL</label>
            <div className="flex gap-2">
              <input
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && newUrl.trim()) addPeer.mutate(); }}
                placeholder="https://partner-pod.example.com"
                className="flex-1 bg-muted/30 border border-border rounded-md px-3 py-2 text-sm font-mono placeholder:text-muted-foreground"
              />
              <button
                onClick={() => addPeer.mutate()}
                disabled={!newUrl.trim() || addPeer.isPending}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-accent-fg text-xs font-semibold rounded-md disabled:opacity-40 transition-colors"
              >
                {addPeer.isPending ? <Loader2 className="size-4 animate-spin" /> : "Connect"}
              </button>
            </div>
            {addPeer.isError && <p className="text-xs text-danger mt-1.5">{(addPeer.error as Error).message}</p>}
          </CardContent>
        </Card>
      )}

      {/* Peer list */}
      {peers.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <CardDescription>No peer pods connected yet.</CardDescription>
          </CardContent>
        </Card>
      ) : (
        peers.map((peer) => {
          const lastSeen = relativeTime(peer.last_seen_at);
          return (
            <Card key={peer.id} className="gap-0 py-0">
              <CardContent className="py-3 flex items-center gap-3">
                <div className="relative">
                  <Avatar name={peer.name || "P"} className="w-9 h-9" />
                  <StatusDot status={peer.status} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">{peer.name || "Unknown Pod"}</span>
                    <Badge variant={peer.status === "active" ? "secondary" : "destructive"} className="text-[10px]">{peer.status}</Badge>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono truncate">{peer.url}</span>
                    {lastSeen && <span className="shrink-0">{lastSeen}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {peer.agent_count > 0 && <span className="text-[10px] text-muted-foreground">{peer.agent_count} agents</span>}
                  <button
                    onClick={() => pingPeer(peer.id)}
                    disabled={pinging[peer.id]}
                    className="p-2 rounded-md hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
                    title="Ping"
                  >
                    {pinging[peer.id] ? <Loader2 className="size-4 animate-spin" /> : <Wifi className="size-4" />}
                  </button>
                  <button
                    onClick={() => removePeer.mutate(peer.id)}
                    disabled={removePeer.isPending}
                    className="p-2 rounded-md hover:bg-danger/10 text-muted-foreground hover:text-danger transition-colors disabled:opacity-40"
                    title="Disconnect"
                  >
                    <WifiOff className="size-4" />
                  </button>
                </div>
              </CardContent>
            </Card>
          );
        })
      )}
    </div>
  );
}
