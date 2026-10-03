## Strata v4.29.1 full native build

Bare `lake build` fails compiling generated C for:
`Strata.Languages.Core.DDMTransform.Translate:c.o`

Clang error:
`bracket nesting level exceeded maximum of 256`

This module is not currently required for the P0 target
`Strata.Languages.Core.StatementSemanticsProps`.

Decision: do not modify compiler flags or upstream Strata unless a later
competition task actually requires this native artifact.
