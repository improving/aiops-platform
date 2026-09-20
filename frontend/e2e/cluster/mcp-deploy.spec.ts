import type { APIRequestContext } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { test, expect } from "../fixtures";

// The real path on kind: the backend installs charts/mcp-server with Helm
// (AIOPS_CHARTS_DIR serves the checkout's chart), the poller finds the pod
// ready and registers it in the LiteLLM proxy, and the platform's MCP
// endpoint then lists the server's tools. The Grafana entry starts and
// lists its tools with no Grafana reachable, so no second system is needed.

const INSTANCES = "/api/v1alpha1/mcp/instances";
const SERVERS = "/api/v1alpha1/mcp/servers";
const ENDPOINT = "/api/v1alpha1/mcp";
const NAMESPACE = process.env.E2E_NAMESPACE ?? "ai-stack";

type Server = {
  id: string;
  name: string;
  url: string;
  status: string;
  tools: { name: string }[];
  deploy: { instance_id: string; status: string; usable: boolean } | null;
};

async function find(request: APIRequestContext, id: string) {
  const servers = (await (await request.get(SERVERS)).json()) as Server[];
  return servers.find((s) => s.id === id);
}

function kubectl(...args: string[]): string {
  try {
    return execFileSync("kubectl", args, { encoding: "utf8", timeout: 60_000 });
  } catch (e) {
    return String((e as { stdout?: string }).stdout ?? "") + String(e);
  }
}

test.describe(
  "a deployed MCP server on the cluster",
  { tag: "@cluster" },
  () => {
    test.setTimeout(8 * 60_000);
    let serverId = "";

    test.afterEach(async ({ asUser }) => {
      if (!serverId) return;
      const admin = await asUser("admin");
      await admin.request.delete(`${SERVERS}/${serverId}`);
      serverId = "";
    });

    test("deploy, register when ready, list tools through the one door, closed to other pods, delete", async ({
      asUser,
    }) => {
      const admin = (await asUser("admin")).request;
      const name = `graf_${Date.now().toString(36)}`;
      const created = await admin.post(INSTANCES, {
        data: {
          catalog: "grafana",
          name,
          settings: { GRAFANA_URL: "http://grafana.invalid:3000" },
        },
      });
      expect(created.status(), await created.text()).toBe(201);
      const server = (await created.json()) as Server;
      serverId = server.id;
      expect(server.status).toBe("unreachable");
      expect(server.deploy?.usable).toBe(false);
      const release = `mcpi-${server.deploy!.instance_id.slice(-8)}`;
      expect(server.url).toBe(`http://${release}.${NAMESPACE}.svc:8000/mcp`);

      // The poller: ready, registered, tools listed.
      await expect
        .poll(async () => (await find(admin, server.id))?.deploy?.usable, {
          timeout: 6 * 60_000,
          intervals: [5_000],
        })
        .toBe(true);
      const running = (await find(admin, server.id))!;
      expect(running.status).toBe("connected");
      expect(running.tools.length).toBeGreaterThan(10);

      // Through the one door, as a member.
      const member = (await asUser("alice")).request;
      const listed = await member.post(ENDPOINT, {
        headers: {
          Accept: "application/json, text/event-stream",
          "X-Mcp-Servers": name,
        },
        data: { jsonrpc: "2.0", id: 1, method: "tools/list" },
      });
      expect(listed.status()).toBe(200);
      expect(await listed.text()).toContain("search_dashboards");

      // The pod: hardened, and closed to every pod but the proxy's.
      const pod = kubectl(
        "-n",
        NAMESPACE,
        "get",
        "pod",
        "-l",
        `app.kubernetes.io/instance=${release}`,
        "-o",
        "jsonpath={.items[0].spec.automountServiceAccountToken} {.items[0].spec.containers[0].securityContext.readOnlyRootFilesystem}"
      );
      expect(pod.trim()).toBe("false true");
      const probe = kubectl(
        "-n",
        NAMESPACE,
        "run",
        `np-${Date.now().toString(36)}`,
        "--rm",
        "-i",
        "--restart=Never",
        "--image=curlimages/curl:8.10.1",
        "--quiet",
        "--",
        "sh",
        "-c",
        `curl -s -m 6 -o /dev/null -w '%{http_code}' http://${release}.${NAMESPACE}.svc:8000/mcp || echo blocked`
      );
      expect(probe).toContain("blocked");

      // Delete: the proxy, the release, the Secret, the rows.
      const deleted = await admin.delete(`${SERVERS}/${server.id}`);
      expect(deleted.status()).toBe(204);
      serverId = "";
      expect(await find(admin, server.id)).toBeUndefined();
      await expect
        .poll(
          () =>
            kubectl(
              "-n",
              NAMESPACE,
              "get",
              "deploy,svc,networkpolicy",
              "-l",
              `app.kubernetes.io/instance=${release}`,
              "-o",
              "name"
            ).trim(),
          {
            timeout: 60_000,
          }
        )
        .toBe("");
    });
  }
);
