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
  }

  async open(instanceId?: string) {
    await this.goto(instanceId ? `/chat?instance=${instanceId}` : "/chat");
  }

  async selectTarget(label: string | RegExp) {
    await this.targetSelect.click();
    await this.page.getByRole("option", { name: label }).click();
  }

  async send(text: string) {
    await this.input.fill(text);
    await this.sendButton.click();
  }
}
