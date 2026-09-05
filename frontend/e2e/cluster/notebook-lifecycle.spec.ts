import { test, expect, shortId } from "../fixtures";
import { NotebookFormPage } from "../pages/notebook-form";
import { NotebookListPage, NotebookDetailsPage } from "../pages/notebooks";

const CREATE_TIMEOUT = 2 * 60_000;
const RUNNING_TIMEOUT = 6 * 60_000;
const DELETE_TIMEOUT = 2 * 60_000;

const kinds = [
  { type: "jupyter", option: "Jupyter" as const },
  { type: "vscode", option: "VSCode" as const },
];

test.describe("notebook lifecycle", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });

  const leftovers: string[] = [];

  // Notebooks are visible to their owner and org admins only, so the
  // automation user behind `api` neither sees nor may delete alice's;
  // clean up as admin.
  test.afterEach(async ({ userApi }) => {
    const admin = await userApi("admin");
    for (const id of leftovers.splice(0)) {
      await admin.deleteNotebook(id);
      await expect
        .poll(async () => (await admin.notebooks()).map((n) => n.id), {
          timeout: DELETE_TIMEOUT,
        })
        .not.toContain(id);
    }
  });

  for (const kind of kinds) {
    test(`create a ${kind.type} notebook, wait until Running, then delete it`, async ({
      page,
      userApi,
    }) => {
      const name = `e2e-${kind.type}-${shortId()}`;
      // The owner's view of the API: the automation user cannot see it.
      const api = await userApi("alice");

      const form = new NotebookFormPage(page);
      await form.open();
      await form.name.fill(name);
      if (kind.option !== "Jupyter") {
        await form.selectType(kind.option);
      } else {
        await expect(form.gpuSwitch).not.toBeChecked();
      }
      await expect(form.cpu).toHaveValue("0.5");
      await expect(form.memory).toHaveValue("1");
      await expect(form.storage).toHaveValue("5");
      await form.launchButton.click();

      await expect(form.toast("Notebook created")).toBeVisible({
        timeout: CREATE_TIMEOUT,
      });
      await expect(page).toHaveURL(/\/notebooks$/);

      const record = (await api.notebooks()).find((n) => n.name === name);
      expect(record, `notebook ${name} exists in the API`).toBeTruthy();
      const id = record!.id;
      leftovers.push(id);

      // The list shows it; the title link opens the details page.
      const list = new NotebookListPage(page);
      await expect(list.notebookLink(name)).toBeVisible();
      await list.notebookLink(name).click();
      await expect(page).toHaveURL(new RegExp(`/notebooks/${id}$`));

      const details = new NotebookDetailsPage(page);
      await details.expectHeading("Notebook Details");
      await expect(details.field("Type")).toHaveText(kind.type);
      await expect(details.field("Nvidia GPU")).toHaveText("No");

      // The details page does not poll; wait through the API, then reload.
      await api.waitForNotebookStatus(id, "Running", RUNNING_TIMEOUT);
      await page.reload();
      await expect(details.field("Status")).toHaveText("Running");
      await expect(details.connectButton).toBeEnabled();

      await details.deleteButton.click();
      await details.confirmDelete(DELETE_TIMEOUT);
      await expect(details.toast("Item deleted successfully")).toBeVisible();
      await expect(page).toHaveURL(/\/notebooks$/);
      await expect(list.notebookLink(name)).toHaveCount(0);

      await expect
        .poll(async () => (await api.notebooks()).map((n) => n.id), {
          timeout: DELETE_TIMEOUT,
        })
        .not.toContain(id);
      if ((await api.notebooks()).length === 0) {
        await page.reload();
        await expect(list.emptyState).toBeVisible();
      }
      leftovers.length = 0;
    });
  }
});
