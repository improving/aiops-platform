import { test, expect } from "../fixtures";
import { ProvidersPage } from "../pages/providers";
import { ChatPage } from "../pages/chat";

// Exercises the hosted-provider path against the real OpenAI API, so it
// needs a real key and never runs in CI. The hosted path is otherwise
// covered by backend/test_providers.py and e2e/fast/providers.spec.ts
// (mock discovery and registration, no real provider).
test.describe("hosted chat through OpenAI", { tag: "@cluster" }, () => {
  test.skip(!process.env.E2E_OPENAI_API_KEY, "needs E2E_OPENAI_API_KEY");
  test.setTimeout(5 * 60_000);

  const PROVIDER_NAME = "openai-cluster";

  test("add an OpenAI provider through the UI, chat, spend increases", async ({
    asUser,
    userApi,
  }) => {
    // alice (the default signed-in user) is a member and cannot add
    // providers; only an admin can.
    const adminContext = await asUser("admin");
    const page = await adminContext.newPage();

    const providers = new ProvidersPage(page);
    await providers.open();
    await providers.addProvider({
      kind: "openai",
      name: PROVIDER_NAME,
      apiKey: process.env.E2E_OPENAI_API_KEY!,
      models: ["gpt-4o-mini"],
    });

    const admin = await userApi("admin");
    const target = (await admin.chatTargets()).find(
      (t) => t.model === "gpt-4o-mini"
    );
    expect(target, "the hosted model is a chat target").toBeTruthy();

    const chat = new ChatPage(page);
    await chat.open(target!.name);
    await chat.send("Reply with the single word pong.");
    await expect(chat.assistantMessages.last()).not.toBeEmpty({
      timeout: 60_000,
    });

    await expect
      .poll(async () => (await admin.orgSpend()).spend, {
        message: "spend did not increase after a hosted chat call",
        timeout: 60_000,
        intervals: [5_000],
      })
      .toBeGreaterThan(0);

    await providers.deleteProvider(PROVIDER_NAME);
    await page.close();
  });
});
