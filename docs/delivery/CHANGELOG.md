# Changelog

Reverse-chronological, append-only. Format: see `documentation-conventions.md`.

## 2026-11-05

- **Adding to the queue is reliable (NS-28, NS-24a)**: the DB runs in WAL mode with a 30 s lock wait; a locked database gives a retry, then 503 "database busy" instead of a bare 500; the same link added twice at once gives one row (atomic insert); the SSL context is built once (no 230-700 ms stalls); unhandled errors go to `backend.log`, pytest no longer writes to the live log; DB backups now use `tools/backup_db.py`. Queue page: "New" button (uses the Home pipeline choice), add timeout, "Adding..." state, clear error with Retry, no lost quick links, honest text when an answer is lost; a known link opens its result by the server's id (no blank page); "Not found" page. Reviewed: clean after several rounds; QA passed on the live app. The live DB was converted to WAL by the backend's `--reload` before a backup (restore point taken right after; integrity ok). Commits: `23ea03e`..`6448294` (NS-24a and NS-28).

- **The agent chooses what it gets (NS-29)**: MCP `get_result` takes `parts` (summary, transcript, cleaned, mindmap, status) with `offset`/`limit` paging and a line telling what exists for the video; default answer unchanged except that line and the channel (the field was read under the wrong name). `search_history` now covers the whole history (it saw only the 20 newest), finds Cyrillic in any case, and with `in_text=True` searches inside the texts (new read-only `GET /api/history/text-search`; hits show the position to pass to `get_result`). Reviewed: clean after one round (Cyrillic case, query length cap, scan note). Checked live against the running backend. Restart the MCP client to load the new tools. Commits: `ff63a55`, `eb6ac1e`, `b4d5c88`, `b7c19b0`, `32dd2a3`, `b226f51`, `1fbdee0`, `dc37ae8`.

- **Empty model answers fixed (NS-26)**: summary, mind map and cleanup failed on long texts because Ollama ran with its default 4096-token context and a thinking model spent it all on thinking, returning an empty answer. Every Ollama chat call now sends a `num_ctx` sized to the input (setting `llm_max_num_ctx`, 4096–65536; the chat keeps `chat_num_ctx` as a floor); an empty answer is its own error with a clear message on the result page (`cleanup_error`, `summary_error`, `mindmap_error` columns, added by a migration; a backup was taken). Verified live: the two videos that failed now get summary and mind map. Reviewed: clean after two rounds. Commits: `90c7437`, `7d26488`, `41ae0bf`, `552d34a`, `8b45c65`.

## 2026-11-01

- **Qwen3-ASR works (NS-20)**: the Qwen engine picks its device through torch and falls back to CPU; CUDA build of torch installed (`2.14.1+cu126`); audio is converted to wav with ffmpeg first, so `.m4a`/`.mp4`/`.mkv` work; both engines accept language codes and names (re-transcribe with large-v3 had failed silently on `Russian`); `requirements.txt` fixed (`qwen-asr>=0.0.6`, torch note). Reviewed: clean after follow-ups. Commits: `a4b14c7`, `0cebb65`, `79304c9`, `0749a62`, `a2cc87d`.
- **ResultPage split (NS-14)**: 1,280-line `ResultPage.tsx` split into 10 files under `components/result/` (page now 424 lines); 14 smoke tests added first; pure move, 114 DOM snapshots identical before and after. Reviewed: clean. Commits: `dee1c7f`, `6c05d60`.
- **SettingsPage split (NS-13)**: 1,585-line `SettingsPage.tsx` split into 9 files under `components/settings/` (page now 300 lines); 8 smoke tests added first; pure move. Reviewed: clean. Commits: `dfdb205`, `ab8bb82`.

## 2026-10-31

- **api.py split (NS-12)**: 1,644-line `routers/api.py` split into 7 routers plus an 18-line aggregator; pure move, 52 routes and OpenAPI schema unchanged. Reviewed: clean after one fix (restored yt-dlp update error log). Commits: `54c43ae`, `41329dd`.
- **Housekeeping (NS-07, NS-09, NS-10)**: fixed hard-coded model count in tests (all 69+10+18 green); stale `processing` statuses reset on startup + try/except/finally on stage functions; `.env` path fixed to repo root (absolute via `Path(__file__).resolve()`). NS-06 already tracked; NS-08 local-only (launcher files gitignored). Reviewed: clean. Commits: `e8be8a1`, `729218e`, `c9b0a92`.
- **Security minimum (NS-01–05)**: bind backend to 127.0.0.1; cookie upload basename-only + 5 MB cap; yt-dlp URL whitelist (https + YouTube hosts) + `--` before every user URL; markmap HTML escaped; uploads/cookies/db gitignored. Reviewed: clean. Commit: `db66a96`.
- **Project created from TeamKit**: rules, roles and addenda in place; New Start backlog (NS-01–14) written.
