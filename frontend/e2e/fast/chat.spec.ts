import { test, expect } from "../fixtures";
import { ChatPage } from "../pages/chat";

// The TEST_MODE backend answers chat with AIOPS_CHAT_MOCK (playwright.config),
// so only the instance list is stubbed.
const INSTANCE_ID = "11111111-2222-4333-8444-555555555555";
const INSTANCE = {
  id: INSTANCE_ID,
  model: {
    id: "22222222-2222-4333-8444-555555555555",
    name: "Qwen3 0.6B",
    modelId: "qwen3:0.6b",
    description: "",
    category: "llm",
    subcategory: "text generation",
    size: 1,
    countAdapters: 0,
  },
  engine: { id: "33333333-2222-4333-8444-555555555555", name: "Ollama" },
  host: "",
  endpoint: "https://inf-55555555.127.0.0.1.nip.io",
  healthEndpoint: "",
  metricsEndpoint: "",
  ready: true,
  status: "Running",
  config: {
    id: "c",
    lora_adapters: [],
    env_vars: {},
    args: {},
    enable_tracing: false,
  },
};

test.describe("chat page", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: [INSTANCE] })
    );
  });

  test("streams an answer, keeps it across reloads, and clears it", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open();
    await chat.selectTarget(/Qwen3 0.6B/);
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

  test("preselects the instance from the query string", async ({ page }) => {
    const chat = new ChatPage(page);
    await chat.open(INSTANCE_ID);
    await expect(chat.targetSelect).toContainText("Qwen3 0.6B");
    await expect(chat.sendButton).toBeDisabled();
    await chat.input.fill("ping");
    await expect(chat.sendButton).toBeEnabled();
  });

  test("shows an empty state without running instances", async ({ page }) => {
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
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
