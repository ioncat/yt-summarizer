"""Speech-to-text service — engine-agnostic transcription interface.

Engines:
  faster-whisper — CTranslate2-based Whisper; default.
  qwen3_asr      — Qwen3-ASR from Alibaba; beats Whisper on most benchmarks.
Models are downloaded on demand from HuggingFace and cached locally.
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger("services.transcriber")

# ---------------------------------------------------------------------------
# Model catalogs — source of truth for available models
# ---------------------------------------------------------------------------

MODEL_CATALOG: dict[str, dict] = {
    "tiny":      {"size_mb": 77,   "languages": 99, "description": "Fastest, lowest accuracy",              "speed": "very fast", "engine": "faster_whisper"},
    "tiny.en":   {"size_mb": 77,   "languages": 1,  "description": "English-only, fastest",                 "speed": "very fast", "engine": "faster_whisper"},
    "base":      {"size_mb": 145,  "languages": 99, "description": "Good balance — recommended",            "speed": "fast",      "engine": "faster_whisper"},
    "base.en":   {"size_mb": 145,  "languages": 1,  "description": "English-only base",                     "speed": "fast",      "engine": "faster_whisper"},
    "small":     {"size_mb": 466,  "languages": 99, "description": "Better quality, still fast",            "speed": "fast",      "engine": "faster_whisper"},
    "small.en":  {"size_mb": 466,  "languages": 1,  "description": "English-only small",                    "speed": "fast",      "engine": "faster_whisper"},
    "medium":    {"size_mb": 1530, "languages": 99, "description": "High quality, moderate speed",          "speed": "medium",    "engine": "faster_whisper"},
    "medium.en": {"size_mb": 1530, "languages": 1,  "description": "English-only medium",                   "speed": "medium",    "engine": "faster_whisper"},
    "large-v1":  {"size_mb": 3100, "languages": 99, "description": "Very high quality",                     "speed": "slow",      "engine": "faster_whisper"},
    "large-v2":  {"size_mb": 3100, "languages": 99, "description": "Improved large, better accuracy",       "speed": "slow",      "engine": "faster_whisper"},
    "large-v3":  {"size_mb": 3100, "languages": 99, "description": "Best quality, most accurate",           "speed": "slow",      "engine": "faster_whisper"},
}

QWEN_CATALOG: dict[str, dict] = {
    "Qwen3-ASR-0.6B": {
        "size_mb": 1400, "languages": 52,
        "description": "Qwen3-ASR compact — fast, beats Whisper small",
        "speed": "fast", "engine": "qwen3_asr",
    },
    "Qwen3-ASR-1.7B": {
        "size_mb": 3600, "languages": 52,
        "description": "Qwen3-ASR — state-of-the-art, beats Whisper large-v3",
        "speed": "medium", "engine": "qwen3_asr",
    },
}

DEFAULT_CACHE_PATH = str(Path.home() / ".cache" / "huggingface" / "hub")

# In-memory download progress: {model_name: {status, downloaded_mb, total_mb, error}}
_DOWNLOAD_PROGRESS: dict[str, dict] = {}
_DOWNLOAD_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Disk scan helpers
# ---------------------------------------------------------------------------

def _model_cache_dir(model_name: str, cache_path: str) -> Path:
    """Returns the HuggingFace cache directory for a given Whisper model."""
    return Path(cache_path) / f"models--Systran--faster-whisper-{model_name}"


def _qwen_cache_dir(model_name: str, cache_path: str) -> Path:
    """Returns the HuggingFace cache directory for a Qwen3-ASR model."""
    return Path(cache_path) / f"models--Qwen--{model_name}"


def is_model_downloaded(model_name: str, cache_path: str) -> bool:
    """Return True if the model is fully present in the HuggingFace cache."""
    if model_name in QWEN_CATALOG:
        snapshots_dir = _qwen_cache_dir(model_name, cache_path) / "snapshots"
        if not snapshots_dir.exists():
            return False
        for snap in snapshots_dir.iterdir():
            if snap.is_dir() and any(snap.rglob("*.safetensors")):
                return True
        return False
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
        _catalog = QWEN_CATALOG if model_name in QWEN_CATALOG else MODEL_CATALOG
        _DOWNLOAD_PROGRESS[model_name] = {
            "status": "downloading",
            "downloaded_mb": 0.0,
            "total_mb": _catalog.get(model_name, {}).get("size_mb", 0),
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
            "error": "huggingface_hub not installed",
        }
        return

    is_qwen = model_name in QWEN_CATALOG
    repo_id = f"Qwen/{model_name}" if is_qwen else f"Systran/faster-whisper-{model_name}"
    catalog = QWEN_CATALOG if is_qwen else MODEL_CATALOG

    try:
        snapshot_download(
            repo_id=repo_id,
            cache_dir=cache_path or None,
        )
        size_mb = catalog.get(model_name, {}).get("size_mb", 0)
        _DOWNLOAD_PROGRESS[model_name] = {
            "status": "done",
            "downloaded_mb": size_mb,
            "total_mb": size_mb,
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
        if is_model_downloaded(model_name, cache_path):
            return {"status": "done", "downloaded_mb": 0, "total_mb": 0}
        return {"status": "not_started", "downloaded_mb": 0, "total_mb": 0}

    if prog["status"] == "downloading":
        model_dir = (
            _qwen_cache_dir(model_name, cache_path)
            if model_name in QWEN_CATALOG
            else _model_cache_dir(model_name, cache_path)
        )
        actual_mb = _dir_size_mb(model_dir)
        return {
            "status": "downloading",
            "downloaded_mb": actual_mb,
            "total_mb": prog["total_mb"],
        }

    return prog.copy()


def delete_model(model_name: str, cache_path: str) -> bool:
    """Remove a model from the HuggingFace cache. Returns False if not present."""
    model_dir = (
        _qwen_cache_dir(model_name, cache_path)
        if model_name in QWEN_CATALOG
        else _model_cache_dir(model_name, cache_path)
    )
    if not model_dir.exists():
        return False
    shutil.rmtree(model_dir)
    _DOWNLOAD_PROGRESS.pop(model_name, None)
    logger.info("delete: model=%s", model_name)
    return True


# ---------------------------------------------------------------------------
# Public catalog API
# ---------------------------------------------------------------------------

def get_available_models(cache_path: str | None = None) -> list[dict]:
    """Return the full catalog (Whisper + Qwen3-ASR) enriched with downloaded status."""
    resolved_cache = cache_path or DEFAULT_CACHE_PATH
    result = []
    for catalog in (MODEL_CATALOG, QWEN_CATALOG):
        for name, meta in catalog.items():
            result.append({
                "name": name,
                "size_mb": meta["size_mb"],
                "languages": meta["languages"],
                "description": meta["description"],
                "speed": meta.get("speed", "medium"),
                "engine": meta.get("engine", "faster_whisper"),
                "downloaded": is_model_downloaded(name, resolved_cache),
            })
    return result


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    segments: list[dict]          # [{"start": float, "end": float, "text": str}]
    detected_language: str
    success: bool
    error_message: str | None = None
    device_used: str | None = None


def transcribe(
    audio_path: str,
    *,
    language: str = "auto",
    model: str = "base",
    device: str = "auto",
    cache_path: str | None = None,
    on_progress: Callable[[int, float, float], None] | None = None,
) -> TranscriptionResult:
    """Transcribe audio/video file using the appropriate engine.

    language:   BCP-47 code or "auto" for detection
    model:      model name (Whisper: "base"/"large-v3"/…; Qwen3: "Qwen3-ASR-1.7B"/…)
    device:     "auto" (CUDA if available), "cpu", or "cuda"
    cache_path: HuggingFace cache directory; uses DEFAULT_CACHE_PATH if None
    on_progress(segments_done, seconds_done, total_seconds): called after each segment
    """
    resolved = cache_path or DEFAULT_CACHE_PATH
    if model in QWEN_CATALOG:
        return _transcribe_qwen3_asr(audio_path, language, model, device, resolved, on_progress)
    return _transcribe_faster_whisper(audio_path, language, model, device, resolved, on_progress)


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
    # Auto-detect: try ctranslate2 (faster-whisper's backend) first, then torch
    try:
        import ctranslate2  # type: ignore
        if ctranslate2.get_cuda_device_count() > 0:
            logger.info("transcriber: CUDA available via ctranslate2 — using float16")
            return "cuda", "float16"
    except Exception:
        pass
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            logger.info("transcriber: CUDA available via torch — using float16")
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
    on_progress: Callable[[int, float, float], None] | None,
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
        try:
            whisper_model = WhisperModel(
                model_name,
                device=actual_device,
                compute_type=compute_type,
                download_root=cache_path,
            )
        except Exception as cuda_exc:
            if actual_device == "cuda":
                logger.warning(
                    "transcribe: CUDA init failed (%s) — falling back to CPU", cuda_exc
                )
                actual_device, compute_type = "cpu", "int8"
                whisper_model = WhisperModel(
                    model_name,
                    device=actual_device,
                    compute_type=compute_type,
                    download_root=cache_path,
                )
            else:
                raise

        lang_arg = None if language == "auto" else language
        segments_iter, info = whisper_model.transcribe(
            audio_path,
            language=lang_arg,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        total_duration = info.duration or 0.0

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
                on_progress(len(segments), seg.end, total_duration)

        detected = info.language or (language if language != "auto" else "unknown")
        logger.info(
            "transcribe: done path=%s lang=%s segments=%d",
            audio_path, detected, len(segments),
        )
        return TranscriptionResult(segments=segments, detected_language=detected, success=True, device_used=actual_device)

    except Exception as exc:
        logger.error("transcribe: failed path=%s error=%s", audio_path, exc, exc_info=True)
        return TranscriptionResult(
            segments=[], detected_language="", success=False, error_message=str(exc)
        )


# ---------------------------------------------------------------------------
# Internal: Qwen3-ASR implementation
# ---------------------------------------------------------------------------

def _get_audio_duration(audio_path: str) -> float:
    """Return audio duration in seconds using av (already a dependency)."""
    try:
        import av  # type: ignore
        with av.open(audio_path) as container:
            return float(container.duration) / 1_000_000 if container.duration else 0.0
    except Exception:
        return 0.0


def _text_to_segments(text: str, total_duration: float) -> list[dict]:
    """Split clean transcript text into pseudo-segments with estimated timestamps.

    Qwen3-ASR returns clean text without timestamps; we split by sentence boundaries
    and assign proportional time ranges so the formatter can group into paragraphs.
    """
    sentences = [s.strip() for s in re.split(r'(?<=[.!?。！？])\s+', text.strip()) if s.strip()]
    if not sentences:
        return [{"start": 0.0, "end": max(total_duration, 1.0), "text": text.strip()}]
    step = total_duration / len(sentences) if total_duration > 0 else 2.0
    return [
        {"start": round(i * step, 3), "end": round((i + 1) * step, 3), "text": s}
        for i, s in enumerate(sentences)
    ]


def _transcribe_qwen3_asr(
    audio_path: str,
    language: str,
    model_name: str,
    device: str,
    cache_path: str,
    on_progress: Callable[[int, float, float], None] | None,
) -> TranscriptionResult:
    try:
        import torch  # type: ignore
        from qwen_asr import Qwen3ASRModel  # type: ignore
    except ImportError as exc:
        return TranscriptionResult(
            segments=[], detected_language="", success=False,
            error_message=f"qwen-asr not installed ({exc}). Run: pip install qwen-asr",
        )

    try:
        # Resolve device
        actual_device: str
        if device == "cuda":
            actual_device = "cuda:0"
        elif device == "cpu":
            actual_device = "cpu"
        else:
            try:
                import ctranslate2  # type: ignore
                actual_device = "cuda:0" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                actual_device = "cpu"

        dtype = torch.bfloat16 if "cuda" in actual_device else torch.float32

        logger.info("qwen3-asr: loading model=%s device=%s", model_name, actual_device)
        if on_progress:
            on_progress(0, 0.0, 0.0)

        model = Qwen3ASRModel.from_pretrained(
            f"Qwen/{model_name}",
            dtype=dtype,
            device_map=actual_device,
            max_new_tokens=4096,
        )

        lang_arg = None if language == "auto" else language

        logger.info("qwen3-asr: transcribing path=%s lang=%s", audio_path, lang_arg)
        results = model.transcribe(audio=audio_path, language=lang_arg)

        if not results:
            return TranscriptionResult(
                segments=[], detected_language="", success=False,
                error_message="Qwen3-ASR returned empty result",
            )

        result = results[0]
        text = (result.text or "").strip()
        detected = result.language or (language if language != "auto" else "unknown")

        total_duration = _get_audio_duration(audio_path)
        segments = _text_to_segments(text, total_duration)

        if on_progress:
            on_progress(len(segments), total_duration, total_duration)

        logger.info(
            "qwen3-asr: done path=%s lang=%s segments=%d",
            audio_path, detected, len(segments),
        )
        return TranscriptionResult(
            segments=segments, detected_language=detected, success=True,
            device_used=actual_device,
        )

    except Exception as exc:
        logger.error("qwen3-asr: failed path=%s error=%s", audio_path, exc, exc_info=True)
        return TranscriptionResult(
            segments=[], detected_language="", success=False, error_message=str(exc)
        )
