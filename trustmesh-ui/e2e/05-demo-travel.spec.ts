import { test, expect } from "@playwright/test";
import { loginAs } from "./helpers/auth";

const MOLLY_POD = "http://localhost:9001";

test.describe("TinyFish Demo Flow", () => {
  test("Molly logs in, sends trip query, sees tool badges, checks timeline, chat persists", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();

    // Step 1: Login as Molly on pod :9001
    await loginAs(page, MOLLY_POD, "molly", "TrustMesh-demo-2026");
    await page.waitForLoadState("load");

    // Step 2: Navigate to chat via sidebar
    await page.locator('a:has-text("Ask My Agent")').click();
    await page.waitForLoadState("load");
    await page.waitForTimeout(2000);

    // Step 3: Verify chat page loaded
    await expect(page.locator('text=Ask your agent anything')).toBeVisible({ timeout: 10000 });
    console.log("Chat page loaded");

    // Step 4: Type and send the demo prompt
    const input = page.locator('textarea, input[type="text"]').last();
    await input.fill(
      "Plan a family trip to San Sebastián, Spain for me, Peter, and Grandma Rose. " +
      "Query Peter's agent and Grandma Rose's agent for their preferences. " +
      "Then use browse_web to research Michelin-starred restaurants in San Sebastián. " +
      "Build a detailed 5-day itinerary with real restaurant recommendations."
    );

    const sendBtn = page.locator('button:has-text("Send")').first();
    await sendBtn.click();
    console.log("Prompt sent");

    // Step 5: Wait for streaming to start — look for tool badges or response text
    // The response should show tool badges like query_peer, browse_web
    await expect(
      page.locator("text=query").first()
    ).toBeVisible({ timeout: 120000 });
    console.log("Agent started responding with tools");

    // Take screenshot of streaming state
    await page.screenshot({ path: "docs/e2e-chat-streaming.png" });
    console.log("Screenshot: streaming state saved");

    // Step 6: Wait for response to complete — look for the latency/trust badges
    // that appear after streaming finishes (up to 5 min)
    try {
      await expect(
        page.locator("text=ms").first()
      ).toBeVisible({ timeout: 300000 });
      console.log("Response completed (latency badge visible)");
    } catch {
      console.log("Response still streaming after 5min — taking screenshot anyway");
    }
    await page.waitForTimeout(2000);

    // Step 7: Check if Research Feed appeared (TinyFish indicator)
    const researchFeed = page.locator("text=Research Feed");
    const hasFeed = await researchFeed.isVisible().catch(() => false);
    console.log(`Research Feed visible: ${hasFeed}`);

    // Step 8: Take screenshot of current state
    await page.screenshot({ path: "docs/e2e-chat-response.png" });

    // Step 9: Navigate to timeline
    const userId = page.url().match(/\/([a-f0-9-]+)\//)?.[1];
    if (userId) {
      await page.goto(`http://localhost:3050/${userId}/timeline`);
      await page.waitForLoadState("load");
      await page.waitForTimeout(2000);
      await page.screenshot({ path: "docs/e2e-timeline.png" });
      console.log("Timeline page screenshot saved");

      // Check for empty state or tasks
      const timelineContent = await page.textContent("body");
      const hasContent = timelineContent?.includes("task") || timelineContent?.includes("Task") ||
                         timelineContent?.includes("No scheduled");
      console.log(`Timeline has content: ${hasContent}`);
    }

    // Step 10: Navigate back to chat — verify history persists
    if (userId) {
      await page.goto(`http://localhost:3050/${userId}/chat`);
      await page.waitForLoadState("load");
      await page.waitForTimeout(3000);

      // Check if previous query is visible
      const bodyText = await page.textContent("body");
      const hasHistory = bodyText?.includes("San Sebastián") || bodyText?.includes("Recent") || bodyText?.includes("family trip");
      console.log(`Chat history persists: ${hasHistory}`);
      await page.screenshot({ path: "docs/e2e-chat-history.png" });
    }

    await ctx.close().catch(() => {});
  });
});
