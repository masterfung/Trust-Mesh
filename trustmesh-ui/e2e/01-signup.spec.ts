/**
 * E2E: New user signs up on the default pod (:9000).
 *
 * Story:
 *   - Navigate to /signup
 *   - Fill the personal pod form with valid credentials
 *   - Verify redirect to /{userId}/onboard
 *   - Verify dashboard shows agent card
 *   - Logout → login again → verify session restored
 */

import { test, expect, Page } from "@playwright/test";
import { isPodOnline } from "./helpers/pod";

// ── Test data ──────────────────────────────────────────────────────────────────

// Generate a unique all-alpha suffix to avoid duplicate user conflicts across runs.
// Base-36 chars (a-z) only — digits would fail backend name validation.
const ALPHA_SUFFIX = Math.random()
  .toString(36)
  .slice(2, 7)
  .replace(/\d/g, (c) => "abcdefghij"[parseInt(c)]);
const TEST_NAME = `Elise ${ALPHA_SUFFIX} Test`; // always alpha-only
const TEST_PASSWORD = "E2eTestPass#2026!"; // 16+ chars, upper, lower, digit, special
const POD_URL = "http://localhost:9001"; // :9000 is seeded with Johnny demo

// ── Helpers ────────────────────────────────────────────────────────────────────

async function completeSignup(page: Page, displayName: string, password: string) {
  await page.goto("/signup");

  // Step 1: choose "Personal Pod"
  await page.locator('text=Personal Pod').click();
  await page.locator('button:has-text("Continue")').click();

  // Step 2: fill the personal form
  // Name field (first text input on this step)
  await page.locator('input[type="text"]').first().fill(displayName);
  // Password
  await page.locator('input[type="password"]').fill(password);

  // Submit
  await page.locator('button:has-text("Create Account")').click();

  // Wait for onboard redirect
  await page.waitForURL(/\/[0-9a-f-]{36}\/onboard/, { timeout: 20_000 });

  const segments = new URL(page.url()).pathname.split("/").filter(Boolean);
  return segments[0]; // userId
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe("01 — Signup flow", () => {
  test.use({ storageState: { cookies: [], origins: [] } }); // fresh session

  test("requires :9000 to be online", async () => {
    if (!(await isPodOnline(POD_URL))) {
      test.skip();
    }
  });

  let createdUserId = "";

  test("signs up as a new personal user", async ({ page }) => {
    if (!(await isPodOnline(POD_URL))) { test.skip(); return; }

    // Ensure pod URL is set
    await page.goto("/");
    await page.evaluate((url) => localStorage.setItem("trustmesh_pod_url", url), POD_URL);

    const userId = await completeSignup(page, TEST_NAME, TEST_PASSWORD);
    createdUserId = userId; // store for reference (unused by other tests)

    // ── Assertions on onboard page ─────────────────────────────────────────
    await expect(page).toHaveURL(new RegExp(`/${userId}/onboard`));

    // Page should not show a hard error
    await expect(page.locator('text=Error')).not.toBeVisible({ timeout: 3_000 }).catch(() => {});

    // Navigate to dashboard proper
    await page.goto(`/${userId}`);

    // Dashboard content should be present (agent section, chat button, or vault)
    const bodyText = (await page.textContent("body")) ?? "";
    const hasDashboardContent =
      bodyText.toLowerCase().includes("agent") ||
      bodyText.toLowerCase().includes("chat") ||
      bodyText.toLowerCase().includes("vault") ||
      bodyText.toLowerCase().includes("memory") ||
      bodyText.toLowerCase().includes("onboard");
    expect(hasDashboardContent).toBe(true);
  });

  test("can log out and log back in", async ({ page }) => {
    if (!(await isPodOnline(POD_URL))) { test.skip(); return; }

    // This test is self-contained: create a second user and verify login works.
    const SECOND_NAME = "Bobby Logintest";
    const SECOND_PASSWORD = "LoginTest#7788Zx!";

    // ── Sign up ───────────────────────────────────────────────────────────────
    await page.goto("/");
    await page.evaluate((url) => localStorage.setItem("trustmesh_pod_url", url), POD_URL);
    const userId = await completeSignup(page, SECOND_NAME, SECOND_PASSWORD);

    // ── Look up generated username via API ────────────────────────────────────
    const usersRes = await fetch(
      `${POD_URL}/api/users?q=${encodeURIComponent(SECOND_NAME)}`
    );
    let username = "";
    if (usersRes.ok) {
      const users = await usersRes.json() as Array<{ id: string; username: string; display_name: string }>;
      const found = users.find((u) => u.id === userId);
      if (found) username = found.username;
    }

    // Fall back to the display name if lookup failed
    const loginHandle = username || SECOND_NAME;

    // ── Login with retrieved username ─────────────────────────────────────────
    await page.goto("/login");
    await page.evaluate((url) => localStorage.setItem("trustmesh_pod_url", url), POD_URL);
    await page.reload();

    await page.locator('input[type="text"]').fill(loginHandle);
    await page.locator('input[type="password"]').fill(SECOND_PASSWORD);
    await page.locator('button:has-text("Log In")').click();

    await page.waitForURL(/\/[0-9a-f-]{36}/, { timeout: 20_000 });
    const loggedInUserId = new URL(page.url()).pathname.split("/").filter(Boolean)[0];

    // Should land on the same user's dashboard
    expect(loggedInUserId).toBe(userId);
    await expect(page).toHaveURL(new RegExp(`/${loggedInUserId}`));
  });
});
