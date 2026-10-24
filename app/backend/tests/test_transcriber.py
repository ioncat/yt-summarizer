"""Tests for services.transcriber."""
import os
import shutil
import pytest
import tempfile
from pathlib import Path

from services.transcriber import (
    MODEL_CATALOG,
    DEFAULT_CACHE_PATH,
    TranscriptionResult,
    get_available_models,
    get_downloaded_models,
    is_model_downloaded,
    get_download_status,
    delete_model,
    segments_to_entries,
    _resolve_device,
    _model_cache_dir,
)


# ---------------------------------------------------------------------------
# MODEL_CATALOG
# ---------------------------------------------------------------------------

def test_catalog_has_expected_models():
    assert "base" in MODEL_CATALOG
    assert "tiny" in MODEL_CATALOG
    assert "large-v3" in MODEL_CATALOG


def test_catalog_entries_have_required_fields():
    for name, meta in MODEL_CATALOG.items():
        assert "size_mb" in meta, f"{name} missing size_mb"
        assert "languages" in meta, f"{name} missing languages"
        assert "description" in meta, f"{name} missing description"
        assert meta["size_mb"] > 0, f"{name} has zero size"


def test_catalog_size_ordering():
    assert MODEL_CATALOG["tiny"]["size_mb"] < MODEL_CATALOG["base"]["size_mb"]
    assert MODEL_CATALOG["base"]["size_mb"] < MODEL_CATALOG["small"]["size_mb"]
    assert MODEL_CATALOG["small"]["size_mb"] < MODEL_CATALOG["large-v3"]["size_mb"]


def test_en_only_models_have_1_language():
    for name, meta in MODEL_CATALOG.items():
        if name.endswith(".en"):
            assert meta["languages"] == 1, f"{name} should be 1 language"


# ---------------------------------------------------------------------------
# get_available_models
# ---------------------------------------------------------------------------

def test_get_available_models_returns_all_catalog_entries():
    result = get_available_models("/nonexistent/cache")
    assert len(result) == len(MODEL_CATALOG)


def test_get_available_models_shape():
    result = get_available_models("/nonexistent/cache")
    for item in result:
        assert "name" in item
        assert "size_mb" in item
        assert "languages" in item
        assert "description" in item
        assert "downloaded" in item
        assert isinstance(item["downloaded"], bool)


def test_get_available_models_nonexistent_cache_shows_nothing_downloaded():
    result = get_available_models("/nonexistent/cache/path/xyz")
    assert all(not m["downloaded"] for m in result)


# ---------------------------------------------------------------------------
# Disk scan (using a temp dir to simulate HF cache)
# ---------------------------------------------------------------------------

def _create_fake_model(cache_dir: Path, model_name: str) -> None:
    """Create a minimal fake HF cache entry for a model."""
    snap_dir = cache_dir / f"models--Systran--faster-whisper-{model_name}" / "snapshots" / "abc123"
    snap_dir.mkdir(parents=True)
    (snap_dir / "model.bin").write_bytes(b"fake model data")


def test_is_model_downloaded_false_when_not_present():
    with tempfile.TemporaryDirectory() as tmp:
        assert not is_model_downloaded("base", tmp)


def test_is_model_downloaded_true_when_present():
    with tempfile.TemporaryDirectory() as tmp:
        _create_fake_model(Path(tmp), "base")
        assert is_model_downloaded("base", tmp)


def test_get_downloaded_models_empty_cache():
    with tempfile.TemporaryDirectory() as tmp:
        assert get_downloaded_models(tmp) == []


def test_get_downloaded_models_finds_installed():
    with tempfile.TemporaryDirectory() as tmp:
        _create_fake_model(Path(tmp), "base")
        _create_fake_model(Path(tmp), "small")
        downloaded = get_downloaded_models(tmp)
        assert "base" in downloaded
        assert "small" in downloaded
        assert "large-v3" not in downloaded


