import os

# Route fingerprints run inline under test, never as detached Lean processes.
os.environ.setdefault("ARENA_ROUTES_INLINE", "1")
