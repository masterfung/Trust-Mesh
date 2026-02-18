"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, type AgentTask, type Briefing, type ServiceProvider } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, CapsuleTypeBadge } from "@/components/TrustBadge";
import { Markdown } from "@/components/Markdown";
import Link from "next/link";

export default function Dashboard() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();

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

  // New queries: briefing, tasks, services
  const {
    data: briefing,
    isLoading: briefingLoading,
    isError: briefingError,
  } = useQuery({
    queryKey: ["briefing", userId],
    queryFn: () => api.getBriefing(userId),
  });

  const { data: tasks } = useQuery({
    queryKey: ["tasks", userId],
    queryFn: () => api.listTasks(userId),
  });

  const { data: services } = useQuery({
    queryKey: ["services"],
    queryFn: () => api.listServices(),
  });

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.getHealthFull(),
    staleTime: 60_000,
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
      color: "text-accent",
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

  const pendingTasks = tasks?.filter(
    (t: AgentTask) => t.status === "pending" || t.status === "in_progress"
  ) ?? [];

  const taskStatusColor = (status: string) => {
    switch (status) {
      case "pending":
        return "bg-yellow-500/15 text-yellow-400 border-yellow-500/20";
      case "in_progress":
        return "bg-blue-500/15 text-blue-400 border-blue-500/20";
      case "completed":
        return "bg-green-500/15 text-green-400 border-green-500/20";
      default:
        return "bg-muted/15 text-muted-foreground border-card-border";
    }
  };

  const isNewUser = (capsules?.length ?? 0) === 0 && (connections?.length ?? 0) === 0;

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-1">{user?.display_name}&apos;s Dashboard</h1>
        <p className="text-muted-foreground text-sm">{user?.bio}</p>
      </div>

      {/* Getting Started — shown for new users with no capsules */}
      {isNewUser && (
        <div className="mb-8">
          <div className="bg-gradient-to-br from-accent/8 via-accent-dim/5 to-transparent border border-accent/20 rounded-2xl p-6 mb-4">
            <div className="flex items-start gap-4">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-accent to-accent-dim flex items-center justify-center shrink-0 shadow-lg shadow-accent/20">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/>
                  <circle cx="10" cy="16" r="1"/><circle cx="14" cy="16" r="1"/>
                </svg>
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-bold mb-1">Welcome to your pod!</h2>
                <p className="text-sm text-muted-foreground mb-4">
                  Your AI agent is ready but doesn&apos;t know you yet. Let&apos;s fix that — it only takes a couple minutes.
                </p>
                <Link
                  href={`/${userId}/onboard`}
                  className="inline-flex items-center gap-2 px-6 py-3 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm transition-all hover:shadow-lg hover:shadow-accent/20"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                  </svg>
                  Set Up Your Agent
                </Link>
              </div>
            </div>
          </div>

          {/* Quick start cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Link
              href={`/${userId}/onboard`}
              className="group p-4 bg-card border border-card-border rounded-xl hover:border-accent/30 hover:bg-card-hover transition-all"
            >
              <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center text-blue-400 mb-3">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
              </div>
              <p className="text-sm font-medium mb-0.5">Tell your agent about you</p>
              <p className="text-xs text-muted-foreground">Quick conversation to set up your profile</p>
            </Link>
            <Link
              href={`/${userId}/vault`}
              className="group p-4 bg-card border border-card-border rounded-xl hover:border-accent/30 hover:bg-card-hover transition-all"
            >
              <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center text-amber-400 mb-3">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
                </svg>
              </div>
              <p className="text-sm font-medium mb-0.5">Add knowledge manually</p>
              <p className="text-xs text-muted-foreground">Store info in your encrypted vault</p>
            </Link>
            <Link
              href={`/${userId}/discover`}
              className="group p-4 bg-card border border-card-border rounded-xl hover:border-accent/30 hover:bg-card-hover transition-all"
            >
              <div className="w-8 h-8 rounded-lg bg-green-500/10 flex items-center justify-center text-green-400 mb-3">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
              </div>
              <p className="text-sm font-medium mb-0.5">Discover services</p>
              <p className="text-xs text-muted-foreground">Find and connect with other pods</p>
            </Link>
          </div>
        </div>
      )}

      {/* ── Everything below is hidden for brand-new users ── */}
      {!isNewUser && agent && (
        <div className="bg-gradient-to-r from-accent/5 to-accent-dim/5 border border-accent/20 rounded-2xl p-5 mb-6">
          <div className="flex items-start gap-4">
            <div className="w-11 h-11 rounded-xl bg-accent flex items-center justify-center shrink-0">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-accent-fg text-sm font-medium rounded-xl transition-all hover:shadow-lg hover:shadow-accent/20"
            >
              Ask Agents
            </Link>
          </div>
        </div>
      )}

      {!isNewUser && health && (
        <div className="flex flex-wrap items-center gap-3 mb-6 px-1">
          {[
            { label: "Anthropic", ok: health.providers.anthropic, detail: "Claude Opus 4.6" },
            { label: "TEE", ok: health.providers.tee.enabled, detail: health.providers.tee.provider ? `via ${health.providers.tee.provider}` : "not configured" },
            { label: "Web Search", ok: health.providers.tavily, detail: "Tavily" },
            { label: "Citadel", ok: (health.providers.citadel as Record<string, unknown>).active ?? health.providers.citadel.reachable, detail: health.providers.citadel.reachable ? "sidecar active" : (health.providers.citadel as Record<string, unknown>).heuristic_active ? "heuristic active" : health.providers.citadel.configured ? "configured, offline" : "not configured" },
          ].map((p) => (
            <span
              key={p.label}
              className={`inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border font-medium ${
                p.ok
                  ? "bg-green-500/10 text-green-400 border-green-500/20"
                  : "bg-muted/10 text-muted-foreground border-card-border"
              }`}
              title={p.detail}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${p.ok ? "bg-green-400" : "bg-muted-foreground/40"}`} />
              {p.label}
            </span>
          ))}
        </div>
      )}

      {/* Dynamic Briefing Card */}
      {!isNewUser && <BriefingCard userId={userId} briefing={briefing} briefingLoading={briefingLoading} briefingError={briefingError} queryClient={queryClient} />}

      {/* Pending Tasks Card */}
      {!isNewUser && <div className="bg-card border border-card-border rounded-2xl p-5 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold">Agent Tasks</h2>
          <span className="text-xs text-muted-foreground">
            {pendingTasks.length} pending
          </span>
        </div>
        {tasks && tasks.length > 0 ? (
          <div className="space-y-2">
            {tasks.slice(0, 8).map((task: AgentTask) => (
              <div
                key={task.id}
                className="flex items-center gap-3 py-2.5 px-3 rounded-xl hover:bg-card-hover transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{task.title}</p>
                  {task.description && (
                    <p className="text-xs text-muted-foreground mt-0.5 truncate">
                      {task.description}
                    </p>
                  )}
                </div>
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${taskStatusColor(
                    task.status
                  )}`}
                >
                  {task.status.replace("_", " ")}
                </span>
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium bg-card-hover text-muted-foreground">
                  {task.task_type}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-6">No tasks yet. Your agent will create tasks from conversations.</p>
        )}
      </div>}

      {/* Stats Grid — hidden for new users */}
      {!isNewUser && <>
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
            <p className="text-xs text-muted-foreground mt-1">{s.label}</p>
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
              <p className="text-sm text-muted-foreground text-center py-6">No capsules yet. Add knowledge to your vault.</p>
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
                    n.network_type === "team" ? "bg-amber-500/15 text-amber-400" :
                    "bg-green-500/15 text-green-400"
                  }`}>
                    {n.name[0]}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{n.name}</p>
                    <p className="text-[11px] text-muted-foreground">{n.network_type}</p>
                  </div>
                </div>
                <span className="text-xs text-muted-foreground">{n.members.length} members</span>
              </div>
            ))}
            {!networks?.length && (
              <p className="text-sm text-muted-foreground text-center py-6">No networks yet.</p>
            )}
          </div>
        </div>

        {/* Service Providers */}
        <div className="bg-card border border-card-border rounded-2xl p-5 lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">Service Providers</h2>
            <span className="text-xs text-muted-foreground">
              {services?.length ?? 0} available
            </span>
          </div>
          {services && services.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {services.map((sp: ServiceProvider) => (
                <div
                  key={sp.id}
                  className="flex items-start gap-3 p-3 rounded-xl border border-card-border hover:border-accent/20 hover:bg-card-hover transition-all"
                >
                  <div className="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center text-accent font-bold text-sm shrink-0">
                    {sp.display_name[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{sp.display_name}</p>
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {sp.bio}
                    </p>
                    {sp.agent_card?.skills && sp.agent_card.skills.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {sp.agent_card.skills.slice(0, 4).map((skill) => (
                          <span
                            key={skill.id}
                            className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent/80"
                          >
                            {skill.name}
                          </span>
                        ))}
                        {sp.agent_card.skills.length > 4 && (
                          <span className="text-[10px] text-muted-foreground">
                            +{sp.agent_card.skills.length - 4} more
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <Link
                    href={`/${userId}/chat`}
                    className="shrink-0 px-3 py-1.5 text-xs font-medium text-accent hover:text-accent-hover bg-accent/5 hover:bg-accent/10 rounded-lg transition-all"
                  >
                    Request Quote
                  </Link>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-6">No service providers available yet.</p>
          )}
        </div>
      </div>
      </>}
    </div>
  );
}

/** Time-of-day config for briefing card styling. */
const BRIEFING_THEMES = {
  morning: { label: "Morning Briefing", icon: "\u2600\uFE0F", gradient: "from-amber-500/5 to-orange-500/5", border: "border-amber-500/20", accent: "text-amber-400" },
  afternoon: { label: "Afternoon Briefing", icon: "\u26C5", gradient: "from-sky-500/5 to-blue-500/5", border: "border-sky-500/20", accent: "text-sky-400" },
  evening: { label: "Evening Briefing", icon: "\uD83C\uDF19", gradient: "from-indigo-500/5 to-purple-500/5", border: "border-indigo-500/20", accent: "text-indigo-400" },
} as const;

type TimeOfDay = keyof typeof BRIEFING_THEMES;

function getTimeOfDay(): TimeOfDay {
  const hour = new Date().getHours();
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}

function BriefingCard({
  userId, briefing, briefingLoading, briefingError, queryClient,
}: {
  userId: string; briefing?: Briefing; briefingLoading: boolean; briefingError: boolean; queryClient: QueryClient;
}) {
  const [timeOfDay, setTimeOfDay] = useState<TimeOfDay>("morning");
  useEffect(() => {
    // Defer to the next frame to avoid hydration mismatch (server renders "morning").
    const raf = requestAnimationFrame(() => setTimeOfDay(getTimeOfDay()));
    return () => cancelAnimationFrame(raf);
  }, []);

  const theme = BRIEFING_THEMES[timeOfDay];
  const isWeekend = [0, 6].includes(new Date().getDay());

  return (
    <div className={`bg-gradient-to-r ${theme.gradient} border ${theme.border} rounded-2xl p-5 mb-6`}>
      <div className="flex items-start gap-4">
        <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center shrink-0 text-xl">
          {theme.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-semibold text-sm">
              {theme.label}
              {isWeekend && <span className="ml-2 text-xs font-normal text-muted-foreground">Weekend</span>}
            </h2>
            <button
              onClick={() => queryClient.invalidateQueries({ queryKey: ["briefing", userId] })}
              className={`inline-flex items-center gap-1.5 text-xs ${theme.accent} hover:opacity-80 transition-colors`}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
              Refresh
            </button>
          </div>
          {briefingLoading ? (
            <div className="space-y-2 animate-pulse">
              <div className="h-3 bg-amber-500/10 rounded w-3/4" />
              <div className="h-3 bg-amber-500/10 rounded w-1/2" />
              <div className="h-3 bg-amber-500/10 rounded w-5/6" />
              <p className="text-xs text-amber-400/60 mt-2">Generating briefing...</p>
            </div>
          ) : briefingError ? (
            <p className="text-xs text-muted-foreground">Unable to load briefing. Click Refresh to try again.</p>
          ) : briefing ? (
            <Markdown>{briefing.briefing}</Markdown>
          ) : (
            <p className="text-xs text-muted-foreground">No briefing available.</p>
          )}
        </div>
      </div>
    </div>
  );
}
