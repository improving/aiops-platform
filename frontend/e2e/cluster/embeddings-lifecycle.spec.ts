import {
  test,
  expect,
  helmReleases,
  waitForHelmReleaseGone,
} from "../fixtures";

const READY_TIMEOUT = 12 * 60_000;
const MODEL_TAG = "all-minilm:33m";

test.describe("embeddings through LiteLLM", { tag: "@cluster" }, () => {
  test.setTimeout(20 * 60_000);
  const leftovers: string[] = [];
  test.afterEach(async ({ userApi }) => {
    for (const id of leftovers.splice(0)) {
      await (await userApi("admin")).deleteInferenceInstance(id);
      await waitForHelmReleaseGone(`ollama-${id.slice(0, 8)}`);
    }
  });

  test("launch an Ollama embedding model, embed two sentences, delete", async ({
    api,
  }) => {
    const model = (await api.models()).find((m) => m.modelId === MODEL_TAG);
    const engine = (await api.engines()).find((e) => e.name === "Ollama");
    expect(model && engine).toBeTruthy();
    const created = await api.createInferenceInstance({
      model: { id: model!.id },
      engine: { id: engine!.id },
      config: {},
    });
    leftovers.push(created.id);
    expect(helmReleases()).toContain(`ollama-${created.id.slice(0, 8)}`);
    await api.waitForInferenceReady(created.id, READY_TIMEOUT);
    const target = (await api.chatTargets()).find(
      (t) => t.instance_id === created.id
    );
    expect(target?.capability).toBe("embedding");
    const vectors = await api.embeddings(target!.name, [
      "hello world",
      "goodbye world",
    ]);
    expect(vectors).toHaveLength(2);
    expect(vectors[0]).toHaveLength(384);
    await api.deleteInferenceInstance(created.id);
    await waitForHelmReleaseGone(`ollama-${created.id.slice(0, 8)}`);
    leftovers.length = 0;
  });
});
