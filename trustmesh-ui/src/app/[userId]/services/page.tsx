"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type ServiceProvider } from "@/lib/api";
import { useParams } from "next/navigation";
import Link from "next/link";

export default function ServicesPage() {
  const { userId } = useParams<{ userId: string }>();

  const { data: services, isLoading } = useQuery({
    queryKey: ["services"],
    queryFn: () => api.listServices(),
  });

  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-1">Service Providers</h1>
        <p className="text-muted-foreground text-sm">
          Discover trusted service providers in the mesh. Request quotes directly through your agent.
        </p>
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
                      <p className="text-xs text-muted mb-1.5">Capabilities</p>
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
                    className="px-4 py-2 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded-xl transition-all hover:shadow-lg hover:shadow-accent/20 text-center"
                  >
                    Request Quote
                  </Link>
                  {sp.agent_card && (
                    <span className="text-[10px] text-muted text-center">
                      A2A Protocol v{sp.agent_card.version}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-card border border-card-border rounded-2xl p-12 text-center">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-muted mx-auto mb-4">
            <path d="M20 7h-9"/><path d="M14 17H5"/>
            <circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>
          </svg>
          <p className="text-muted-foreground">No service providers available yet.</p>
          <p className="text-xs text-muted mt-1">Service providers will appear here once they join the mesh.</p>
        </div>
      )}
    </div>
  );
}
