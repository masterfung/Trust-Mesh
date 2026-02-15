import { NextResponse } from "next/server";
import { getStats } from "@/lib/db";

export function GET() {
  const stats = getStats();
  return NextResponse.json({
    status: "ok",
    service: "trustmesh-registry",
    agent_count: stats.total,
  });
}
