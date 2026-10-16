"""The vendored Space filter and arena.forbidden reject the same proofs."""

import unittest
from typing import cast

from arena.forbidden import FORBIDDEN, official_filter, remove_comments


def _official_globals() -> dict[str, object]:
    loaded = official_filter()
    return cast(dict[str, object], loaded.__globals__)  # ty: ignore[unresolved-attribute]


# One sample per FORBIDDEN label. Each sample hits that label and no earlier one.
SAMPLES = [
    ("#eval", "#eval 1"),
    ("#reduce", "#reduce 1"),
    ("IO.", "IO.println"),
    ("unsafe def/fun/theorem", "unsafe def f := 1"),
    ("extern", "extern"),
    ("initialize", "initialize"),
    ("@[implemented_by]", "@[implemented_by foo]"),
    ("@[extern]", "@[extern]"),
    ("sorry", "sorry"),
    ("sorryAx", "sorryAx"),
    ("admit", "admit"),
    ("axiom", "axiom"),
    ("native_decide", "native_decide"),
    ("ofReduceBool", "ofReduceBool"),
    ("ofReduceNat", "ofReduceNat"),
    ("run_cmd", "run_cmd"),
    ("run_elab", "run_elab"),
    ("#exit", "#exit"),
    ("#count_heartbeats", "#count_heartbeats"),
    ("attribute command", "attribute [simp] foo"),
    ("macro/elab/notation", "macro foo"),
    ("deriving instance", "deriving instance"),
    ("auxiliary declaration", "def foo := 1"),
]


# Pattern triples (label, source, flags) on one side only. The byte cap is the official filter's
# only other check and is asserted separately; the patterns themselves agree on this vendored commit.
KNOWN_PATTERN_DIFFERENCES: set[tuple[str, str, int]] = set()


def harness_label(text: str) -> str | None:
    clean = remove_comments(text)
    for label, pattern in FORBIDDEN:
        if pattern.search(clean):
            return label
    return None


class OfficialFilterParityTests(unittest.TestCase):
    def test_pattern_labels_match_and_comments_do_not_trigger(self):
        official_labels = [label for label, _pattern in cast(list[tuple], _official_globals()["_FORBIDDEN_PATTERNS"])]
        self.assertEqual(official_labels, [label for label, _pattern in FORBIDDEN])
        # `@[extern]` contains the word `extern`, and that earlier pattern wins.
        first_hit = {"@[extern]": "extern"}
        corpus = []
        for label, sample in SAMPLES:
            corpus.append((sample, first_hit.get(label, label)))
            corpus.append((f"-- {sample}\n", None))
            corpus.append((f"/- {sample} -/\n", None))
        corpus.append(("macromolecule", None))
        limit = cast(int, _official_globals()["_MAX_PROOF_BYTES"])
        under = "a" * limit
        over = "a" * (limit + 1)
        corpus.append((under, None))
        self.assertGreaterEqual(len(corpus), 40)
        for text, expected in corpus:
            with self.subTest(text=text[:24], expected=expected):
                self.assertEqual(official_filter()(text), expected)
                self.assertEqual(harness_label(text), expected)
        # The byte cap is the official filter's own gate. It is not one of FORBIDDEN's labels,
        # so a long proof with no construct is rejected only there.
        self.assertEqual(official_filter()(over), f"too large (> {limit // 1024} KB)")
        self.assertIsNone(harness_label(over))
        official_patterns = dict(cast(list[tuple], _official_globals()["_FORBIDDEN_PATTERNS"]))
        our_patterns = dict(FORBIDDEN)
        for label, sample in SAMPLES:
            self.assertIsNotNone(official_patterns[label].search(sample), label)
            self.assertIsNotNone(our_patterns[label].search(sample), label)

    def test_pattern_sources_and_flags_match_except_known_differences(self):
        official = [
            (label, pattern.pattern, pattern.flags)
            for label, pattern in cast(list[tuple], _official_globals()["_FORBIDDEN_PATTERNS"])
        ]
        ours = [(label, pattern.pattern, pattern.flags) for label, pattern in FORBIDDEN]
        self.assertEqual(set(official) ^ set(ours), KNOWN_PATTERN_DIFFERENCES)
        # Order decides which label is reported first, so it must match too.
        shared = set(official) & set(ours)
        self.assertEqual([item for item in official if item in shared], [item for item in ours if item in shared])


if __name__ == "__main__":
    unittest.main()
