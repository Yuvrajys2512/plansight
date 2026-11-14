"""Tests never call paid/remote models: the router stays on its $0 paths (English parser + template bank)."""
import os

os.environ.setdefault("PLANSIGHT_NO_LLM", "1")
