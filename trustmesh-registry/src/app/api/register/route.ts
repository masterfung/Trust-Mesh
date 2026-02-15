import { NextRequest, NextResponse } from "next/server";
import { registerAgent } from "@/lib/db";
import { verifyRegistration } from "@/lib/crypto";

export async function POST(request: NextRequest) {
  let body: Record<string, unknown>;
  let rawBody: Uint8Array;
  try {
    rawBody = new Uint8Array(await request.arrayBuffer());
    body = JSON.parse(new TextDecoder().decode(rawBody));
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const did = body.did as string;
  const name = body.name as string;
  const pod_url = body.pod_url as string;

  if (!did || !name || !pod_url) {
    return NextResponse.json(
      { error: "Missing required fields: did, name, pod_url" },
      { status: 400 },
    );
  }

  // Verify signature if present (unsigned requests accepted as "unverified")
  const headers: Record<string, string | undefined> = {
    "x-trustmesh-timestamp": request.headers.get("x-trustmesh-timestamp") ?? undefined,
    "x-trustmesh-nonce": request.headers.get("x-trustmesh-nonce") ?? undefined,
    "x-trustmesh-signature": request.headers.get("x-trustmesh-signature") ?? undefined,
  };

  const verification = verifyRegistration(did, rawBody, headers);
  if (verification.status === "invalid") {
    return NextResponse.json(
      { error: "Signature verification failed", reason: verification.reason },
      { status: 403 },
    );
  }

  const agent = registerAgent({
    did,
    name,
    pod_url,
    entity_type: (body.entity_type as string) || "person",
    capabilities: (body.capabilities as string[]) || [],
    username: (body.username as string) || "",
    display_name: (body.display_name as string) || "",
    bio: (body.bio as string) || "",
  });

  return NextResponse.json({
    status: "registered",
    verified: verification.status === "valid",
    did: agent.did,
    total_agents: agent ? 1 : 0,
  });
}
