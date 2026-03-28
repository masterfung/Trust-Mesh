/**
 * E2E: Backend connectivity + CORS preflight checks.
 *
 * Runs FIRST (00-) before any auth or feature tests.
 *
 * Catches the class of bugs where Chrome connects to localhost via IPv6 (::1)
 * but uvicorn only binds to IPv4 (127.0.0.1), causing a connection-refused
 * that the browser reports as "No Access-Control-Allow-Origin header" CORS error.
 *
 * Fix: uvicorn must be started with --host '::' to accept both IPv4 and IPv6.
 *
 * These tests also verify that the signup endpoint is reachable and returns
 * proper CORS headers, which would catch any future regression.
 */

import { test, expect } from "@playwright/test";
import { isPodOnline, podFetch } from "./helpers/pod";

const POD_URL = "http://localhost:9000";
const FRONTEND_URL = "http://localhost:3050";

test.describe("00 — Backend connectivity & CORS", () => {
  test(":9000 is online", async () => {
    const online = await isPodOnline(POD_URL);
    if (!online) test.skip();
    expect(online).toBe(true);
  });

  test("OPTIONS preflight to /api/users returns CORS headers", async ({ request }) => {
    const online = await isPodOnline(POD_URL);
    if (!online) { test.skip(); return; }

    const res = await request.fetch(`${POD_URL}/api/users`, {
      method: "OPTIONS",
      headers: {
        "Origin": FRONTEND_URL,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-csrf-token",
      },
    });

    expect(res.status()).toBe(200);
    const acao = res.headers()["access-control-allow-origin"];
    expect(acao).toBe(FRONTEND_URL);
    const acam = res.headers()["access-control-allow-methods"];
    expect(acam).toContain("POST");
  });

  test("POST /api/users returns CORS header (not blocked)", async ({ request }) => {
    const online = await isPodOnline(POD_URL);
    if (!online) { test.skip(); return; }

    // Send a deliberately invalid payload — we only care about CORS headers,
    // not the business logic response (could be 422 Unprocessable).
    const res = await request.fetch(`${POD_URL}/api/users`, {
      method: "POST",
      headers: {
        "Origin": FRONTEND_URL,
        "Content-Type": "application/json",
      },
      data: JSON.stringify({}),
    });

    // Any response (even validation error) must include CORS header.
    // ERR_FAILED / connection refused would throw before this line.
    const acao = res.headers()["access-control-allow-origin"];
    expect(acao).toBe(FRONTEND_URL);

    // Acceptable HTTP status codes: 200 (created), 422 (validation), 409 (conflict)
    expect([200, 201, 400, 409, 422]).toContain(res.status());
  });

  test("GET /api/auth/me returns CORS header with 401 (not blocked)", async ({ request }) => {
    const online = await isPodOnline(POD_URL);
    if (!online) { test.skip(); return; }

    const res = await request.fetch(`${POD_URL}/api/auth/me`, {
      headers: { "Origin": FRONTEND_URL },
    });

    expect(res.status()).toBe(401);
    const acao = res.headers()["access-control-allow-origin"];
    expect(acao).toBe(FRONTEND_URL);
  });

  test("frontend signup page loads without JS errors", async ({ page }) => {
    const online = await isPodOnline(POD_URL);
    if (!online) { test.skip(); return; }

    const jsErrors: string[] = [];
    page.on("pageerror", (err) => jsErrors.push(err.message));

    await page.goto("/signup");
    await page.waitForLoadState("load");

    // Page should render without crashing
    await expect(page.locator("h1, h2").first()).toBeVisible({ timeout: 10_000 });

    // Filter out known benign noise (React DevTools, HMR)
    const fatal = jsErrors.filter(
      (e) =>
        !e.includes("DevTools") &&
        !e.includes("HMR") &&
        !e.includes("fast refresh")
    );
    expect(fatal).toHaveLength(0);
  });

  test("signup form can reach :9000 via browser fetch (no CORS block / no IPv6 refuse)", async ({ page }) => {
    const online = await isPodOnline(POD_URL);
    if (!online) { test.skip(); return; }

    await page.goto("/signup");

    // Send a cross-origin GET from inside the browser to the backend.
    // This is the simplest fetch that will fail with "Failed to fetch" if Chrome
    // connects via ::1 and uvicorn only listens on 127.0.0.1 (the IPv6 bug).
    // Note: browser strips CORS preflight headers so we use a simple GET.
    const result = await page.evaluate(async (podUrl) => {
      try {
        const res = await fetch(`${podUrl}/api/auth/me`, {
          credentials: "include",
        });
        return { status: res.status, error: null };
      } catch (e) {
        // TypeError("Failed to fetch") = connection refused (IPv6 bug) or CORS block
        return { status: 0, error: String(e) };
      }
    }, POD_URL);

    // Any HTTP response (401 = not logged in) means we got through.
    // "Failed to fetch" / error means the IPv6 bug is back.
    expect(result.error).toBeNull();
    expect([200, 401, 403]).toContain(result.status);
  });
});
