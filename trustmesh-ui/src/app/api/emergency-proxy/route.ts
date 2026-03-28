import { NextRequest, NextResponse } from "next/server";

const DEFAULT_POD_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000";

/** Block SSRF: reject non-http(s) schemes, cloud metadata IPs, and private ranges.
 *  Localhost is allowed — in dev the Next.js server proxies to pods on the same machine. */
function validatePodUrl(raw: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  const h = parsed.hostname;
  // Cloud metadata endpoints
  if (
    h === "169.254.169.254" ||
    h === "metadata.google.internal" ||
    h === "100.100.100.200"
  )
    return null;
  // Private IP ranges (non-localhost) — localhost is intentionally allowed for dev
  if (/^10\./.test(h)) return null;
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(h)) return null;
  if (/^192\.168\./.test(h)) return null;
  return parsed.origin;
}

/**
 * Server-side proxy for emergency QR scans and responder alerts.
 *
 * GET  /api/emergency-proxy?t=TOKEN&p=USERNAME[&pod=...] → scan QR data
 * POST /api/emergency-proxy  body: { t, p, message, pod? }  → send family alert
 *
 * The phone browser can't reach localhost:9004 directly, but the Next.js server
 * running on the same machine CAN. This proxy forwards the request server-side
 * so a single cloudflare/ngrok tunnel on port 3050 is all that's needed for demos.
 */
export async function POST(req: NextRequest) {
  let body: Record<string, string>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const token = body.t;
  const patient = body.p;
  const message = body.message;

  if (!token || !patient || !message) {
    return NextResponse.json({ detail: "Missing t, p, or message" }, { status: 400 });
  }
  if (token.length > 4096 || patient.length > 50 || message.length > 500) {
    return NextResponse.json({ detail: "Invalid parameters" }, { status: 400 });
  }

  const podUrl = validatePodUrl(body.pod || DEFAULT_POD_URL);
  if (!podUrl) {
    return NextResponse.json({ detail: "Invalid pod URL" }, { status: 400 });
  }

  const target = `${podUrl}/api/emergency/qr/alert`;
  try {
    const resp = await fetch(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ t: token, p: patient, message }),
      cache: "no-store",
    });
    const resBody = await resp.json();
    return NextResponse.json(resBody, { status: resp.status });
  } catch {
    return NextResponse.json({ detail: "Pod unreachable — is the backend running?" }, { status: 503 });
  }
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const token = searchParams.get("t");
  const patient = searchParams.get("p");

  if (!token || !patient) {
    return NextResponse.json({ detail: "Missing t or p parameter" }, { status: 400 });
  }

  if (token.length > 4096 || patient.length > 50) {
    return NextResponse.json({ detail: "Invalid parameters" }, { status: 400 });
  }

  const podUrl = validatePodUrl(searchParams.get("pod") || DEFAULT_POD_URL);
  if (!podUrl) {
    return NextResponse.json({ detail: "Invalid pod URL" }, { status: 400 });
  }

  const target = `${podUrl}/api/emergency/qr?t=${encodeURIComponent(token)}&p=${encodeURIComponent(patient)}`;

  try {
    const resp = await fetch(target, { cache: "no-store" });
    const body = await resp.json();
    return NextResponse.json(body, { status: resp.status });
  } catch {
    return NextResponse.json({ detail: "Pod unreachable — is the backend running?" }, { status: 503 });
  }
}
