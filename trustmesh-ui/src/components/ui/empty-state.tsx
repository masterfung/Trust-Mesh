import { cn } from "@/lib/utils";

interface EmptyStateProps {
  /** SVG icon element to display above the title. */
  icon?: React.ReactNode;
  title: string;
  description?: string;
  /** Optional call-to-action rendered below the description. */
  action?: React.ReactNode;
  className?: string;
  /** Use "card" to render inside a bordered card background (vault style). */
  variant?: "default" | "card";
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  variant = "default",
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center py-12",
        variant === "card" && "bg-card border border-card-border rounded-2xl px-6",
        className
      )}
    >
      {icon && <div className="text-muted-foreground mb-3">{icon}</div>}
      <p className={cn("font-medium text-muted-foreground", description ? "text-sm" : "text-sm")}>
        {title}
      </p>
      {description && (
        <p className="text-sm text-muted-foreground mt-1">{description}</p>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
