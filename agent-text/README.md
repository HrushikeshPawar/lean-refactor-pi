# Agent-facing text

This directory contains the exact text sent to the model. Keep templates logic-free: put conditionals, pluralization,
sorting, and ready-made fragments in Python or TypeScript, then pass the completed fragments as values.

## Editing templates

Each `.md` file is a template keyed by its path without the extension. Placeholders use `{name}` or `{name:fmt}`;
supported formats are `d`, `.Nf`, and `g`. Literal braces are written `{{` and `}}`. Rendering is strict: all
placeholders must be supplied by a value or `numbers.yaml`, and supplied values must be used.

YAML files contain maps with two-space indentation. Values are plain or JSON double-quoted strings, or `|-` / `|`
block scalars. `numbers.yaml` plain scalars are numbers and are available to every template. Do not add YAML features
such as lists, anchors, or flow style; both runtimes intentionally implement only this small subset.

The budget table counts whitespace-separated words in each raw template. Regenerate it with `arena text budget --write`.

<!-- budget:start -->
| Template | Words | Where shown | Per run |
| --- | ---: | --- | --- |
| `messages/arena-line` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.being_checked` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.best_verified` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.brief` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.brief_estimated` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.brief_proxy` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.join` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.leading_unverified` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.none` | 1 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.not_yet_checked` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/arena-line.only_spend` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/assembly.assembled` | 13 | Agent messages and notices | when the matching event occurs |
| `messages/assembly.assembly_failed` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.allowance` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.best_verified` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.blocker` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.failure` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.failures` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.header` | 24 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_best` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_empty` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_failure` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_more` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.ideas` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.leading_unverified` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.metrics_estimated` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.metrics_none` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.metrics_verified` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.none_verified` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.work` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.cause_clause` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.request_failed` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.turn_ended_with_text` | 13 | Agent messages and notices | when the matching event occurs |
| `messages/errors.ambiguous_symbol` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.arguments_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.cold_session_unavailable` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.cold_verification_paused` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.command_failed` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.command_no_result` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.decision_invalid` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.declaration_items` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.declaration_missing` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.declarations_usage` | 20 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_limit` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_missing` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_operation_text` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.empty_arguments` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.evaluation_mode` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.evaluation_proof_missing` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.evaluation_reference` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.extra_command` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.fill_hole` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.fill_text` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.find_limit` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.find_queries` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.forbidden_construct` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/errors.idea_id_label` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.idea_id_unknown` | 12 | Agent messages and notices | when the matching event occurs |
| `messages/errors.idea_reason` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.idea_statuses` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.idea_title_missing` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.invalid_declaration` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.invalid_declaration_cursor` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.invalid_run_id` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.lean_context_timeout` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.lean_timeout` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.library_file_missing` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.library_path` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.measure_version_missing` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.measurement_version_missing` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.merge_operation_take` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.mode_invalid` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.module_missing` | 16 | Agent messages and notices | when the matching event occurs |
| `messages/errors.name_not_visible` | 19 | Agent messages and notices | when the matching event occurs |
| `messages/errors.no_candidate_cold_passed` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/errors.no_candidate_passed` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.no_source_declaration` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.node_reference_invalid` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.operation_type_invalid` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.parent_ignored` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.pinned_project_path` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.pinned_statement_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.probe_forbidden` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.probe_parent_missing` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_candidate_missing` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_compile_failed` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_instrumentation_failed` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_proof_compile` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_requires_complete` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_timeout` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.project_file_missing` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.proof_utility_parse` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.request` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.resolve_name_timeout` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_exists` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_theorem_mismatch` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_uninitialized` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_uninitialized_theorem` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_commit_mismatch` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_line_range` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_path_missing` | 12 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_range_order` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_search_failed` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_versions_changed` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.stall_target` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.stall_threshold` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.standalone_row` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.statement_modified_first` | 28 | Agent messages and notices | when the matching event occurs |
| `messages/errors.statement_modified_suffix` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.stopped_run` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.theorem_location_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.toolchains_missing` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.turn_cut` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.unknown_candidate` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.unknown_candidate_short` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/errors.unknown_probe` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/footer` | 8 | Agent messages and notices | after each tool result |
| `messages/notices.block_shell` | 16 | Agent messages and notices | when the matching event occurs |
| `messages/notices.block_workspace` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/notices.closest_tool` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/notices.profile_degraded` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/phase.stall_focus` | 12 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.allowance` | 21 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.axes` | 26 | Agent messages and notices | when the matching event occurs |
| `messages/run.preflight` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/run.resume` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/salvage.salvaged` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/trim.repeated` | 7 | Agent messages and notices | when a repeat is shortened |
| `messages/trim.result_stub` | 14 | Agent messages and notices | when a repeat is shortened |
| `packet/inventory` | 34 | Initial theorem packet | once per run |
| `packet/library` | 35 | Initial theorem packet | once per run |
| `packet/price-table` | 7 | Prices action replies | when the table is requested |
| `packet/price-table.rates` | 18 | Prices action replies | when the table is requested |
| `packet/price-table.row` | 7 | Prices action replies | when the table is requested |
| `packet/price-table.total` | 6 | Prices action replies | when the table is requested |
| `packet/profile` | 40 | Initial theorem packet | once per run |
| `packet/rates` | 35 | Initial theorem packet | once per run |
| `packet/scoring` | 160 | Initial theorem packet | once per run |
| `packet/sections.fixed.budget_certification_failed` | 8 | Initial theorem packet | once per run |
| `packet/sections.fixed.context_missing` | 4 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_intro` | 14 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_name` | 1 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_preview` | 9 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_summary` | 16 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_conclusion` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_line` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_mention` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_reason` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_rewrite` | 1 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_usage` | 4 | Initial theorem packet | once per run |
| `packet/sections.fixed.goal` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.imports` | 3 | Initial theorem packet | once per run |
| `packet/sections.fixed.library_line` | 5 | Initial theorem packet | once per run |
| `packet/sections.fixed.local_intro` | 15 | Initial theorem packet | once per run |
| `packet/sections.fixed.local_line` | 7 | Initial theorem packet | once per run |
| `packet/sections.fixed.namespace` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.original` | 4 | Initial theorem packet | once per run |
| `packet/sections.fixed.packet_not_certifiable` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.pin` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.pins` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_cost` | 5 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_hotspot` | 16 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_missing` | 3 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_row` | 11 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_span` | 7 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_top` | 10 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_unavailable` | 10 | Initial theorem packet | once per run |
| `packet/sections.fixed.root_namespace` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.signature` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.source` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.standalone_source` | 11 | Initial theorem packet | once per run |
| `packet/sections.fixed.type_construct` | 4 | Initial theorem packet | once per run |
| `packet/sections.fixed.type_definition` | 5 | Initial theorem packet | once per run |
| `packet/sections.fixed.used_intro` | 24 | Initial theorem packet | once per run |
| `packet/sections.fixed.used_line` | 4 | Initial theorem packet | once per run |
| `packet/sections.fixed.used_preview` | 11 | Initial theorem packet | once per run |
| `packet/sections.required.dependencies` | 3 | Initial theorem packet | once per run |
| `packet/sections.required.environment` | 4 | Initial theorem packet | once per run |
| `packet/sections.required.reference` | 2 | Initial theorem packet | once per run |
| `packet/sections.required.source` | 2 | Initial theorem packet | once per run |
| `packet/sections.titles.dependencies` | 3 | Initial theorem packet | once per run |
| `packet/sections.titles.earlier` | 6 | Initial theorem packet | once per run |
| `packet/sections.titles.goals` | 9 | Initial theorem packet | once per run |
| `packet/sections.titles.inventory` | 3 | Initial theorem packet | once per run |
| `packet/sections.titles.library` | 9 | Initial theorem packet | once per run |
| `packet/sections.titles.locals` | 2 | Initial theorem packet | once per run |
| `packet/sections.titles.pinned` | 4 | Initial theorem packet | once per run |
| `packet/sections.titles.profile` | 6 | Initial theorem packet | once per run |
| `packet/sections.titles.reference` | 4 | Initial theorem packet | once per run |
| `packet/sections.titles.scope` | 13 | Initial theorem packet | once per run |
| `packet/sections.titles.source` | 2 | Initial theorem packet | once per run |
| `packet/sections.titles.types` | 9 | Initial theorem packet | once per run |
| `packet/task` | 110 | Initial theorem packet | once per run |
| `replies/candidate.original_reference` | 4 | Tool replies | when the matching tool result occurs |
| `replies/check.could_not_run` | 7 | Tool replies | when the matching tool result occurs |
| `replies/check.failed` | 6 | Tool replies | when the matching tool result occurs |
| `replies/check.passed` | 7 | Tool replies | when the matching tool result occurs |
| `replies/check.queued` | 10 | Tool replies | when the matching tool result occurs |
| `replies/evaluate.calibration_pending` | 5 | Tool replies | when the matching tool result occurs |
| `replies/evaluate.diagnostic_headline` | 6 | Tool replies | when the matching tool result occurs |
| `replies/merge.entry` | 5 | Tool replies | when the matching tool result occurs |
| `replies/merge.hypothesis` | 5 | Tool replies | when the matching tool result occurs |
| `replies/merge.none_checked` | 2 | Tool replies | when the matching tool result occurs |
| `replies/merge.not_submitted` | 7 | Tool replies | when the matching tool result occurs |
| `replies/merge.summary` | 9 | Tool replies | when the matching tool result occurs |
| `replies/price-row` | 16 | Compile replies | when a scored proof is compiled |
| `replies/price-row.changed` | 3 | Compile replies | when a scored proof is compiled |
| `replies/price-row.row_root` | 9 | Compile replies | when a scored proof is compiled |
| `replies/price-row.versions_full` | 1 | Compile replies | when a scored proof is compiled |
| `replies/price-row.versions_pending` | 4 | Compile replies | when a scored proof is compiled |
| `replies/probe.complete_candidate` | 7 | Tool replies | when the matching tool result occurs |
| `replies/profile.degraded` | 7 | Tool replies | when the matching tool result occurs |
| `replies/profile.floor_method` | 6 | Tool replies | when the matching tool result occurs |
| `replies/profile.hotspot_label` | 6 | Tool replies | when the matching tool result occurs |
| `replies/profile.unit` | 13 | Tool replies | when the matching tool result occurs |
| `replies/routes.best_proxy` | 4 | Tool replies | when the matching tool result occurs |
| `replies/routes.credited_tag` | 1 | Tool replies | when the matching tool result occurs |
| `replies/routes.no_scored_proof` | 3 | Tool replies | when the matching tool result occurs |
| `replies/routes.none` | 1 | Tool replies | when the matching tool result occurs |
| `replies/routes.not_credited_tag` | 2 | Tool replies | when the matching tool result occurs |
| `replies/routes.original_tag` | 2 | Tool replies | when the matching tool result occurs |
| `replies/routes.row` | 6 | Tool replies | when the matching tool result occurs |
| `replies/routes.state_count` | 4 | Tool replies | when the matching tool result occurs |
| `replies/state.advisory` | 15 | Tool replies | when the matching tool result occurs |
| `replies/state.cold_compile_without_session` | 5 | Tool replies | when the matching tool result occurs |
| `replies/state.no_candidate_cold_passed` | 14 | Tool replies | when the matching tool result occurs |
| `replies/state.no_candidate_passed` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.compile_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.duplicate` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_goal` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.errors_incomplete` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.filed_focus` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.filed_root` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_draft` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_fill` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_focus` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_merge` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_root` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_splice` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.finish_archive` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.finish_points` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.goal_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.handles` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.hole_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_archive` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_best` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_effort` | 12 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_hole` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_recent` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.no_goal` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.price` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_diff` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_hole` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_node_source` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_price_row` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_source` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_step` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.same_diagnostic` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.same_goal` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_hint` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_hit` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_miss` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.timeout` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_item` | 8 | Tool replies | when the matching tool result occurs |
| `skill/SKILL` | 739 | Agent skill instructions | once per run |
| `tools/compile.description` | 13 | Model tool definitions | every request |
| `tools/compile.params.base` | 5 | Model tool definitions | every request |
| `tools/compile.params.check` | 8 | Model tool definitions | every request |
| `tools/compile.params.drafts` | 9 | Model tool definitions | every request |
| `tools/compile.params.fill` | 7 | Model tool definitions | every request |
| `tools/compile.params.fill_hole` | 6 | Model tool definitions | every request |
| `tools/compile.params.fill_text` | 6 | Model tool definitions | every request |
| `tools/compile.params.from` | 7 | Model tool definitions | every request |
| `tools/compile.params.merge` | 6 | Model tool definitions | every request |
| `tools/compile.params.merge_base` | 9 | Model tool definitions | every request |
| `tools/compile.params.merge_from` | 5 | Model tool definitions | every request |
| `tools/compile.params.merge_step` | 4 | Model tool definitions | every request |
| `tools/compile.params.merge_take` | 6 | Model tool definitions | every request |
| `tools/compile.params.note` | 3 | Model tool definitions | every request |
| `tools/compile.params.splice` | 10 | Model tool definitions | every request |
| `tools/compile.params.splice_base` | 9 | Model tool definitions | every request |
| `tools/compile.params.splice_steps` | 7 | Model tool definitions | every request |
| `tools/compile.params.splice_text` | 6 | Model tool definitions | every request |
| `tools/finish.description` | 16 | Model tool definitions | every request |
| `tools/goal.description` | 13 | Model tool definitions | every request |
| `tools/goal.params.hole` | 6 | Model tool definitions | every request |
| `tools/goal.params.line` | 6 | Model tool definitions | every request |
| `tools/goal.params.node` | 3 | Model tool definitions | every request |
| `tools/goal.params.try` | 7 | Model tool definitions | every request |
| `tools/read.description` | 13 | Model tool definitions | every request |
| `tools/read.params.against` | 7 | Model tool definitions | every request |
| `tools/read.params.handle` | 5 | Model tool definitions | every request |
| `tools/read.params.hole` | 3 | Model tool definitions | every request |
| `tools/read.params.node` | 3 | Model tool definitions | every request |
| `tools/read.params.view` | 7 | Model tool definitions | every request |
| `tools/search.description` | 10 | Model tool definitions | every request |
| `tools/search.params.after` | 5 | Model tool definitions | every request |
| `tools/search.params.kind` | 6 | Model tool definitions | every request |
| `tools/search.params.queries` | 5 | Model tool definitions | every request |
<!-- budget:end -->
