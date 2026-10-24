"""Speech-to-text service — engine-agnostic transcription interface.

Current engine: faster-whisper.
Models are downloaded on demand from HuggingFace and cached locally.
"""
from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger("services.transcriber")

# ---------------------------------------------------------------------------
# Model catalog — source of truth for available models
# ---------------------------------------------------------------------------

MODEL_CATALOG: dict[str, dict] = {
    "tiny":      {"size_mb": 77,   "languages": 99, "description": "Fastest, lowest accuracy"},
    "tiny.en":   {"size_mb": 77,   "languages": 1,  "description": "English-only, fastest"},
    "base":      {"size_mb": 145,  "languages": 99, "description": "Good balance — recommended starting point"},
    "base.en":   {"size_mb": 145,  "languages": 1,  "description": "English-only base"},
    "small":     {"size_mb": 466,  "languages": 99, "description": "Better quality, still fast"},
    "small.en":  {"size_mb": 466,  "languages": 1,  "description": "English-only small"},
    "medium":    {"size_mb": 1530, "languages": 99, "description": "High quality, slower"},
    "medium.en": {"size_mb": 1530, "languages": 1,  "description": "English-only medium"},
    "large-v1":  {"size_mb": 3100, "languages": 99, "description": "Very high quality"},
    "large-v2":  {"size_mb": 3100, "languages": 99, "description": "Improved large, better accuracy"},
    "large-v3":  {"size_mb": 3100, "languages": 99, "description": "Best quality, most accurate"},
}

DEFAULT_CACHE_PATH = str(Path.home() / ".cache" / "huggingface" / "hub")

# In-memory download progress: {model_name: {status, downloaded_mb, total_mb, error}}
_DOWNLOAD_PROGRESS: dict[str, dict] = {}
_DOWNLOAD_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Disk scan helpers
# ---------------------------------------------------------------------------

def _model_cache_dir(model_name: str, cache_path: str) -> Path:
    """Returns the HuggingFace cache directory for a given model."""
    return Path(cache_path) / f"models--Systran--faster-whisper-{model_name}"


def is_model_downloaded(model_name: str, cache_path: str) -> bool:
    """Return True if the model is fully present in the HuggingFace cache."""
    snapshots_dir = _model_cache_dir(model_name, cache_path) / "snapshots"
    if not snapshots_dir.exists():
        return False
    for snap in snapshots_dir.iterdir():
        if snap.is_dir() and (snap / "model.bin").exists():
            return True
    return False


def get_downloaded_models(cache_path: str) -> list[str]:
    """Return names of all catalog models that are present on disk."""
    return [name for name in MODEL_CATALOG if is_model_downloaded(name, cache_path)]


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 1)


# ---------------------------------------------------------------------------
# Download management
# ---------------------------------------------------------------------------

def start_model_download(model_name: str, cache_path: str) -> bool:
    """Start an async background download. Returns False if already in progress."""
    with _DOWNLOAD_LOCK:
        prog = _DOWNLOAD_PROGRESS.get(model_name, {})
        if prog.get("status") == "downloading":
            return False
        _DOWNLOAD_PROGRESS[model_name] = {
            "status": "downloading",
            "downloaded_mb": 0.0,
            "total_mb": MODEL_CATALOG.get(model_name, {}).get("size_mb", 0),
        }

    t = threading.Thread(
        target=_download_worker,
        args=(model_name, cache_path),
        daemon=True,
        name=f"stt-download-{model_name}",
    )
    t.start()
    logger.info("download: started model=%s", model_name)
    return True


def _download_worker(model_name: str, cache_path: str) -> None:
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError:
        _DOWNLOAD_PROGRESS[model_name] = {
            "status": "failed",
            "error": "huggingface_hub not installed — install faster-whisper",
        }
        return

    try:
        snapshot_download(
            repo_id=f"Systran/faster-whisper-{model_name}",
            cache_dir=cache_path or None,
        )
        _DOWNLOAD_PROGRESS[model_name] = {
            "status": "done",
            "downloaded_mb": MODEL_CATALOG.get(model_name, {}).get("size_mb", 0),
            "total_mb": MODEL_CATALOG.get(model_name, {}).get("size_mb", 0),
        }
        logger.info("download: done model=%s", model_name)
    except Exception as exc:
        _DOWNLOAD_PROGRESS[model_name] = {"status": "failed", "error": str(exc)}
        logger.error("download: failed model=%s error=%s", model_name, exc)


