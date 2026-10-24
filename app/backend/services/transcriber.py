"""Speech-to-text service — engine-agnostic transcription interface.

Current engine: faster-whisper.
To add a new engine: implement a _transcribe_<engine> function and extend
the dispatching in transcribe().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("services.transcriber")

# Ordered from smallest (fastest) to largest (most accurate)
FASTER_WHISPER_MODELS: list[str] = [
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large-v1", "large-v2", "large-v3",
]


@dataclass
class TranscriptionResult:
    segments: list[dict]          # [{"start": float, "end": float, "text": str}]
    detected_language: str
    success: bool
    error_message: str | None = None


def transcribe(
    audio_path: str,
    *,
    language: str = "auto",
    model: str = "base",
    device: str = "auto",
    on_progress: Callable[[int], None] | None = None,
) -> TranscriptionResult:
    """Transcribe audio/video file.

    audio_path: path to a local audio or video file
    language:   BCP-47 code ("ru", "en", …) or "auto" for auto-detection
    model:      faster-whisper model name (e.g. "base", "large-v3")
    device:     "auto" picks CUDA when available, else CPU; "cpu" or "cuda"
    on_progress(segments_done): called after each segment is processed
    """
    return _transcribe_faster_whisper(audio_path, language, model, device, on_progress)


def get_available_models(engine: str = "faster-whisper") -> list[str]:
    """Return the ordered list of model names for the given engine."""
    if engine == "faster-whisper":
        return list(FASTER_WHISPER_MODELS)
    logger.warning("get_available_models: unknown engine '%s'", engine)
    return []


def segments_to_entries(segments: list[dict]) -> list[dict]:
    """Convert Whisper segments to the subtitle-entry format used by text_formatter.

    Returns [{"start": float, "end": float, "text": str}, ...], empty strings stripped.
    """
    return [
        {"start": seg["start"], "end": seg["end"], "text": seg["text"]}
        for seg in segments
        if seg.get("text", "").strip()
    ]


# ---------------------------------------------------------------------------
# Internal: faster-whisper implementation
# ---------------------------------------------------------------------------

def _resolve_device(device: str) -> tuple[str, str]:
    """Return (device, compute_type) suitable for WhisperModel."""
    if device == "cuda":
        return "cuda", "float16"
    if device == "cpu":
        return "cpu", "int8"
    # auto: prefer CUDA when torch reports it available
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            logger.info("transcriber: CUDA available — using float16")
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def _transcribe_faster_whisper(
    audio_path: str,
    language: str,
    model_name: str,
    device: str,
    on_progress: Callable[[int], None] | None,
) -> TranscriptionResult:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return TranscriptionResult(
            segments=[],
            detected_language="",
            success=False,
            error_message=(
                "faster-whisper is not installed. "
                "Run: pip install faster-whisper"
            ),
        )

    try:
        actual_device, compute_type = _resolve_device(device)
        logger.info(
            "transcribe: loading model=%s device=%s compute_type=%s",
            model_name, actual_device, compute_type,
        )
        whisper_model = WhisperModel(
            model_name,
            device=actual_device,
            compute_type=compute_type,
        )

        lang_arg = None if language == "auto" else language
        segments_iter, info = whisper_model.transcribe(
            audio_path,
            language=lang_arg,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        segments: list[dict] = []
        for seg in segments_iter:
            text = seg.text.strip()
            if text:
                segments.append({
                    "start": round(seg.start, 3),
                    "end":   round(seg.end, 3),
                    "text":  text,
                })
            if on_progress:
                on_progress(len(segments))

        detected = info.language or (language if language != "auto" else "unknown")
        logger.info(
            "transcribe: done path=%s lang=%s segments=%d model=%s device=%s",
            audio_path, detected, len(segments), model_name, actual_device,
        )
        return TranscriptionResult(
            segments=segments,
            detected_language=detected,
            success=True,
        )

    except Exception as exc:
        logger.error(
            "transcribe: failed path=%s error=%s", audio_path, exc, exc_info=True
        )
        return TranscriptionResult(
            segments=[], detected_language="", success=False, error_message=str(exc)
        )
