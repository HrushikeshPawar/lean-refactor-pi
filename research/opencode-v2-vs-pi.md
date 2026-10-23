# OpenCode v2 vs Pi for the Arena runner

Primary vendor sources checked live on 2026-10-16. This is a docs-level comparison; it does not measure runtime behavior or inspect the Arena adapter.

## Short answer

Using DeepSeek V4.1 Flash Free does not by itself require replacing Pi. OpenCode v2's Console catalog lists the exact model ID `deepseek-v4.1-flash-free` at an OpenAI-compatible Chat Completions endpoint. Pi documents `models.json` support for OpenAI-compatible endpoints. So the smallest experiment is to add the provider/model configuration to Pi and verify authentication, tool calls, and accounting with a bounded smoke run. OpenCode Console is explicitly usable by other coding agents. ([OpenCode Console model catalog](https://opencode.ai/v2/docs/console/models), [Pi model configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md))

## The model and the plan

- The current v2 Console page lists **DeepSeek V4.1 Flash Free**, ID `deepseek-v4.1-flash-free`, endpoint `https://opencode.ai/inference/openai/v1/chat/completions`, with the `@ai-sdk/openai-compatible` package. Its listed input, output, and cached-read prices are Free. The page says it is free for a limited time, and says this provider has zero retention and does not use data for training. ([Console model catalog](https://opencode.ai/v2/docs/console/models))
- The v2 docs distinguish **Console** from **OpenCode Go**: Console uses credits and pay-as-you-go billing, while Go is a subscription (currently $10/month, with a $40/month Go Plus tier). Go's current list includes DeepSeek V4.1 Flash, without the `-free` model ID; it does not list DeepSeek V4.1 Flash Free. ([Console billing and model list](https://opencode.ai/v2/docs/console/models), [Go plans and model list](https://opencode.ai/v2/docs/console/go))
- Thus “Zen sub” may conflate two things: the free model is currently documented in the v2 **Console** catalog, while the subscription is **Go**. The docs provide no quota or throughput commitment for the limited-time free model, so its present free price is not a durable run-volume guarantee. The catalog and prices can change.

## What a runtime swap buys, and what changes

| | Pi | OpenCode v2 |
|---|---|---|
| Embedding | Pi's TypeScript SDK embeds a session in Node.js or Bun and exposes the agent, session, tools, models, resources, events, and persistent or in-memory session managers. ([Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)) | `@opencode/sdk` embeds an OpenCode host in-process; it exposes a generated client with session/event aliases and async event streams. ([OpenCode embedded SDK](https://opencode.ai/v2/docs/build/sdk/)) |
| Custom behavior | Pi extensions register tools and providers, observe/intercept lifecycle events, change context, and manage session state. ([Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)) | OpenCode plugins can add tools and hooks and transform agents, models, and other behavior. The v2 SDK accepts plugins at host startup. ([Plugins](https://opencode.ai/v2/docs/plugins), [SDK](https://opencode.ai/v2/docs/build/sdk/)) |
| Model choice | Compatible endpoints can be described in `models.json`; custom streaming or authentication needs a provider extension. ([Pi models](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md), [Pi custom providers](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/custom-provider.md)) | Built-in catalog, configurable providers, and a dedicated Console model catalog; providers and models have their own config contracts. ([Providers](https://opencode.ai/v2/docs/providers), [models](https://opencode.ai/v2/docs/models)) |

**Pros of moving:** OpenCode gives the framework a documented embedded host, generated session/event client, and plugin system alongside its broader provider/model catalog and native coding-agent capabilities. That may be attractive if Arena wants to adopt more of OpenCode's session, permission, worktree, or tool infrastructure, not just its model gateway. ([SDK](https://opencode.ai/v2/docs/build/sdk/), [tools](https://opencode.ai/v2/docs/tools))

**Cons of moving:** It is a runtime integration change, not a model-provider swap. Pi exposes its own session, event, extension, persistence, and provider contracts; OpenCode exposes a different SDK client, plugin, session, and tool contract. Inference: Arena-specific code coupled to Pi's context assembly, event interpretation, tool lifecycle, retries, or ledger would need an adapter or rewrite and fresh behavior/accounting validation. The published SDK docs do not claim Pi compatibility.

OpenCode's own v2 migration guide confirms that its v1 plugin API and server API have new contracts in v2. That is a separate migration warning for any OpenCode v1 integration; it does not establish the cost of replacing Pi. ([OpenCode v1-to-v2 migration guide](https://opencode.ai/v2/docs/migrate-v1))

## Practical recommendation

First test `deepseek-v4.1-flash-free` through Pi's compatible-provider configuration. This isolates the question “does this model improve or expand our pattern experiments?” from “should Arena change agent runtimes?” Consider a runtime port only if OpenCode's embedded session/tool/plugin capabilities are independently valuable and after comparing the current Pi adapter against those contracts. Treat free availability as temporary and recheck the model list before planning a large campaign.
