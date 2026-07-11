# Epic 38: pytest API Tests

**Status:** 🔵 Planned  
**Phase:** Engineering Quality  
**Depends on:** —  
**Blocks:** —

---

## Strategic Context

YT Summarizer is an API-first app: all business logic lives in the FastAPI backend. The frontend is a thin client. There are no automated tests — every change is verified manually.

pytest API tests cover the full backend contract without a browser or a running Ollama instance. They run in-process via `httpx.AsyncClient + ASGITransport`, use an isolated in-memory SQLite DB, and mock external calls (yt-dlp subprocess, Ollama HTTP). Fast, deterministic, easy to add to CI.

Highest ROI test type for this stack. Playwright E2E can come later on top.

---

## Goal

A `pytest` suite in `tests/` that covers all critical API endpoints. Runs with one command (`pytest`), no external services needed.

---

## Tech Decisions

| Choice | Decision | Reason |
|---|---|---|
| HTTP client | `httpx.AsyncClient` + `ASGITransport` | In-process, no real server needed |
| DB | In-memory SQLite (`:memory:`) | Isolated per session, no cleanup needed |
| yt-dlp | `unittest.mock.patch` on `subprocess.run` | Returns fixture VTT data |
| Ollama | `pytest-httpx` or `respx` — mock `httpx.AsyncClient` | Returns fixture LLM responses |
| Async | `pytest-asyncio` with `asyncio_mode = "auto"` | All tests are async |
| Fixtures | `conftest.py` shared fixtures | `app`, `client`, `seeded_video`, `seeded_result` |

---

## File Structure

```
tests/
├── conftest.py           — app fixture, test client, in-memory DB override
├── fixtures/
│   ├── sample.vtt        — minimal VTT subtitle file for yt-dlp mock
│   └── ollama_chat.json  — sample Ollama /api/chat response
├── test_health.py        — GET /api/health
├── test_settings.py      — GET/PUT/DELETE /api/settings
├── test_process.py       — POST /api/process, GET /api/status/{task_id}
├── test_result.py        — GET /api/result/{video_id}, DELETE
├── test_cleanup.py       — POST/DELETE /api/result/{video_id}/cleanup
├── test_summary.py       — POST/DELETE /api/result/{video_id}/summary
├── test_queue.py         — POST /api/queue/bulk, GET, DELETE endpoints
└── test_history.py       — GET /api/history (pagination, search, favorites)
```

---

## User Stories

### US-3801: Test infrastructure (conftest + fixtures)

**Given** `pytest` runs  
**When** any test is collected  
**Then**
- FastAPI `app` uses an in-memory SQLite DB (`sqlite+aiosqlite:///:memory:`)
- `_migrate_db()` + `init_db()` run once per session
- `app_settings` seeded with test values (`ollama_url=http://mock-ollama`, `ytdlp_path=/fake/yt-dlp`, `cookies_path=/fake/cookies.txt`)
- `httpx.AsyncClient` is the test client, bound to the app via `ASGITransport`
- All tests share one DB session (faster) OR each test gets a fresh DB (safer — TBD in impl)

**Fixtures needed:**
```python
@pytest.fixture(scope="session")
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

@pytest.fixture
async def seeded_video(client) -> dict:
    # inserts a Video + SubtitleFormatted row directly into DB
    # returns { video_id, task_id }
```

**Edge Cases:**
- DB override must happen before `lifespan()` runs (engine created at import time) — use `app.dependency_overrides` or monkeypatch `database.DATABASE_URL` before import

**Notes for Engineering:**
- `pytest-asyncio >= 0.23`, set `asyncio_mode = "auto"` in `pyproject.toml` or `pytest.ini`
- Add `tests/` to `.gitignore` exclusions for `__pycache__` only; keep test files tracked

---

### US-3802: Health endpoint tests

**File:** `test_health.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_health_backend_up` | GET /api/health, Ollama mock returns 200 | `{ backend: true, ollama: true }` |
| `test_health_ollama_down` | GET /api/health, Ollama mock returns ConnectionError | `{ backend: true, ollama: false }` |

**Notes for Engineering:**
- Mock `httpx.AsyncClient.get("{ollama_url}/api/tags")` via `respx` or `pytest-httpx`

---

### US-3803: Settings CRUD tests

**File:** `test_settings.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_get_settings_default` | GET /api/settings after seed | Returns `{ app, cleanup, summarization }` with seeded values |
| `test_put_app_settings` | PUT /api/settings/app `{ ollama_url: "http://new" }` | 200, GET /api/settings returns updated value |
| `test_put_stage_settings` | PUT /api/settings/cleanup `{ model: "qwen2.5:7b", system_prompt: "..." }` | 200, persisted |
| `test_delete_stage_settings` | DELETE /api/settings/cleanup | 200, prompts reset to defaults |
| `test_get_models_ollama_down` | GET /api/models, Ollama offline | Returns `[]` (not 500) |

---

### US-3804: Process + status endpoint tests

