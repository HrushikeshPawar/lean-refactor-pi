---
name: arena-lean
description: Lean proof optimization in the Arena.
license: MIT
---

# Arena task

Replace the proof of one theorem with a proof that scores more points and compiles on every listed Lean version.
The packet states the scoring rule and this theorem's rates.
The tools are `compile`, `goal`, `search`, `read` and `scratch`; each description states its inputs and replies.
The harness files every compiled proof as a node of a graph.
Ids: node nN, top-level step sK, open hole nN.hK.
Status closed: the node compiles with no open hole.
Status sketch: the node compiles with open holes.
Status broken: the node does not compile.
Spend counts only your own tokens, reasoning included; Lean checks are free, so a scratch test is cheaper than long reasoning.
`#check` a declaration before passing it positional arguments. One compile call takes up to {compile_max_drafts} drafts.
Each turn should call a tool; recaps are not needed.
