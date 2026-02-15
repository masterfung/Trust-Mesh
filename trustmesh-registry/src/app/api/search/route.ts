import { NextRequest, NextResponse } from "next/server";
import { searchAgents } from "@/lib/db";

export function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get("q") || "";
  const entityType = request.nextUrl.searchParams.get("entity_type") || undefined;
  const results = searchAgents(q, entityType);
  return NextResponse.json({ query: q, results, count: results.length });
}
