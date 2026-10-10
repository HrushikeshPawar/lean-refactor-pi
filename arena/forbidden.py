"""The forbidden-construct filter the official Space applies to every submitted proof."""

import re

# Synced from pinned Lean Refactor Arena Space app.py.
FORBIDDEN = [
    ("#eval", re.compile(r"#\s*eval\b")),
    ("#reduce", re.compile(r"#\s*reduce\b")),
    ("IO.", re.compile(r"\bIO\.")),
    ("unsafe def/fun/theorem", re.compile(r"\bunsafe\s+(def|fun|theorem|lemma)\b")),
    ("extern", re.compile(r"\bextern\b")),
    ("initialize", re.compile(r"\binitialize\b")),
    ("@[implemented_by]", re.compile(r"@\[\s*implemented[_]?[Bb]y\b")),
    ("@[extern]", re.compile(r"@\[\s*extern\b")),
    ("sorry", re.compile(r"\bsorry\b")),
    ("sorryAx", re.compile(r"\bsorryAx\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("axiom", re.compile(r"\baxiom\b")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
    ("ofReduceBool", re.compile(r"\bofReduceBool\b")),
    ("ofReduceNat", re.compile(r"\bofReduceNat\b")),
    ("run_cmd", re.compile(r"\brun_cmd\b")),
    ("run_elab", re.compile(r"\brun_elab\b")),
    ("#exit", re.compile(r"#\s*exit\b")),
    ("#count_heartbeats", re.compile(r"#\s*count_heartbeats\b")),
    ("attribute command", re.compile(r"(?m)^\s*attribute\b")),
    (
        "macro/elab/notation",
        re.compile(r"\b(macro|macro_rules|elab|elab_rules|notation|syntax)\b"),
    ),
    ("deriving instance", re.compile(r"\bderiving\s+instance\b")),
    (
        "auxiliary declaration",
        re.compile(r"(?m)^\s*(def|abbrev|instance|structure|inductive|class|opaque)\b"),
    ),
]


def remove_comments(text: str) -> str:
    out = []
    i = 0
    n = len(text)

    while i < n:
        if text[i] == '"':
            out.append(text[i])
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue

        if text.startswith("/-", i):
            depth = 1
            i += 2
            while i < n and depth:
                if text.startswith("/-", i):
                    depth += 1
                    i += 2
                elif text.startswith("-/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            out.append(" ")
            continue

        if text.startswith("--", i):
            while i < n and text[i] != "\n":
                i += 1
            continue

        out.append(text[i])
        i += 1

    return "".join(out)
