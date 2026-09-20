import { test, expect, FAILED_RESOURCE } from "../fixtures";
import { ChatPage } from "../pages/chat";

// Compaction of a playground conversation. The mock model echoes a
// message, answers "system?" with the system message it got, and writes
// "Mock summary of <n> user turns." for a compaction request, so these
// cases can follow the summary into the next request.

async function say(chat: ChatPage, text: string, answers: number) {
  await chat.send(text);
  await expect(chat.assistantMessages).toHaveCount(answers);
  await expect(chat.assistantMessages.last()).not.toBeEmpty();
  await expect(chat.sendButton).toBeVisible();
}

test.describe("compaction in the playground", () => {
  test("Compact summarizes the older turns, the model gets the summary, and Undo brings them back", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    const compact = page.getByRole("button", { name: "Compact", exact: true });

    await say(chat, "My cluster is named orion.", 1);
    await say(chat, "It has three GPU nodes.", 2);
    // Two turns of the user always stay word for word: nothing to gain yet.
    await expect(compact).toHaveCount(0);
    await say(chat, "What did I tell you?", 3);

    await compact.click();
    const marker = page.getByTestId("chat-compaction");
    await expect(marker).toContainText("Earlier conversation, summarized");
    await expect(marker).toContainText("2 messages");
    await marker.getByText("Read the summary").click();
    await expect(marker).toContainText("Mock summary of 1 user turns.");
    // The old turns stay on the page, collapsed.
    const earlier = page.getByTestId("chat-compacted");
    await expect(earlier).toContainText("2 messages, not sent to the model");
    await expect(earlier).not.toHaveAttribute("open", "");

    // The next request: the summary in the system message, and the turns
    // after the marker only.
    const request = page.waitForRequest(
      (r) => r.url().endsWith("/api/chat") && r.method() === "POST"
    );
    await chat.send("system?");
    const body = (await request).postDataJSON() as {
      summary: string;
      messages: { role: string; parts: { text?: string }[] }[];
    };
    expect(body.summary).toBe("Mock summary of 1 user turns.");
    const sent = body.messages.map((m) => m.parts.map((p) => p.text).join(""));
    expect(sent.join(" | ")).not.toContain("orion");
    expect(sent[0]).toBe("It has three GPU nodes.");
    await expect(chat.assistantMessages.last()).toContainText(
      "Summary of the earlier conversation"
    );
    await expect(chat.assistantMessages.last()).toContainText(
      "Mock summary of 1 user turns."
    );

    // It survives a reload (the conversation is in this browser), and
    // Undo makes every turn live again.
    await page.reload();
    await expect(page.getByTestId("chat-compaction")).toBeVisible();
    await page
      .getByTestId("chat-compaction")
      .getByRole("button", { name: "Undo" })
      .click();
    await expect(page.getByTestId("chat-compaction")).toHaveCount(0);
    await expect(page.getByTestId("chat-compacted")).toHaveCount(0);
    const whole = page.waitForRequest(
      (r) => r.url().endsWith("/api/chat") && r.method() === "POST"
    );
    await chat.send("And now?");
    const after = (await whole).postDataJSON() as {
      summary?: string;
      messages: { parts: { text?: string }[] }[];
    };
    expect(after.summary).toBeUndefined();
    expect(after.messages[0].parts[0].text).toBe("My cluster is named orion.");
    await chat.closeSettings();
    await chat.clearButton.click();
  });

  test("with Compact automatically a nearly full window is summarized before the next message", async ({
    page,
  }) => {
    // A window of 30 tokens: the mock counts one token for each word, so
    // two turns fill three quarters of it.
    await page.route("**/api/v1alpha1/chat/targets", (route) =>
      route.fulfill({
        json: [
          {
            name: "inst-mock",
            label: "Mock model · Mock",
            capability: "chat",
            instance_id: null,
            provider_id: null,
            model: "mock",
            engine: "Mock",
            ready: true,
            via: "litellm",
            context_length: 30,
            tools: null,
          },
        ],
      })
    );
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await chat.openSettings();
    await page.getByLabel("Compact automatically").click();

    await say(chat, "alpha beta gamma delta epsilon", 1);
    await say(chat, "one two three four five six", 2);
    await say(chat, "seven eight nine ten eleven twelve", 3);
    await expect(page.getByTestId("chat-compaction")).toHaveCount(0);

    // The window is nearly full, and now there is something to compact.
    // The message must go AFTER the compaction, with the summary and
    // without the old turns: the compaction and the send are one click.
    const request = page.waitForRequest(
      (r) => r.url().endsWith("/api/chat") && r.method() === "POST"
    );
    await say(chat, "what now", 4);
    const body = (await request).postDataJSON() as {
      summary?: string;
      messages: { parts: { text?: string }[] }[];
    };
    expect(body.summary).toBe("Mock summary of 1 user turns.");
    expect(body.messages[0].parts[0].text).toBe("one two three four five six");
    const marker = page.getByTestId("chat-compaction");
    await expect(marker).toContainText("summarized automatically");
    // The answer to the message still came, after the compaction.
    await expect(chat.assistantMessages.last()).toContainText("what now");

    // The choice is kept for this user.
    await page.reload();
    await chat.openSettings();
    await expect(page.getByLabel("Compact automatically")).toBeChecked();
    await chat.openSettings();
    await page.getByLabel("Compact automatically").click();
    await chat.closeSettings();
    await chat.clearButton.click();
  });

  test("a summary that arrives after a switch of target touches neither conversation", async ({
    page,
  }) => {
    const target = (name: string, label: string) => ({
      name,
      label,
      capability: "chat",
      instance_id: null,
      provider_id: null,
      model: "mock",
      engine: "Mock",
      ready: true,
      via: "litellm",
      context_length: 4096,
      tools: null,
    });
    await page.route("**/api/v1alpha1/chat/targets", (route) =>
      route.fulfill({
        json: [
          target("inst-mock", "Mock model · Mock"),
          target("inst-other", "Other model · Mock"),
        ],
      })
    );
    // A slow model: the summary takes two seconds.
    let asked = 0;
    await page.route("**/api/chat/compact", async (route) => {
      asked += 1;
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.continue().catch(() => undefined);
    });
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await say(chat, "a private note for the first model", 1);
    await say(chat, "second", 2);
    await say(chat, "third", 3);

    await chat.closeSettings();
    await page.getByRole("button", { name: "Compact", exact: true }).click();
    // While the summary is written nothing else changes the conversation.
    await expect(
      page.getByRole("button", { name: "Compacting…" })
    ).toBeDisabled();
    await chat.closeSettings();
    await expect(chat.clearButton).toBeDisabled();
    await expect(chat.sendButton).toBeDisabled();

    await chat.selectTarget(/Other model/);
    await expect(page).toHaveURL(/target=inst-other/);
    await page.waitForTimeout(3000);
    expect(asked).toBe(1);

    // The other target's conversation is still empty, on the page and in
    // the browser's storage, and the first one is whole, with no marker.
    await expect(page.getByTestId("chat-compaction")).toHaveCount(0);
    await expect(chat.messages).toHaveCount(0);
    const stored = await page.evaluate(() => ({
      other: window.localStorage.getItem("aiops.chat.dev.inst-other"),
      first: window.localStorage.getItem("aiops.chat.dev.inst-mock"),
    }));
    expect(stored.other).toBeNull();
    const first = JSON.parse(stored.first ?? "[]") as { role: string }[];
    expect(first).toHaveLength(6);
    expect(first.some((m) => m.role === "system")).toBe(false);

    await chat.selectTarget(/Mock model/);
    await expect(chat.assistantMessages).toHaveCount(3);
    await chat.closeSettings();
    await chat.clearButton.click();
  });

  test.describe("a refusal", () => {
    // Chromium logs a non-2xx answer as a console error.
    test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

    test("a summary that fails changes nothing, and says so", async ({
      page,
    }) => {
      await page.route("**/api/chat/compact", (route) =>
        route.fulfill({
          status: 502,
          json: { detail: "The model answered 500" },
        })
      );
      const chat = new ChatPage(page);
      await chat.open("inst-mock");
      await say(chat, "first", 1);
      await say(chat, "second", 2);
      await say(chat, "third", 3);
      await chat.closeSettings();
      await page.getByRole("button", { name: "Compact", exact: true }).click();
      await expect(
        page.getByText("The conversation was not compacted").first()
      ).toBeVisible();
      await expect(page.getByTestId("chat-compaction")).toHaveCount(0);
      await chat.closeSettings();
      await chat.clearButton.click();
    });
  });
});
