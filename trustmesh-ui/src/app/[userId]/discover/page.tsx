"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type RegistryAgent, type RegistryPodAgent } from "@/lib/api";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Search, Globe, Box, User, Building2, Landmark, ExternalLink, Loader2 } from "lucide-react";

/* ── Shared ── */

const ENTITY_STYLE: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  person:       { icon: <User size={12} />,     color: "text-blue-400 bg-blue-500/15 border-blue-500/25",     label: "Person" },
  organization: { icon: <Building2 size={12} />, color: "text-amber-400 bg-amber-500/15 border-amber-500/25", label: "Organization" },
  government:   { icon: <Landmark size={12} />,  color: "text-emerald-400 bg-emerald-500/15 border-emerald-500/25", label: "Government" },
  service:      { icon: <Building2 size={12} />, color: "text-amber-400 bg-amber-500/15 border-amber-500/25", label: "Service" },
};

function EntityBadge({ type }: { type: string }) {
  const s = ENTITY_STYLE[type] || ENTITY_STYLE.person;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border ${s.color}`}>
      {s.icon} {s.label}
    </span>
  );
}

const FILTER_OPTIONS = [
  { value: "", label: "All Types" },
  { value: "person", label: "People" },
  { value: "organization", label: "Organizations" },
  { value: "government", label: "Government" },
];

/* ── Local Agent Card ── */

function LocalAgentCard({ agent, userId }: { agent: RegistryAgent; userId: string }) {
  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 hover:border-accent/30 hover:bg-card-hover transition-all group">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-11 h-11 rounded-xl bg-accent/10 flex items-center justify-center text-accent font-bold text-sm shrink-0 group-hover:bg-accent/20 transition-colors">
          {agent.display_name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold truncate">{agent.display_name}</h3>
            <EntityBadge type={agent.user_type} />
          </div>
          <p className="text-xs text-muted-foreground truncate">@{agent.username}</p>
        </div>
      </div>

      {agent.bio && (
        <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">{agent.bio}</p>
      )}

      {(agent.skills?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {agent.skills.slice(0, 4).map((skill, i) => (
            <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent/80">
              {skill.name}
            </span>
          ))}
          {agent.skills.length > 4 && (
            <span className="text-[10px] text-muted-foreground">+{agent.skills.length - 4}</span>
          )}
        </div>
      )}

      {(agent.pools?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {agent.pools.map((pool, i) => (
            <Badge key={i} variant="secondary" className="text-[10px] gap-1">
              <Globe size={8} /> {pool}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between mt-auto pt-3 border-t border-card-border/50">
        <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[60%]" title={agent.did}>
          {agent.did}
        </span>
        <Link
          href={`/${userId}/chat`}
          className="shrink-0 px-3 py-1.5 text-xs font-medium text-accent hover:text-accent-hover bg-accent/5 hover:bg-accent/10 rounded-lg transition-all"
        >
          Query Agent
        </Link>
      </div>
    </div>
  );
}

/* ── Public Registry Agent Card ── */

function PublicAgentCard({ agent }: { agent: RegistryPodAgent }) {
  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 hover:border-accent/30 hover:bg-card-hover transition-all group">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-11 h-11 rounded-xl bg-emerald-500/10 flex items-center justify-center text-emerald-400 font-bold text-sm shrink-0 group-hover:bg-emerald-500/20 transition-colors">
          {agent.display_name?.[0] || agent.name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold truncate">{agent.display_name || agent.name}</h3>
            <EntityBadge type={agent.entity_type} />
          </div>
          {agent.username && (
            <p className="text-xs text-muted-foreground truncate">@{agent.username}</p>
          )}
        </div>
      </div>

      {agent.bio && (
        <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">{agent.bio}</p>
      )}

      {agent.capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {agent.capabilities.slice(0, 5).map((cap, i) => (
            <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400/80">
              {cap}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between mt-auto pt-3 border-t border-card-border/50">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[40%]" title={agent.did}>
            {agent.did}
          </span>
          <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
            <ExternalLink size={9} />
            <span className="truncate max-w-[120px]" title={agent.pod_url}>{agent.pod_url.replace(/^https?:\/\//, "")}</span>
          </span>
        </div>
        {agent.registered_at && (
          <span className="text-[10px] text-muted-foreground shrink-0">
            {new Date(agent.registered_at).toLocaleDateString()}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Search Bar ── */

function SearchBar({
  searchQuery, setSearchQuery, typeFilter, setTypeFilter, capabilityFilter, setCapabilityFilter, categories,
}: {
  searchQuery: string; setSearchQuery: (v: string) => void;
  typeFilter: string; setTypeFilter: (v: string) => void;
  capabilityFilter: string; setCapabilityFilter: (v: string) => void;
  categories: string[];
}) {
  return (
    <div className="flex flex-col sm:flex-row gap-3 mb-6">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
        <input
          type="text"
          placeholder="Search by name, skill, or description..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full pl-10 pr-4 py-2.5 bg-card border border-card-border rounded-xl text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50 transition-all"
        />
      </div>
      <select
        value={typeFilter}
        onChange={(e) => setTypeFilter(e.target.value)}
        className="px-3 py-2.5 bg-card border border-card-border rounded-xl text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 appearance-none cursor-pointer"
      >
        {FILTER_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      {categories.length > 0 && (
        <select
          value={capabilityFilter}
          onChange={(e) => setCapabilityFilter(e.target.value)}
          className="px-3 py-2.5 bg-card border border-card-border rounded-xl text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 appearance-none cursor-pointer"
        >
          <option value="">All Capabilities</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>{cat}</option>
          ))}
        </select>
      )}
    </div>
  );
}

/* ── Skeleton Grid ── */

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="bg-card border border-card-border rounded-2xl p-5 animate-pulse">
          <div className="flex items-start gap-3 mb-3">
            <div className="w-11 h-11 rounded-xl bg-card-hover" />
            <div className="flex-1">
              <div className="h-4 bg-card-hover rounded w-1/2 mb-2" />
              <div className="h-3 bg-card-hover rounded w-1/3" />
            </div>
          </div>
          <div className="h-3 bg-card-hover rounded w-3/4 mb-2" />
          <div className="h-3 bg-card-hover rounded w-1/2" />
        </div>
      ))}
    </div>
  );
}

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <div className="bg-card border border-card-border rounded-2xl p-12 text-center">
      <Search className="mx-auto mb-3 text-muted-foreground" size={40} strokeWidth={1.5} />
      <p className="text-sm text-muted-foreground mb-1">No agents found</p>
      <p className="text-xs text-muted-foreground">
        {hasFilters ? "Try adjusting your search or filters." : "No discoverable agents yet."}
      </p>
    </div>
  );
}

/* ── Main Page ── */

export default function DiscoverPage() {
  const { userId } = useParams<{ userId: string }>();
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [capabilityFilter, setCapabilityFilter] = useState("");
  const [publicSearch, setPublicSearch] = useState("");

  // Local registry
  const hasFilters = !!(searchQuery || capabilityFilter);

  const { data: searchData, isLoading: searchLoading } = useQuery({
    queryKey: ["registry-search", searchQuery, typeFilter, capabilityFilter],
    queryFn: () => api.registrySearch(searchQuery, { user_type: typeFilter || undefined, capability: capabilityFilter || undefined }),
    enabled: hasFilters,
  });

  const { data: allData, isLoading: allLoading } = useQuery({
    queryKey: ["registry-agents", typeFilter],
    queryFn: () => api.registryAgents({ user_type: typeFilter || undefined }),
    enabled: !hasFilters,
  });

  // Public registry
  const { data: registryHealth } = useQuery({
    queryKey: ["public-registry-health"],
    queryFn: () => api.registryHealth(),
    retry: false,
    staleTime: 30_000,
  });

  const registryOnline = registryHealth?.status === "ok";

  const { data: publicAgents, isLoading: publicLoading } = useQuery({
    queryKey: ["public-registry-agents", publicSearch],
    queryFn: async (): Promise<{ agents: RegistryPodAgent[]; count: number }> => {
      if (publicSearch) {
        const r = await api.registrySearchAll(publicSearch);
        return { agents: r.results, count: r.count };
      }
      return api.registryListAll();
    },
    enabled: registryOnline,
    retry: false,
  });

  const { data: podInfo } = useQuery({
    queryKey: ["pod-info"],
    queryFn: () => api.getPodInfo(),
    staleTime: 60_000,
  });

  const localAgents: RegistryAgent[] = hasFilters ? (searchData?.results ?? []) : (allData?.agents ?? []);
  const localCount = hasFilters ? (searchData?.count ?? 0) : (allData?.count ?? 0);
  const localLoading = hasFilters ? searchLoading : allLoading;

  const publicAgentList: RegistryPodAgent[] = publicAgents?.agents ?? [];
  const publicCount = publicAgents?.count ?? 0;

  const allCategories = Array.from(
    new Set(localAgents.flatMap((a) => (a.skills || []).map((s) => s.category)).filter(Boolean))
  ).sort();

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-2xl font-bold">Discover Agents</h1>
          {podInfo && (
            <Badge variant="outline" className="text-[11px] gap-1.5">
              <Box size={10} /> {podInfo.pod_name}
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground text-sm">
          Find and connect with agents on this pod or across the public registry.
        </p>
      </div>

      <Tabs defaultValue="local">
        <TabsList variant="line" className="mb-6">
          <TabsTrigger value="local" className="gap-2">
            <Box size={14} /> This Pod
            <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">{localCount}</Badge>
          </TabsTrigger>
          <TabsTrigger value="public" className="gap-2">
            <Globe size={14} /> Public Registry
            {registryOnline ? (
              <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">{publicCount}</Badge>
            ) : (
              <span className="ml-1 text-[10px] text-muted-foreground">(offline)</span>
            )}
          </TabsTrigger>
        </TabsList>

        {/* ── Local Pod Tab ── */}
        <TabsContent value="local">
          <SearchBar
            searchQuery={searchQuery} setSearchQuery={setSearchQuery}
            typeFilter={typeFilter} setTypeFilter={setTypeFilter}
            capabilityFilter={capabilityFilter} setCapabilityFilter={setCapabilityFilter}
            categories={allCategories}
          />

          {localLoading ? (
            <SkeletonGrid />
          ) : localAgents.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {localAgents.map((agent) => (
                <LocalAgentCard key={agent.did} agent={agent} userId={userId} />
              ))}
            </div>
          ) : (
            <EmptyState hasFilters={hasFilters} />
          )}
        </TabsContent>

        {/* ── Public Registry Tab ── */}
        <TabsContent value="public">
          {registryOnline ? (
            <>
              <div className="flex flex-col sm:flex-row gap-3 mb-6">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
                  <input
                    type="text"
                    placeholder="Search the public registry..."
                    value={publicSearch}
                    onChange={(e) => setPublicSearch(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 bg-card border border-card-border rounded-xl text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50 transition-all"
                  />
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="w-2 h-2 rounded-full bg-green-400" />
                  Registry online &middot; {publicCount} agent{publicCount !== 1 ? "s" : ""}
                </div>
              </div>

              {publicLoading ? (
                <SkeletonGrid />
              ) : publicAgentList.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {publicAgentList.map((agent) => (
                    <PublicAgentCard key={agent.did} agent={agent} />
                  ))}
                </div>
              ) : (
                <EmptyState hasFilters={!!publicSearch} />
              )}
            </>
          ) : (
            <div className="bg-card border border-card-border rounded-2xl p-12 text-center">
              <Globe className="mx-auto mb-3 text-muted-foreground" size={40} strokeWidth={1.5} />
              <p className="text-sm text-foreground mb-2">Public Registry Offline</p>
              <p className="text-xs text-muted-foreground mb-4 max-w-md mx-auto">
                The public registry service is not running. Start it to discover agents across pods.
              </p>
              <code className="text-xs bg-card-hover border border-card-border rounded-lg px-3 py-2 font-mono text-muted-foreground">
                ./multi-pod.sh demo
              </code>
              <p className="text-[10px] text-muted-foreground mt-2">
                Or standalone: <code className="font-mono">uv run uvicorn src.registry_service:app --port 8100</code>
              </p>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Pod Info Footer */}
      {podInfo && (
        <div className="mt-8 bg-card/50 border border-card-border rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-accent flex items-center justify-center">
              <Box size={16} className="text-accent-fg" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">{podInfo.pod_name}</h3>
              <p className="text-xs text-muted-foreground">TrustMesh Pod &middot; {podInfo.protocol}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span>{podInfo.agent_count} agent{podInfo.agent_count !== 1 ? "s" : ""}</span>
            <span className="font-mono text-[10px] truncate max-w-xs" title={podInfo.pod_url}>{podInfo.pod_url}</span>
          </div>
        </div>
      )}
    </div>
  );
}
