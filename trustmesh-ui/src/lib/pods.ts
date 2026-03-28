/**
 * Shared utilities for multi-pod demo environments.
 */

import { getPodUrl, type User } from "@/lib/api";

export interface DemoPod {
  label: string;
  sublabel: string;
  url: string;
}

export const DEMO_PODS: DemoPod[] = [
  { label: "Molly Johnson",      sublabel: ":9001", url: "http://localhost:9001" },
  { label: "Peter Johnson",      sublabel: ":9002", url: "http://localhost:9002" },
  { label: "Jane Johnson",       sublabel: ":9003", url: "http://localhost:9003" },
  { label: "Grandma Rose",       sublabel: ":9004", url: "http://localhost:9004" },
  { label: "Dr. Sarah Lee",      sublabel: ":9005", url: "http://localhost:9005" },
  { label: "Kyle Rivera",        sublabel: ":9006", url: "http://localhost:9006" },
  { label: "Amy Torres",         sublabel: ":9007", url: "http://localhost:9007" },
  { label: "Dorothy Park",       sublabel: ":9008", url: "http://localhost:9008" },
  { label: "Nurse Davis",        sublabel: ":9009", url: "http://localhost:9009" },
  { label: "EMT Mike",           sublabel: ":9010", url: "http://localhost:9010" },
  { label: "SparkleClean",       sublabel: ":9011", url: "http://localhost:9011" },
  { label: "Riverside Hospital", sublabel: ":9012", url: "http://localhost:9012" },
  { label: "AceTutor",           sublabel: ":9013", url: "http://localhost:9013" },
  { label: "City of Riverside",  sublabel: ":9014", url: "http://localhost:9014" },
  { label: "HandyPro",           sublabel: ":9015", url: "http://localhost:9015" },
  { label: "Dance Studio",       sublabel: ":9016", url: "http://localhost:9016" },
  { label: "Johnny Hung",        sublabel: ":9000", url: "http://localhost:9000" },
];

/** Ports used for live sibling-pod probing (smaller set for speed). */
export const SIBLING_PORTS = ["9001", "9002", "9003", "9004", "9005", "9006", "9007", "9008"];

/**
 * Fetch the primary owner of each sibling pod in parallel.
 * Returns User objects (with pod_url set) for pods that respond.
 * Skips the current pod.
 */
export async function fetchSiblingPodUsers(currentPodUrl?: string): Promise<User[]> {
  const base = (currentPodUrl ?? getPodUrl()).replace(/:\d+$/, "");
  const currentPort = (currentPodUrl ?? getPodUrl()).match(/:(\d+)/)?.[1] ?? "";

  const results = await Promise.all(
    SIBLING_PORTS.filter(p => p !== currentPort).map(async port => {
      const podUrl = `${base}:${port}`;
      try {
        const r = await fetch(`${podUrl}/api/pod`, { signal: AbortSignal.timeout(3000) });
        if (!r.ok) return null;
        const d = await r.json();
        const agent = d.agents?.[0];
        if (!agent?.owner_id) return null;
        return {
          id: agent.owner_id,
          username: agent.owner_username,
          display_name: agent.owner_display_name ?? d.pod_name,
          bio: d.pod_name ?? "",
          email: null,
          user_type: "person",
          is_discoverable: true,
          is_remote: true,
          pod_url: podUrl,
        } as User;
      } catch {
        return null;
      }
    })
  );
  return results.filter(Boolean) as User[];
}
