"use client";

import type { User, Connection, Network } from "@/lib/api";

const TYPE_BADGES: Record<string, { label: string; color: string }> = {
  organization: { label: "Org", color: "bg-amber-500/15 text-amber-400" },
  government: { label: "Gov", color: "bg-emerald-500/15 text-emerald-400" },
};

interface ProfilePreviewProps {
  user: User;
  connections?: Connection[];
  networks?: Network[];
  compact?: boolean;
}

function getMutualCounts(
  user: User,
  connections?: Connection[],
  networks?: Network[],
): { mutualConnections: number; sharedNetworks: number } {
  if (!connections && !networks) return { mutualConnections: 0, sharedNetworks: 0 };

  const myPeerIds = new Set(connections?.map((c) => c.peer?.id).filter(Boolean) ?? []);
  const mutualConnections = myPeerIds.has(user.id) ? 0 : 0; // can't compute without their connections
  // shared networks = networks where user is a member
  const sharedNetworks =
    networks?.filter((n) => n.members?.some((m) => m.id === user.id)).length ?? 0;

  return { mutualConnections, sharedNetworks };
}

export function ProfilePreview({ user, connections, networks, compact }: ProfilePreviewProps) {
  const profile = user.profile_data;
  const occupation = profile?.occupation;
  const skills = profile?.skills?.slice(0, 5) ?? [];
  const interests = profile?.interests?.slice(0, 3) ?? [];
  const typeBadge = TYPE_BADGES[user.user_type ?? ""];
  const { sharedNetworks } = getMutualCounts(user, connections, networks);

  if (compact) {
    return (
      <div className="flex items-center gap-2 min-w-0">
        <div className="w-8 h-8 rounded-lg bg-accent/15 flex items-center justify-center text-accent font-bold text-xs shrink-0">
          {user.display_name?.[0] || "?"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium truncate">{user.display_name}</span>
            {typeBadge && (
              <span className={`text-[9px] px-1 py-0.5 rounded font-semibold uppercase shrink-0 ${typeBadge.color}`}>
                {typeBadge.label}
              </span>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground truncate">
            @{user.username}
            {occupation?.title && <> &middot; {occupation.title}</>}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-card-hover/50 rounded-xl border border-card-border">
      <div className="flex items-start gap-3">
        <div className="w-11 h-11 rounded-xl bg-accent/15 flex items-center justify-center text-accent font-bold shrink-0">
          {user.display_name?.[0] || "?"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{user.display_name}</span>
            {typeBadge && (
              <span className={`text-[9px] px-1 py-0.5 rounded font-semibold uppercase ${typeBadge.color}`}>
                {typeBadge.label}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">@{user.username}</p>
          {user.bio && <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{user.bio}</p>}
        </div>
      </div>

      <div className="mt-3 space-y-1.5">
        {occupation?.title && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
            </svg>
            <span>
              {occupation.title}
              {occupation.industry && <> at {occupation.industry}</>}
            </span>
          </div>
        )}

        {skills.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground shrink-0">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
            {skills.map((s) => (
              <span key={s.name} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/15">
                {s.name}
              </span>
            ))}
          </div>
        )}

        {interests.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground shrink-0">
              <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
            {interests.map((i) => (
              <span key={i.name} className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400 border border-yellow-500/15">
                {i.name}
              </span>
            ))}
          </div>
        )}

        {sharedNetworks > 0 && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
            </svg>
            <span>{sharedNetworks} shared network{sharedNetworks !== 1 ? "s" : ""}</span>
          </div>
        )}
      </div>
    </div>
  );
}
