# V8 shared implementation contracts

Status: accepted handoff contracts for the local implementation tickets. Proposed APIs/modules are not claims of existing code. The numbered tickets contain their current entry points, per-ticket contract and one fast smoke.


### S1. Retain the existing ledger and file-lock model

Existing `arena/campaign.py::_append` appends and fsyncs JSONL; `_file_node` separately locks graph filing. Keep those storage conventions rather than adding a second database. Introduce proposed `arena/run_control.py` for run-scoped operation receipts, serialized state transitions and shared spend. Preserve existing original records and raw artifacts; do not rewrite old lines into the new envelope.

Use a distinct `control.lock` to serialize v8 read/modify/write decisions. All participating processes use the same lock ordering: control, then graph filing, then the short ledger append lock. Do not reacquire control recursively through an unmodified helper. Pass a locked-operation context to internal append/file helpers. Persist operation intent, exact event/artifact references, then a commit receipt before acknowledging success. Each v8 operation's records include its operation identity. Replay publishes only committed v8 operations; legacy records keep their old interpretation. On crash, a complete intent can be reconciled or an incomplete operation marked aborted; never infer author approval from a partial append. Loop on partial writes and preserve an incomplete trailing record as diagnostic evidence rather than silently rewriting it.

Proposed control API responsibilities are `read_state(run)`, `apply_operation(run, operation, changes)`, `settle_usage(run, settlement)`, `begin_dispatch(run, request)`, `mark_dispatch_started(run, grant)`, and `submit_candidate(run, attempt)`. These are an organizing seam, not seven unrelated stores. The commit receipt returns operation identity, event sequence range, status and stable evidence references. Same identity/same canonical argument digest reuses its receipt; same identity/different digest returns `operation_conflict`.

Use fields `schema_version`, `event_id`, `event_seq`, `operation_id`, `run_id`, `actor_id`, `session_id`, optional `job_id` and `activation_id`, `kind`, and typed `data`. Event order comes from the durable sequence, not timestamps. A raw-record reference includes ledger byte range/hash so original serialized lineage remains retrievable. Proof identity remains the existing target/proof identity; attempts and derivations have separate identities. No mutable focus field belongs in the canonical proof identity.

### S2. Shared spend and dispatch ordering

Store reported monetary amounts as decimal strings and sum them with decimal arithmetic. Preserve the original provider usage object as evidence. A settlement has request identity or explicit covered-request identities, reported cost, accounting state `known` or `unknown`, and evidence references. Actual zero is `known` zero. Invalid/missing values are unknown, not a numeric zero. Late actual information adds a reconciliation record; it does not mutate an original report or charge it again.

For dispatch ordering, distinguish a prepared request from a dispatch grant and actual transport start. The short dispatch guard serializes grants/start with settlement/stop commits; it does not reserve dollars and is not held for a response. Hold that ordering boundary until the actor has invoked its transport and acknowledged start, or until a launch failure is reconciled. A stale generation cannot use a grant. Failure before start is recorded; uncertain dispatch remains unknown. Broker/actor failure cannot leave an indefinite lock: recovery fences dispatch and resolves the owned activation before replacement.

A run-scoped coordinator owned by the runner hosts management and asynchronous notifications. Keep this separate from the machine-wide Lean service. Proposed `arena/orchestration.py` owns job state and the control transport; proposed `arena/pi_rpc.py` owns child RPC I/O. Run-scoped control accepts local JSONL requests over a private Unix socket, with operation IDs and one complete reply per request; long `await_results` is cancellable. Never log provider credentials. Protocol/tool subprocesses and Pi extensions use the same control boundary, not separate session totals. This is local coordination, not a new model or MCP subsystem.

### S3. Verified provider gate route

The installed Pi 1.3.0 extension API supports `registerProvider` with `api` and `streamSimple`. Its model registry exposes `getProvider`. The provider composer dispatches ordinary and direct runtime requests through the configured provider; `ModelRuntime.streamSimple` also serves direct summary work. The current `before_provider_request` event handler is a notification/payload path whose error is swallowed, so it cannot enforce a veto.

