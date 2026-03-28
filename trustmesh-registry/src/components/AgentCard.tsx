"use client";

import Link from "next/link";
import { EntityBadge, ENTITY_CONFIG } from "@/components/EntityBadge";
import { ExternalLink, Fingerprint } from "lucide-react";

interface AgentCardProps {
  did: string;
  name: string;
  display_name: string;
  username: string;
  entity_type: string;
  bio: string;
  capabilities: string[];
  pod_url: string;
}

function avatarInitial(name: string): string {
  return (name || "?").charAt(0).toUpperCase();
}

function avatarColor(entityType: string): string {
  switch (entityType) {
    case "organization": return "bg-purple-500/20 text-purple-400 border-purple-500/30";
    case "government": return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    default: return "bg-blue-500/20 text-blue-400 border-blue-500/30";
  }
}

function truncateDid(did: string): string {
  if (did.length <= 24) return did;
  return `${did.slice(0, 14)}...${did.slice(-6)}`;
}

function shortenPodUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.host;
  } catch {
    return url;
  }
}

export function AgentCard({
  did,
  name,
  display_name,
  username,
  entity_type,
  bio,
  capabilities,
  pod_url,
}: AgentCardProps) {
  const displayLabel = display_name || name;
  const config = ENTITY_CONFIG[entity_type] || ENTITY_CONFIG.person;

  return (
    <Link href={`/agents/${encodeURIComponent(did)}`}>
      <div
        className={`group h-full cursor-pointer rounded-xl border border-l-4 ${config.border} border-white/[0.06] ${config.bg} p-4 transition-all hover:border-yellow-400/30 hover:shadow-[0_0_20px_rgba(254,220,37,0.05)]`}
      >
        {/* Entity type label — prominent at top */}
        <div className="flex items-center justify-between mb-3">
          <EntityBadge entityType={entity_type} size="md" />
          <span className={`text-[10px] font-mono ${config.accent} opacity-60`}>live</span>
        </div>

        {/* Avatar + Name */}
        <div className="flex items-center gap-3 mb-3">
          <div
            className={`flex size-10 shrink-0 items-center justify-center rounded-full border text-base font-bold ${avatarColor(entity_type)}`}
          >
            {avatarInitial(displayLabel)}
          </div>
          <div className="min-w-0 flex-1">
            <span className="font-semibold text-sm block truncate">{displayLabel}</span>
            {username && (
              <p className="text-xs text-muted-foreground truncate">@{username}</p>
            )}
          </div>
        </div>

        {/* Bio */}
        {bio && (
          <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">{bio}</p>
        )}

        {/* Capabilities */}
        {capabilities.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {capabilities.slice(0, 3).map((cap) => (
              <span key={cap} className="inline-flex items-center rounded-md bg-white/[0.05] border border-white/[0.06] px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {cap}
              </span>
            ))}
            {capabilities.length > 3 && (
              <span className="inline-flex items-center rounded-md bg-white/[0.05] border border-white/[0.06] px-1.5 py-0.5 text-[10px] text-muted-foreground">
                +{capabilities.length - 3}
              </span>
            )}
          </div>
        )}

        {/* Footer: DID + Pod */}
        <div className="flex items-center gap-3 pt-2 border-t border-white/[0.04] text-[11px] text-muted-foreground/70">
          <span className="flex items-center gap-1 truncate font-mono">
            <Fingerprint className="size-3 shrink-0" />
            {truncateDid(did)}
          </span>
          <span className="flex items-center gap-1 truncate ml-auto">
            <ExternalLink className="size-3 shrink-0" />
            {shortenPodUrl(pod_url)}
          </span>
        </div>
      </div>
    </Link>
  );
}
