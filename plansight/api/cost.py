"""Transparent estimate for the naive full-sheet frontier VLM baseline."""

# Estimate using GPT-4o pricing as a round-number frontier vision baseline: $2.50 / 1M
# input tokens. A 2048px sheet is budgeted at 1,105 image tokens (high-detail image
# tiling: 85 base + 4 * 170 crops), and the question/system prompt at 250 tokens.
FRONTIER_MODEL = "GPT-4o (estimate)"
INPUT_USD_PER_MILLION = 2.50
IMAGE_TOKENS_2048 = 85 + 4 * 170
QUESTION_TOKENS = 250


def naive_cost_usd(width: int | None = None, height: int | None = None, question: str = "") -> float:
    # One 2048px high-detail image estimate; longer questions add roughly 1 token / 4 chars.
    tokens = IMAGE_TOKENS_2048 + QUESTION_TOKENS + len(question) // 4
    return tokens * INPUT_USD_PER_MILLION / 1_000_000
