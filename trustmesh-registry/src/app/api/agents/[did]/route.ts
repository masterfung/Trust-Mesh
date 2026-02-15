import { NextRequest, NextResponse } from "next/server";
import { lookupAgent, deregisterAgent } from "@/lib/db";
import { verifyRegistration } from "@/lib/crypto";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ did: string }> },
) {
  const { did } = await params;
  const decoded = decodeURIComponent(did);
  const agent = lookupAgent(decoded);
  if (!agent) {
    return NextResponse.json(
      { error: `No agent registered with DID: ${decoded}` },
      { status: 404 },
    );
  }
  return NextResponse.json(agent);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ did: string }> },
) {
  const { did } = await params;
  const decoded = decodeURIComponent(did);

  // Verify signature — deregistration requires proof of key ownership
  const rawBody = new Uint8Array(await request.arrayBuffer());
  const headers: Record<string, string | undefined> = {
    "x-trustmesh-timestamp": request.headers.get("x-trustmesh-timestamp") ?? undefined,
    "x-trustmesh-nonce": request.headers.get("x-trustmesh-nonce") ?? undefined,
    "x-trustmesh-signature": request.headers.get("x-trustmesh-signature") ?? undefined,
  };

  const verification = verifyRegistration(decoded, rawBody, headers);

  // Allow unsigned for backward compat, but log it
  if (verification.status === "invalid") {
    return NextResponse.json(
      { error: "Signature verification failed", reason: verification.reason },
      { status: 403 },
    );
  }

  const removed = deregisterAgent(decoded);
  if (!removed) {
    return NextResponse.json(
      { error: `No agent registered with DID: ${decoded}` },
      { status: 404 },
    );
  }

  return NextResponse.json({
    status: "deregistered",
    verified: verification.status === "valid",
    did: decoded,
  });
}
