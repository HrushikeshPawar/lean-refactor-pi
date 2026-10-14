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
| `messages/assembly.assembled` | 13 | Agent messages and notices | when the matching event occurs |
| `messages/assembly.assembly_failed` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.best` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.compaction_header` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.hole` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.holes_heading` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.library` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.library_heading` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.map_heading` | 1 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.no_best` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.read` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.read_heading` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.seed_header` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.cause_clause` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.finish_available` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.points_left` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.request_failed` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.turn_ended_with_text` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.ambiguous_symbol` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.cold_session_unavailable` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.cold_verification_paused` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.command_failed` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.command_no_result` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.declaration_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_limit` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_missing` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_operation_text` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.empty_arguments` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.evaluation_mode` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.extra_command` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.fill_hole` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.fill_text` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.forbidden_construct` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.invalid_declaration` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.invalid_run_id` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.lean_context_timeout` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.lean_timeout` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.library_file_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.library_path` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.measure_version_missing` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.merge_operation_take` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.mode_invalid` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.module_missing` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.node_reference_invalid` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.operation_type_invalid` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.parent_ignored` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.pinned_project_path` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.pinned_statement_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_compile_failed` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_instrumentation_failed` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_proof_compile` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_requires_complete` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_timeout` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.project_file_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.proof_utility_parse` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.request` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_exists` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_theorem_mismatch` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_uninitialized` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_commit_mismatch` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_line_range` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_path_missing` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_range_order` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_search_failed` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_versions_changed` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.stall_target` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.stall_threshold` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.standalone_row` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.statement_modified_first` | 15 | Agent messages and notices | when the matching event occurs |
| `messages/errors.statement_modified_suffix` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.stopped_run` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.theorem_location_missing` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.toolchains_missing` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.turn_cut` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/footer` | 8 | Agent messages and notices | after each tool result |
| `messages/notices.block_shell` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/notices.block_workspace` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/notices.closest_tool` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/phase.stall_focus` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/run.preflight` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/run.resume` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/run.system_prompt` | 18 | Agent messages and notices | when the matching event occurs |
| `messages/salvage.salvaged` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/trim.result_stub` | 9 | Agent messages and notices | when a repeat is shortened |
| `packet/price-table` | 7 | Prices action replies | when the table is requested |
| `packet/price-table.legend` | 34 | Prices action replies | when the table is requested |
| `packet/price-table.row` | 7 | Prices action replies | when the table is requested |
| `packet/price-table.total` | 11 | Prices action replies | when the table is requested |
| `packet/scoring` | 144 | Initial theorem packet | once per run |
| `packet/sections.fixed.budget_certification_failed` | 8 | Initial theorem packet | once per run |
| `packet/sections.fixed.context_missing` | 4 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_intro` | 13 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_name` | 1 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_preview` | 9 | Initial theorem packet | once per run |
| `packet/sections.fixed.dependency_summary` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_conclusion` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_line` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_mention` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_reason` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_rewrite` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.earlier_usage` | 4 | Initial theorem packet | once per run |
| `packet/sections.fixed.goal` | 3 | Initial theorem packet | once per run |
| `packet/sections.fixed.goal_unavailable` | 1 | Initial theorem packet | once per run |
| `packet/sections.fixed.imports` | 3 | Initial theorem packet | once per run |
| `packet/sections.fixed.library_line` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.local_intro` | 15 | Initial theorem packet | once per run |
| `packet/sections.fixed.local_line` | 7 | Initial theorem packet | once per run |
| `packet/sections.fixed.namespace` | 2 | Initial theorem packet | once per run |
| `packet/sections.fixed.none` | 1 | Initial theorem packet | once per run |
| `packet/sections.fixed.packet_not_certifiable` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.pin` | 6 | Initial theorem packet | once per run |
| `packet/sections.fixed.pins` | 6 | Initial theorem packet | once per run |
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
| `packet/sections.required.environment` | 2 | Initial theorem packet | once per run |
| `packet/sections.required.reference` | 5 | Initial theorem packet | once per run |
| `packet/sections.required.source` | 2 | Initial theorem packet | once per run |
| `packet/sections.titles.dependencies` | 3 | Initial theorem packet | once per run |
| `packet/sections.titles.earlier` | 6 | Initial theorem packet | once per run |
| `packet/sections.titles.goals` | 4 | Initial theorem packet | once per run |
| `packet/sections.titles.library` | 3 | Initial theorem packet | once per run |
| `packet/sections.titles.locals` | 2 | Initial theorem packet | once per run |
| `packet/sections.titles.pinned` | 2 | Initial theorem packet | once per run |
| `packet/sections.titles.reference` | 7 | Initial theorem packet | once per run |
| `packet/sections.titles.scope` | 13 | Initial theorem packet | once per run |
| `packet/sections.titles.source` | 2 | Initial theorem packet | once per run |
| `packet/sections.titles.types` | 9 | Initial theorem packet | once per run |
| `packet/task` | 10 | Initial theorem packet | once per run |
| `replies/check.could_not_run` | 7 | Tool replies | when the matching tool result occurs |
| `replies/check.diagnostic` | 6 | Tool replies | when the matching tool result occurs |
| `replies/check.failed` | 10 | Tool replies | when the matching tool result occurs |
| `replies/check.passed` | 8 | Tool replies | when the matching tool result occurs |
| `replies/check.queued` | 5 | Tool replies | when the matching tool result occurs |
| `replies/merge.entry` | 5 | Tool replies | when the matching tool result occurs |
| `replies/merge.hypothesis` | 5 | Tool replies | when the matching tool result occurs |
| `replies/merge.none_checked` | 2 | Tool replies | when the matching tool result occurs |
| `replies/merge.not_submitted` | 9 | Tool replies | when the matching tool result occurs |
| `replies/merge.summary` | 9 | Tool replies | when the matching tool result occurs |
| `replies/price-row` | 20 | Compile replies | when a scored proof is compiled |
| `replies/price-row.changed` | 3 | Compile replies | when a scored proof is compiled |
| `replies/price-row.row_root` | 12 | Compile replies | when a scored proof is compiled |
| `replies/price-row.versions_full` | 1 | Compile replies | when a scored proof is compiled |
| `replies/price-row.versions_pending` | 4 | Compile replies | when a scored proof is compiled |
| `replies/tools.compile_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.duplicate` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_goal` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.errors_incomplete` | 6 | Tool replies | when the matching tool result occurs |
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
| `skill/SKILL` | 106 | Agent skill instructions | once per run |
| `skill/lean-facts` | 35 | Agent skill instructions | once per run |
| `tools/compile.description` | 29 | Model tool definitions | every request |
| `tools/compile.params.base` | 6 | Model tool definitions | every request |
| `tools/compile.params.check` | 11 | Model tool definitions | every request |
| `tools/compile.params.drafts` | 5 | Model tool definitions | every request |
| `tools/compile.params.fill` | 7 | Model tool definitions | every request |
| `tools/compile.params.fill_hole` | 6 | Model tool definitions | every request |
| `tools/compile.params.fill_text` | 5 | Model tool definitions | every request |
| `tools/compile.params.from` | 6 | Model tool definitions | every request |
| `tools/compile.params.merge` | 6 | Model tool definitions | every request |
| `tools/compile.params.merge_base` | 8 | Model tool definitions | every request |
| `tools/compile.params.merge_from` | 5 | Model tool definitions | every request |
| `tools/compile.params.merge_step` | 5 | Model tool definitions | every request |
| `tools/compile.params.merge_take` | 6 | Model tool definitions | every request |
| `tools/compile.params.note` | 5 | Model tool definitions | every request |
| `tools/compile.params.splice` | 8 | Model tool definitions | every request |
| `tools/compile.params.splice_base` | 8 | Model tool definitions | every request |
| `tools/compile.params.splice_steps` | 6 | Model tool definitions | every request |
| `tools/compile.params.splice_text` | 6 | Model tool definitions | every request |
| `tools/finish.description` | 22 | Model tool definitions | every request |
| `tools/goal.description` | 17 | Model tool definitions | every request |
| `tools/goal.params.hole` | 6 | Model tool definitions | every request |
| `tools/goal.params.line` | 7 | Model tool definitions | every request |
| `tools/goal.params.node` | 5 | Model tool definitions | every request |
| `tools/goal.params.try` | 8 | Model tool definitions | every request |
| `tools/read.description` | 12 | Model tool definitions | every request |
| `tools/read.params.against` | 6 | Model tool definitions | every request |
| `tools/read.params.handle` | 8 | Model tool definitions | every request |
| `tools/read.params.hole` | 6 | Model tool definitions | every request |
| `tools/read.params.node` | 5 | Model tool definitions | every request |
| `tools/read.params.view` | 7 | Model tool definitions | every request |
| `tools/search.description` | 12 | Model tool definitions | every request |
| `tools/search.params.after` | 5 | Model tool definitions | every request |
| `tools/search.params.kind` | 7 | Model tool definitions | every request |
| `tools/search.params.queries` | 7 | Model tool definitions | every request |
<!-- budget:end -->
