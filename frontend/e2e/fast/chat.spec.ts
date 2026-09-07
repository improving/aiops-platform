import { test, expect } from "../fixtures";
import { ChatPage } from "../pages/chat";

// The TEST_MODE backend runs with AIOPS_CHAT_MOCK (playwright.config), which
// serves one target "inst-mock" ("Mock model · Mock") and echoes chat with
// "You said: <last user message>" without any real instance.

test.describe("chat page", () => {
  test("streams an answer, keeps it across reloads, and clears it", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open();
    await chat.selectTarget(/Mock model/);
    await chat.send("hello there");
    await expect(chat.messages).toHaveCount(2);
    await expect(chat.assistantMessages.last()).toContainText(
      "You said: hello there"
    );

    await page.reload();
    await expect(chat.assistantMessages.last()).toContainText(
      "You said: hello there"
    );

    await chat.clearButton.click();
    await expect(chat.messages).toHaveCount(0);
  });

  test("a long conversation scrolls inside the log, not the page", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    // Seed a history long enough to overflow the log box.
    await page.evaluate(() => {
      const turns = Array.from({ length: 40 }, (_, i) => [
        {
          id: `u${i}`,
          role: "user",
          parts: [{ type: "text", text: `question number ${i}` }],
        },
        {
          id: `a${i}`,
          role: "assistant",
          parts: [{ type: "text", text: `answer number ${i}` }],
        },
      ]).flat();
      localStorage.setItem("aiops.chat.dev.inst-mock", JSON.stringify(turns));
    });
    await page.reload();
    await expect(chat.messages).toHaveCount(80);

    // The log itself is the scroller: its content is taller than its box.
    const box = await chat.conversation.evaluate((el) => ({
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      overflowY: getComputedStyle(el).overflowY,
    }));
    expect(box.overflowY).toBe("auto");
    expect(box.scrollHeight).toBeGreaterThan(box.clientHeight);

    // The composer stays reachable without scrolling the page.
    await expect(chat.input).toBeInViewport();
    const pageScrolls = await page.evaluate(
      () =>
        document.documentElement.scrollHeight >
        document.documentElement.clientHeight + 4
    );
    expect(pageScrolls).toBe(false);

    // It opens pinned to the newest message.
    const atBottom = await chat.conversation.evaluate(
      (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 80
    );
    expect(atBottom).toBe(true);
  });

  test("preselects the target from the query string", async ({ page }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await expect(chat.targetSelect).toContainText("Mock model");
    await expect(chat.sendButton).toBeDisabled();
    await chat.input.fill("ping");
    await expect(chat.sendButton).toBeEnabled();
  });

  test("shows an empty state without running instances", async ({ page }) => {
    await page.route("**/api/v1alpha1/chat/targets", (route) =>
      route.fulfill({ json: [] })
    );
    const chat = new ChatPage(page);
    await chat.open();
    await expect(chat.emptyState).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Model catalog" })
    ).toHaveAttribute("href", "/models/catalog");
  });
});
