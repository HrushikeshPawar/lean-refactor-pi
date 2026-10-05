/** Offline Pi integration fixture. Never load this extension for a paid run. */
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function fakeOpenCode(pi: ExtensionAPI) {
  pi.registerProvider("opencode-go", {
    api: "openai-responses", apiKey: "offline-test", baseUrl: "http://127.0.0.1:0",
    models: [{ id: "gpt-6-luna", name: "Offline Luna fixture", reasoning: true,
      input: ["text"], cost: { input: 0.20, output: 0.75, cacheRead: 0.02, cacheWrite: 0.25 },
      contextWindow: 1_050_000, maxTokens: 128_000 }],
    streamSimple(model, context, options) {
      const stream = createAssistantMessageEventStream();
      void (async () => {
        try {
          const payload = await options?.onPayload?.({ model: model.id, input: context.messages,
            max_output_tokens: options.maxTokens ?? 128_000 });
          if (!payload || (payload as { max_output_tokens?: number }).max_output_tokens !== 16_000) {
            throw new Error("Arena did not enforce the fake provider output ceiling");
          }
          if (process.env.ARENA_FAKE_CRASH === "1") process.exit(23);
          if (process.env.ARENA_FAKE_ERROR === "1") throw new Error("Offline provider failure with unknown usage");
          const message = { role: "assistant" as const, content: [{ type: "text" as const, text: "Offline fixture response." }],
            api: model.api, provider: model.provider, model: model.id,
            usage: { input: 100, output: 10, cacheRead: 0, cacheWrite: 0, totalTokens: 110,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
            stopReason: "stop" as const, timestamp: Date.now() };
          stream.push({ type: "start", partial: { ...message, content: [] } });
          stream.push({ type: "text_start", contentIndex: 0, partial: message });
          stream.push({ type: "text_end", contentIndex: 0, content: message.content[0].text, partial: message });
          stream.push({ type: "done", reason: "stop", message });
        } catch (error) {
          stream.push({ type: "error", reason: "error", error: {
            role: "assistant", content: [], api: model.api, provider: model.provider, model: model.id,
            usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
            stopReason: "error", errorMessage: String(error), timestamp: Date.now() } });
        } finally { stream.end(); }
      })();
      return stream;
    },
  });
}
