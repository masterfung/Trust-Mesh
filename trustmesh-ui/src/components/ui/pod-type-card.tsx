import { type ReactNode } from "react";

interface PodTypeCardProps {
  selected: boolean;
  onClick: () => void;
  icon: ReactNode;
  title: string;
  description: string;
  badge?: string;
}

export function PodTypeCard({ selected, onClick, icon, title, description, badge }: PodTypeCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative flex flex-col gap-3 p-4 rounded-2xl border text-left transition-all w-full ${
        selected
          ? "border-accent bg-accent/10 ring-1 ring-accent/30"
          : "border-card-border bg-card hover:border-accent/40 hover:bg-accent/5"
      }`}
    >
      {badge && (
        <span className="absolute top-3 right-3 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-accent/15 text-accent">
          {badge}
        </span>
      )}
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${selected ? "bg-accent/20" : "bg-muted/10"}`}>
        {icon}
      </div>
      <div>
        <p className={`text-sm font-semibold ${selected ? "text-accent" : "text-foreground"}`}>{title}</p>
        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{description}</p>
      </div>
      <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ml-auto mt-auto ${
        selected ? "border-accent bg-accent" : "border-muted-foreground/30"
      }`}>
        {selected && (
          <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
      </div>
    </button>
  );
}
