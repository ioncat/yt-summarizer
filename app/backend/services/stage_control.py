"""Cancel flags shared by the request handlers and the queue worker (NS-11 stage 2).

The Stop button of a running stage sets a flag here; the stage polls it (`is_cancelled`) and ends by resetting its
status. The flags used to live in routers/result.py, where the queue worker could not reach them: a mind map run by
the queue could not be stopped. routers/result.py still exposes the same set objects under its old names.
"""
from __future__ import annotations

MINDMAP_CANCEL: set[str] = set()  # video ids whose running mind map must stop


class StageCancelled(Exception):
    """A stage stopped on the user's request. Its status has been reset; the queue item ends 'skipped'."""
