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
