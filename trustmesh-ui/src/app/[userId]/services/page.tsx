"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type ContextMode, type ServiceProvider, type RegistryPodAgent } from "@/lib/api";
import { useParams } from "next/navigation";
import Link from "next/link";

/** Map service industry to context. Healthcare spans both; home services are personal. */
function serviceMatchesContext(sp: ServiceProvider, activeContext: ContextMode): boolean {
  if (activeContext === "all") return true;
  const industry = sp.profile_data?.occupation?.industry?.toLowerCase() || "";
  // Healthcare services are relevant in both work and personal contexts
  if (industry.includes("healthcare") || industry.includes("medical")) return true;
  // Home services (cleaning, tutoring, handyman) are personal only
  if (activeContext === "work") return false;
  return true; // personal context shows everything
}

export default function ServicesPage() {
  const { userId } = useParams<{ userId: string }>();

  const { data: currentUser } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });
  const activeContext: ContextMode = (currentUser?.active_context as ContextMode) || "all";

  const { data: allServices, isLoading } = useQuery({
    queryKey: ["services"],
    queryFn: () => api.listServices(),
  });
  const services = allServices?.filter((sp) => serviceMatchesContext(sp, activeContext));

  const { data: registryData } = useQuery({
    queryKey: ["registryAgents"],
    queryFn: () => api.registryListAll(),
    // Registry is optional — don't fail if unavailable
    retry: false,
  });
  // Show org/government agents from registry that aren't already in local services
  const localNames = new Set(allServices?.map(s => s.display_name.toLowerCase()) ?? []);
  const registryAgents = (registryData?.agents ?? []).filter(
    (a: RegistryPodAgent) =>
      (a.entity_type === "organization" || a.entity_type === "government") &&
      !localNames.has(a.display_name.toLowerCase())
  );

  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold mb-1">Live Agents</h1>
        <p className="text-muted-foreground text-sm mb-3">
          These are live AI agents. Your agent can query them directly — just ask in chat.
        </p>
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-accent/5 border border-accent/15 w-fit">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent shrink-0">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <span className="text-xs text-accent/80">Try: <span className="font-medium">&quot;Ask Dr. Lee about appointment availability&quot;</span></span>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-card border border-card-border rounded-2xl p-6 animate-pulse">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-card-hover" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-card-hover rounded w-1/3" />
                  <div className="h-3 bg-card-hover rounded w-2/3" />
                  <div className="h-3 bg-card-hover rounded w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : services && services.length > 0 ? (
        <div className="space-y-4">
          {services.map((sp: ServiceProvider) => (
            <div
              key={sp.id}
              className="bg-card border border-card-border rounded-2xl p-6 hover:border-accent/20 transition-all"
            >
              <div className="flex items-start gap-4">
                {/* Avatar */}
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-white font-bold text-lg shrink-0">
                  {sp.display_name[0]}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h2 className="text-base font-semibold">{sp.display_name}</h2>
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20">
                      Service Provider
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mb-3">{sp.bio}</p>

                  {/* Skills */}
                  {sp.agent_card?.skills && sp.agent_card.skills.length > 0 && (
                    <div className="mb-3">
                      <p className="text-xs text-muted-foreground mb-1.5">Capabilities</p>
                      <div className="flex flex-wrap gap-1.5">
                        {sp.agent_card.skills.map((skill) => (
                          <span
                            key={skill.id}
                            className="inline-flex items-center px-2 py-1 rounded-lg text-xs font-medium bg-accent/10 text-accent/80 border border-accent/10"
                          >
                            {skill.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Profile data extras */}
                  {sp.profile_data?.occupation && (
                    <p className="text-xs text-muted-foreground">
                      <span className="text-foreground/60 font-medium">{sp.profile_data.occupation.title}</span>
                      {sp.profile_data.occupation.industry && (
                        <span> in {sp.profile_data.occupation.industry}</span>
                      )}
                    </p>
                  )}
                </div>

                {/* Actions */}
                <div className="shrink-0 flex flex-col gap-2">
                  <Link
                    href={`/${userId}/chat`}
                    className="px-4 py-2 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded-xl transition-all hover:shadow-lg hover:shadow-accent/20 text-center whitespace-nowrap"
                  >
                    Talk to Agent
                  </Link>
                  {sp.agent_card && (
                    <span className="text-[10px] text-muted-foreground text-center">
                      Live · A2A v{sp.agent_card.version}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-card border border-card-border rounded-2xl p-12 text-center">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground mx-auto mb-4">
            <path d="M20 7h-9"/><path d="M14 17H5"/>
            <circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>
          </svg>
          <p className="text-muted-foreground">No service providers available yet.</p>
          <p className="text-xs text-muted-foreground mt-1">Service providers will appear here once they join the mesh.</p>
        </div>
      )}

      {/* Registry agents section */}
      {registryAgents.length > 0 && (
        <div className="mt-8">
          <div className="flex items-center gap-2 mb-4">
            <h2 className="text-base font-semibold">More Live Agents on the Network</h2>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-500/10 text-green-400 border border-green-500/20">
              {registryAgents.length} discoverable
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {registryAgents.map((agent: RegistryPodAgent) => (
              <div key={agent.did} className="bg-card border border-card-border rounded-xl p-4 hover:border-accent/20 transition-all">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-400 to-purple-600 flex items-center justify-center text-white font-bold text-sm shrink-0">
                    {agent.display_name[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{agent.display_name}</p>
                    {agent.bio && <p className="text-xs text-muted-foreground truncate mt-0.5">{agent.bio}</p>}
                    <div className="flex items-center gap-1.5 mt-1.5">
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-500/10 text-violet-400 border border-violet-500/20">
                        {agent.entity_type}
                      </span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-500/10 text-green-400 border border-green-500/20">
                        live
                      </span>
                    </div>
                  </div>
                  <Link
                    href={`/${userId}/chat`}
                    className="shrink-0 px-3 py-1.5 text-xs font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded-lg transition-all"
                  >
                    Talk to Agent
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