Implement the gate in proposed `packages/arena-pi/extensions/provider_gate.ts`. Capture the existing configured provider object before registering its wrapper; call that captured object, never recursively resolve the newly wrapped provider. Preserve provider ID, models, OAuth/auth resolution, base URL, headers, transcript, signals, callbacks and price metadata. Pass an injected `fetch` through the supported stream options so each actual HTTP attempt, including adapter-internal retries, enters the dispatch guard. Preserve an existing custom fetch when present; otherwise delegate to the original fetch implementation. Request identity groups transport attempts, and every attempt has its own dispatch reference. Provider-level/grouped usage identifies covered attempts rather than duplicating the same total.

Keep Pi's retry policy. Do not wrap only the outer stream and assume it covers HTTP retries: OpenAI completion/response adapters run `retryProviderRequest`, and `onPayload` occurs before that retry loop. Denial must prevent the captured fetch call, abort the request cleanly and notify the coordinator; it must not become another retry that can bypass the guard. The focused smoke uses a stub captured fetch and a stop committed between two attempts, asserting the second fetch never executes. The current fake-provider helper prices DeepSeek directly; extend its final-E2E fixture to use the requested model for mixed Sol/DeepSeek runs. Actual Pi/OAuth/summary coverage is deferred to final E2E; source inspection alone is not an integration result. If an adapter ignores the supported fetch override, report that concrete adapter gap rather than claiming enforcement or changing authentication routes.

Verified installed source symbols are `ExtensionAPI.registerProvider`, `ProviderConfig.streamSimple`, `ModelRegistry.getProvider`, `composeModelProvider`, `ModelRuntime.streamSimple`, `retryProviderRequest`, and the `FetchFunction` stream option. Do not modify the operator's installed Pi files; the wrapper belongs in the repository extension.

### S4. Worker process policy

Launch a fresh child with RPC mode, explicit session directory/model/provider and the worker tool allowlist. Persist launch intent first. The runner/coordinator is the sole owner of activation and concurrency decisions. Workers use inherited run-control access, actor/session/job IDs and explicit immutable anchors; no worker starts its own coordinator.

Subscribe/read before prompting. Split stdout only on LF bytes, preserve UTF-8 partial chunks and Unicode separators inside JSON, accept CRLF, and keep stderr diagnostic. Correlate command IDs separately from session events. A `handled` prompt does not produce a run to await. `agent_settled` closes an assignment activation; process exit remains independently observable. Same-hypothesis follow-up reuses its saved Pi session and creates a new activation. A distinct hypothesis gets a fresh session.

On coordinator restart do not try to attach to abandoned stdin/stdout pipes. Fence dispatch, identify old owned process groups using stored PID plus Linux process-start identity and run generation, stop only a positively identified owned group, confirm exit, reconcile its journals, then resume the saved Pi session in a replacement child if its last request is not ambiguous. Never resend an uncertain provider request. Inject process reads/signals in tests. Unknown owned-child/request state remains a recovery/accounting failure, not permission to create an extra activation.

### S5. Scratch input and promotion mapping

Proposed request forms are mutually exclusive: general exploration uses `code`; an anchored replacement uses `at` plus `replacement`. `at` resolves to immutable parent proof and exactly one step range or hole. A job may supply that anchor, but it is resolved and recorded before execution. `helpers` contains explicit experiment/declaration references. The harness adds actor/job/operation identities. Reject ambiguous mixed input forms rather than guessing which portion replaces the proof.

Code-only `#check`, `#print` and examples remain valid isolated experiments. Anchored mode reconstructs the candidate from the exact saved parent and supplied replacement, so the real parent context is preserved rather than recreated from printed goals. A complete target theorem in code-only mode can promote only when target and exact body extraction are unambiguous. No automatic extraction of arbitrary examples or free-form helper code.

