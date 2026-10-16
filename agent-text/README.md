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
| `messages/continuation.finish_available` | 28 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.focus_material` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.focus_moved` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.request_failed` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.restart` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.skeleton` | 17 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.turn_cut` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/continuation.turn_ended_with_text` | 14 | Agent messages and notices | when the matching event occurs |
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
| `messages/errors.goal_blocked` | 19 | Agent messages and notices | when the matching event occurs |
| `messages/errors.goal_position` | 14 | Agent messages and notices | when the matching event occurs |
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
| `messages/errors.request_bare` | 4 | Agent messages and notices | when the matching event occurs |
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
| `messages/errors.turn_cut` | 23 | Agent messages and notices | when the matching event occurs |
| `messages/footer` | 8 | Agent messages and notices | after each tool result |
| `messages/notices.block_shell` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/notices.block_workspace` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/notices.closest_tool` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/phase.route_tally` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/phase.stall_focus` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/prior-work.call` | 3 | Initial theorem packet | once per seeded run |
| `messages/prior-work.digest_heading` | 8 | Initial theorem packet | once per seeded run |
| `messages/prior-work.heading` | 32 | Initial theorem packet | once per seeded run |
| `messages/prior-work.map_heading` | 7 | Initial theorem packet | once per seeded run |
| `messages/prior-work.omitted` | 6 | Initial theorem packet | once per seeded run |
| `messages/prior-work.reasoning` | 2 | Initial theorem packet | once per seeded run |
| `messages/prior-work.result` | 2 | Initial theorem packet | once per seeded run |
| `messages/prior-work.said` | 2 | Initial theorem packet | once per seeded run |
| `messages/prior-work.turn` | 2 | Initial theorem packet | once per seeded run |
| `messages/run.preflight` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/run.resume` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/run.system_prompt` | 18 | Agent messages and notices | when the matching event occurs |
| `messages/salvage.fill_many` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/salvage.fill_none` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/salvage.fill_one` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/salvage.salvaged` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/salvage.salvaged_unseen` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/trim.result_stub` | 9 | Agent messages and notices | when a repeat is shortened |
| `packet/price-table` | 16 | Prices action replies | when the table is requested |
| `packet/price-table.legend` | 34 | Prices action replies | when the table is requested |
| `packet/price-table.row` | 15 | Prices action replies | when the table is requested |
| `packet/price-table.total` | 19 | Prices action replies | when the table is requested |
| `packet/restart.island_blank` | 29 | Initial theorem packet | once per run |
| `packet/restart.island_start` | 22 | Initial theorem packet | once per run |
| `packet/restart.island_statement` | 6 | Initial theorem packet | once per run |
| `packet/restart.prices_heading` | 6 | Initial theorem packet | once per run |
| `packet/restart.start` | 18 | Initial theorem packet | once per run |
| `packet/restart.tried_failed` | 2 | Initial theorem packet | once per run |
| `packet/restart.tried_heading` | 10 | Initial theorem packet | once per run |
| `packet/restart.tried_line` | 5 | Initial theorem packet | once per run |
| `packet/restart.tried_no_gain` | 7 | Initial theorem packet | once per run |
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
| `packet/sections.fixed.profile_line` | 11 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_selfref` | 33 | Initial theorem packet | once per run |
| `packet/sections.fixed.profile_total` | 22 | Initial theorem packet | once per run |
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
| `packet/sections.titles.profile` | 5 | Initial theorem packet | once per run |
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
| `replies/merge.not_submitted` | 2 | Tool replies | when the matching tool result occurs |
| `replies/merge.submitted` | 2 | Tool replies | when the matching tool result occurs |
| `replies/merge.summary` | 9 | Tool replies | when the matching tool result occurs |
| `replies/price-row` | 18 | Compile replies | when a scored proof is compiled |
| `replies/price-row.changed` | 3 | Compile replies | when a scored proof is compiled |
| `replies/price-row.parenthesis` | 1 | Compile replies | when a scored proof is compiled |
| `replies/price-row.row_root` | 12 | Compile replies | when a scored proof is compiled |
| `replies/price-row.versions_full` | 1 | Compile replies | when a scored proof is compiled |
| `replies/price-row.versions_pending` | 4 | Compile replies | when a scored proof is compiled |
| `replies/price-row.vs_best` | 3 | Compile replies | when a scored proof is compiled |
| `replies/price-row.vs_node` | 3 | Compile replies | when a scored proof is compiled |
| `replies/tools.compile_filed` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.compile_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.duplicate` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_branches` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_goal` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_main_goal_open` | 11 | Tool replies | when the matching tool result occurs |
| `replies/tools.error_same` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.errors_incomplete` | 13 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_draft` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_fill` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_focus` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_merge` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_root` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.filing_splice` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.finish_archive` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.finish_points` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.goal_cases_omitted` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.goal_hyps_omitted` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.goal_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.goal_map_case` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.goal_map_untagged` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.goal_untagged` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.hb_pending` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.hole_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.lean_messages` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_archive` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_best` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_best_head` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_effort` | 12 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_hole` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_hole_goal` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_holes_head` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_lines_note` | 34 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_origin_from` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_origin_root` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_quiet_line` | 9 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_quiet_lines_cols` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_quiet_lines_head` | 15 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_quiet_lines_note` | 27 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_recent` | 13 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_recent_head` | 18 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_recent_salvage` | 20 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_reference` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_repeated_head` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_repeated_line` | 9 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_routes` | 20 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_shape` | 13 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_shapes` | 38 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_step` | 15 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_steps_cols` | 17 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_steps_head` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_steps_legend` | 40 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_steps_more` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_steps_untried` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_steps_untried_item` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_tactic_line` | 9 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_tactic_lines_head` | 22 | Tool replies | when the matching tool result occurs |
| `replies/tools.map_unchanged` | 14 | Tool replies | when the matching tool result occurs |
| `replies/tools.merge_offer` | 13 | Tool replies | when the matching tool result occurs |
| `replies/tools.no_goal` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.open_holes` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.outcome_broken` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.outcome_closed` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.outcome_ineligible` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.outcome_sketch` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.outcome_sketch_one` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.outcome_sketch_open` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.outcome_timeout` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.own_theorem` | 12 | Tool replies | when the matching tool result occurs |
| `replies/tools.price` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_diff` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_hole` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_node_source` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_outline_cols` | 15 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_outline_cut` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_outline_hint` | 18 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_outline_row` | 13 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_price_row` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_range` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_source` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_step` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_step_after` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_step_before` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_tree_cols` | 17 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_tree_head` | 34 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_tree_more` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_tree_pending` | 15 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_tree_row` | 15 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_tree_total` | 23 | Tool replies | when the matching tool result occurs |
| `replies/tools.read_tree_total_floor` | 22 | Tool replies | when the matching tool result occurs |
| `replies/tools.refresh_tail` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.repeat_fact` | 16 | Tool replies | when the matching tool result occurs |
| `replies/tools.same_diagnostic` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.same_goal` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_also` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_decl_cost` | 11 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_failed` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_info_cols` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_info_row` | 7 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_message` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_ok` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_repeat` | 12 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_result` | 5 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_result_body` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_timeout` | 9 | Tool replies | when the matching tool result occurs |
| `replies/tools.scratch_unknown_names` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_cols` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_form` | 17 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_head` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_hint` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_miss` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_missing` | 8 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_place` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_result` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.search_row` | 9 | Tool replies | when the matching tool result occurs |
| `replies/tools.section_map` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.section_result` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.section_updates` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.source_line` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.timeout` | 11 | Tool replies | when the matching tool result occurs |
| `replies/tools.token_draft` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.token_fill` | 6 | Tool replies | when the matching tool result occurs |
| `replies/tools.token_splice` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_closed` | 1 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_error` | 2 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_goals_cut` | 10 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_item` | 4 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_open` | 3 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_replaces` | 29 | Tool replies | when the matching tool result occurs |
| `replies/tools.try_timeout` | 2 | Tool replies | when the matching tool result occurs |
| `skill/SKILL` | 155 | Agent skill instructions | once per run |
| `skill/lean-facts` | 137 | Agent skill instructions | once per run |
| `tools/compile.description` | 29 | Model tool definitions | every request |
| `tools/compile.params.base` | 6 | Model tool definitions | every request |
| `tools/compile.params.check` | 11 | Model tool definitions | every request |
| `tools/compile.params.drafts` | 16 | Model tool definitions | every request |
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
| `tools/goal.description` | 41 | Model tool definitions | every request |
| `tools/goal.params.hole` | 6 | Model tool definitions | every request |
| `tools/goal.params.line` | 7 | Model tool definitions | every request |
| `tools/goal.params.node` | 5 | Model tool definitions | every request |
| `tools/goal.params.try` | 10 | Model tool definitions | every request |
| `tools/read.description` | 13 | Model tool definitions | every request |
| `tools/read.params.against` | 6 | Model tool definitions | every request |
| `tools/read.params.handle` | 13 | Model tool definitions | every request |
| `tools/read.params.hole` | 6 | Model tool definitions | every request |
| `tools/read.params.node` | 5 | Model tool definitions | every request |
| `tools/read.params.step` | 7 | Model tool definitions | every request |
| `tools/read.params.view` | 14 | Model tool definitions | every request |
| `tools/scratch.description` | 47 | Model tool definitions | every request |
| `tools/scratch.params.code` | 15 | Model tool definitions | every request |
| `tools/search.description` | 12 | Model tool definitions | every request |
| `tools/search.params.after` | 14 | Model tool definitions | every request |
| `tools/search.params.kind` | 7 | Model tool definitions | every request |
| `tools/search.params.queries` | 7 | Model tool definitions | every request |
<!-- budget:end -->
