import os

# Ledger and control rows are cached per process and shared between readers; frozen rows make an edit fail loudly.
os.environ.setdefault("ARENA_FROZEN_ROWS", "1")