**File:** `test_process.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_process_new_video` | POST /api/process `{ url, language: "ru" }`, yt-dlp mock returns sample.vtt | 202, `{ task_id, video_id }` |
| `test_process_status_done` | GET /api/status/{task_id} after processing completes | `{ status: "done", video_id }` |
| `test_process_duplicate` | POST /api/process same URL twice | 409, `{ video_id }` |
| `test_process_language_missing` | yt-dlp mock raises LANGUAGE_NOT_AVAILABLE | GET /api/status → `{ status: "failed", available_languages: [...] }` |
| `test_process_invalid_url` | POST /api/process `{ url: "not-a-url" }` | 422 or descriptive error |

**Notes for Engineering:**
- Mock `subprocess.run` → writes `sample.vtt` to a temp path, returns `returncode=0` and fixture JSON via `--print-json`
- Use `tmp_path` pytest fixture for VTT file destination

---

### US-3805: Result endpoint tests

**File:** `test_result.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_get_result` | GET /api/result/{video_id} with seeded row | Returns full result shape: `{ video_id, formatted_text, cleanup_status, summary_status, ... }` |
| `test_get_result_not_found` | GET /api/result/nonexistent | 404 |
| `test_delete_result` | DELETE /api/result/{video_id} | 200, subsequent GET → 404 |

---

### US-3806: Cleanup endpoint tests

**File:** `test_cleanup.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_trigger_cleanup` | POST /api/result/{video_id}/cleanup, Ollama mock returns cleaned text | `cleanup_status` transitions `null → processing → done` |
| `test_cleanup_no_model` | POST trigger when `cleanup.model` is null in settings | `cleanup_status: "failed"` |
| `test_cancel_cleanup` | POST trigger, then DELETE before done | `cleanup_status` resets to `null`; `cleaned_text` unchanged |
| `test_cleanup_ollama_down` | Ollama mock → ConnectionError | `cleanup_status: "failed"` |

**Notes for Engineering:**
- `cleanup_status` transitions happen in background task — await task completion via `asyncio.sleep` polling or mock `asyncio.create_task` to run synchronously

---

### US-3807: Summary endpoint tests

**File:** `test_summary.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_trigger_summary_single_pass` | POST summary, text < 24K, Ollama mock → summary | `summary_status: done`, `summary_mode: single_pass` |
| `test_trigger_summary_map_reduce` | POST summary, text ≥ 24K, mock MAP+REDUCE | `summary_status: done`, `summary_mode: map_reduce` |
| `test_cancel_summary` | POST then DELETE | Status resets, `summary_text` unchanged |
| `test_summary_uses_cleaned_text` | `cleaned_text` present | Input to Ollama = `cleaned_text`, not `formatted_text` |

---

### US-3808: Queue endpoint tests

**File:** `test_queue.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_queue_bulk_add` | POST /api/queue/bulk `{ urls: ["https://..."], stages: ["extract"] }` | `{ added: 1, duplicates: [], invalid: [] }` |
| `test_queue_bulk_duplicate` | Add same URL twice | Second call: `{ added: 0, duplicates: ["url"] }` |
| `test_queue_bulk_invalid_url` | Add `"not-a-url"` | `{ added: 0, invalid: ["not-a-url"] }` |
| `test_queue_get` | GET /api/queue after bulk add | Returns item with correct `status: pending` |
| `test_queue_counts` | GET /api/queue/counts | `{ pending: 1, processing: 0, failed: 0 }` |
| `test_queue_delete_item` | DELETE /api/queue/{id} | 200, item gone |
| `test_queue_clear_all` | DELETE /api/queue/all | 200, queue empty |

---

### US-3809: History endpoint tests

**File:** `test_history.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_history_empty` | GET /api/history, no videos | `{ items: [], total: 0 }` |
| `test_history_pagination` | Seed 25 videos, GET /api/history?page=1 | Returns 20 items |
| `test_history_page_2` | GET /api/history?page=2 | Returns 5 items |
| `test_history_search` | Seed video with title "Python Tutorial", GET /api/history?q=python | Returns 1 match |
| `test_history_favorites_filter` | Seed 3 videos, favorite 1, GET /api/history?favorites_only=true | Returns 1 |
| `test_history_delete_bulk` | POST /api/history/delete-bulk `{ video_ids: [...] }` | 200, history empty |

---

## Dependencies (pyproject.toml additions)

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "respx>=0.21",        # mock httpx calls (Ollama)
]
```

Or `requirements-test.txt`:
```
pytest>=8.0
pytest-asyncio>=0.23
httpx>=0.27
respx>=0.21
```

---

## Run Command

```bash
cd app/backend
pytest tests/ -v
pytest tests/test_health.py -v    # single file
pytest -k "test_queue" -v         # filter by name
```

---

## Acceptance Criteria

**Given** `pytest tests/` is run with no external services  
**When** all tests pass  
**Then** all listed test cases exit green and total runtime < 30s

**Given** a new API endpoint is added  
**When** a developer adds a corresponding test  
**Then** the test verifies status code, response shape, and at least one error path

---

## Complexity Estimate

~4–5 hours:
- conftest + DB override + fixtures (~1.5h)
- Mock setup (yt-dlp subprocess + Ollama httpx) (~1h)
- test_health + test_settings + test_result (~0.5h)
- test_process + test_cleanup + test_summary (~1h)
- test_queue + test_history (~1h)
