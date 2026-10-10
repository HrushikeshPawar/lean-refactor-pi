"""Goal-state signatures: cosmetic edits keep a signature, a changed goal changes it."""

import unittest

from arena import goalstate

GOAL = "P : PureExpr\nσ✝ σ : Store P\nhu : Update σ ks σ✝\n⊢ ∃ σ₁,\n    σ₁ = f σ ?m.12"


def probe(goals=(), errors=(), passed=False, sorry=True):
    diagnostics = [{"severity": "error", "message": message} for message in errors]
    return {
        "compat": {
            "v": {
                "passed": passed,
                "diagnostics": diagnostics,
                "goals": [{"proof_line": 3, "goals": text} for text in goals],
            }
        },
        "contains_sorry": sorry,
    }


class SignatureTests(unittest.TestCase):
    def test_cosmetic_renames_whitespace_and_hygiene_keep_the_signature(self):
        renamed = "case h\nQ : PureExpr\nτ✝¹ τ : Store Q\nH  : Update τ ks τ✝¹\n⊢ ∃ σ₁, σ₁ =    f τ ?m.99".replace(
            "Q", "P"
        )
        self.assertEqual(goalstate.signature(probe([GOAL])), goalstate.signature(probe([renamed])))

    def test_goal_order_does_not_matter_but_a_changed_goal_does(self):
        other = "n : Nat\n⊢ n = n"
        self.assertEqual(goalstate.signature(probe([GOAL + "\n\n" + other])), goalstate.signature(probe([other, GOAL])))
        changed = GOAL.replace("f σ", "g σ")
        self.assertNotEqual(goalstate.signature(probe([GOAL])), goalstate.signature(probe([changed])))
        self.assertNotEqual(goalstate.signature(probe([GOAL])), goalstate.signature(probe([GOAL, other])))

    def test_unsolved_goals_in_an_error_count_as_goals_and_positions_do_not_matter(self):
        error = "unsolved goals\ncase a\n" + GOAL
        self.assertEqual(
            goalstate.signature(probe(errors=[error])), goalstate.signature(probe([GOAL], errors=["unsolved goals"]))
        )
        self.assertEqual(goalstate.parts(probe(errors=[error]))[1], ["unsolved goals"])

    def test_error_classes_blank_quoted_names_so_a_typo_is_not_a_new_state(self):
        self.assertEqual(
            goalstate.signature(probe(errors=["Unknown identifier `foo`"])),
            goalstate.signature(probe(errors=["Unknown identifier `bar`"])),
        )
        self.assertNotEqual(
            goalstate.signature(probe(errors=["Unknown identifier `foo`"])),
            goalstate.signature(probe(errors=["`simp` made no progress"])),
        )
        self.assertEqual(goalstate.error_class("failed at line 12, column 4"), "failed at")

    def test_a_compiled_proof_is_closed_and_a_sorry_is_not(self):
        done = probe(passed=True, sorry=False)
        self.assertEqual(goalstate.signature(done), goalstate.CLOSED)
        self.assertNotEqual(goalstate.signature(probe(passed=True, sorry=True)), goalstate.CLOSED)
        warned = probe(passed=True, sorry=False)
        warned["compat"]["v"]["diagnostics"] = [{"severity": "warning", "message": "declaration uses `sorry`"}]
        self.assertNotEqual(goalstate.signature(warned), goalstate.CLOSED)


if __name__ == "__main__":
    unittest.main()
