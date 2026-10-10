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
| Template | Words |
| --- | ---: |
| `messages/compaction-memory.allowance` | 7 |
| `messages/compaction-memory.best_verified` | 9 |
| `messages/compaction-memory.blocker` | 2 |
| `messages/compaction-memory.failure` | 3 |
| `messages/compaction-memory.failures` | 3 |
| `messages/compaction-memory.header` | 25 |
| `messages/compaction-memory.idea` | 6 |
| `messages/compaction-memory.idea_best` | 2 |
| `messages/compaction-memory.idea_empty` | 3 |
| `messages/compaction-memory.idea_failure` | 3 |
| `messages/compaction-memory.idea_more` | 2 |
| `messages/compaction-memory.ideas` | 2 |
| `messages/compaction-memory.leading_unverified` | 4 |
| `messages/compaction-memory.metrics_estimated` | 11 |
| `messages/compaction-memory.metrics_none` | 2 |
| `messages/compaction-memory.metrics_verified` | 8 |
| `messages/compaction-memory.none_verified` | 6 |
| `messages/compaction-memory.routes` | 5 |
| `messages/compaction-memory.work` | 9 |
| `packet/inventory` | 34 |
| `packet/library` | 35 |
| `packet/profile` | 40 |
| `packet/rates` | 35 |
| `packet/scoring` | 160 |
| `packet/sections.fixed.context_missing` | 4 |
| `packet/sections.fixed.dependency_intro` | 14 |
| `packet/sections.fixed.dependency_name` | 1 |
| `packet/sections.fixed.dependency_preview` | 9 |
| `packet/sections.fixed.dependency_summary` | 16 |
| `packet/sections.fixed.earlier_conclusion` | 2 |
| `packet/sections.fixed.earlier_line` | 6 |
| `packet/sections.fixed.earlier_mention` | 2 |
| `packet/sections.fixed.earlier_reason` | 2 |
| `packet/sections.fixed.earlier_rewrite` | 1 |
| `packet/sections.fixed.earlier_usage` | 4 |
| `packet/sections.fixed.goal` | 6 |
| `packet/sections.fixed.imports` | 3 |
| `packet/sections.fixed.library_line` | 5 |
| `packet/sections.fixed.local_intro` | 15 |
| `packet/sections.fixed.local_line` | 7 |
| `packet/sections.fixed.namespace` | 2 |
| `packet/sections.fixed.original` | 4 |
| `packet/sections.fixed.pins` | 6 |
| `packet/sections.fixed.profile_cost` | 5 |
| `packet/sections.fixed.profile_hotspot` | 16 |
| `packet/sections.fixed.profile_missing` | 3 |
| `packet/sections.fixed.profile_row` | 11 |
| `packet/sections.fixed.profile_top` | 10 |
| `packet/sections.fixed.profile_unavailable` | 10 |
| `packet/sections.fixed.root_namespace` | 2 |
| `packet/sections.fixed.signature` | 6 |
| `packet/sections.fixed.source` | 2 |
| `packet/sections.fixed.standalone_source` | 11 |
| `packet/sections.fixed.type_construct` | 4 |
| `packet/sections.fixed.type_definition` | 5 |
| `packet/sections.fixed.used_intro` | 24 |
| `packet/sections.fixed.used_line` | 4 |
| `packet/sections.fixed.used_preview` | 11 |
| `packet/sections.required.dependencies` | 3 |
| `packet/sections.required.environment` | 4 |
| `packet/sections.required.reference` | 2 |
| `packet/sections.required.source` | 2 |
| `packet/sections.titles.dependencies` | 3 |
| `packet/sections.titles.earlier` | 6 |
| `packet/sections.titles.goals` | 9 |
| `packet/sections.titles.inventory` | 3 |
| `packet/sections.titles.library` | 9 |
| `packet/sections.titles.locals` | 2 |
| `packet/sections.titles.pinned` | 4 |
| `packet/sections.titles.profile` | 6 |
| `packet/sections.titles.reference` | 4 |
| `packet/sections.titles.scope` | 13 |
| `packet/sections.titles.source` | 2 |
| `packet/sections.titles.types` | 9 |
| `packet/task` | 184 |
| `skill/SKILL` | 1202 |
<!-- budget:end -->
