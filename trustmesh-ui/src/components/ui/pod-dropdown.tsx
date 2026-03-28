"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check } from "lucide-react";
import { DEMO_PODS, type DemoPod } from "@/lib/pods";

interface PodDropdownProps {
  pods?: DemoPod[];
  value: string;
  onChange: (url: string) => void;
}

export function PodDropdown({ pods = DEMO_PODS, value, onChange }: PodDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const selected = pods.find((p) => p.url === value) ?? pods[0];

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm text-foreground focus:outline-none focus:border-accent/50 transition-colors hover:border-accent/30"
      >
        <span className="flex items-center gap-2">
          <span>{selected.label}</span>
          <span className="text-muted-foreground font-mono text-xs">{selected.sublabel}</span>
        </span>
        <ChevronDown
          size={14}
          className={`text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute z-50 top-full mt-1 left-0 right-0 bg-card border border-card-border rounded-xl shadow-2xl overflow-hidden max-h-64 overflow-y-auto">
          {pods.map((p) => (
            <button
              key={p.url}
              type="button"
              onClick={() => {
                onChange(p.url);
                setOpen(false);
              }}
              className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-left hover:bg-card-hover transition-colors"
            >
              <span className="flex items-center gap-2">
                <span className={value === p.url ? "text-accent font-medium" : "text-foreground"}>
                  {p.label}
                </span>
                <span className="text-muted-foreground font-mono text-xs">{p.sublabel}</span>
              </span>
              {value === p.url && <Check size={13} className="text-accent shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
