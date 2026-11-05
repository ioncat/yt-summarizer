"""Cancel flags shared by the request handlers and the queue worker (NS-11 stage 2).

The Stop button of a running stage sets a flag here; the stage polls it (`is_cancelled`) and ends by resetting its
status. The flags used to live in routers/result.py, where the queue worker could not reach them: a mind map run by
the queue could not be stopped. routers/result.py still exposes the same set objects under its old names.
"""
from __future__ import annotations

CLEANUP_CANCEL: set[str] = set()  # video ids whose running cleanup must stop (after the paragraph in hand)
MINDMAP_CANCEL: set[str] = set()  # video ids whose running mind map must stop
SUMMARY_CANCEL: set[str] = set()  # video ids whose running summarization must stop
# Live chunk progress of a running summarization {video_id: {"done": n, "total": m}}, shown on the result page
# (GET /api/result/<id> adds summary_chunks_done / summary_chunks_total while it runs)
SUMMARY_PROGRESS: dict[str, dict] = {}
# Live paragraph progress of a running cleanup {video_id: {"done": n, "total": m}} (GET /api/result/<id> adds
# cleanup_paragraphs_done / cleanup_paragraphs_total while it runs). In memory for now; NS-11 decision 2 moves it to the DB.
CLEANUP_PROGRESS: dict[str, dict] = {}


class StageCancelled(Exception):
    """A stage stopped on the user's request. Its status has been reset; the queue item ends 'skipped'."""
