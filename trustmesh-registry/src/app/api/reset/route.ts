import { NextRequest, NextResponse } from "next/server";
import { resetAll } from "@/lib/db";

export async function POST(request: NextRequest) {
  // Require X-Registry-Secret header for reset (reseed-only operation)
  const secret = request.headers.get("x-registry-secret");
  const expectedSecret = process.env.REGISTRY_SECRET;

  if (expectedSecret && secret !== expectedSecret) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 403 });
  }

  resetAll();
  return NextResponse.json({ status: "reset", message: "All agents cleared" });
}
