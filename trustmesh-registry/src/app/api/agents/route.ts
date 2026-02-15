import { NextRequest, NextResponse } from "next/server";
import { listAgents } from "@/lib/db";

export function GET(request: NextRequest) {
  const entityType = request.nextUrl.searchParams.get("entity_type") || undefined;
  const agents = listAgents(entityType);
  return NextResponse.json({ agents, count: agents.length });
}
