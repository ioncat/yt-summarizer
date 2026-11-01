"""Tests for services.transcriber."""
import os
import shutil
import pytest
import tempfile
from pathlib import Path

from services.transcriber import (
    MODEL_CATALOG,
    QWEN_CATALOG,
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
    assert len(result) == len(MODEL_CATALOG) + len(QWEN_CATALOG)


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
    assert len(models) == len(MODEL_CATALOG) + len(QWEN_CATALOG)
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


# ---------------------------------------------------------------------------
# Qwen3-ASR device selection (torch / qwen_asr mocked)
# ---------------------------------------------------------------------------

def _run_qwen(monkeypatch, cuda_available, fail_on_cuda=False, cuda_check_raises=False, device="auto"):
    import sys
    import types
    from unittest.mock import MagicMock
    from services.transcriber import _transcribe_qwen3_asr

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = "bf16"
    fake_torch.float32 = "f32"
    fake_torch.cuda = types.SimpleNamespace(
        is_available=(MagicMock(side_effect=RuntimeError("boom")) if cuda_check_raises
                      else MagicMock(return_value=cuda_available))
    )
    calls = []

    class FakeModel:
        def transcribe(self, audio, language=None):
            return [types.SimpleNamespace(text="Hello world.", language="English")]

    class FakeQwen:
        @staticmethod
        def from_pretrained(name, dtype, device_map, max_new_tokens):
            calls.append((device_map, dtype))
            if fail_on_cuda and "cuda" in device_map:
                raise RuntimeError("Torch not compiled with CUDA enabled")
            return FakeModel()

    fake_qwen = types.ModuleType("qwen_asr")
    fake_qwen.Qwen3ASRModel = FakeQwen
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "qwen_asr", fake_qwen)
    monkeypatch.setattr("services.transcriber._convert_to_wav", lambda p: _fake_wav())
    result = _transcribe_qwen3_asr("missing.wav", "auto", "Qwen3-ASR-1.7B", device, "", None)
    return result, calls


def _fake_wav():
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    return path


def test_qwen_uses_cuda_when_torch_reports_cuda(monkeypatch):
    result, calls = _run_qwen(monkeypatch, cuda_available=True)
    assert result.success
    assert result.device_used == "cuda:0"
    assert calls == [("cuda:0", "bf16")]


def test_qwen_uses_cpu_when_torch_has_no_cuda(monkeypatch):
    result, calls = _run_qwen(monkeypatch, cuda_available=False)
    assert result.success
    assert result.device_used == "cpu"
    assert calls == [("cpu", "f32")]


def test_qwen_cpu_when_cuda_check_raises(monkeypatch):
    result, calls = _run_qwen(monkeypatch, cuda_available=False, cuda_check_raises=True)
    assert result.success
    assert result.device_used == "cpu"


def test_qwen_falls_back_to_cpu_when_cuda_init_fails(monkeypatch):
    result, calls = _run_qwen(monkeypatch, cuda_available=True, fail_on_cuda=True)
    assert result.success
    assert result.device_used == "cpu"
    assert calls == [("cuda:0", "bf16"), ("cpu", "f32")]


def test_qwen_explicit_cuda_falls_back_when_init_fails(monkeypatch):
    result, calls = _run_qwen(monkeypatch, cuda_available=False, fail_on_cuda=True, device="cuda")
    assert result.success
    assert result.device_used == "cpu"


# ---------------------------------------------------------------------------
# Qwen3-ASR input conversion (ffmpeg + model mocked)
# ---------------------------------------------------------------------------

def _qwen_env(monkeypatch, transcribe_raises=False):
    import sys
    import types
    from unittest.mock import MagicMock

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = "bf16"
    fake_torch.float32 = "f32"
    fake_torch.cuda = types.SimpleNamespace(is_available=MagicMock(return_value=False))
    seen = {}

    class FakeModel:
        def transcribe(self, audio, language=None):
            seen["audio"] = audio
            seen["language"] = language
            seen["existed"] = os.path.exists(audio)
            if transcribe_raises:
                raise RuntimeError("model blew up")
            return [types.SimpleNamespace(text="Hi.", language="English")]

    class FakeQwen:
        @staticmethod
        def from_pretrained(name, dtype, device_map, max_new_tokens):
            return FakeModel()

    fake_qwen = types.ModuleType("qwen_asr")
    fake_qwen.Qwen3ASRModel = FakeQwen
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "qwen_asr", fake_qwen)
    return seen


def _fake_run(calls, returncode=0, stderr=""):
    import types

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
    return run


def test_qwen_converts_input_to_wav_with_ffmpeg_arg_list(monkeypatch):
    from services.transcriber import _transcribe_qwen3_asr
    seen = _qwen_env(monkeypatch)
    calls = []
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "/usr/bin/ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", _fake_run(calls))
    result = _transcribe_qwen3_asr("talk.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert result.success
    cmd, kwargs = calls[0]
    assert isinstance(cmd, list)
    assert not kwargs.get("shell")
    wav = seen["audio"]
    assert cmd == ["/usr/bin/ffmpeg", "-y", "-nostdin", "-loglevel", "error",
                   "-protocol_whitelist", "file", "-i", "talk.m4a",
                   "-vn", "-ar", "16000", "-ac", "1", wav]
    assert kwargs["timeout"] == 600
    assert wav.endswith(".wav")
    assert seen["existed"] is True


def test_qwen_temp_wav_removed_after_success(monkeypatch):
    from services.transcriber import _transcribe_qwen3_asr
    seen = _qwen_env(monkeypatch)
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", _fake_run([]))
    assert _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None).success
    assert not os.path.exists(seen["audio"])


