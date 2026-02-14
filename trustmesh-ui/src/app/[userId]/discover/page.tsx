"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type RegistryAgent } from "@/lib/api";
import { useParams } from "next/navigation";
import Link from "next/link";

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  person: { bg: "bg-blue-500/15 border-blue-500/25", text: "text-blue-400", label: "Person" },
  organization: { bg: "bg-amber-500/15 border-amber-500/25", text: "text-amber-400", label: "Organization" },
  government: { bg: "bg-emerald-500/15 border-emerald-500/25", text: "text-emerald-400", label: "Government" },
  service: { bg: "bg-amber-500/15 border-amber-500/25", text: "text-amber-400", label: "Service" },
};

const FILTER_OPTIONS = [
  { value: "", label: "All Types" },
  { value: "person", label: "People" },
  { value: "organization", label: "Organizations" },
  { value: "government", label: "Government" },
];

function TypeBadge({ userType }: { userType: string }) {
  const style = TYPE_STYLES[userType] || TYPE_STYLES.person;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold border ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function AgentCard({ agent, userId }: { agent: RegistryAgent; userId: string }) {
  const skills = agent.skills || [];
  const pools = agent.pools || [];

  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 hover:border-accent/30 hover:bg-card-hover transition-all group">
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <div className="w-11 h-11 rounded-xl bg-accent/10 flex items-center justify-center text-accent font-bold text-sm shrink-0 group-hover:bg-accent/20 transition-colors">
          {agent.display_name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold truncate">{agent.display_name}</h3>
            <TypeBadge userType={agent.user_type} />
          </div>
          <p className="text-xs text-muted-foreground truncate">@{agent.username}</p>
        </div>
      </div>

      {/* Bio */}
      {agent.bio && (
        <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">
          {agent.bio}
        </p>
      )}

      {/* Skills */}
      {skills.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {skills.slice(0, 4).map((skill, i) => (
            <span
              key={i}
              className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent/80"
            >
              {skill.name}
            </span>
          ))}
          {skills.length > 4 && (
            <span className="text-[10px] text-muted-foreground">+{skills.length - 4}</span>
          )}
        </div>
      )}

      {/* Pools */}
      {pools.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {pools.map((pool, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400/80"
            >
              <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
                <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
              </svg>
              {pool}
            </span>
          ))}
        </div>
      )}

      {/* DID (truncated) */}
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

export default function DiscoverPage() {
  const { userId } = useParams<{ userId: string }>();
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [capabilityFilter, setCapabilityFilter] = useState("");

  // Use search API when we have a query or filters, otherwise list all
  const hasFilters = !!(searchQuery || capabilityFilter);

  const { data: searchData, isLoading: searchLoading } = useQuery({
    queryKey: ["registry-search", searchQuery, typeFilter, capabilityFilter],
    queryFn: () =>
      api.registrySearch(searchQuery, {
        user_type: typeFilter || undefined,
        capability: capabilityFilter || undefined,
      }),
    enabled: hasFilters,
  });

  const { data: allData, isLoading: allLoading } = useQuery({
    queryKey: ["registry-agents", typeFilter],
    queryFn: () => api.registryAgents({ user_type: typeFilter || undefined }),
    enabled: !hasFilters,
  });

  const { data: podInfo } = useQuery({
    queryKey: ["pod-info"],
    queryFn: () => api.getPodInfo(),
    staleTime: 60_000,
  });

  const agents: RegistryAgent[] = hasFilters
    ? (searchData?.results ?? [])
    : (allData?.agents ?? []);
  const count = hasFilters ? (searchData?.count ?? 0) : (allData?.count ?? 0);
  const isLoading = hasFilters ? searchLoading : allLoading;

  // Unique skill categories for filter suggestions
  const allCategories = Array.from(
    new Set(agents.flatMap((a) => (a.skills || []).map((s) => s.category)).filter(Boolean))
  ).sort();

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-2xl font-bold">Discover Agents</h1>
          {podInfo && (
            <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border bg-accent/10 text-accent border-accent/20 font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-accent" />
              {podInfo.pod_name}
            </span>
          )}
        </div>
        <p className="text-muted-foreground text-sm">
          Find and connect with agents on this pod. {count} agent{count !== 1 ? "s" : ""} discoverable.
        </p>
      </div>

      {/* Search & Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        {/* Search Input */}
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            placeholder="Search by name, skill, or description..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-card border border-card-border rounded-xl text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50 transition-all"
          />
        </div>

        {/* Type Filter */}
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-2.5 bg-card border border-card-border rounded-xl text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 appearance-none cursor-pointer"
        >
          {FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        {/* Capability Filter */}
        {allCategories.length > 0 && (
          <select
            value={capabilityFilter}
            onChange={(e) => setCapabilityFilter(e.target.value)}
            className="px-3 py-2.5 bg-card border border-card-border rounded-xl text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 appearance-none cursor-pointer"
          >
            <option value="">All Capabilities</option>
            {allCategories.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        )}
      </div>

      {/* Results */}
      {isLoading ? (
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
      ) : agents.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {agents.map((agent) => (
            <AgentCard key={agent.did} agent={agent} userId={userId} />
          ))}
        </div>
      ) : (
        <div className="bg-card border border-card-border rounded-2xl p-12 text-center">
          <svg
            className="mx-auto mb-3 text-muted-foreground"
            width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <p className="text-sm text-muted-foreground mb-1">No agents found</p>
          <p className="text-xs text-muted-foreground">
            {hasFilters ? "Try adjusting your search or filters." : "No discoverable agents on this pod yet."}
          </p>
        </div>
      )}

      {/* Pod Info Footer */}
      {podInfo && (
        <div className="mt-8 bg-card/50 border border-card-border rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-accent flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
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
