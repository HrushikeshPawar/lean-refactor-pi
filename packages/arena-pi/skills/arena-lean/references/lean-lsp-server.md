# Lean tools in the Arena

The Lean language server runs on the candidate file the harness materializes: the pinned source file
with your current candidate (or restored probe) in place of the original proof, truncated after the
theorem. `arena_evaluate`, `arena_probe` and `arena_candidate` return its path as `candidate_path`,
with the theorem's `start_line` and `end_line`. Diagnostics from the harness use the same line numbers
(`file_line`), so you can query exactly the line that failed.

You have five Lean tools. Nothing else from the Lean server is available, and there is no shell:
compile with `arena_probe` / `arena_evaluate`, profile with `arena_profile`.

| Tool | Use | Arguments |
|------|-----|-----------|
| `lean_goal` | Goal state at a line (before and after it), or at a column | `file_path`, `line`, optional `column` |
| `lean_diagnostic_messages` | Errors and warnings in the file, optionally for a line range | `file_path`, optional `start_line`, `end_line` |
| `lean_multi_attempt` | Try several replacement tactics at one line without editing anything; returns the goal or error each one leaves | `file_path`, `line`, `snippets` (list of tactic strings) |
| `lean_hover_info` | Type and docstring of the identifier at a position | `file_path`, `line`, `column` (start of the identifier) |
| `lean_local_search` | Declarations in the project and its dependencies by name or prefix | `query`, optional `limit` |

`arena_declaration` returns a declaration's exact source signature, including constructors and
library lemmas. `arena_source` reads pinned project files by line range.

## Workflow

1. Before changing a step, read its goal with `lean_goal` at that line.
2. To compare alternatives for one step, call `lean_multi_attempt` with all of them at once. It is much
   cheaper than one probe per alternative, and it does not change the candidate.
3. Assemble the edit into a full proof and run `arena_probe` (holes allowed) or `arena_evaluate`.
4. After a failure, call `lean_goal` at the reported `file_line` and read the goal before trying again.

## Notes

- Lines are 1-indexed. `lean_goal` without `column` shows the goals before and after the line.
- `lean_multi_attempt` snippets replace the tactic on that line. Keep each snippet to one tactic or
  `t1 <;> t2` chain at the line's indentation.
- After you restore another candidate or probe, the file changes and the server re-elaborates it, so
  the first query can take a few seconds.
- If `lean_local_search` finds nothing, try a shorter prefix or the namespace (`List.foldl` rather
  than `List.foldl_cons_eq`). Then use `arena_declaration` with the exact name.
- An "unknown identifier" error usually means a missing namespace prefix. `lean_hover_info` on a
  working use of the name shows its full name.
