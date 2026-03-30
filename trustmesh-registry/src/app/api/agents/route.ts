import { NextRequest, NextResponse } from "next/server";
import { listAgents } from "@/lib/db";
import { signRegistryResponse } from "@/lib/registry-key";

export function GET(request: NextRequest) {
  const entityType = request.nextUrl.searchParams.get("entity_type") || undefined;
  const agents = listAgents(entityType);
  const body = JSON.stringify({ agents, count: agents.length });
  const sigHeaders = signRegistryResponse(new TextEncoder().encode(body));
  return new NextResponse(body, {
    status: 200,
    headers: { "Content-Type": "application/json", ...sigHeaders },
  });
}
