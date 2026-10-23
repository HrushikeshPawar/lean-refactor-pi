# Packet forensic audit — 2026-10-17

This audit measures the saved post-hook provider request bodies and their matching usage records. It replaces the earlier source-only packet estimates in the 16 October v8 design note for the run corpus listed here. The exact offline scanner and its generated summary are [scan.py](../../tools/audits/packet-forensics-2026-10-17/scan.py) and its generated [summary.json](../../tools/audits/packet-forensics-2026-10-17/summary.json).

## Coverage and method

The inspected corpus is the 29 run directories named v8, v8a, v8b, or v8c under runs/pi-budget. It contains 2,721 request records. All 29 trace journals reconstruct successfully through arena.traces.read_journal, which checks the stored SHA-256 after applying each delta. The raw request bytes can also be recovered with arena.traces.post_hook_bytes. This is the actual post-hook JSON payload passed toward the provider, not a reconstruction from packet templates.

Five requests have no matching response usage record: one v8 request, three v8a requests, and one v8b request. The remaining 2,716 requests have provider usage. Prompt-token totals below use the saved provider fields input + cache_read + cache_write; cache reuse uses the repository’s provider-standard formula in packages/arena-pi/extensions/spend.ts. No token counts are estimated from text length.

Every run’s saved packet.txt is present in its first provider request. The packet text occurs in 1,386 of all 2,721 request bodies. Later requests may carry a compacted or transformed context, so absence of the exact packet string does not prove that none of its facts survived.

## Measured sizes and usage

| Run family | Runs | Requests | Packet size per run, chars | Requests containing exact packet | Provider prompt tokens, median / max | Cache-read share |
|---|---:|---:|---:|---:|---:|---:|
| v8 | 1 | 1 | 19,426 | 1 / 1 | unavailable | unavailable |
| v8a | 19 | 2,081 | 19,426–61,159 | 1,168 / 2,081 (56.1%) | 44,767 / 377,059 | 95.4% |
| v8b | 4 | 200 | 20,736–41,119 | 85 / 200 (42.5%) | 36,703 / 84,037 | 94.6% |
| v8c | 5 | 439 | 24,361–41,288 | 132 / 439 (30.1%) | 32,625 / 76,248 | 95.0% |

The complete serialized request bodies have these median and maximum UTF-8 byte sizes: v8a 178,662 / 1,084,712; v8b 138,338 / 399,561; v8c 146,875 / 451,174. These bodies include the accumulated conversation, tool schemas, and request settings as well as the initial packet. For the five v8c runs, the first request body is 33,577–51,616 bytes and reports 10,088–17,474 input tokens. Those token counts describe the entire request, including developer text and tools, not the packet alone.

The known settled amounts in the matching response records sum to $23.77. This is a lower-bound ledger observation because the five usage holes have no corresponding settled response value in this trace view. It is not a packet-only cost. The records do not assign tokens or dollars to individual message fields, so a packet-specific token share or marginal cost cannot be computed from this evidence.

## What the requests contain

The v8c saved packet snapshots range from 24,361 to 41,288 characters. In every v8c run the first request’s user text matches packet.txt byte-for-byte. The same is true as a substring of the first request for each of the 29 runs. The five v8c requests use the same five-tool schema, whose compact JSON representation is 5,065 characters. v8a and v8b use provider-specific encodings of the same tool surface, measuring 5,060 or 5,125 characters. These schema sizes recur in later requests, but cache reads account for 94.6–95.4% of reported prompt tokens in v8a–v8c, so repeated text should not be treated as repeated uncached cost.

Full packet text appears in 56% of all v8a calls, 43% of all v8b calls, and 30% of all v8c calls; these denominators include first calls. This is consistent with the saved request history changing as context is compacted, but the count alone cannot establish whether the model retained each fact in its summary. It does show why the first packet size is not a sufficient proxy for every request’s context or cost: median full request bodies are 138–179 KB, and the largest v8-family body is 1,084,712 bytes with 377,059 provider-reported prompt tokens.

The v8c packet files end with a compact search map: best and original proof, proof shapes, latest nodes, and highest-value proof steps. These headings occupy a small tail of the packet; most characters precede the search map. That is a byte layout fact only. There is no controlled packet ablation in this corpus that would support calling the larger sections useful or wasteful.

## Conclusions and limits

- The packet is present in the first provider request in all 29 sessions. Its size varies from 19,426 to 61,159 Unicode characters; its separately measured UTF-8 size ranges from 21,561 to 63,157 bytes.
- The first request’s provider usage is a whole-request measurement. The available logs do not break token use down by packet, tool schema, or developer instructions.
- The later context often no longer contains the exact packet string. A summary may retain some of its information; this audit does not infer what survived.
- The runs are not a controlled comparison of packet variants. A lower or higher score cannot be attributed to packet content from these records alone.
- The five missing usage rows are listed by request in the underlying journals. Packet bytes remain recoverable and hash-verified for all five; their token usage and settled response amount are unavailable here.

For reproduction, load each run’s trace-journal.jsonl with arena.traces.read_journal, then join request.request_id to response.request_id. Use the parsed request’s input field or messages field according to provider, and count packet.txt occurrences in textual content. The reader’s hash check validates that the expanded body matches the request payload hash. Representative source records are runs/pi-budget/v8c-Core.InitsUpdatesComm-gpt-6.1-sol-r1/trace-journal.jsonl and runs/pi-budget/v8a-Core.InitsUpdatesComm-deepseek-v4.1-flash-r1/trace-journal.jsonl; the current request capture and restoration code is in packages/arena-pi/extensions/arena.ts and arena/traces.py.
