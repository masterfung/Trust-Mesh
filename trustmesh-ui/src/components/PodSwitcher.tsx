"use client";

import { useEffect, useState, useCallback } from "react";
import { getPodUrl, setPodUrl } from "@/lib/api";

interface PodEntry {
  key: string;
  port: number;
  name: string;
  type: "person" | "organization" | "government";
  online: boolean;
}

const PODS: Omit<PodEntry, "online">[] = [
  { key: "molly",               port: 8001, name: "Molly Johnson",            type: "person" },
  { key: "peter",               port: 8002, name: "Peter Johnson",            type: "person" },
  { key: "jane",                port: 8003, name: "Jane Johnson",             type: "person" },
  { key: "grandmarose",         port: 8004, name: "Grandma Rose",             type: "person" },
  { key: "dr_lee",              port: 8005, name: "Dr. Sarah Lee",            type: "person" },
  { key: "kyle",                port: 8006, name: "Kyle Rivera",              type: "person" },
  { key: "amy",                 port: 8007, name: "Amy Torres",               type: "person" },
  { key: "dorothy",             port: 8008, name: "Dorothy Park",             type: "person" },
  { key: "nurse_davis",         port: 8009, name: "Nurse Rachel Davis",       type: "person" },
  { key: "emt_johnson",         port: 8010, name: "EMT Mike Johnson",         type: "person" },
  { key: "sparkleclean",        port: 8011, name: "SparkleClean",             type: "organization" },
  { key: "riverside_hospital",  port: 8012, name: "Riverside Hospital",       type: "organization" },
  { key: "acetutor",            port: 8013, name: "AceTutor SAT Prep",        type: "organization" },
  { key: "riverside_gov",       port: 8014, name: "City of Riverside",        type: "government" },
  { key: "handypro",            port: 8015, name: "HandyPro",                 type: "organization" },
  { key: "riverside_ambulance", port: 8016, name: "Riverside Ambulance",      type: "organization" },
];

const TYPE_BADGE: Record<string, { label: string; className: string }> = {
  person:       { label: "P", className: "bg-blue-500/20 text-blue-400" },
  organization: { label: "O", className: "bg-amber-500/20 text-amber-400" },
  government:   { label: "G", className: "bg-emerald-500/20 text-emerald-400" },
};

export function PodSwitcher({ userName }: { userName?: string }) {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<string>("");
  const [statuses, setStatuses] = useState<Record<number, boolean>>({});

  useEffect(() => {
    setCurrent(getPodUrl());
  }, []);

  const checkStatuses = useCallback(async () => {
    const checks = PODS.map(async (pod) => {
      try {
        const r = await fetch(`http://localhost:${pod.port}/health`, {
          signal: AbortSignal.timeout(2000),
        });
        return { port: pod.port, online: r.ok };
      } catch {
        return { port: pod.port, online: false };
      }
    });
    const results = await Promise.all(checks);
    const map: Record<number, boolean> = {};
    for (const r of results) map[r.port] = r.online;
    setStatuses(map);
  }, []);

  useEffect(() => {
    if (open) checkStatuses();
  }, [open, checkStatuses]);

  const switchPod = (port: number) => {
    const url = `http://localhost:${port}`;
    setPodUrl(url);
    setCurrent(url);
    setOpen(false);
    window.location.reload();
  };

  const currentPort = current.match(/:(\d+)/)?.[1] || "8000";
  const currentPod = PODS.find(p => p.port === Number(currentPort));
  const isSinglePod = currentPort === "8000";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs bg-card-hover border border-card-border hover:border-accent/30 transition-colors"
      >
        <span className={`w-2 h-2 rounded-full ${isSinglePod ? "bg-accent" : statuses[Number(currentPort)] !== false ? "bg-green-400" : "bg-red-400"}`} />
        <span className="truncate font-medium">
          {isSinglePod
            ? `${userName ? `${userName}'s Pod` : "Single Pod"} (:8000)`
            : `${currentPod?.name || "Pod"} (:${currentPort})`}
        </span>
        <svg className={`w-3 h-3 ml-auto transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 bg-card border border-card-border rounded-lg shadow-xl max-h-80 overflow-y-auto">
          {/* Single-pod mode */}
          <button
            onClick={() => { setPodUrl("http://localhost:8000"); setCurrent("http://localhost:8000"); setOpen(false); window.location.reload(); }}
            className={`w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-card-hover transition-colors ${isSinglePod ? "bg-accent/10 text-accent" : ""}`}
          >
            <span className="w-2 h-2 rounded-full bg-accent" />
            <span className="font-medium">{userName ? `${userName}'s Pod` : "Single Pod"} (:8000)</span>
          </button>

          <div className="border-t border-card-border my-1" />

          <p className="px-3 py-1 text-[10px] text-muted-foreground uppercase tracking-wider">Multi-Pod Federation</p>
          {PODS.map((pod) => {
            const badge = TYPE_BADGE[pod.type];
            const isActive = current === `http://localhost:${pod.port}`;
            const online = statuses[pod.port];
            return (
              <button
                key={pod.key}
                onClick={() => switchPod(pod.port)}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-card-hover transition-colors ${isActive ? "bg-accent/10 text-accent" : ""}`}
              >
                <span className={`w-2 h-2 rounded-full ${online === true ? "bg-green-400" : online === false ? "bg-red-400" : "bg-gray-500"}`} />
                <span className={`w-4 h-4 rounded text-[9px] flex items-center justify-center font-bold ${badge.className}`}>
                  {badge.label}
                </span>
                <span className="truncate">{pod.name}</span>
                <span className="ml-auto text-muted-foreground">:{pod.port}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
