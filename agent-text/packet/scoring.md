Score: the mean of three percentages: token reduction, heartbeat reduction and compatibility.
Token reduction: percent fewer tokens than the reference proof ({reference_tokens} tokens).
Heartbeat reduction: percent fewer heartbeats than the reference proof ({reference_heartbeats} heartbeats).
Compatibility: percent of the listed versions on which the proof compiles.
A proof that does not compile scores zero.
Rates: 1 token = {points_per_token} points; 100 heartbeats = {points_per_100_heartbeats} points; 1 version = {points_per_lost_version} points.
Token count: proof text after `:=`, without comments and attributes.
Each identifier or number counts 1 token, whatever its length.
Each other nonspace character counts 1 token, except these groups, which count 1 token each: `:= != && -. -> ← .. ... :: :> <;> ;; == || => <= >= ⁻¹ ?_`.
Spaces and line breaks count 0; a tab counts 1.
Examples: `exact foo` = {example_short} tokens; `⟨a, b⟩` = {example_pair} tokens.
