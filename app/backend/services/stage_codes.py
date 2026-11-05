"""Names used by the per-stage table `processing_stages` (NS-25): stages, statuses and failure reason codes."""
from __future__ import annotations

STAGES = ("extract", "transcribe", "cleanup", "summary", "mindmap")
STATUSES = ("processing", "done", "failed", "cancelled")

# Reason codes of a failed (or cancelled) run. The first eight are the NS-25 plan; no_text / not_found / upstream_failed
# are the three "could not even start" reasons the queue stages report.
ERROR_CODES = (
    "empty_answer",      # the model produced nothing (thinking used the context, empty content, mostly empty paragraphs)
    "context_too_small", # the answer was cut off: num_ctx too small for this input
    "model_missing",     # no model / no Ollama URL configured
    "timeout",
    "no_subtitles",
    "ollama_down",       # Ollama not reachable
    "cancelled",         # stopped by the user
    "unexpected",        # anything else (an exception)
    "no_text",           # the video has no text for this stage
    "not_found",         # the video is not in History
    "upstream_failed",   # an earlier stage of the same queue item failed, so this one never ran
)


def classify_error(error_text: str | None) -> str | None:
    """Reason code for a stored error text (None for no text). Used by the migration of old rows and by the stage writer."""
    if not error_text or not error_text.strip():
        return None
    t = error_text.lower()
    if "did not run: an earlier stage failed" in t:
        return "upstream_failed"
    if "cancelled" in t or "canceled" in t:
        return "cancelled"
    if "needs an ollama url" in t or "no model" in t or "model configured" in t or "ollama url not configured" in t:
        return "model_missing"
    if "not in history" in t or ("not found" in t and "subtitles" not in t):
        return "not_found"
    if "no text" in t or "has no text" in t:
        return "no_text"
    if "no subtitles" in t or "subtitles available" in t:
        return "no_subtitles"
    if "timed out" in t or "timeout" in t:
        return "timeout"
    if "cut off" in t or ("num_ctx" in t and "answer" not in t):
        return "context_too_small"
    if ("returned no answer" in t or "returned nothing" in t or "was produced" in t or "thinking used" in t
            or "empty answer" in t):
        return "empty_answer"
    if "cannot connect" in t or "connection refused" in t or "unreachable" in t or "refused" in t:
        return "ollama_down"
    return "unexpected"
