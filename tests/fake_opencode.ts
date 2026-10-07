/** Offline Pi integration fixture. Never load this extension for a paid run.
 *
 * Scripted mode: ARENA_FAKE_SCRIPT points at a JSON array of steps. Each step is
 *   { text?, tool_calls?: [{ name, arguments }], usage?: { input, output, cacheRead, cacheWrite },
 *     error?: string, delay_ms?: number }
 * A step is consumed per provider request; once exhausted the model answers with plain text and stops.
 * ARENA_FAKE_LOG receives one JSON line per request: the full message transcript and thinking level.
 *
 * Wire mode: ARENA_FAKE_WIRE_URL points at a local HTTP server (tests/pi_support.py AnthropicWire).
 * Qwen is then served by Pi's real Anthropic Messages client, so the exact payload Pi and the
 * budget guard build is what the server validates.
 */
import { appendFileSync, readFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Step = {
  text?: string;
  tool_calls?: Array<{ name: string; arguments: Record<string, unknown>; raw_arguments?: string }>;
  usage?: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number };
  error?: string;
  delay_ms?: number;
};

// Fixture prices equal Arena's ledger, as Pi's real opencode-go catalog must.
export default function fakeOpenCode(pi: ExtensionAPI) {
  let request = 0;
  const script: Step[] = process.env.ARENA_FAKE_SCRIPT
    ? JSON.parse(readFileSync(process.env.ARENA_FAKE_SCRIPT, "utf8")) : [];
  const zeroCost = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 };
  const pad = Number(process.env.ARENA_TRACE_PAD ?? "0");
  if (pad > 0) {
    pi.registerTool({
      name: "arena_trace_pad",
      label: "Arena trace pad",
      description: "Test-only pad used to prove a tool result longer than 20,000 characters is kept. Not an Arena product tool.",
      parameters: Type.Object({}),
      async execute() {
        return { content: [{ type: "text" as const, text: "P".repeat(pad) }], details: {} };
      },
    });
  }
  if (process.env.ARENA_FAKE_WIRE_URL) {
    pi.registerProvider("opencode-go", {
      api: "anthropic-messages", apiKey: "offline-test", baseUrl: process.env.ARENA_FAKE_WIRE_URL,
      models: [{ id: "qwen3.8-flash", name: "Offline Qwen wire fixture", api: "anthropic-messages",
        baseUrl: process.env.ARENA_FAKE_WIRE_URL, reasoning: true, input: ["text"],
        compat: { allowEmptySignature: true },
        cost: { input: 0.15, output: 0.47, cacheRead: 0.016, cacheWrite: 0.20 },
        contextWindow: 1_000_000, maxTokens: 131_072 }],
    });
    return;
  }
  pi.registerProvider("opencode-go", {
    api: "openai-responses", apiKey: "offline-test", baseUrl: "http://127.0.0.1:0",
    models: [{ id: "gpt-6-luna", name: "Offline Luna fixture", reasoning: true,
      input: ["text"], cost: { input: 0.10, output: 0.50, cacheRead: 0.01, cacheWrite: 0.125 },
      contextWindow: 1_050_000, maxTokens: 128_000 }],
    streamSimple(model, context, options) {
      const stream = createAssistantMessageEventStream();
      // Pi's own summarization requests (compaction) carry no system sections; they are answered
      // with plain text and do not consume a scripted step.
      const first = context.messages[0] as unknown as { sections?: Record<string, unknown> } | undefined;
      const summarizing = !first?.sections || Object.keys(first.sections).length === 0;
      const step: Step | undefined = summarizing ? { text: "Offline summary of the earlier turns." } : script[request];
      const index = summarizing ? -1 - request : request++;
      void (async () => {
        try {
          const input = [...context.messages];
          const padInput = Number(process.env.ARENA_FAKE_PAD_INPUT ?? "0");
          if (padInput > 0) input.push({ role: "user", content: "x".repeat(padInput) } as never);
          const payload = await options?.onPayload?.({ model: model.id, input,
            max_output_tokens: options.maxTokens ?? 128_000 });
          if (!payload || Number((payload as { max_output_tokens?: number }).max_output_tokens) > 16_000) {
            throw new Error("Arena did not enforce the fake provider output ceiling");
          }
          if (process.env.ARENA_FAKE_LOG) {
            const requestShape = { max_output_tokens: (payload as any)?.max_output_tokens ?? null,
              max_tokens: (payload as any)?.max_tokens ?? null,
              thinking: (payload as any)?.thinking ?? null,
              reasoning: (payload as any)?.reasoning ?? null };
            appendFileSync(process.env.ARENA_FAKE_LOG, `${JSON.stringify({ index,
              thinking: options?.reasoning ?? null, tools: (context.tools ?? []).map(tool => tool.name),
              request_shape: requestShape, messages: context.messages })}\n`);
          }
          if (process.env.ARENA_FAKE_CRASH === "1") process.exit(23);
          if (process.env.ARENA_FAKE_ERROR === "1") throw new Error("Offline provider failure with unknown usage");
          if (step?.delay_ms) await new Promise(done => setTimeout(done, step.delay_ms));
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
              const call = step?.tool_calls?.[number];
              if (call?.raw_arguments !== undefined) {
                stream.push({ type: "toolcall_delta", contentIndex: number, delta: call.raw_arguments,
                  partial: message as never });
              }
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
