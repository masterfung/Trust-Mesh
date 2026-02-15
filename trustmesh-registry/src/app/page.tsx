import { listAgents, getStats } from "@/lib/db";
import { RegistryHome } from "./registry-home";

export const dynamic = "force-dynamic";

export default function HomePage() {
  const agents = listAgents();
  const stats = getStats();
  return <RegistryHome initialAgents={agents} initialStats={stats} />;
}
