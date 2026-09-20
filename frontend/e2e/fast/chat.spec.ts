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

  test("a long target name stays inside the side panel", async ({ page }) => {
    const label =
      "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ-with-a-very-long-suffix · vLLM";
    await page.route("**/api/v1alpha1/chat/targets", (route) =>
      route.fulfill({
        json: [
          {
            name: "inst-mock",
            label,
            capability: "chat",
            instance_id: null,
            provider_id: null,
            model: "mock",
            engine: "vLLM",
            ready: true,
            via: "litellm",
          },
        ],
      })
    );
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await expect(chat.targetSelect).toContainText("Qwen/Qwen2.5-Coder");

    const panel = (await page.locator("aside").first().boundingBox())!;
    const select = (await chat.targetSelect.boundingBox())!;
    expect(select.x + select.width).toBeLessThanOrEqual(
      panel.x + panel.width + 1
    );
  });

  test("an answer renders as Markdown, code in a block with a copy button", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    // The mock echoes the message, so the fence comes back in the answer.
    await chat.send("**loud** and\n```python\nprint(1)\n```");
    const answer = chat.assistantMessages.last();
    await expect(answer.locator("strong")).toHaveText("loud");
    const block = answer.getByRole("group", { name: "python code" });
    await expect(block).toContainText("print(1)");
    await expect(
      answer.getByRole("button", { name: "Copy python code" })
    ).toBeVisible();
    await expect(answer).not.toContainText("```");
    // The user's own turn stays as typed.
    await expect(chat.messages.first()).toContainText("**loud**");
  });

  test("shows a waiting row until the answer starts, then its speed and the window use", async ({
    page,
  }) => {
    await page.route("**/api/chat", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 700));
      await route.continue();
    });
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await chat.send("hello there");
    await expect(chat.waiting).toBeVisible();
    await expect(chat.assistantMessages.last()).toContainText("You said");
    await expect(chat.waiting).toBeHidden();

    // "You said: hello there" is four words, one token each in the mock.
    await expect(chat.speed).toContainText("4 tokens");
    await expect(chat.speed).toContainText("tok/s");
    await expect(chat.contextMeter).toContainText("of 4,096 tokens");

    await page.reload();
    await expect(chat.speed).toContainText("4 tokens");
  });

  test("an answer shows its tool calls in order, done and failed", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await page.evaluate(() => {
      const turns = [
        {
          id: "u1",
          role: "user",
          parts: [{ type: "text", text: "what changed in PR 52?" }],
        },
        {
          id: "a1",
          role: "assistant",
          parts: [
            { type: "step-start" },
            {
              type: "dynamic-tool",
              toolName: "github-get_pull_request",
              toolCallId: "call_1",
              state: "output-available",
              input: { number: 52 },
              output: {
                content: [{ type: "text", text: "Edit settings dialog" }],
                isError: false,
              },
            },
            {
              type: "dynamic-tool",
              toolName: "github-search_issues",
              toolCallId: "call_2",
              state: "output-error",
              input: { query: "tool calling" },
              errorText: "403 Forbidden",
            },
            { type: "step-start" },
            { type: "text", text: "PR 52 adds an Edit settings dialog." },
          ],
        },
      ];
      localStorage.setItem("aiops.chat.dev.inst-mock", JSON.stringify(turns));
    });
    await page.reload();

    await expect(chat.toolCalls).toHaveCount(2);
    const done = chat.toolCalls.first();
    await expect(done).toHaveAttribute("data-state", "done");
    await expect(done).toContainText("github-get_pull_request");
    // Closed once done: the answer is the main text.
    await expect(done.getByRole("group", { name: /^Result of/ })).toBeHidden();
    await done.locator("summary").click();
    await expect(
      done.getByRole("group", { name: "Input of github-get_pull_request" })
    ).toContainText('"number": 52');
    // An MCP result shows the text the model read, not its envelope.
    await expect(
      done.getByRole("group", { name: "Result of github-get_pull_request" })
    ).toHaveText("Edit settings dialog");

    const failed = chat.toolCalls.nth(1);
    await expect(failed).toHaveAttribute("data-state", "failed");
    await failed.locator("summary").click();
    await expect(failed.getByRole("alert")).toHaveText("403 Forbidden");

    await expect(chat.assistantMessages.last()).toContainText(
      "PR 52 adds an Edit settings dialog."
    );
  });

  test("a streamed tool call replaces the waiting row and stays open while it runs", async ({
    page,
  }) => {
    // The stream ends before the tool's result: what a stopped answer
    // leaves behind, and the only way to hold the running state still.
    const chunks = [
      { type: "start", messageId: "m1" },
      { type: "start-step" },
      {
        type: "tool-input-available",
        toolCallId: "call_1",
        toolName: "echo",
        input: { message: "hi" },
        dynamic: true,
      },
    ];
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "content-type": "text/event-stream",
          "x-vercel-ai-ui-message-stream": "v1",
        },
        body:
          chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join("") +
          "data: [DONE]\n\n",
      })
    );
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await chat.send("call hi");

    await expect(chat.toolCalls).toHaveCount(1);
    await expect(chat.toolCalls.first()).toHaveAttribute(
      "data-state",
      "running"
    );
    await expect(
      chat.toolCalls.first().getByRole("group", { name: "Input of echo" })
    ).toContainText('"message": "hi"');
    await expect(chat.waiting).toBeHidden();
  });

  test("the last turn can be regenerated, and the last message edited", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await chat.send("first try");
    await expect(chat.assistantMessages.last()).toContainText("first try");

    await chat.assistantMessages.last().hover();
    await page.getByRole("button", { name: "Regenerate answer" }).click();
    await expect(chat.messages).toHaveCount(2);
    await expect(chat.assistantMessages.last()).toContainText("first try");
    await expect(chat.speed).toBeVisible();

    await chat.messages.first().hover();
    await page.getByRole("button", { name: "Edit message" }).click();
    await expect(chat.messages).toHaveCount(0);
    await expect(chat.input).toHaveValue("first try");
    await expect(chat.input).toBeFocused();
  });

  test("a starter prompt fills the field without sending", async ({ page }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await expect(chat.starterPrompts).toHaveCount(4);
    const prompt = await chat.starterPrompts.first().innerText();
    await chat.starterPrompts.first().click();
    await expect(chat.input).toHaveValue(prompt);
    await expect(chat.messages).toHaveCount(0);
    await expect(chat.sendButton).toBeEnabled();
  });

  test("temperature and the token limit are sent only when set", async ({
    page,
  }) => {
    const bodies: Record<string, unknown>[] = [];
    await page.route("**/api/chat", async (route) => {
      bodies.push(route.request().postDataJSON());
      await route.continue();
    });
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    const slider = page.getByRole("slider", { name: "Temperature" });
    await expect(slider).toBeDisabled();
    await chat.send("one");
    await expect(chat.assistantMessages).toHaveCount(1);

    await page.getByRole("switch", { name: "Model default" }).click();
    await expect(slider).toBeEnabled();
    await slider.press("ArrowRight");
    await page.getByRole("spinbutton", { name: "Max tokens" }).fill("64");
    await chat.systemPrompt.fill("Be brief.");
    await expect(page.getByText("Active", { exact: true })).toBeVisible();
    await chat.send("two");
    await expect(chat.assistantMessages).toHaveCount(2);

    expect(bodies[0].temperature).toBeUndefined();
    expect(bodies[0].maxOutputTokens).toBeUndefined();
    expect(bodies[1].temperature).toBeCloseTo(0.8);
    expect(bodies[1].maxOutputTokens).toBe(64);
    expect(bodies[1].system).toBe("Be brief.");
  });

  test("a cleared conversation comes back with Undo", async ({ page }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await chat.send("keep me");
    await expect(chat.assistantMessages.last()).toContainText("keep me");
    await chat.clearButton.click();
    await expect(chat.messages).toHaveCount(0);
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(chat.messages).toHaveCount(2);
    await page.reload();
    await expect(chat.messages).toHaveCount(2);
  });

  test("the target list is searchable and shows an instance that is starting", async ({
    page,
  }) => {
    const base = {
      capability: "chat",
      instance_id: null,
      provider_id: null,
      engine: "vLLM",
      ready: true,
      via: "litellm",
    };
    await page.route("**/api/v1alpha1/chat/targets", (route) =>
      route.fulfill({
        json: [
          {
            ...base,
            name: "inst-mock",
            label: "Ready model · vLLM",
            model: "a",
          },
          {
            ...base,
            name: "inst-0000beef",
            label: "Slow model · vLLM",
            model: "b",
            ready: false,
          },
          {
            ...base,
            name: "prov-1/gpt",
            label: "gpt-hosted · openai",
            model: "gpt",
            provider_id: "p1",
            engine: "openai",
          },
        ],
      })
    );
    const chat = new ChatPage(page);
    // A link to an instance that is starting says so, and cannot send.
    await chat.open("inst-0000beef");
    await expect(chat.targetSelect).toContainText(
      "Slow model · vLLM · Starting"
    );
    await expect(chat.input).toHaveAttribute(
      "placeholder",
      "This instance is still starting"
    );
    await chat.input.fill("ping");
    await expect(chat.sendButton).toBeDisabled();

    await chat.targetSelect.click();
    await expect(page.getByRole("option")).toHaveCount(3);
    await expect(
      page.getByRole("option", { name: /Slow model/ })
    ).toHaveAttribute("aria-disabled", "true");
    await expect(
      page.getByRole("option", { name: /Slow model/ })
    ).toContainText("Starting");
    await page.getByPlaceholder("Search targets").fill("hosted");
    await expect(page.getByRole("option")).toHaveCount(1);
    await page.getByRole("option", { name: /gpt-hosted/ }).click();
    await expect(chat.targetSelect).toContainText("gpt-hosted");
    await expect(page).toHaveURL(/target=prov-1%2Fgpt|target=prov-1\/gpt/);
  });

  test("View code shows the playground's request for a client", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await chat.systemPrompt.fill("Be brief.");
    await page.getByRole("button", { name: "View code" }).click();
    const curl = page.getByRole("group", { name: "curl example" });
    await expect(curl).toContainText("/v1alpha1/chat/completions");
    await expect(curl).toContainText('"model": "inst-mock"');
    await expect(curl).toContainText("Be brief.");
    await expect(curl).toContainText("<API_TOKEN>");
    await page.getByRole("tab", { name: "Python" }).click();
    await expect(
      page.getByRole("group", { name: "Python example" })
    ).toContainText('model="inst-mock"');
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