def get_download_status(model_name: str, cache_path: str) -> dict:
    """Return current download progress for polling.

    Possible statuses: not_started | downloading | done | failed
    """
    prog = _DOWNLOAD_PROGRESS.get(model_name)
    if not prog:
        # Check if already on disk (e.g. downloaded in a previous session)
        if is_model_downloaded(model_name, cache_path):
            return {"status": "done", "downloaded_mb": 0, "total_mb": 0}
        return {"status": "not_started", "downloaded_mb": 0, "total_mb": 0}

    if prog["status"] == "downloading":
        # Measure actual disk usage for an honest progress bar
        model_dir = _model_cache_dir(model_name, cache_path)
        actual_mb = _dir_size_mb(model_dir)
        return {
            "status": "downloading",
            "downloaded_mb": actual_mb,
            "total_mb": prog["total_mb"],
        }

    return prog.copy()


def delete_model(model_name: str, cache_path: str) -> bool:
    """Remove a model from the HuggingFace cache. Returns False if not present."""
    model_dir = _model_cache_dir(model_name, cache_path)
    if not model_dir.exists():
        return False
    shutil.rmtree(model_dir)
    # Clear any stale progress entry
    _DOWNLOAD_PROGRESS.pop(model_name, None)
    logger.info("delete: model=%s", model_name)
    return True


# ---------------------------------------------------------------------------
# Public catalog API
# ---------------------------------------------------------------------------

def get_available_models(cache_path: str | None = None) -> list[dict]:
    """Return the full catalog enriched with downloaded status.

    Each entry: {name, size_mb, languages, description, downloaded}
    """
    resolved_cache = cache_path or DEFAULT_CACHE_PATH
    return [
        {
            "name": name,
            "size_mb": meta["size_mb"],
            "languages": meta["languages"],
            "description": meta["description"],
            "downloaded": is_model_downloaded(name, resolved_cache),
        }
        for name, meta in MODEL_CATALOG.items()
    ]


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

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
    cache_path: str | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> TranscriptionResult:
    """Transcribe audio/video file using faster-whisper.

    language:   BCP-47 code or "auto" for detection
    model:      model name from MODEL_CATALOG
    device:     "auto" (CUDA if available), "cpu", or "cuda"
    cache_path: HuggingFace cache directory; uses DEFAULT_CACHE_PATH if None
    on_progress(segments_done): called after each segment
    """
    return _transcribe_faster_whisper(
        audio_path, language, model, device,
        cache_path or DEFAULT_CACHE_PATH,
        on_progress,
    )


def segments_to_entries(segments: list[dict]) -> list[dict]:
    """Convert Whisper segments to the subtitle-entry format used by text_formatter."""
    return [
        {"start": seg["start"], "end": seg["end"], "text": seg["text"]}
        for seg in segments
        if seg.get("text", "").strip()
    ]


# ---------------------------------------------------------------------------
# Internal: faster-whisper implementation
# ---------------------------------------------------------------------------

def _resolve_device(device: str) -> tuple[str, str]:
    """Return (device, compute_type) for WhisperModel."""
    if device == "cuda":
        return "cuda", "float16"
    if device == "cpu":
        return "cpu", "int8"
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
    cache_path: str,
    on_progress: Callable[[int], None] | None,
) -> TranscriptionResult:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return TranscriptionResult(
            segments=[], detected_language="", success=False,
            error_message="faster-whisper is not installed. Run: pip install faster-whisper",
        )

    try:
        actual_device, compute_type = _resolve_device(device)
        logger.info(
            "transcribe: model=%s device=%s compute_type=%s",
            model_name, actual_device, compute_type,
        )
        whisper_model = WhisperModel(
            model_name,
            device=actual_device,
            compute_type=compute_type,
            download_root=cache_path,
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
            "transcribe: done path=%s lang=%s segments=%d",
            audio_path, detected, len(segments),
        )
        return TranscriptionResult(segments=segments, detected_language=detected, success=True)

    except Exception as exc:
        logger.error("transcribe: failed path=%s error=%s", audio_path, exc, exc_info=True)
        return TranscriptionResult(
            segments=[], detected_language="", success=False, error_message=str(exc)
        )
