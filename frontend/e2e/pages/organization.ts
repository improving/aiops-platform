import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class OrganizationPage extends AppShell {
  readonly inviteButton: Locator;
  readonly createOrganizationButton: Locator;
  readonly membersTable: Locator;
  readonly invitationsTable: Locator;

  constructor(page: Page) {
    super(page);
    this.inviteButton = page.getByRole("button", { name: "Invite" });
    this.createOrganizationButton = page.getByRole("button", {
      name: "Create organization",
    });
    this.membersTable = page.getByRole("table", { name: "Members" });
    this.invitationsTable = page.getByRole("table", { name: "Invitations" });
  }

  async open() {
    await this.goto("/organization");
  }

  memberRow(email: string): Locator {
    return this.membersTable.locator("tbody tr").filter({ hasText: email });
  }

  invitationRow(email: string): Locator {
    return this.invitationsTable.locator("tbody tr").filter({ hasText: email });
  }

  async invite(email: string, role: "admin" | "member" | "viewer") {
    await this.inviteButton.click();
    const dialog = this.page.getByRole("dialog", { name: "Invite a member" });
    await dialog.getByRole("textbox", { name: "Email" }).fill(email);
    await dialog.getByRole("combobox", { name: "Role" }).click();
    await this.page.getByRole("option", { name: role, exact: true }).click();
    await dialog.getByRole("button", { name: "Send invitation" }).click();
    await dialog.waitFor({ state: "hidden" });
  }

  async withdraw(email: string) {
    await this.invitationRow(email)
      .getByRole("button", { name: "Withdraw" })
      .click();
    // Not confirmDelete(): the dialog title here is "Withdraw invitation",
    // not the shared DeleteButton default "Confirm Deletion".
    const dialog = this.page.getByRole("dialog", {
      name: "Withdraw invitation",
    });
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
  }

  async createOrganization(slug: string, name: string) {
    await this.createOrganizationButton.click();
    const dialog = this.page.getByRole("dialog", {
      name: "Create organization",
    });
    await dialog.getByRole("textbox", { name: "Slug" }).fill(slug);
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await Promise.all([
      this.page.waitForEvent("load"),
      dialog.getByRole("button", { name: "Create", exact: true }).click(),
    ]);
    await this.openUserMenu();
  }
}
