/**
 * Direct pod API helpers — bypass the browser for server-side assertions.
 */

export interface PodFetchResult {
  status: number;
  body: Record<string, unknown>;
}

/** Fetch a path from a specific pod URL and return status + JSON body. */
export async function podFetch(
  podUrl: string,
  path: string,
  opts?: RequestInit
): Promise<PodFetchResult> {
  const url = `${podUrl}${path}`;
  const res = await fetch(url, opts);
  let body: Record<string, unknown> = {};
  try {
    body = await res.json();
  } catch {
    // non-JSON body — leave empty
  }
  return { status: res.status, body };
}

/** POST a JSON payload to a pod endpoint (no auth — public endpoints only). */
export async function podPost(
  podUrl: string,
  path: string,
  payload: Record<string, unknown>
): Promise<PodFetchResult> {
  return podFetch(podUrl, path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Lightweight health check — returns true if pod responds with 200. */
export async function isPodOnline(podUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${podUrl}/health`, { signal: AbortSignal.timeout(3_000) });
    return res.ok;
  } catch {
    return false;
  }
}
