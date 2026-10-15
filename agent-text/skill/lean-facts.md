The theorem statement and all bytes before `:=` must remain unchanged.
A submitted proof may contain no `sorry`, `admit`, `axiom`, `native_decide`, `#eval`, `IO.`, `unsafe`, `macro`, `elab`, `notation`, `syntax`, `attribute`, auxiliary declaration, or extra top-level command.
A dotted name such as `h.1`, `x.inl` or `Nat.succ_le` is one run of letters, digits, `.`, `_` and `'`, so it counts 1 token.
Measured: `case inl x y => exact x` is 7 tokens; `case inl => rename_i x y; exact x` is 9.
`all_goals tac` and `tac <;> tac'` run one tactic on every goal.
