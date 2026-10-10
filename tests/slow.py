"""Shared gate for tests that start Pi, compile Lean or open a Lean session."""

import os
import unittest

SLOW = os.environ.get("ARENA_SLOW_TESTS") == "1"
slow = unittest.skipUnless(SLOW, "slow: starts Pi / compiles Lean / opens a Lean session; set ARENA_SLOW_TESTS=1")
