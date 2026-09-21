import { test, expect } from "../fixtures";
import { ChatPage } from "../pages/chat";

// The pages fit the screen they are on. The check that matters most is
// the cheapest one: the PAGE never scrolls sideways (a wide table scrolls
// inside its own wrapper). It was lost once without anybody seeing it:
// the full navigation needs about 1,190 px and showed from 768 px on, so
// every page was 420 px too wide on a tablet.

const PAGES = [
  "/",
  "/chat?target=inst-mock",
  "/mcp-servers",
  "/providers",
  "/usage",
  "/models/catalog",
  "/models/endpoints",
  "/models/registry",
  "/vector-databases/catalog",
  "/vector-databases/endpoints",
  "/notebooks",
  "/organization",
  "/audit",
  "/settings/tokens",
  "/develop",
];

const SCREENS = [
  { name: "a phone", width: 390, height: 844 },
  { name: "a tablet", width: 768, height: 1024 },
  { name: "a small laptop", width: 1024, height: 768 },
];

for (const screen of SCREENS) {
  test(`no page scrolls sideways on ${screen.name} (${screen.width} px)`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: screen.width, height: screen.height });
    for (const path of PAGES) {
      await page.goto(path);
      await page.getByRole("heading", { level: 1 }).first().waitFor();
      const extra = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth
      );
      expect(
        extra,
        `${path} is ${extra} px wider than the screen`
      ).toBeLessThanOrEqual(1);
    }
  });
}

test.describe("the navigation", () => {
  test("is a menu button below 1280 px, and the full bar from there on", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1279, height: 800 });
    await page.goto("/");
    const bar = page.getByRole("navigation", { name: "Main" });
    await expect(bar).toBeHidden();
    await page.getByRole("button", { name: /menu/i }).first().click();
    await expect(page.getByRole("link", { name: "Providers" })).toBeVisible();
    await page.keyboard.press("Escape");

    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(bar).toBeVisible();
    // On one line: the chat page counts on the header's height.
    const header = (await page.locator("header").first().boundingBox())!;
    expect(header.height).toBeLessThan(70);
  });
});

test.describe("the chat page fills the window", () => {
  for (const screen of [
    { width: 390, height: 844 },
    { width: 1280, height: 720 },
    { width: 1920, height: 1080 },
  ]) {
    test(`at ${screen.width} x ${screen.height}`, async ({ page }) => {
      await page.setViewportSize(screen);
      const chat = new ChatPage(page);
      await chat.open("inst-mock");
      await expect(chat.toolsButton).toBeInViewport();
      const geometry = await page.evaluate(() => {
        const footer = document
          .querySelector("footer")!
          .getBoundingClientRect();
        const row = document
          .querySelector('[role="combobox"][aria-label="Target"]')!
          .getBoundingClientRect();
        return {
          scrolls:
            document.documentElement.scrollHeight > window.innerHeight + 1,
          footerBottom: Math.round(footer.bottom),
          gap: Math.round(footer.top - row.bottom),
          window: window.innerHeight,
        };
      });
      // The page is exactly the window: nothing to scroll, the footer at
      // the bottom edge, and no unused band between the composer's row
      // and the footer (it was 85 px with a computed height).
      expect(geometry.scrolls).toBe(false);
      expect(geometry.footerBottom).toBe(geometry.window);
      expect(geometry.gap).toBeLessThan(64);

      // A new conversation starts from its middle: the target's name and
      // the starter prompts are centered in the log, not at its top.
      const log = (await chat.conversation.boundingBox())!;
      const first = (await chat.starterPrompts.first().boundingBox())!;
      const last = (await chat.starterPrompts.last().boundingBox())!;
      const middle = (first.y + last.y + last.height) / 2;
      expect(Math.abs(middle - (log.y + log.height / 2))).toBeLessThan(
        log.height * 0.12
      );
    });
  }
});