def test_get_available_models_marks_downloaded():
    with tempfile.TemporaryDirectory() as tmp:
        _create_fake_model(Path(tmp), "tiny")
        result = get_available_models(tmp)
        by_name = {m["name"]: m for m in result}
        assert by_name["tiny"]["downloaded"] is True
        assert by_name["base"]["downloaded"] is False


# ---------------------------------------------------------------------------
# Download status
# ---------------------------------------------------------------------------

def test_get_download_status_not_started():
    with tempfile.TemporaryDirectory() as tmp:
        status = get_download_status("large-v3", tmp)
        assert status["status"] == "not_started"


def test_get_download_status_done_when_on_disk():
    with tempfile.TemporaryDirectory() as tmp:
        _create_fake_model(Path(tmp), "base")
        status = get_download_status("base", tmp)
        assert status["status"] == "done"


# ---------------------------------------------------------------------------
# delete_model
# ---------------------------------------------------------------------------

def test_delete_model_returns_false_when_not_present():
    with tempfile.TemporaryDirectory() as tmp:
        assert delete_model("base", tmp) is False


def test_delete_model_removes_directory():
    with tempfile.TemporaryDirectory() as tmp:
        _create_fake_model(Path(tmp), "base")
        assert is_model_downloaded("base", tmp)
        assert delete_model("base", tmp) is True
        assert not is_model_downloaded("base", tmp)


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
        {"start": 0.0, "end": 1.0, "text": "   "},
        {"start": 1.0, "end": 2.0, "text": ""},
        {"start": 2.0, "end": 3.0, "text": "Real text"},
    ]
    assert len(segments_to_entries(segs)) == 1


def test_segments_to_entries_empty_input():
    assert segments_to_entries([]) == []


# ---------------------------------------------------------------------------
# _resolve_device
# ---------------------------------------------------------------------------

def test_resolve_device_cpu():
    device, compute = _resolve_device("cpu")
    assert device == "cpu" and compute == "int8"


def test_resolve_device_cuda():
    device, compute = _resolve_device("cuda")
    assert device == "cuda" and compute == "float16"


def test_resolve_device_auto_valid():
    device, compute = _resolve_device("auto")
    assert device in ("cpu", "cuda")
    assert (device == "cpu" and compute == "int8") or (device == "cuda" and compute == "float16")


# ---------------------------------------------------------------------------
# transcribe — faster-whisper missing stub
# ---------------------------------------------------------------------------

def test_transcribe_error_when_faster_whisper_missing(monkeypatch):
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
    assert "faster-whisper" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stt_models_endpoint_returns_catalog(client):
    r = await client.get("/api/stt/models")
    assert r.status_code == 200
    data = r.json()
    assert "engine" in data
    assert "models" in data
    models = data["models"]
    assert isinstance(models, list)
    assert len(models) == len(MODEL_CATALOG)
    first = models[0]
    assert all(k in first for k in ("name", "size_mb", "languages", "description", "downloaded"))


@pytest.mark.asyncio
async def test_stt_models_download_unknown_returns_404(client):
    r = await client.post("/api/stt/models/nonexistent-model/download")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stt_models_delete_unknown_returns_404(client):
    r = await client.delete("/api/stt/models/nonexistent-model")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stt_settings_saved_and_returned(client):
    r = await client.put("/api/settings/app", json={
        "stt_model": "small",
        "stt_device": "cpu",
        "stt_cache_path": "/tmp/test_cache",
    })
    assert r.status_code == 200

    r2 = await client.get("/api/settings")
    app = r2.json()["app"]
    assert app["stt_model"] == "small"
    assert app["stt_device"] == "cpu"
    assert app["stt_cache_path"] == "/tmp/test_cache"

    # Restore defaults
    await client.put("/api/settings/app", json={
        "stt_model": "base",
        "stt_device": "auto",
        "stt_cache_path": "",
    })
