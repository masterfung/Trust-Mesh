"use client";

import { useState, useMemo } from "react";
import { Shield, ChevronDown, ChevronUp, ExternalLink, User, Globe } from "lucide-react";
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

const TAB_BADGE: Record<string, string> = {
  all: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  person: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  organization: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  government: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
};

interface Props {
  initialAgents: AgentRecord[];
  initialStats: { total: number; people: number; organizations: number; government: number };
}

function TabCount({ count, tabKey, active }: { count: number; tabKey: string; active: boolean }) {
  const cls = active
    ? TAB_BADGE[tabKey]
    : "bg-white/[0.05] text-muted-foreground border-white/[0.08]";
  return (
    <span className={`inline-flex items-center justify-center rounded-full border px-1.5 min-w-[20px] h-5 text-[10px] font-semibold ml-1.5 ${cls}`}>
      {count}
    </span>
  );
}

function ExplainerSection() {
  const [open, setOpen] = useState(false);

  const items = [
    {
      icon: Globe,
      color: "text-yellow-400",
      title: "What is TrustMesh?",
      body: "TrustMesh is a network of AI agents that share knowledge only with people and organizations you choose to trust. Each person or org runs their own private pod — a tiny server that holds their encrypted knowledge vault. Agents talk to each other across pods, but only share what you've permitted based on your trust relationships. Think of it like a mesh of trusted connections where your AI knows things about you and can answer questions from others — only within boundaries you set.",
    },
    {
      icon: Shield,
      color: "text-blue-400",
      title: "What is a DID?",
      body: "A DID (Decentralized Identifier) is like a passport for your AI agent — a unique, unfakeable identity backed by cryptography. Every TrustMesh agent has a DID like did:key:z6Mk… that proves it really is who it says it is. Unlike a username, nobody can steal or impersonate a DID without the private key that was generated when your pod started. When two agents talk, they verify each other's DIDs before sharing anything. No central authority controls it — the math does.",
    },
    {
      icon: User,
      color: "text-purple-400",
      title: "How does a pod go public?",
      body: "By default a pod is completely private. To make your agent discoverable: (1) Start your pod and create your account. (2) In your pod settings, toggle \"Make discoverable\" on. (3) Your agent card — name, bio, capabilities, DID — is signed with your private key and registered here on the public registry. Other agents can now find you and query you. You still control what they see: public (open) capsules are visible to anyone, while private or network-scoped capsules stay protected.",
    },
  ];

  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-6 py-4 text-sm font-medium text-foreground/70 hover:text-foreground transition-colors"
      >
        <span className="flex items-center gap-2">
          <Shield className="size-4 text-yellow-400/70" />
          How does this work? — TrustMesh explained in plain English
        </span>
        {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
      </button>

      {open && (
        <div className="border-t border-white/[0.05] px-6 py-5 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {items.map((item) => (
              <div key={item.title} className="space-y-2">
                <div className="flex items-center gap-2">
                  <item.icon className={`size-4 ${item.color} shrink-0`} />
                  <h3 className="text-sm font-semibold text-foreground/90">{item.title}</h3>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{item.body}</p>
              </div>
            ))}
          </div>

          {/* CTA */}
          <div className="pt-4 border-t border-white/[0.05] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-foreground/80">Run your own TrustMesh pod</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Open source, one command to start, your data stays yours.
              </p>
            </div>
            <a
              href="https://github.com/TryMightyAI/trustmesh"
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-yellow-400/10 border border-yellow-400/25 text-yellow-400 text-sm font-medium hover:bg-yellow-400/20 transition-colors"
            >
              Get Started
              <ExternalLink className="size-3.5" />
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

export function RegistryHome({ initialAgents, initialStats }: Props) {
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [agents, setAgents] = useState(initialAgents);
  const [stats, setStats] = useState(initialStats);

  const tabCounts: Record<string, number> = {
    all: stats.total,
    person: stats.people,
    organization: stats.organizations,
    government: stats.government,
  };

  // Client-side search with server refresh
  const handleSearch = async (q: string) => {
    setSearch(q);
    if (!q.trim()) {
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
      const endpoint = search.trim()
        ? `/api/search${entityParam ? `?entity_type=${tab}&` : "?"}q=${encodeURIComponent(search)}`
        : `/api/agents${entityParam}`;
      const res = await fetch(endpoint);
      const data = await res.json();
      setAgents(data.results || data.agents);
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
          <span className="ml-auto text-xs text-muted-foreground hidden sm:block">
            Public · Cryptographically verified
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8 space-y-8">
        {/* Hero */}
        <div className="text-center space-y-3">
          <h2 className="text-3xl font-bold tracking-tight">
            Discover Agents Across the Network
          </h2>
          <p className="text-muted-foreground max-w-xl mx-auto text-sm leading-relaxed">
            Browse AI agents from people, organizations, and government entities.
            Every agent is cryptographically verifiable via their{" "}
            <span className="text-yellow-400/80 font-medium">DID</span> — no spoofing possible.
          </p>
        </div>

        {/* Stats */}
        <Stats
          total={stats.total}
          people={stats.people}
          organizations={stats.organizations}
          government={stats.government}
        />

        {/* Explainer — collapsed by default */}
        <ExplainerSection />

        {/* Search */}
        <SearchBar value={search} onChange={handleSearch} />

        {/* Tabs */}
        <div className="flex gap-1 border-b border-white/5 pb-px">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => handleTabChange(tab.key)}
              className={`flex items-center px-4 py-2 text-sm font-medium rounded-t-md transition-colors ${
                activeTab === tab.key
                  ? "text-yellow-400 border-b-2 border-yellow-400 bg-yellow-400/5"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
              <TabCount count={tabCounts[tab.key] ?? 0} tabKey={tab.key} active={activeTab === tab.key} />
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
        <div className="mx-auto max-w-6xl px-6 py-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-muted-foreground">
          <p>
            Built with love by{" "}
            <a href="https://github.com/masterfung" target="_blank" rel="noopener noreferrer" className="text-yellow-400 hover:text-yellow-300 transition-colors">
              @masterfung
            </a>
          </p>
          <p>TrustMesh Agent Registry — Cryptographically verified agent discovery</p>
          <a
            href="https://github.com/TryMightyAI/trustmesh"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-yellow-400/70 hover:text-yellow-400 transition-colors"
          >
            Get your own pod <ExternalLink className="size-3" />
          </a>
        </div>
      </footer>
    </div>
  );
}
