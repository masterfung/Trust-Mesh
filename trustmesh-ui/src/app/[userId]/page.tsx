"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, CapsuleTypeBadge } from "@/components/TrustBadge";
import Link from "next/link";

export default function Dashboard() {
  const { userId } = useParams<{ userId: string }>();

  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });
  const { data: agent } = useQuery({
    queryKey: ["agent", userId],
    queryFn: () => api.getAgent(userId),
  });
  const { data: capsules } = useQuery({
    queryKey: ["capsules", userId],
    queryFn: () => api.listCapsules(userId),
  });
  const { data: networks } = useQuery({
    queryKey: ["networks", userId],
    queryFn: () => api.listNetworks(userId),
  });
  const { data: connections } = useQuery({
    queryKey: ["connections", userId],
    queryFn: () => api.listConnections(userId),
  });
  const { data: queries } = useQuery({
    queryKey: ["queries", userId],
    queryFn: () => api.listQueries(userId),
  });

  const stats = [
    {
      label: "Knowledge Capsules",
      value: capsules?.length ?? 0,
      href: `/${userId}/vault`,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
        </svg>
      ),
      color: "text-accent",
    },
    {
      label: "Networks",
      value: networks?.length ?? 0,
      href: `/${userId}/networks`,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
          <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
        </svg>
      ),
      color: "text-purple-400",
    },
    {
      label: "Connections",
      value: connections?.length ?? 0,
      href: `/${userId}/connections`,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
          <line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>
        </svg>
      ),
      color: "text-green-400",
    },
    {
      label: "Agent Queries",
      value: queries?.length ?? 0,
      href: `/${userId}/chat`,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      ),
      color: "text-orange-400",
    },
  ];

  const tierCounts = {
    public: capsules?.filter((c) => c.tier === "public").length ?? 0,
    network: capsules?.filter((c) => c.tier === "network").length ?? 0,
    private: capsules?.filter((c) => c.tier === "private").length ?? 0,
  };

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-1">{user?.display_name}&apos;s Dashboard</h1>
        <p className="text-muted-foreground text-sm">{user?.bio}</p>
      </div>

      {/* Agent Card */}
      {agent && (
        <div className="bg-gradient-to-r from-accent/5 to-purple-500/5 border border-accent/20 rounded-2xl p-5 mb-6">
          <div className="flex items-start gap-4">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center shrink-0">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/>
                <circle cx="10" cy="16" r="1"/><circle cx="14" cy="16" r="1"/>
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="font-semibold text-sm">{agent.name}</h2>
              <p className="text-xs text-muted-foreground mt-0.5">{agent.personality}</p>
              <div className="flex items-center gap-2 mt-2">
                <span className="inline-flex items-center gap-1 text-[10px] text-accent bg-accent/10 px-2 py-0.5 rounded-full font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                  Claude Opus 4.6
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {capsules?.length ?? 0} capsules loaded
                </span>
              </div>
            </div>
            <Link
              href={`/${userId}/chat`}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-xl transition-all hover:shadow-lg hover:shadow-accent/20"
            >
              Ask Agents
            </Link>
          </div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {stats.map((s) => (
          <Link
            key={s.label}
            href={s.href}
            className="group bg-card border border-card-border rounded-2xl p-4 hover:border-accent/30 hover:bg-card-hover transition-all"
          >
            <div className={`${s.color} mb-3 opacity-60 group-hover:opacity-100 transition-opacity`}>
              {s.icon}
            </div>
            <p className="text-2xl font-bold">{s.value}</p>
            <p className="text-xs text-muted mt-1">{s.label}</p>
          </Link>
        ))}
      </div>

      {/* Trust Distribution */}
      <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
        <h2 className="text-sm font-semibold mb-4">Knowledge by Trust Tier</h2>
        <div className="flex gap-4">
          {Object.entries(tierCounts).map(([tier, count]) => {
            const total = capsules?.length ?? 1;
            const pct = total > 0 ? Math.round((count / total) * 100) : 0;
            return (
              <div key={tier} className="flex-1">
                <div className="flex items-center justify-between mb-2">
                  <TrustBadge tier={tier} />
                  <span className="text-sm font-bold">{count}</span>
                </div>
                <div className="h-1.5 bg-card-border rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      tier === "public" ? "bg-warning" : tier === "network" ? "bg-accent" : "bg-danger"
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Knowledge */}
        <div className="bg-card border border-card-border rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">Recent Knowledge</h2>
            <Link href={`/${userId}/vault`} className="text-xs text-accent hover:text-accent-hover transition-colors">
              View all &rarr;
            </Link>
          </div>
          <div className="space-y-2">
            {capsules?.slice(0, 5).map((c) => (
              <div key={c.id} className="flex items-center gap-3 py-2 px-3 rounded-xl hover:bg-card-hover transition-colors">
                <CapsuleTypeBadge type={c.capsule_type} />
                <span className="text-sm flex-1 truncate">{c.title}</span>
                <TrustBadge tier={c.tier} />
              </div>
            ))}
            {!capsules?.length && (
              <p className="text-sm text-muted text-center py-6">No capsules yet. Add knowledge to your vault.</p>
            )}
          </div>
        </div>

        {/* Networks */}
        <div className="bg-card border border-card-border rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">Your Networks</h2>
            <Link href={`/${userId}/networks`} className="text-xs text-accent hover:text-accent-hover transition-colors">
              Manage &rarr;
            </Link>
          </div>
          <div className="space-y-2">
            {networks?.map((n) => (
              <div key={n.id} className="flex items-center justify-between py-2.5 px-3 rounded-xl hover:bg-card-hover transition-colors">
                <div className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold ${
                    n.network_type === "family" ? "bg-blue-500/15 text-blue-400" :
                    n.network_type === "team" ? "bg-purple-500/15 text-purple-400" :
                    "bg-green-500/15 text-green-400"
                  }`}>
                    {n.name[0]}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{n.name}</p>
                    <p className="text-[11px] text-muted">{n.network_type}</p>
                  </div>
                </div>
                <span className="text-xs text-muted-foreground">{n.members.length} members</span>
              </div>
            ))}
            {!networks?.length && (
              <p className="text-sm text-muted text-center py-6">No networks yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
