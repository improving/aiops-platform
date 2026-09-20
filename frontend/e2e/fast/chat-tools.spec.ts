import { test, expect, FAILED_RESOURCE } from "../fixtures";
import { ChatPage } from "../pages/chat";

// The whole loop through the real route handler: the TEST_MODE backend
// mocks the MCP registry, the MCP endpoint (one tool, "echo") and a model
// that calls the first tool when the message starts with "call ".

const SERVERS = "/api/v1alpha1/mcp/servers";

test.describe("chat with tools", () => {
  let serverId = "";
  let serverName = "";

  test.beforeEach(async ({ page }) => {
    serverName = `tools_${Math.random().toString(36).slice(2, 10)}`;
    const created = await page.request.post(SERVERS, {
      data: { name: serverName, url: "https://mcp.example.com/mcp" },
    });
    expect(created.status()).toBe(201);
    serverId = (await created.json()).id;
  });

  test.afterEach(async ({ page }) => {
    await page.request.delete(`${SERVERS}/${serverId}`);
  });

  test("a server turned on gives the model its tools, and the answer shows the call", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    await expect(chat.tools).toContainText(serverName);
    await expect(chat.tools).toContainText("1 tool");
    await expect(chat.toolsOn).toBeHidden();

    await chat.tools.getByRole("switch", { name: `Use ${serverName}` }).click();
    await expect(chat.toolsOn).toContainText("1 tool server on");

    await chat.send("call hi there");
    await expect(chat.toolCalls).toHaveCount(1);
    const call = chat.toolCalls.first();
    await expect(call).toHaveAttribute("data-state", "done");
    await expect(call).toContainText("echo");
    await call.locator("summary").click();
    await expect(call.getByRole("group", { name: /^Result of/ })).toHaveText(
      "hi there"
    );
    await expect(chat.assistantMessages.last()).toContainText(
      "Tool said: hi there"
    );
    await expect(chat.speed).toContainText("2 steps");

    // The choice and the conversation, tool call included, outlive a reload.
    await page.reload();
    await expect(chat.toolsOn).toContainText("1 tool server on");
    await expect(chat.toolCalls).toHaveCount(1);

    // The next turn carries the finished call back to the model.
    await chat.send("and now?");
    await expect(chat.assistantMessages.last()).toContainText(
      "You said: and now?"
    );

    await chat.tools.getByRole("switch", { name: `Use ${serverName}` }).click();
    await expect(chat.toolsOn).toBeHidden();
  });

  test("a Try in chat link turns the server on", async ({ page }) => {
    const chat = new ChatPage(page);
    await page.goto(`/chat?target=inst-mock&tools=${serverName}`);
    await expect(chat.toolsOn).toContainText("1 tool server on");
    await expect(
      chat.tools.getByRole("switch", { name: `Use ${serverName}` })
    ).toBeChecked();
    // Leave the browser's stored choice clean for the other tests.
    await chat.tools.getByRole("switch", { name: `Use ${serverName}` }).click();
  });

  test("a target that cannot call tools says why, and keeps the choice", async ({
    page,
  }) => {
    await page.route("**/api/v1alpha1/chat/targets", (route) =>
      route.fulfill({
        json: [
          {
            name: "inst-abcdef12",
            label: "Qwen3 · vLLM",
            capability: "chat",
            instance_id: "00000000-0000-4000-8000-0000abcdef12",
            provider_id: null,
            model: "Qwen/Qwen3-8B",
            engine: "vLLM",
            ready: true,
            via: "litellm",
            context_length: 16384,
            tools: false,
          },
        ],
      })
    );
    const chat = new ChatPage(page);
    await page.goto(`/chat?target=inst-abcdef12&tools=${serverName}`);
    await expect(chat.tools.getByTestId("tools-blocked")).toContainText(
      "This vLLM instance has Tool calling off."
    );
    await expect(
      chat.tools.getByRole("link", { name: "Turn it on in Edit settings" })
    ).toHaveAttribute(
      "href",
      "/models/endpoints/00000000-0000-4000-8000-0000abcdef12"
    );
    const use = chat.tools.getByRole("switch", { name: `Use ${serverName}` });
    await expect(use).toBeDisabled();
    await expect(use).toBeChecked();
    await expect(chat.toolsOn).toBeHidden();
  });
});

test.describe("chat when the tools are down", () => {
  test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

  test("offers to send the message without tools", async ({ page }) => {
    const bodies: { toolSources?: unknown[] }[] = [];
    await page.route("**/api/chat", async (route) => {
      bodies.push(route.request().postDataJSON());
      if (bodies.length === 1) {
        await route.fulfill({
          status: 502,
          json: { detail: "Could not reach the tools: connect ECONNREFUSED" },
        });
        return;
      }
      await route.continue();
    });
    const name = `down_${Math.random().toString(36).slice(2, 10)}`;
    const created = await page.request.post(SERVERS, {
      data: { name, url: "https://mcp.example.com/mcp" },
    });
    const id = (await created.json()).id;

    const chat = new ChatPage(page);
    await page.goto(`/chat?target=inst-mock&tools=${name}`);
    await expect(chat.toolsOn).toBeVisible();
    await chat.send("hello");
    const alert = chat.conversation.getByRole("alert");
    await expect(alert).toContainText("The tools could not be reached");
    await alert.getByRole("button", { name: "Send without tools" }).click();
    await expect(chat.assistantMessages.last()).toContainText(
      "You said: hello"
    );
    expect(bodies[0].toolSources).toHaveLength(1);
    expect(bodies[1].toolSources).toEqual([]);

    await chat.tools.getByRole("switch", { name: `Use ${name}` }).click();
    await page.request.delete(`${SERVERS}/${id}`);
  });
});
