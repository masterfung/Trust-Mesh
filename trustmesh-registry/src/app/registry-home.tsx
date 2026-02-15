"use client";

import { useState, useMemo } from "react";
import { Shield } from "lucide-react";
import { Stats } from "@/components/Stats";
import { SearchBar } from "@/components/SearchBar";
import { AgentCard } from "@/components/AgentCard";
import type { AgentRecord } from "@/lib/db";

const TABS = [
  { key: "all", label: "All" },
  { key: "person", label: "People" },
  { key: "organization", label: "Orgs" },
  { key: "government", label: "Gov" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

interface Props {
  initialAgents: AgentRecord[];
  initialStats: { total: number; people: number; organizations: number; government: number };
}

export function RegistryHome({ initialAgents, initialStats }: Props) {
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [agents, setAgents] = useState(initialAgents);
  const [stats, setStats] = useState(initialStats);

  // Client-side search with server refresh
  const handleSearch = async (q: string) => {
    setSearch(q);
    if (!q.trim()) {
      // Refresh full list
      try {
        const entityParam = activeTab !== "all" ? `&entity_type=${activeTab}` : "";
        const res = await fetch(`/api/agents?${entityParam}`);
        const data = await res.json();
        setAgents(data.agents);
      } catch { /* use cached */ }
      return;
    }
    try {
      const entityParam = activeTab !== "all" ? `&entity_type=${activeTab}` : "";
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}${entityParam}`);
      const data = await res.json();
      setAgents(data.results);
    } catch { /* use cached */ }
  };

  const handleTabChange = async (tab: TabKey) => {
    setActiveTab(tab);
    try {
      const entityParam = tab !== "all" ? `?entity_type=${tab}` : "";
      const searchParam = search.trim() ? `${entityParam ? "&" : "?"}q=${encodeURIComponent(search)}` : "";
      const endpoint = search.trim() ? `/api/search${entityParam ? `?entity_type=${tab}&` : "?"}q=${encodeURIComponent(search)}` : `/api/agents${entityParam}`;
      const res = await fetch(endpoint);
      const data = await res.json();
      setAgents(data.results || data.agents);
      // Refresh stats
      const statsRes = await fetch("/api/health");
      const statsData = await statsRes.json();
      setStats((prev) => ({ ...prev, total: statsData.agent_count }));
    } catch { /* use cached */ }
  };

  const filteredAgents = useMemo(() => {
    if (activeTab === "all") return agents;
    return agents.filter((a) => a.entity_type === activeTab);
  }, [agents, activeTab]);

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-white/5 bg-white/[0.01]">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center gap-3">
          <Shield className="size-6 text-yellow-400" />
          <h1 className="text-lg font-semibold">
            <span className="text-gradient">TrustMesh</span> Agent Registry
          </h1>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8 space-y-8">
        {/* Hero */}
        <div className="text-center space-y-3">
          <h2 className="text-3xl font-bold tracking-tight">
            Discover Agents Across the Network
          </h2>
          <p className="text-muted-foreground max-w-xl mx-auto">
            Browse AI agents from people, organizations, and government entities.
            Every agent is cryptographically verifiable via their DID.
          </p>
        </div>

        {/* Stats */}
        <Stats
          total={stats.total}
          people={stats.people}
          organizations={stats.organizations}
          government={stats.government}
        />

        {/* Search */}
        <SearchBar value={search} onChange={handleSearch} />

        {/* Tabs */}
        <div className="flex gap-1 border-b border-white/5 pb-px">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => handleTabChange(tab.key)}
              className={`px-4 py-2 text-sm font-medium rounded-t-md transition-colors ${
                activeTab === tab.key
                  ? "text-yellow-400 border-b-2 border-yellow-400 bg-yellow-400/5"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
              {tab.key === "all" && ` (${stats.total})`}
              {tab.key === "person" && ` (${stats.people})`}
              {tab.key === "organization" && ` (${stats.organizations})`}
              {tab.key === "government" && ` (${stats.government})`}
            </button>
          ))}
        </div>

        {/* Card Grid */}
        {filteredAgents.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground">
            <p className="text-lg">No agents found</p>
            <p className="text-sm mt-1">
              {search ? "Try a different search term" : "Pods will appear here when they register"}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {filteredAgents.map((agent) => (
              <AgentCard
                key={agent.did}
                did={agent.did}
                name={agent.name}
                display_name={agent.display_name}
                username={agent.username}
                entity_type={agent.entity_type}
                bio={agent.bio}
                capabilities={agent.capabilities}
                pod_url={agent.pod_url}
              />
            ))}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 mt-16">
        <div className="mx-auto max-w-6xl px-6 py-6 text-center text-xs text-muted-foreground space-y-1">
          <p>Built with love by <a href="https://github.com/masterfung" target="_blank" rel="noopener noreferrer" className="text-yellow-400 hover:text-yellow-300 transition-colors">@masterfung</a></p>
          <p>TrustMesh Agent Registry — Cryptographically verified agent discovery</p>
        </div>
      </footer>
    </div>
  );
}
