/**
 * Proxy all /api/public-registry/* requests to the TrustMesh registry service.
 *
 * TRUSTMESH_REGISTRY_URL is a Cloud Run runtime env var — not available at
 * build time — so this route handler reads it at request time instead of
 * relying on next.config.ts rewrites or NEXT_PUBLIC_* baked values.
 */
import { NextRequest, NextResponse } from "next/server";

const REGISTRY_URL = (process.env.TRUSTMESH_REGISTRY_URL ?? "").replace(/\/$/, "");

async function proxy(req: NextRequest, path: string): Promise<NextResponse> {
  if (!REGISTRY_URL) {
    return NextResponse.json(
      { detail: "Registry not configured (TRUSTMESH_REGISTRY_URL unset)" },
      { status: 503 }
    );
  }

  const search = req.nextUrl.search ?? "";
  const target = `${REGISTRY_URL}/api/${path}${search}`;

  const upstream = await fetch(target, {
    method: req.method,
    cache: "no-store",
  });

  const resHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    resHeaders.set(key, value);
  });

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: resHeaders,
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path.join("/"));
}
