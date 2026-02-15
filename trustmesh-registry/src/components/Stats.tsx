"use client";

import { Users, Building2, Landmark, Globe } from "lucide-react";

interface StatsProps {
  total: number;
  people: number;
  organizations: number;
  government: number;
}

export function Stats({ total, people, organizations, government }: StatsProps) {
  const items = [
    { label: "Total Agents", value: total, icon: Globe, color: "text-yellow-400" },
    { label: "People", value: people, icon: Users, color: "text-blue-400" },
    { label: "Organizations", value: organizations, icon: Building2, color: "text-purple-400" },
    { label: "Government", value: government, icon: Landmark, color: "text-emerald-400" },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-4 py-3"
        >
          <item.icon className={`size-5 ${item.color}`} />
          <div>
            <div className="text-2xl font-bold">{item.value}</div>
            <div className="text-xs text-muted-foreground">{item.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
