import { NextResponse } from "next/server";
import { getStats } from "@/lib/db";
import { signRegistryResponse, getRegistryDid } from "@/lib/registry-key";

export function GET() {
  const stats = getStats();
  const body = JSON.stringify({
    status: "ok",
    service: "trustmesh-registry",
    agent_count: stats.total,
    registry_did: getRegistryDid(),
  });
  const sigHeaders = signRegistryResponse(new TextEncoder().encode(body));
  return new NextResponse(body, {
    status: 200,
    headers: { "Content-Type": "application/json", ...sigHeaders },
  });
}
