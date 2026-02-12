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
    { label: "Knowledge Capsules", value: capsules?.length ?? 0, href: `/${userId}/vault` },
    { label: "Networks", value: networks?.length ?? 0, href: `/${userId}/networks` },
    { label: "Connections", value: connections?.length ?? 0, href: `/${userId}/connections` },
    { label: "Queries", value: queries?.length ?? 0, href: `/${userId}/chat` },
  ];

  const tierCounts = {
    public: capsules?.filter((c) => c.tier === "public").length ?? 0,
    network: capsules?.filter((c) => c.tier === "network").length ?? 0,
    private: capsules?.filter((c) => c.tier === "private").length ?? 0,
  };

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-bold mb-1">{user?.display_name}&apos;s Dashboard</h1>
      <p className="text-muted text-sm mb-6">{user?.bio}</p>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        {stats.map((s) => (
          <Link
            key={s.label}
            href={s.href}
            className="bg-card border border-card-border rounded-lg p-4 hover:border-accent transition-colors"
          >
            <p className="text-2xl font-bold text-accent">{s.value}</p>
            <p className="text-xs text-muted mt-1">{s.label}</p>
          </Link>
        ))}
      </div>

      {/* Trust Distribution */}
      <div className="bg-card border border-card-border rounded-lg p-4 mb-8">
        <h2 className="text-sm font-semibold mb-3">Knowledge by Trust Tier</h2>
        <div className="flex gap-6">
          {Object.entries(tierCounts).map(([tier, count]) => (
            <div key={tier} className="flex items-center gap-2">
              <TrustBadge tier={tier} />
              <span className="text-sm font-medium">{count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Capsules */}
      <div className="bg-card border border-card-border rounded-lg p-4 mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold">Recent Knowledge</h2>
          <Link href={`/${userId}/vault`} className="text-xs text-accent hover:underline">
            View all
          </Link>
        </div>
        <div className="space-y-2">
          {capsules?.slice(0, 5).map((c) => (
            <div key={c.id} className="flex items-center gap-3 py-1.5">
              <CapsuleTypeBadge type={c.capsule_type} />
              <span className="text-sm flex-1 truncate">{c.title}</span>
              <TrustBadge tier={c.tier} />
            </div>
          ))}
          {!capsules?.length && (
            <p className="text-xs text-muted">No capsules yet. Add knowledge to your vault.</p>
          )}
        </div>
      </div>

      {/* Networks */}
      <div className="bg-card border border-card-border rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold">Your Networks</h2>
          <Link href={`/${userId}/networks`} className="text-xs text-accent hover:underline">
            Manage
          </Link>
        </div>
        <div className="space-y-2">
          {networks?.map((n) => (
            <div key={n.id} className="flex items-center justify-between py-1.5">
              <div>
                <span className="text-sm font-medium">{n.name}</span>
                <span className="text-xs text-muted ml-2">{n.network_type}</span>
              </div>
              <span className="text-xs text-muted">{n.members.length} members</span>
            </div>
          ))}
          {!networks?.length && (
            <p className="text-xs text-muted">No networks yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
