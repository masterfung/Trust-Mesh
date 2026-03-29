/**
 * Catch-all API proxy route for production Cloud Run deployments.
 *
 * next.config.ts rewrites are compiled at build time, so TRUSTMESH_PROXY_POD
 * isn't available when the Docker image is built. This route handler reads the
 * env var at **runtime** and proxies all /api/* requests to the backend pod.
 *
 * /api/emergency-proxy is handled by its own route handler (takes priority).
 * Everything else matching /api/* lands here.
 */
import { NextRequest, NextResponse } from "next/server";

const POD_URL = (process.env.TRUSTMESH_PROXY_POD ?? "").replace(/\/$/, "");

async function proxy(req: NextRequest, path: string): Promise<NextResponse> {
  if (!POD_URL) {
    return NextResponse.json(
      { detail: "Backend pod not configured (TRUSTMESH_PROXY_POD unset)" },
      { status: 503 }
    );
  }

  const search = req.nextUrl.search ?? "";
  const target = `${POD_URL}/api/${path}${search}`;

  // Forward all original headers except host (avoids SNI mismatch)
  const forwardHeaders = new Headers();
  req.headers.forEach((value, key) => {
    if (key.toLowerCase() !== "host") {
      forwardHeaders.set(key, value);
    }
  });

  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  const upstream = await fetch(target, {
    method: req.method,
    headers: forwardHeaders,
    body: hasBody ? req.body : undefined,
    // @ts-expect-error -- Node.js fetch requires duplex for streaming bodies
    duplex: hasBody ? "half" : undefined,
    redirect: "manual",
    cache: "no-store",
  });

  // Forward all upstream response headers.
  // Set-Cookie MUST use append (not set) — merging multiple Set-Cookie headers
  // with commas breaks cookie parsing. Use getSetCookie() to get them as an array.
  const resHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() !== "set-cookie") {
      resHeaders.set(key, value);
    }
  });
  // Node.js 18+ / Next.js 15+: getSetCookie() returns each Set-Cookie as its own entry
  const setCookies: string[] =
    typeof (upstream.headers as { getSetCookie?: () => string[] }).getSetCookie === "function"
      ? (upstream.headers as { getSetCookie: () => string[] }).getSetCookie()
      : [];
  for (const cookie of setCookies) {
    resHeaders.append("set-cookie", cookie);
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: resHeaders,
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path.join("/"));
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path.join("/"));
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path.join("/"));
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path.join("/"));
}

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path.join("/"));
}

export async function OPTIONS(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path.join("/"));
}
