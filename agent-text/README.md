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
| `messages/compaction-memory.allowance` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.best_verified` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.blocker` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.failure` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.failures` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.header` | 25 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_best` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_empty` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_failure` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.idea_more` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.ideas` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.leading_unverified` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.metrics_estimated` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.metrics_none` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.metrics_verified` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.none_verified` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.routes` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/compaction-memory.work` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/continuation` | 15 | Agent messages and notices | when the matching event occurs |
| `messages/errors.ambiguous_symbol` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.cold_session_unavailable` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.cold_verification_paused` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.command_no_result` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.decision_invalid` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.declaration_items` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.declaration_missing` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.declarations_usage` | 20 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_limit` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.draft_missing` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.evaluation_mode` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.evaluation_proof_missing` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.evaluation_reference` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.extra_command` | 7 | Agent messages and notices | when the matching event occurs |
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
| `messages/errors.mode_invalid` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.module_missing` | 16 | Agent messages and notices | when the matching event occurs |
| `messages/errors.name_not_visible` | 19 | Agent messages and notices | when the matching event occurs |
| `messages/errors.no_candidate_cold_passed` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/errors.no_candidate_passed` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.no_source_declaration` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.parent_ignored` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.pinned_project_path` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.pinned_statement_missing` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.probe_forbidden` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.probe_parent_missing` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_candidate_missing` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_compile_failed` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_instrumentation_failed` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_proof_compile` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_requires_complete` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.profile_timeout` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.project_file_missing` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.proof_utility_parse` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.resolve_name_timeout` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_exists` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_theorem_mismatch` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_uninitialized` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/errors.run_uninitialized_theorem` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.select_target` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/errors.skill_directory` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.skill_missing` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/errors.skill_path` | 15 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_commit_mismatch` | 10 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_line_range` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_path_missing` | 12 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_range_order` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_search_failed` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/errors.source_versions_changed` | 7 | Agent messages and notices | when the matching event occurs |
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
| `messages/footer` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/notices.auto_idea_abandoned` | 12 | Agent messages and notices | when the matching event occurs |
| `messages/notices.auto_idea_parked` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/notices.auto_idea_succeeded` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/notices.block_shell` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/notices.block_workspace` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/notices.closest_tool` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/notices.evaluate_parent` | 13 | Agent messages and notices | when the matching event occurs |
| `messages/notices.evaluate_parents` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/notices.evaluate_usage` | 12 | Agent messages and notices | when the matching event occurs |
| `messages/notices.finish_reminder` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/notices.finish_review` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/notices.finish_review_action` | 20 | Agent messages and notices | when the matching event occurs |
| `messages/notices.idea_missing` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/notices.lean_path` | 26 | Agent messages and notices | when the matching event occurs |
| `messages/notices.probe_combined` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/notices.probe_limit` | 9 | Agent messages and notices | when the matching event occurs |
| `messages/notices.probe_missing` | 4 | Agent messages and notices | when the matching event occurs |
| `messages/notices.probe_placeholder` | 8 | Agent messages and notices | when the matching event occurs |
| `messages/notices.profile_degraded` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/notices.profile_trimmed` | 25 | Agent messages and notices | when the matching event occurs |
| `messages/notices.stale_route` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.allowance` | 21 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.axes` | 26 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.continuation` | 11 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.finish` | 5 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.idea_row` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.ideas_tried` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.none_recorded` | 2 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.routes_none` | 1 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.routes_row` | 6 | Agent messages and notices | when the matching event occurs |
| `messages/refusals.routes_tried` | 3 | Agent messages and notices | when the matching event occurs |
| `messages/trim.repeated` | 7 | Agent messages and notices | when the matching event occurs |
| `messages/trim.result_stub` | 14 | Agent messages and notices | when the matching event occurs |
| `messages/trim.skill_stub` | 15 | Agent messages and notices | when the matching event occurs |
| `messages/trim.warning_cut` | 9 | Agent messages and notices | when the matching event occurs |
| `packet/inventory` | 34 | Initial theorem packet | once per run |
| `packet/library` | 35 | Initial theorem packet | once per run |
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
| `packet/task` | 184 | Initial theorem packet | once per run |
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
| `skill/SKILL` | 1202 | Agent skill instructions | once per run |
| `tools/arena_candidate.description` | 23 | Model tool definitions | every request |
| `tools/arena_candidate.params.candidate` | 3 | Model tool definitions | every request |
| `tools/arena_declarations.description` | 29 | Model tool definitions | every request |
| `tools/arena_evaluate.description` | 109 | Model tool definitions | every request |
| `tools/arena_evaluate.params.candidate` | 5 | Model tool definitions | every request |
| `tools/arena_evaluate.params.from_probe` | 5 | Model tool definitions | every request |
| `tools/arena_evaluate.params.idea` | 12 | Model tool definitions | every request |
| `tools/arena_evaluate.params.proof` | 6 | Model tool definitions | every request |
| `tools/arena_find.description` | 48 | Model tool definitions | every request |
| `tools/arena_finish.description` | 86 | Model tool definitions | every request |
| `tools/arena_idea.description` | 103 | Model tool definitions | every request |
| `tools/arena_probe.description` | 104 | Model tool definitions | every request |
| `tools/arena_probe.params.idea` | 12 | Model tool definitions | every request |
| `tools/arena_profile.description` | 59 | Model tool definitions | every request |
| `tools/arena_skill_read.description` | 24 | Model tool definitions | every request |
| `tools/arena_source.description` | 37 | Model tool definitions | every request |
| `tools/arena_state.description` | 28 | Model tool definitions | every request |
<!-- budget:end -->
