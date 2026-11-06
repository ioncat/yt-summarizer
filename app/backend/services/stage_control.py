"""Cancel flags shared by the request handlers and the queue worker (NS-11 stage 2).

The Stop button of a running stage sets a flag here; the stage polls it (`is_cancelled`) and ends by resetting its
status. The flags used to live in routers/result.py, where the queue worker could not reach them: a mind map run by
the queue could not be stopped. routers/result.py still exposes the same set objects under its old names.
"""
from __future__ import annotations

CLEANUP_CANCEL: set[str] = set()  # video ids whose running cleanup must stop (after the paragraph in hand)
MINDMAP_CANCEL: set[str] = set()  # video ids whose running mind map must stop
TRANSCRIBE_CANCEL: set[str] = set()  # video ids (file-...) whose running transcription must stop (NS-11 stage 5)
SUMMARY_CANCEL: set[str] = set()  # video ids whose running summarization must stop
ITEM_CANCEL: set[int] = set()  # queue item ids to stop (NS-16): the worker checks it between the stages of an item, so a step that
                               # cannot be cut short (yt-dlp) still ends the item before the next stage starts
# (The live paragraph / chunk counters of a running cleanup / summary are no longer here: they are on the stage's run row in
# processing_stages, services/stage_progress.py - NS-11 decision 2.)


class StageCancelled(Exception):
    """A stage stopped on the user's request. Its status has been reset; the queue item ends 'skipped'."""
