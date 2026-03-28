import { User, Building2, Landmark } from "lucide-react";

export const ENTITY_CONFIG: Record<
  string,
  { label: string; fullLabel: string; icon: typeof User; badge: string; accent: string; border: string; bg: string }
> = {
  person: {
    label: "Person",
    fullLabel: "Person",
    icon: User,
    badge: "bg-blue-500/10 text-blue-400 border-blue-500/25",
    accent: "text-blue-400",
    border: "border-l-blue-500/60",
    bg: "bg-blue-500/[0.02]",
  },
  organization: {
    label: "Org",
    fullLabel: "Organization",
    icon: Building2,
    badge: "bg-purple-500/10 text-purple-400 border-purple-500/25",
    accent: "text-purple-400",
    border: "border-l-purple-500/60",
    bg: "bg-purple-500/[0.02]",
  },
  government: {
    label: "Gov",
    fullLabel: "Government",
    icon: Landmark,
    badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
    accent: "text-emerald-400",
    border: "border-l-emerald-500/60",
    bg: "bg-emerald-500/[0.02]",
  },
};

interface EntityBadgeProps {
  entityType: string;
  size?: "sm" | "md";
}

export function EntityBadge({ entityType, size = "sm" }: EntityBadgeProps) {
  const config = ENTITY_CONFIG[entityType] || ENTITY_CONFIG.person;
  const Icon = config.icon;
  const textSize = size === "md" ? "text-[11px] px-2 py-1 gap-1.5" : "text-[10px] px-1.5 py-0.5 gap-1";
  const iconSize = size === "md" ? "size-3.5" : "size-3";
  return (
    <span className={`inline-flex items-center rounded-full border font-medium ${config.badge} ${textSize}`}>
      <Icon className={iconSize} />
      {config.fullLabel}
    </span>
  );
}
