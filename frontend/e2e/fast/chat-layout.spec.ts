import { test, expect } from "../fixtures";
import { ChatPage } from "../pages/chat";

// The playground's layout: the conversation first, and each option where
// it is used. No side panel and no bar above: the page starts with the
// conversation, and the row under the message field has the target, the
// tools (a button, chips, a popover) and three icon buttons; the rest is
// in a sheet.

const SERVERS = "/api/v1alpha1/mcp/servers";

test.describe("the layout of the playground", () => {
  const names = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"].map(
    (n) => `lay_${n}_${Math.random().toString(36).slice(2, 7)}`
  );
  const ids: string[] = [];

  test.beforeAll(async ({ request }) => {
    for (const name of names) {
      const created = await request.post(SERVERS, {
        data: { name, url: "https://mcp.example.com/mcp" },
      });
      ids.push((await created.json()).id);
    }
  });
  test.afterAll(async ({ request }) => {
    for (const id of ids) await request.delete(`${SERVERS}/${id}`);
  });

  test("tools are one button with chips and a searchable, grouped popover", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await expect(page.locator("aside")).toHaveCount(0);
    await expect(chat.toolsButton).toHaveText("Tools");

    await chat.openTools();
    // More than five entries: a search field, and groups. (Each worker
    // makes its own servers, so the search is for this worker's name.)
    await expect(chat.tools).toContainText("Available");
    await chat.tools
      .getByRole("textbox", { name: "Search tools" })
      .fill(names[2]);
    await expect(chat.tools.getByRole("switch")).toHaveCount(1);
    await chat.tools.getByRole("switch", { name: `Use ${names[2]}` }).click();
    await chat.tools.getByRole("textbox", { name: "Search tools" }).fill("");
    await chat.tools.getByRole("switch", { name: `Use ${names[0]}` }).click();
    await expect(chat.tools).toContainText("On");
    await chat.closeTools();

    // What is on shows next to the button, and one click turns it off.
    await expect(chat.toolsButton).toContainText("2");
    const chips = page.getByRole("list", { name: "Tools that are on" });
    await expect(chips).toContainText(names[0]);
    await expect(chips).toContainText(names[2]);
    await chips.getByRole("button", { name: `Turn off ${names[2]}` }).click();
    await expect(chips).not.toContainText(names[2]);
    await expect(chat.toolsButton).toContainText("1");
    await chips.getByRole("button", { name: `Turn off ${names[0]}` }).click();
    await expect(chips).toHaveCount(0);
  });

  test("rare settings are in a sheet, and the bar says when one is set", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    const changed = page.getByTestId("chat-settings-changed");
    await expect(changed).toHaveCount(0);
    // Nothing stands above the conversation: it is the first thing of
    // the page, and the target is in the row under the message field.
    const log = (await chat.conversation.boundingBox())!;
    const target = (await chat.targetSelect.boundingBox())!;
    const field = (await chat.input.boundingBox())!;
    expect(target.y).toBeGreaterThan(log.y + log.height);
    expect(target.y).toBeGreaterThan(field.y);

    await chat.openSettings();
    await chat.systemPrompt.fill("Be brief.");
    for (const label of [
      "Max tokens",
      "Compact automatically",
      "Ask before each tool call",
    ]) {
      await expect(chat.settings.getByLabel(label).first()).toBeVisible();
    }
    await chat.closeSettings();
    await expect(changed).toBeVisible();
    await expect(chat.settingsButton).toHaveAttribute(
      "title",
      "Settings (a system prompt is active)"
    );
    // Three icon buttons, each with its name.
    for (const name of ["View code", "Settings", "Clear conversation"]) {
      await expect(
        page.getByRole("button", { name, exact: true })
      ).toBeVisible();
    }

    // The setting is sent, although its field is not on the page now.
    await chat.send("system?");
    await expect(chat.assistantMessages.last()).toContainText(
      "System: Be brief."
    );
  });

  test("the conversation has the width of the page at a laptop size", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    const log = (await chat.conversation.boundingBox())!;
    expect(log.width).toBeGreaterThan(1000);
    // The whole page fits: the composer's row is not pushed out of view.
    await expect(chat.toolsButton).toBeInViewport();
    const scrolls = await page.evaluate(
      () => document.documentElement.scrollHeight > window.innerHeight + 1
    );
    expect(scrolls).toBe(false);
  });
});
