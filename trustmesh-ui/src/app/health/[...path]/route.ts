/**
 * Proxy /health/* requests to the backend pod.
 *
 * The pod exposes /health and /health/full at the root level (not under /api/).
 * The catch-all at /api/[...path] only covers /api/* paths, so we need a
 * separate handler for /health/*.
 */
import { NextRequest, NextResponse } from "next/server";

const POD_URL = (process.env.TRUSTMESH_PROXY_POD ?? "").replace(/\/$/, "");

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;

  if (!POD_URL) {
    return NextResponse.json(
      { detail: "Backend pod not configured (TRUSTMESH_PROXY_POD unset)" },
      { status: 503 }
    );
  }

  const search = req.nextUrl.search ?? "";
  const upstream = await fetch(`${POD_URL}/health/${path.join("/")}${search}`, {
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
