import { test, expect, type InferenceInstanceRecord } from "../fixtures";
import { AppShell } from "../pages/app-shell";

test.use({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
});

const paths = [
  "/",
  "/models/catalog",
  "/notebooks/new",
  "/vector-databases/catalog",
];

// Minimal InferenceInstance rows (InferenceInstanceRecord plus the fields
// the frontend type also requires) so the list is non-empty: the endpoints
// toolbar (search, filter-by, status, sort, refresh -- five controls) only
// mounts once there is at least one instance.
const MOCK_INSTANCES: (InferenceInstanceRecord & {
  config: {
    lora_adapters: unknown[];
    env_vars: Record<string, string>;
    args: Record<string, string>;
    enable_tracing: boolean;
  };
  host: string;
  healthEndpoint: string | null;
  metricsEndpoint: string | null;
})[] = Array.from({ length: 3 }, (_, i) => ({
  id: `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`,
  ready: false,
  status: "Failed",
  endpoint: null,
  model: { id: `m-${i}`, name: `Model ${i}`, modelId: `model-${i}` },
  engine: { id: `e-${i}`, name: `Engine ${i}` },
  config: {
    lora_adapters: [],
    env_vars: {},
    args: {},
    enable_tracing: false,
  },
  host: "",
  healthEndpoint: null,
  metricsEndpoint: null,
}));

test.describe("mobile layout", () => {
  for (const path of paths) {
    test(`${path} has no horizontal overflow`, async ({ page }) => {
      const shell = new AppShell(page);
      await shell.goto(path);
      await expect(shell.heading).toBeVisible();
      await shell.waitForLoaded();
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(
        overflow.scrollWidth,
        JSON.stringify(overflow)
      ).toBeLessThanOrEqual(overflow.clientWidth);
    });
  }

  test("/models/endpoints has no horizontal overflow with the toolbar mounted", async ({
    page,
  }) => {
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: MOCK_INSTANCES })
    );
    const shell = new AppShell(page);
    await shell.goto("/models/endpoints");
    await expect(shell.heading).toBeVisible();
    await shell.waitForLoaded();
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollWidth, JSON.stringify(overflow)).toBeLessThanOrEqual(
      overflow.clientWidth
    );
  });

  test("the hamburger opens the menu and navigates", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    await expect(shell.mobileMenuButton).toBeVisible();
    await shell.mobileMenuButton.click();
    const sheet = shell.dialog();
    await expect(sheet).toBeVisible();
    await sheet.getByRole("link", { name: "Notebooks" }).click();
    await expect(page).toHaveURL(/\/notebooks$/);
    await shell.expectHeading("Notebooks");
    await expect(sheet).toBeHidden();
  });
});
