import { lookupAgent } from "@/lib/db";
import { notFound } from "next/navigation";
import { AgentDetailClient } from "./agent-detail";

export const dynamic = "force-dynamic";

export default async function AgentDetailPage({
  params,
}: {
  params: Promise<{ did: string }>;
}) {
  const { did } = await params;
  const decoded = decodeURIComponent(did);
  const agent = lookupAgent(decoded);

  if (!agent) notFound();

  return <AgentDetailClient agent={agent} />;
}
