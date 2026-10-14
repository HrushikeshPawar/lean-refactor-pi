---
name: arena-lean
description: Lean proof optimization in the Arena.
license: MIT
---

# Arena task

Replace the supplied proof with one that earns more points while compiling on the listed toolchains. Scoring is mechanical; the packet gives its rule and measured rates. The harness records the graph and measurements. The available tools are `compile`, `goal`, `search`, `read`, and `finish`; their descriptions define their inputs and replies.

Nodes have identifiers nN; top-level steps have identifiers sK; an open hole is nN.hK. A closed node compiles, a sketch has open holes, and a broken node has failed compilation.
