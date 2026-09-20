import { test, expect } from "../fixtures";
import { ChatPage } from "../pages/chat";

// A function the user types: the model calls it, nothing runs, the user
// gives the result. The mock model calls the first tool it is offered
// when the message starts with "call ", with the rest of the text as
// the first argument, and answers "Tool said: <result>" afterwards.

test.describe("functions typed in the playground", () => {
  test("define a function, let the model call it, and answer with a result", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await chat.open("inst-mock");
    const functions = page.getByRole("group", { name: "Functions" });
    await functions.getByRole("button", { name: "Add function" }).click();

    const dialog = page.getByRole("dialog", { name: "Add function" });
    await dialog.getByLabel("Function name").fill("get-weather");
    await expect(dialog.getByRole("alert")).toContainText("letters, digits");
    await dialog.getByLabel("Function name").fill("get_weather");
    await dialog.getByLabel("What it does").fill("The weather in a city, now");
    await dialog.getByLabel("Parameters (JSON Schema)").fill("{ not json");
    await expect(dialog.getByRole("alert")).toContainText("not valid JSON");
    await expect(
      dialog.getByRole("button", { name: "Save function" })
    ).toBeDisabled();
    await dialog.getByLabel("Parameters (JSON Schema)").fill(
      JSON.stringify({
        type: "object",
        properties: { city: { type: "string" } },
        required: ["city"],
      })
    );
    await dialog.getByRole("button", { name: "Save function" }).click();
    await expect(
      functions.getByRole("switch", { name: "Use function get_weather" })
    ).toBeChecked();

    await chat.send("call Pune");
    const call = chat.toolCalls.first();
    await expect(call).toHaveAttribute("data-state", "yours");
    await expect(call).toContainText("get_weather");
    await expect(call).toContainText("waiting for your result");
    await expect(
      call.getByRole("group", { name: "Input of get_weather" })
    ).toContainText('"city": "Pune"');

    await call.getByLabel("Result of get_weather").fill('{"temperature": 31}');
    await call.getByRole("button", { name: "Send result" }).click();
    await expect(call).toHaveAttribute("data-state", "done");
    await expect(chat.assistantMessages.last()).toContainText(
      'Tool said: {"temperature": 31}'
    );

    // It is kept for this user; turned off, the model gets no tools.
    await page.reload();
    const use = functions.getByRole("switch", {
      name: "Use function get_weather",
    });
    await expect(use).toBeChecked();
    await use.click();
    await chat.send("call Mumbai");
    await expect(chat.assistantMessages.last()).toContainText(
      "You said: call Mumbai"
    );

    // Delete it again.
    await functions.getByRole("button", { name: "Edit get_weather" }).click();
    await page
      .getByRole("dialog", { name: "Edit function" })
      .getByRole("button", { name: "Delete function" })
      .click();
    await expect(functions).toContainText("Try a function-calling prompt");
  });
});
