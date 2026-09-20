import { createHash } from "node:crypto";
import type { APIRequestContext } from "@playwright/test";
import { test, expect } from "../fixtures";
import { ChatPage } from "../pages/chat";

// The real path, without a model: backend -> LiteLLM MCP gateway -> the
// test server in kind (`make mcp-test-up`: echo and whoami behind a
// required bearer). `whoami` answers a fingerprint of the credential it
// got, which is how this spec proves that each member's own credential
// travels with that member's calls and with nobody else's.

const SERVER_URL = "http://mcp-test.mcp-test.svc.cluster.local:8000/mcp";
const SERVERS = "/api/v1alpha1/mcp/servers";
const ENDPOINT = "/api/v1alpha1/mcp";

const fingerprint = (token: string) =>
  createHash("sha256").update(token).digest("hex").slice(0, 8);

type Rpc = { result?: Record<string, unknown>; error?: unknown };

/** One JSON-RPC call on the platform's MCP endpoint (an SSE answer). */
async function rpc(
  request: APIRequestContext,
  method: string,
  params: object = {},
  headers: Record<string, string> = {}
): Promise<{ status: number; body: Rpc | null; text: string }> {
  const response = await request.post(ENDPOINT, {
    headers: {
      Accept: "application/json, text/event-stream",
      ...headers,
    },
    data: { jsonrpc: "2.0", id: 1, method, params },
  });
  const text = await response.text();
  const line = text.split("\n").find((l) => l.startsWith("data: "));
  const json = line ? line.slice(6) : text.trim().startsWith("{") ? text : "";
  return {
    status: response.status(),
    body: json ? (JSON.parse(json) as Rpc) : null,
    text,
  };
}

function toolText(body: Rpc | null): string {
  const content = (body?.result?.content ?? []) as { text?: string }[];
  return content.map((c) => c.text ?? "").join("");
}

test.describe("MCP servers on the cluster", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(5 * 60_000);

  let serverId = "";

  test.afterEach(async ({ asUser }) => {
    if (!serverId) return;
    const admin = await asUser("admin");
    await admin.request.delete(`${SERVERS}/${serverId}`);
    serverId = "";
  });

  test("each member's own credential travels with their tool calls", async ({
    asUser,
  }) => {
    const name = `whoami_${Date.now().toString(36)}`;
    const admin = await asUser("admin");
    const alice = await asUser("alice");
    const bob = await asUser("bob");

    const created = await admin.request.post(SERVERS, {
      data: {
        name,
        url: SERVER_URL,
        credential_mode: "per_user",
        credential: { auth_type: "bearer", value: "tok-admin" },
      },
    });
    expect(
      created.status(),
      `register the test server (run "make mcp-test-up" first): ${await created.text()}`
    ).toBe(201);
    const server = await created.json();
    serverId = server.id;
    expect(server.my_credential).toBe("set");
    expect(server.tools.map((t: { name: string }) => t.name).sort()).toEqual([
      "echo",
      "whoami",
    ]);
    const whoami = `${server.tool_prefix}whoami`;

    // A value the server refuses is not stored (it wants a bearer).
    const saved = await alice.request.put(`${SERVERS}/${serverId}/credential`, {
      data: { value: "tok-alice" },
    });
    expect(saved.status(), await saved.text()).toBe(200);
    expect((await saved.json()).my_credential).toBe("set");

    // The same tool, the same endpoint, two callers, two credentials.
    for (const [who, token] of [
      [admin, "tok-admin"],
      [alice, "tok-alice"],
      [admin, "tok-admin"],
    ] as const) {
      const called = await rpc(who.request, "tools/call", {
        name: whoami,
        arguments: {},
      });
      expect(called.status, called.text).toBe(200);
      expect(toolText(called.body)).toBe(fingerprint(token));
    }

    // Bob has none: the server is not among "all servers", and asked
    // for by name the endpoint says what to do.
    const listed = await rpc(bob.request, "tools/list");
    expect(listed.status, listed.text).toBe(200);
    const names = (
      (listed.body?.result?.tools ?? []) as { name: string }[]
    ).map((t) => t.name);
    expect(names.filter((n) => n.startsWith(server.tool_prefix))).toEqual([]);
    const named = await rpc(
      bob.request,
      "tools/list",
      {},
      {
        "X-Mcp-Servers": name,
      }
    );
    expect(named.status).toBe(409);
    expect(named.text).toContain(name);

    // Another client's headers cannot stand in for a credential.
    const forged = await rpc(
      bob.request,
      "tools/call",
      { name: whoami, arguments: {} },
      {
        [`x-mcp-${server.tool_prefix.replace(/-$/, "")}-authorization`]:
          "Bearer tok-alice",
      }
    );
    expect(toolText(forged.body)).not.toBe(fingerprint("tok-alice"));
  });

  test("the chat page offers Connect to a member without a credential", async ({
    asUser,
  }) => {
    const name = `connect_${Date.now().toString(36)}`;
    const admin = await asUser("admin");
    const created = await admin.request.post(SERVERS, {
      data: {
        name,
        url: SERVER_URL,
        credential_mode: "per_user",
        credential: { auth_type: "bearer", value: "tok-admin" },
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    serverId = (await created.json()).id;

    const bob = await asUser("bob");
    const page = await bob.newPage();
    // The Tools section needs a target to show; the cluster may have no
    // model running, and this test is about credentials, not a model.
    await page.route("**/api/v1alpha1/chat/targets", (route) =>
      route.fulfill({
        json: [
          {
            name: "inst-00000000",
            label: "Stub · for the Tools section",
            capability: "chat",
            instance_id: null,
            provider_id: null,
            model: "stub",
            engine: "Ollama",
            ready: true,
            via: "litellm",
            context_length: null,
            tools: null,
          },
        ],
      })
    );
    const chat = new ChatPage(page);
    await page.goto("/chat?target=inst-00000000");
    await chat.openTools();
    await expect(chat.tools).toContainText(name);
    await chat.openTools();
    await expect(chat.tools).toContainText("needs your credential");
    await chat.openTools();
    await chat.tools.getByRole("button", { name: `Connect ${name}` }).click();
    const dialog = page.getByRole("dialog", { name: `Connect ${name}` });
    await dialog.getByLabel("Personal access token").fill("tok-bob");
    await dialog.getByRole("button", { name: "Test and save" }).click();
    await expect(dialog).toBeHidden({ timeout: 60_000 });
    await chat.openTools();
    await expect(
      chat.tools.getByRole("switch", { name: `Use ${name}` })
    ).toBeChecked();

    const called = await rpc(bob.request, "tools/call", {
      name: `${(await (await bob.request.get(SERVERS)).json()).find((s: { id: string }) => s.id === serverId).tool_prefix}whoami`,
      arguments: {},
    });
    expect(toolText(called.body)).toBe(fingerprint("tok-bob"));
    await page.close();
  });
});