Resolve helpers to retained artifacts. Inline a helper only when it can be represented legally inside the target proof and all dependencies are explicit. Otherwise return `helper_not_embeddable` or `dependency_missing`; do not add forbidden top-level declarations or invent a general Lean source transformer. Route the resulting exact proof through normal compile/submission once, reusing matching-context evidence when available rather than blindly compiling twice.

The reply identifies experiment, local outcome, promotion state, reason when absent, attempt/proof/derivation/evaluation references and verification coverage. Submit under the same control stop boundary. After stop, keep experiment evidence and return `run_stopped`; no new candidate or authorizing attempt is created.

### S6. Scope and error contracts

Actor delivery state is keyed by actor identity, not one run-global cursor. `delivered_reply` commits the cursor and exact evidence references; replay may redeliver an identity after a transport failure. Observations and hypotheses are referenced, not copied into every node. Sol replaces strategy; workers append attributed observations.

Use stable categories `invalid_input`, `operation_conflict`, `busy`, `not_found`, `no_pending_work`, `run_stopped`, `recovery_required`, and `accounting_unknown` at management/control boundaries. Tool-specific error details remain attached. Search no-match is a normal empty result; incomplete goal trials are `open`, not input errors. Evaluation outcomes are `passed`, `proof_error`, or `inconclusive` with timeout/resource/worker/context causes. None substitutes for all-pin/cold acceptance.

For basic Lean priority use a request class separate from existing lane: `sol_foreground`, `full_check`, `ds_experiment`, `opportunistic`, in that order for queued dispatch. Preserve FIFO inside a class. Never preempt an executing Lean operation unsafely. Keep existing lane/header matching and machine-memory/worker-token checks; initially permit one DS Lean compilation. Record queue/admission reasons. The optional later retention/concurrency experiment must not silently change defaults.

### S7. Initial public management shapes and delivery semantics

| Operation | Caller inputs | Normalized/returned contract |
|---|---|---|
| delegate, fresh | task string, scope proof or step, optional at object | at has node and, for step scope, exactly one steps range or hole. Resolve default actor-local parent and any job-supplied anchor immediately. Persist immutable proof/step hashes and exact source range; return job_id, activation_id, session_id, state and evidence references. |
| delegate, follow-up | job_id and task string | Same hypothesis/session/anchor, new activation; incompatible scope/anchor changes are invalid_input and a currently active follow-up is busy. No implicit steering. |
| jobs | optional job_ids list, optional cursor | Read-only snapshots plus retained applicable events and next_cursor. No provider requests. Sol manages all its delegated jobs; worker proof tools may read shared evidence without acquiring management powers. |
| await_results | optional job_ids list, optional cursor | Events plus wake_reason result/settled/cancelled/failed/run_stopped/no_pending_work. Missing cursor uses the actor's last committed delivery state. |
| cancel | job_id | Durable cancellation receipt and current state; cancelling retains a model slot until positively observed exit. |
| scratch, general | code string, optional explicit helper references | Isolated experiment; exact input retained. Promote a full target proof only when its exact extraction and scope are unambiguous. |
| scratch, anchored | replacement string, at object or inherited immutable job step anchor, optional helper references | Replace the exact range/hole in saved parent context and use ordinary compile/submission once. code and replacement forms are mutually exclusive. |

A control response has ok, operation_id, state or result items, evidence_refs, next_cursor and shared-spend accounting state. Errors carry a stable category and specific reason without losing already-recorded experiment evidence. The proof-tool reply keeps its existing top-level facts/items/map/handles convention while adding typed evidence references, not an unrelated envelope for each tool.

Cursor is an opaque actor-owned delivery-state reference, not merely the greatest global sequence seen. Persist a contiguous acknowledged high-water mark plus sparse delivered event identities where needed. A filtered wait/read acknowledges only events actually delivered in that reply; it must not consume an earlier finding from another job. The same actor can later request all jobs and still receive those unrelated findings. Commit this acknowledgement with the delivered reply, and allow idempotent redelivery after a transport crash. No extra model acknowledgement call is introduced.

