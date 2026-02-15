import { Badge } from "@/components/ui/badge";
import { User, Building2, Landmark } from "lucide-react";

const ENTITY_CONFIG: Record<string, { label: string; icon: typeof User; className: string }> = {
  person: {
    label: "Person",
    icon: User,
    className: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  },
  organization: {
    label: "Org",
    icon: Building2,
    className: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  },
  government: {
    label: "Gov",
    icon: Landmark,
    className: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  },
};

export function EntityBadge({ entityType }: { entityType: string }) {
  const config = ENTITY_CONFIG[entityType] || ENTITY_CONFIG.person;
  const Icon = config.icon;
  return (
    <Badge variant="outline" className={config.className}>
      <Icon className="size-3" />
      {config.label}
    </Badge>
  );
}
