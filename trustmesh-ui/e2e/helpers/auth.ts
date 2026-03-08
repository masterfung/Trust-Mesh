import { Page } from "@playwright/test";

/**
 * Log into a TrustMesh pod via the /login page.
 * Sets localStorage.trustmesh_pod_url, selects the pod, fills credentials,
 * clicks Log In, and waits for the /{userId} dashboard redirect.
 *
 * Returns the userId extracted from the URL.
 */
export async function loginAs(
  page: Page,
  podUrl: string,
  username: string,
  password: string
): Promise<string> {
  await page.goto("/login");

  // Set pod URL in localStorage before React reads it so the select starts there.
  await page.evaluate(
    (url) => localStorage.setItem("trustmesh_pod_url", url),
    podUrl
  );

  // Reload so the page picks up the new localStorage value.
  await page.reload();

  // Select the pod in the dropdown.
  await page.locator("select").selectOption(podUrl);

  // Fill credentials.
  await page.locator('input[type="text"]').fill(username);
  await page.locator('input[type="password"]').fill(password);

  // Submit.
  await page.locator('button:has-text("Log In")').click();

  // Wait for dashboard redirect: /{uuid}/...
  await page.waitForURL(/\/[0-9a-f-]{36}/, { timeout: 20_000 });

  // Extract userId from URL path segment.
  const segments = new URL(page.url()).pathname.split("/").filter(Boolean);
  return segments[0];
}

/**
 * Log out by navigating to the sidebar logout button.
 * Waits for redirect to home.
 */
export async function logout(page: Page) {
  // Sidebar log-out button text.
  await page.locator('text=Log Out').click();
  await page.waitForURL("/", { timeout: 10_000 });
}
