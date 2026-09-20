import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class ChatPage extends AppShell {
  readonly targetSelect: Locator;
  readonly input: Locator;
  readonly sendButton: Locator;
  readonly stopButton: Locator;
  readonly clearButton: Locator;
  readonly systemPrompt: Locator;
  readonly conversation: Locator;
  readonly messages: Locator;
  readonly assistantMessages: Locator;
  readonly emptyState: Locator;
  readonly waiting: Locator;
  readonly speed: Locator;
  readonly toolCalls: Locator;
  readonly tools: Locator;
  readonly toolsButton: Locator;
  readonly settings: Locator;
  readonly settingsButton: Locator;
  readonly toolsOn: Locator;
  readonly contextMeter: Locator;
  readonly starterPrompts: Locator;

  constructor(page: Page) {
    super(page);
    this.targetSelect = page.getByRole("combobox", { name: "Target" });
    this.input = page.getByRole("textbox", { name: "Message" });
    this.sendButton = page.getByRole("button", { name: "Send" });
    this.stopButton = page.getByRole("button", { name: "Stop" });
    this.clearButton = page.getByRole("button", {
      name: "Clear conversation",
    });
    this.systemPrompt = page.getByRole("textbox", { name: "System prompt" });
    this.conversation = page.getByRole("log", { name: "Conversation" });
    this.messages = this.conversation.getByTestId("chat-message");
    this.assistantMessages = this.conversation.locator(
      '[data-testid="chat-message"][data-role="assistant"]'
    );
    this.emptyState = page.getByText("No running inference instance");
    this.waiting = page.getByRole("status", { name: "Waiting for the model" });
    this.speed = this.conversation.getByTestId("chat-speed");
    this.toolCalls = this.conversation.getByTestId("chat-tool-call");
    // In a popover of the composer's row: `openTools()` first.
    this.tools = page.getByRole("group", { name: "Tools", exact: true });
    this.toolsButton = page.getByRole("button", { name: /^Tools/ });
    // In a sheet: `openSettings()` first, and `closeSettings()` before
    // anything on the page behind it (`send()` does that itself).
    this.settings = page.getByRole("dialog", { name: "Settings" });
    this.settingsButton = page.getByRole("button", {
      name: "Settings",
      exact: true,
    });
    this.toolsOn = page.getByTestId("chat-tools-on");
    this.contextMeter = page.getByTestId("chat-context");
    this.starterPrompts = page
      .getByRole("group", { name: "Starter prompts" })
      .getByRole("button");
  }

  async open(target?: string) {
    await this.goto(target ? `/chat?target=${target}` : "/chat");
  }

  async selectTarget(label: string | RegExp) {
    await this.targetSelect.click();
    await this.page.getByRole("option", { name: label }).click();
  }

  /** The Tools popover of the composer's row, open. */
  async openTools() {
    // The sheet is modal: nothing behind it takes a click.
    await this.closeSettings();
    if (!(await this.tools.isVisible())) await this.toolsButton.click();
    await this.tools.waitFor();
  }

  async closeTools() {
    if (await this.tools.isVisible()) {
      await this.page.keyboard.press("Escape");
      await this.tools.waitFor({ state: "hidden" });
    }
  }

  /** The Settings sheet (system prompt, temperature, max tokens, the
      two switches), open. */
  async openSettings() {
    await this.closeTools();
    if (!(await this.settings.isVisible())) await this.settingsButton.click();
    await this.settings.waitFor();
  }

  async closeSettings() {
    if (await this.settings.isVisible()) {
      await this.page.keyboard.press("Escape");
      await this.settings.waitFor({ state: "hidden" });
    }
  }

  async send(text: string) {
    // A sheet is modal, and a popover would take the first click.
    await this.closeSettings();
    await this.closeTools();
    await this.input.fill(text);
    await this.sendButton.click();
  }
}
