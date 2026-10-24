"""Tests for services.transcriber — unit tests that run without faster-whisper installed."""
import pytest

from services.transcriber import (
    FASTER_WHISPER_MODELS,
    TranscriptionResult,
    get_available_models,
    segments_to_entries,
    _resolve_device,
)


# ---------------------------------------------------------------------------
# get_available_models
# ---------------------------------------------------------------------------

def test_get_available_models_faster_whisper():
    models = get_available_models("faster-whisper")
    assert isinstance(models, list)
    assert len(models) > 0
    assert "base" in models
    assert "tiny" in models
    assert "large-v3" in models


def test_get_available_models_unknown_engine():
    models = get_available_models("nonexistent-engine")
    assert models == []


def test_get_available_models_default_engine():
    assert get_available_models() == get_available_models("faster-whisper")


def test_models_are_ordered_small_to_large():
    models = get_available_models()
    assert models.index("tiny") < models.index("base")
    assert models.index("base") < models.index("small")
    assert models.index("small") < models.index("large-v3")


# ---------------------------------------------------------------------------
# segments_to_entries
# ---------------------------------------------------------------------------

def test_segments_to_entries_basic():
    segs = [
        {"start": 0.0, "end": 1.5, "text": "Hello world"},
        {"start": 1.5, "end": 3.0, "text": "Second line"},
    ]
    result = segments_to_entries(segs)
    assert len(result) == 2
    assert result[0]["text"] == "Hello world"
    assert result[1]["start"] == 1.5


def test_segments_to_entries_filters_empty():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "   "},  # whitespace-only
        {"start": 1.0, "end": 2.0, "text": ""},      # empty
        {"start": 2.0, "end": 3.0, "text": "Real text"},
    ]
    result = segments_to_entries(segs)
    assert len(result) == 1
    assert result[0]["text"] == "Real text"


def test_segments_to_entries_preserves_timing():
    segs = [{"start": 12.345, "end": 15.678, "text": "Hello"}]
    result = segments_to_entries(segs)
    assert result[0]["start"] == 12.345
    assert result[0]["end"] == 15.678


def test_segments_to_entries_empty_input():
    assert segments_to_entries([]) == []


# ---------------------------------------------------------------------------
# _resolve_device
# ---------------------------------------------------------------------------

def test_resolve_device_cpu():
    device, compute = _resolve_device("cpu")
    assert device == "cpu"
    assert compute == "int8"


def test_resolve_device_cuda():
    device, compute = _resolve_device("cuda")
    assert device == "cuda"
    assert compute == "float16"


def test_resolve_device_auto_returns_valid_pair():
    device, compute = _resolve_device("auto")
    assert device in ("cpu", "cuda")
    assert compute in ("int8", "float16")
    # cpu must use int8, cuda must use float16
    if device == "cpu":
        assert compute == "int8"
    else:
        assert compute == "float16"


# ---------------------------------------------------------------------------
# transcribe — faster-whisper not installed stub
# ---------------------------------------------------------------------------

def test_transcribe_returns_error_when_faster_whisper_missing(monkeypatch):
    """When faster-whisper is not importable, transcribe returns a failed result."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("No module named 'faster_whisper'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    from services.transcriber import transcribe
    result = transcribe("/fake/path.mp3", language="en", model="base", device="cpu")

    assert result.success is False
    assert result.error_message is not None
    assert "faster-whisper" in result.error_message.lower()
    assert result.segments == []


# ---------------------------------------------------------------------------
# GET /api/stt/models endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stt_models_endpoint(client):
    r = await client.get("/api/stt/models")
    assert r.status_code == 200
    data = r.json()
    assert "engine" in data
    assert "models" in data
    assert isinstance(data["models"], list)
    assert len(data["models"]) > 0
    assert "base" in data["models"]


@pytest.mark.asyncio
async def test_stt_settings_saved_and_returned(client):
    """STT settings saved via PUT /api/settings/app appear in GET /api/settings."""
    r = await client.put("/api/settings/app", json={
        "stt_model": "small",
        "stt_device": "cpu",
    })
    assert r.status_code == 200

    r2 = await client.get("/api/settings")
    app = r2.json()["app"]
    assert app["stt_model"] == "small"
    assert app["stt_device"] == "cpu"

    # Restore defaults
    await client.put("/api/settings/app", json={"stt_model": "base", "stt_device": "auto"})
