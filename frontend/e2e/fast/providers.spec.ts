import { test, expect, shortId } from "../fixtures";
import { ProvidersPage } from "../pages/providers";

// The TEST_MODE backend runs with AIOPS_CHAT_MOCK and AIOPS_SECRET_STORE=memory
// (playwright.config.ts): discovery returns two canned models ("mock-chat-1"
// chat, "mock-embed-1" embedding) for every kind, registration never calls a
// real LiteLLM, and the provider's key lives in an in-process dict.

test.describe("providers page", () => {
  test("add, disable, remove a model and delete a hosted provider", async ({
    page,
    api,
  }) => {
    const providers = new ProvidersPage(page);
    await providers.open();

    const name = `openai-${shortId()}`;
    await providers.addProvider({
      kind: "openai",
      name,
      apiKey: "sk-test",
      models: ["mock-chat-1", "mock-embed-1"],
    });

    await expect(providers.providerRow(name)).toBeVisible();
    await providers.expandButton(name).click();
    await expect(providers.modelCell("mock-chat-1")).toBeVisible();
    await expect(providers.modelCell("mock-embed-1")).toBeVisible();

    const created = (await api.providers()).find((p) => p.name === name);
    expect(created, "the provider was persisted").toBeTruthy();

    // Disable: its models drop out of the chat targets (backend/api/chat.py
    // list_hosted_targets only lists enabled providers).
    await providers.enabledSwitch(name).click();
    await expect
      .poll(async () =>
        (await api.chatTargets()).some((t) => t.provider_id === created!.id)
      )
      .toBe(false);

    // Re-enable so removing a model below exercises the live listing.
    await providers.enabledSwitch(name).click();
    await expect
      .poll(
        async () =>
          (await api.chatTargets()).filter((t) => t.provider_id === created!.id)
            .length
      )
      .toBe(2);

    // Remove one model.
    await providers.removeModelButton(name, "mock-embed-1").click();
    await expect(providers.modelCell("mock-embed-1")).toHaveCount(0);
    await expect
      .poll(
        async () =>
          (await api.chatTargets()).filter((t) => t.provider_id === created!.id)
            .length
      )
      .toBe(1);

    // Delete the provider.
    await providers.deleteProvider(name);
    await expect(providers.providerRow(name)).toHaveCount(0);
    await expect
      .poll(async () =>
        (await api.providers()).some((p) => p.id === created!.id)
      )
      .toBe(false);
  });

  test("sets a monthly budget", async ({ page }) => {
    const providers = new ProvidersPage(page);
    await providers.open();
    await providers.budgetInput.fill("42.5");
    await providers.saveBudgetButton.click();
    await expect(page.getByText("$42.50")).toBeVisible();
  });
});