def test_qwen_temp_wav_removed_after_model_failure(monkeypatch):
    from services.transcriber import _transcribe_qwen3_asr
    seen = _qwen_env(monkeypatch, transcribe_raises=True)
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", _fake_run([]))
    result = _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert not result.success
    assert "model blew up" in result.error_message
    assert not os.path.exists(seen["audio"])


def test_qwen_ffmpeg_failure_reports_error_and_leaves_no_temp_file(monkeypatch):
    import glob
    from services.transcriber import _transcribe_qwen3_asr
    _qwen_env(monkeypatch)
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "qwen_asr_*.wav")))
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", _fake_run([], returncode=1, stderr="bad file"))
    result = _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert not result.success
    assert "ffmpeg could not convert" in result.error_message
    assert set(glob.glob(os.path.join(tempfile.gettempdir(), "qwen_asr_*.wav"))) == before


def test_qwen_missing_ffmpeg_reports_error(monkeypatch):
    from services.transcriber import _transcribe_qwen3_asr
    _qwen_env(monkeypatch)
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: None)
    result = _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert not result.success
    assert "ffmpeg not found" in result.error_message


def test_whisper_path_does_not_convert(monkeypatch):
    import sys
    import types
    from services.transcriber import transcribe

    class FakeWhisper:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, path, **k):
            seg = types.SimpleNamespace(text=" hi ", start=0.0, end=1.0)
            return iter([seg]), types.SimpleNamespace(duration=1.0, language="en")

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = FakeWhisper
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)

    def boom(*a, **k):
        raise AssertionError("subprocess must not run on the Whisper path")

    monkeypatch.setattr("services.transcriber.subprocess.run", boom)
    result = transcribe("talk.m4a", model="base", device="cpu")
    assert result.success
    assert result.segments[0]["text"] == "hi"


def _temp_wavs():
    import glob
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "qwen_asr_*.wav")))


def test_qwen_ffmpeg_timeout_reports_error_and_removes_wav(monkeypatch):
    import subprocess as sp
    from services.transcriber import _transcribe_qwen3_asr
    _qwen_env(monkeypatch)
    before = _temp_wavs()

    def run(cmd, **kwargs):
        raise sp.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", run)
    result = _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert not result.success
    assert "timed out" in result.error_message
    assert _temp_wavs() == before


def test_qwen_subprocess_raising_removes_wav(monkeypatch):
    from services.transcriber import _transcribe_qwen3_asr
    _qwen_env(monkeypatch)
    before = _temp_wavs()

    def run(cmd, **kwargs):
        raise OSError("cannot start ffmpeg")

    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", run)
    result = _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert not result.success
    assert "cannot start ffmpeg" in result.error_message
    assert _temp_wavs() == before


def test_qwen_conversion_failure_does_not_load_model(monkeypatch):
    import sys
    import types
    from services.transcriber import _transcribe_qwen3_asr
    _qwen_env(monkeypatch)
    loaded = []

    class Spy:
        @staticmethod
        def from_pretrained(*a, **k):
            loaded.append(1)

    sys.modules["qwen_asr"].Qwen3ASRModel = Spy
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: None)
    result = _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert not result.success
    assert loaded == []


# ---------------------------------------------------------------------------
# Language forms: ISO codes for Whisper and storage, names for Qwen3-ASR
# ---------------------------------------------------------------------------

def test_language_to_code_accepts_codes_and_names():
    from services.transcriber import language_to_code
    assert language_to_code("ru") == "ru"
    assert language_to_code("Russian") == "ru"
    assert language_to_code("russian") == "ru"
    assert language_to_code("auto") == "auto"
    assert language_to_code("xx") == "xx"


def test_language_to_qwen_name():
    from services.transcriber import language_to_qwen_name
    assert language_to_qwen_name("ru") == "Russian"
    assert language_to_qwen_name("Russian") == "Russian"
    assert language_to_qwen_name("uk") is None


@pytest.mark.parametrize("given", ["ru", "Russian"])
def test_whisper_receives_iso_code(monkeypatch, given):
    import sys
    import types
    from services.transcriber import transcribe
    seen = {}

    class FakeWhisper:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, path, language=None, **k):
            seen["language"] = language
            return iter([]), types.SimpleNamespace(duration=1.0, language="ru")

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = FakeWhisper
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    assert transcribe("a.wav", language=given, model="base", device="cpu").success
    assert seen["language"] == "ru"


@pytest.mark.parametrize("given,expected", [("ru", "Russian"), ("Russian", "Russian"), ("uk", None), ("auto", None)])
def test_qwen_receives_language_name(monkeypatch, given, expected):
    from services.transcriber import _transcribe_qwen3_asr
    seen = _qwen_env(monkeypatch)
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", _fake_run([]))
    assert _transcribe_qwen3_asr("a.m4a", given, "Qwen3-ASR-1.7B", "cpu", "", None).success
    assert seen["language"] == expected


def test_qwen_stores_iso_code_as_detected_language(monkeypatch):
    from services.transcriber import _transcribe_qwen3_asr
    _qwen_env(monkeypatch)  # fake model reports language "English"
    monkeypatch.setattr("services.transcriber.shutil.which", lambda n: "ffmpeg")
    monkeypatch.setattr("services.transcriber.subprocess.run", _fake_run([]))
    result = _transcribe_qwen3_asr("a.m4a", "auto", "Qwen3-ASR-1.7B", "cpu", "", None)
    assert result.detected_language == "en"
