/** Offline Pi integration fixture. Never load this extension for a paid run.
 *
 * Scripted mode: ARENA_FAKE_SCRIPT points at a JSON array of steps. Each step is
 *   { text?, tool_calls?: [{ name, arguments }], usage?: { input, output, cacheRead, cacheWrite },
 *     error?: string }
 * A step is consumed per provider request; once exhausted the model answers with plain text and stops.
 * ARENA_FAKE_LOG receives one JSON line per request: the full message transcript and thinking level.
 */
import { appendFileSync, readFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Step = {
  text?: string;
  tool_calls?: Array<{ name: string; arguments: Record<string, unknown> }>;
  usage?: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number };
  error?: string;
};

export default function fakeOpenCode(pi: ExtensionAPI) {
  let request = 0;
  const script: Step[] = process.env.ARENA_FAKE_SCRIPT
    ? JSON.parse(readFileSync(process.env.ARENA_FAKE_SCRIPT, "utf8")) : [];
  const zeroCost = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 };
  pi.registerProvider("opencode-go", {
    api: "openai-responses", apiKey: "offline-test", baseUrl: "http://127.0.0.1:0",
    models: [{ id: "gpt-6-luna", name: "Offline Luna fixture", reasoning: true,
      input: ["text"], cost: { input: 0.20, output: 0.75, cacheRead: 0.02, cacheWrite: 0.25 },
      contextWindow: 1_050_000, maxTokens: 128_000 }],
    streamSimple(model, context, options) {
      const stream = createAssistantMessageEventStream();
      const step: Step | undefined = script[request];
      const index = request++;
      void (async () => {
        try {
          const payload = await options?.onPayload?.({ model: model.id, input: context.messages,
            max_output_tokens: options.maxTokens ?? 128_000 });
          if (!payload || (payload as { max_output_tokens?: number }).max_output_tokens !== 16_000) {
            throw new Error("Arena did not enforce the fake provider output ceiling");
          }
          if (process.env.ARENA_FAKE_LOG) {
            appendFileSync(process.env.ARENA_FAKE_LOG, `${JSON.stringify({ index,
              thinking: options?.reasoning ?? null, messages: context.messages })}\n`);
          }
          if (process.env.ARENA_FAKE_CRASH === "1") process.exit(23);
          if (process.env.ARENA_FAKE_ERROR === "1") throw new Error("Offline provider failure with unknown usage");
          if (step?.error) throw new Error(step.error);
          const content: Array<Record<string, unknown>> = [];
          if (step?.text || !step?.tool_calls?.length) {
            content.push({ type: "text", text: step?.text ?? "Offline fixture response." });
          }
          (step?.tool_calls ?? []).forEach((call, number) => content.push({
            type: "toolCall", id: `fake-${index}-${number}`, name: call.name, arguments: call.arguments }));
          const usage = { input: 100, output: 10, cacheRead: 0, cacheWrite: 0, ...step?.usage };
          const message = { role: "assistant" as const, content: content as never, api: model.api,
            provider: model.provider, model: model.id,
            usage: { ...usage, totalTokens: usage.input + usage.output + usage.cacheRead + usage.cacheWrite,
              cost: zeroCost },
            stopReason: step?.tool_calls?.length ? "toolUse" as const : "stop" as const,
            timestamp: Date.now() };
          stream.push({ type: "start", partial: { ...message, content: [] } });
          content.forEach((block, number) => {
            if (block.type === "text") {
              stream.push({ type: "text_start", contentIndex: number, partial: message });
              stream.push({ type: "text_end", contentIndex: number, content: String(block.text), partial: message });
            } else {
              stream.push({ type: "toolcall_start", contentIndex: number, partial: message });
              stream.push({ type: "toolcall_end", contentIndex: number, toolCall: block as never, partial: message });
            }
          });
          stream.push({ type: "done", reason: message.stopReason, message });
        } catch (error) {
          stream.push({ type: "error", reason: "error", error: {
            role: "assistant", content: [], api: model.api, provider: model.provider, model: model.id,
            usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: zeroCost },
            stopReason: "error", errorMessage: String(error), timestamp: Date.now() } });
        } finally { stream.end(); }
      })();
      return stream;
    },
  });
}
