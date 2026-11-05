# YT Summarizer - Product Backlog

Navigation and overview of all epics and user stories for YT Summarizer, organized by development phase.

---

## 🔴 New Start — 2026-10-31 (active, blocks all new features)

### Step 1 — Security minimum (each item is independently reviewable)

**NS-01 — Bind backend to 127.0.0.1** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("bind the backend to 127.0.0.1"); fixes F2 (partial)
Value: Closes LAN/Wi-Fi exposure; no network neighbour can reach the API unauthenticated
Labels: `by-backend`, `reviewed` | Commit: `db66a96`

**NS-02 — Cookie upload: basename only** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("keep only the base name of the uploaded cookie file"); fixes F1
Value: Prevents path-traversal write; a crafted filename can no longer overwrite arbitrary files or code
Labels: `by-backend`, `reviewed` | Commit: `db66a96`

**NS-03 — yt-dlp: validate URL and prepend `--`** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("check URLs properly and put `--` before the URL in yt-dlp calls"); fixes F3
Value: Prevents argument injection and SSRF; a `-`-prefixed "URL" can no longer be parsed as a yt-dlp flag
Labels: `by-backend`, `reviewed` | Commit: `db66a96`

**NS-04 — Mind map: disable HTML rendering** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("turn off HTML in markmap"); fixes F4
Value: Prevents stored XSS; LLM output with `<script>` or `<img onerror=...>` can no longer run in the app origin
Labels: `by-frontend`, `reviewed` | Commit: `db66a96`

**NS-05 — Gitignore uploads dir and cookie variants** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("gitignore app/data/uploads/ and the cookie files"); fixes F5
Value: Private video/audio files and live YouTube session cookies cannot be committed to the public repo by mistake
Labels: `by-backend`, `reviewed` | Commit: `db66a96`

---

### Step 2 — Housekeeping (after step 1 is merged)

**NS-06 — Commit untracked MCP server and tests** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("commit the untracked MCP server and tests"); fixes F6
Value: Fresh clone works; `npm test` and MCP feature have coverage in git; agents in a worktree get the full codebase
Fix: all files were already tracked — no commit needed
Labels: `by-backend`, `by-mcp`, `by-frontend` | Note: files were already in git

**NS-07 — Fix 2 failing backend tests** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("fix the 2 failing tests"); fixes F14 (partial)
Value: Suite goes green; regressions surface in CI, not in production
Fix: `test_transcriber.py:59` and `:241` — replaced hard-coded `11` with `len(MODEL_CATALOG) + len(QWEN_CATALOG)`
Labels: `by-backend` | Commit: `e8be8a1`

**NS-08 — One launcher, one port; scope kill-backend.bat** ✅ Done · local only
Origin: Owner, 2026-10-30 ("one launcher and one port, kill-backend.bat must not kill every uvicorn"); fixes F12
Value: Start/stop scripts no longer kill other projects' services; one `make dev` starts everything
Fix: launcher files updated locally (port 8000→9010, PID file in `kill-backend.bat`/`start.vbs`/`start.sh`) — no git record since all 4 launcher files are gitignored
Labels: `by-backend`, `by-cto` | Note: no commit — launcher files are gitignored

**NS-09 — Reset stale "processing" on startup** ✅ Done · reviewed
Origin: Owner, 2026-10-30 ("stale processing status reset on start"); fixes F7
Value: After server restart, UI no longer polls forever; Re-extract and Cancel work again
Fix: startup in `main.py` resets all `processing` rows to `NULL`; try/except/finally on 3 stage functions sets `'failed'`
Labels: `by-backend` | Commit: `729218e`

**NS-10 — Fix .env loading path** ✅ Done · reviewed
Origin: Owner, 2026-10-30 (".env loading"); fixes F16
Value: Settings in `.env` actually apply; CORS and `OLLAMA_URL` become configurable without code changes
Fix: `config.py` — `env_file = Path(__file__).resolve().parents[2] / ".env"`; added `extra="ignore"` (`.env` contains non-backend keys `FRONTEND_PORT`, `BACKEND_HOST`)
Labels: `by-backend` | Commit: `c9b0a92`

---

### Step 3 — Restructure, no new features (after step 2 is merged)

**NS-12 — Split api.py into modules (1,644 lines)**
Origin: Owner, 2026-10-30 ("split the large files"); addresses review root cause 2
Value: Pure move, no behaviour change — easy to verify; makes NS-11 safe (pipeline logic in small focused files)
Fix: extract routers by area (process, result, settings, download, history) into `app/backend/routers/`; each file ≤ 400 lines. Rule: move and behaviour change never in one commit; reviewer checks `git diff --color-moved`; tests must not change
Labels: `by-backend`, `reviewed` | Status: ✅ Done · reviewed | Commits: `54c43ae`, `41329dd` (restored yt-dlp update error log)
Follow-up: `routers/result.py` (665 lines) and `routers/process.py` (459) are still over 400; split them after NS-11. Bugs seen and left alone: `upload_cookies` `db=None` default; `trigger_mindmap`/`trigger_reextract` skip the Ollama/model checks.

**NS-13 — Split SettingsPage.tsx (1,585 lines)**
Origin: Owner, 2026-10-30 ("split the large files"); addresses review root cause 2
Value: Settings changes are contained; 59 `useState` calls visible per component
Fix: add vitest smoke tests for the page first; extract each settings tab into `app/frontend/src/components/settings/`; owner confirms in running app after
Labels: `by-frontend`, `reviewed` | Status: ✅ Done · reviewed, waiting for the owner's visual check | Commits: `dfdb205` (8 smoke tests), `ab8bb82` (1,585 → 300 lines, 9 files)
Left alone (own items later): cookie upload uses raw `fetch`; `StagePanel`/`FileStoragePanel` `handleSave` skip `onSaved`; `SttPanel.saveField` swallows errors; toast timers not cleared; no tests for cookie upload, clear uploads, STT download, yt-dlp update

**NS-21 — `npm run build` fails at tsc (jest types)**
Origin: Code Reviewer, 2026-11-01 (NS-13 review; the same two errors exist before NS-13)
Value: the production build and any CI step pass; `tsc` no longer leaves stray `.js` files next to sources
Fix: `@testing-library/jest-dom` asks for jest types while the project uses vitest: add the vitest globals types / jest-dom vitest entry to `tsconfig`; make `tsc` not emit (`--noEmit`)
Labels: `by-frontend` | Status: 🔴 Open | Order: small, after NS-14

**NS-14 — Split ResultPage.tsx (1,276 lines)**
Origin: Owner, 2026-10-30 ("split the large files"); addresses review root cause 2
Value: Result view changes are contained; 31 `useState` calls visible per component
Fix: add vitest smoke tests first; extract tabs (Subtitles, Cleaned, Summary, MindMap, Chat) and actions bar into `app/frontend/src/components/result/`; owner confirms in running app after
Labels: `by-frontend`, `reviewed` | Status: ✅ Done · reviewed, waiting for the owner's visual check | Commits: `dee1c7f` (14 smoke tests), `6c05d60` (1,280 → 424 lines, 10 files in `components/result/`), `78a8f78` (gitignore `backend.pid`)
Review method worth reusing: 114 DOM snapshots (19 fixtures × initial state + 5 tabs) identical before and after. Left alone: the page is 24 lines over 400 (polling/timers stay); `useResultHandlers` takes about 40 parameters (group them at the next change); cancel errors only logged; mind-map Stop has no try/catch; `sendChatMessage` stale closure; Stop on a queued video cancels only the backend flag (NS-16)

**NS-11 — Remove duplicate pipeline (BackgroundTasks vs queue)**
Origin: Owner, 2026-10-30 ("remove the duplicated pipeline"); addresses review root cause 1
Value: Every fix is made once; the two copies no longer drift; Cancel and progress reporting work for all paths
Fix (in order):
1. Write API tests that fix current behaviour of each stage (cleanup, summary, mindmap, transcribe) — baseline before any change
2. List all divergences between the two copies; owner decides on behaviour differences visible to the user (cancel, order, parallel vs sequential)
3. Switch one stage at a time to queue-only; one commit per stage
4. State lives in DB (`processing_queue`), not module-level dicts — eliminates eternal "processing" on reload
5. Verify MCP server goes through queue too (not a third path)
Stage 0 done 2026-11-01 (tests only, no production change): baseline tests `11d6d63`, `95b1066`, review follow-ups `29314af`; backend 155 and MCP 12 tests pass. Reviewed: clean. Map: MCP uses only the BackgroundTasks copy (no third path); the queue cannot handle local files (`local://` rejected), so file cleanup/summary/mind map/transcribe exist only in the BackgroundTasks copy; the ProcessingPage `startCleanup`/`startSummary` chain is dead code. Divergences ranked (8 data-affecting, 5 visible) are pinned as `# BASELINE: known bug` tests. Waiting for the owner's decisions on the divergences before stage 1
Planned order (one commit per stage, review + QA after each): 0 delete the dead ProcessingPage chain; 1 queue items by `video_id` (local files) and fix the History bulk id; 2 mind map; 3 summary; 4 cleanup (DB-backed progress first); 5 file transcription; 6 re-extract/re-transcribe; 7 YouTube extract (`/api/process`, MCP and HomePage change with it)
Labels: `by-backend` | Status: 🟡 Stage 0 done, decisions pending | Depends on: NS-12

---

### After step 3 — small items unblocked by restructure

**NS-15 — MCP `get_result`: add `kind` parameter**
Origin: Owner, 2026-10-31 (found in live use); noted in new-start.md
Value: MCP callers can get the full transcript instead of just the summary; current `include_text=true` silently returns the summary
Fix: add `kind: Literal["subtitles","cleaned","summary","mindmap"] = "cleaned"` to `get_result`; return the matching field from the DB row
Labels: `by-mcp` | Status: 🔵 Planned | Depends on: NS-11

**NS-16 — One cancel mechanism, two kinds of button** (🔴 first item after NS-11)
Origin: Owner, 2026-11-01 ("the cancel button is a very important element; one global button, one global mechanism; the button on the video/audio page cancels whatever process of this item is in the queue"); found by QA baseline S6 (no cancel for a running job anywhere in the UI; Epic 12 had "Stop" on the result page)
Value: any running or waiting job can be stopped from the UI, from the queue and from the page of its video or audio, whatever the stage (extract, transcribe, cleanup, summary, mind map)
Fix: one cancel path in the backend, in the queue (cancel a pending job = remove; cancel a running job = set a cancel flag that the stage checks, status ends `cancelled`, never stuck in `processing`); the same endpoint serves both buttons. UI: a Cancel button on every active row of the queue page, and a Stop button on the result page whenever a job of this video is pending or running (cancels that job). QA S6 becomes a real scenario: start cleanup of the 3:33 video, press Stop, status returns to idle
Labels: `by-backend`, `by-frontend` | Status: 🔵 Planned | Depends on: NS-11 (the single pipeline gives the single cancel path)

**NS-17 — UI fixes found by the QA baseline (2026-11-01)** (start only after the refactor is finished and accepted)
Origin: Owner, 2026-11-01 ("write all the small remarks into the backlog and fix them after the refactoring ends successfully"); QA baseline report
Value: the app stops looking stuck or broken in everyday use
Items, each a small separate commit:
1. After "Clean with AI" the result page does not refresh when the job ends (Cleaned tab stays empty until reload); the Summary tab does refresh. One refresh behaviour for all tabs
2. "Added to queue (summary/mindmap)" banners stay after the job is done and carry over between tabs
3. Header character count changes between views (247 / 243 / 230)
4. Bulk add: the single-URL form stays visible and the real textarea sits about 860 px lower; newlines typed into the single field glue the URLs together
5. Queue table is wider than its card at 1024 px; the Remove/Cancel column is off-screen
6. Queue row order changes between refreshes
7. Mind map first renders tiny and low-contrast on the dark background
8. A local-file result page has no source badge in the meta row (History has one)
9. (withdrawn) Re-extract showed no effect only because the browser pane auto-dismisses `window.confirm()`; not an app bug. A 409 appeared once during QA, origin unknown
10. markmap throws `NotSupportedError ... SVGLength` when the mind map is drawn while its tab is hidden (render still ends fine)
11. Queue shows 155+ old rows; consider a "clear finished" action (ask the owner first; it deletes data)
12. Owner, 2026-11-03: the owner ticked "download" together with the standard pipeline, but the queue row (`shorts/Ip8NJMk42wE`) shows only `extract → cleanup → summary → mindmap`; download is not shown as a stage. Not yet checked whether the download is skipped or only missing from the display (first look: does NS-11 stage design have a place for it); record only, do not fix now. Owner: the download itself works well and nothing breaks; items 12-14 are live-testing observations, not defects of the download
13. Owner, 2026-11-03 (same row, `failed`: "This video has no subtitles available."): when the video has no subtitles but the user also chose the download option, the download must still happen; the job should report "no subtitles" without failing the download. The owner also suggested telling the user interactively that there are no subtitles and offering to download the file (the rest of his sentence was garbled in dictation; read as "offer to download the file so it can be transcribed", owner said yes 2026-11-03). Related to item 12 and to NS-11 stage 7 (YouTube extract); record only, do not fix now
14. Owner, 2026-11-03 (video `1C3Aj50pcnc` "6 покупок, которые делают вас беднее", 12:26, cleaned text about 28,000 chars, no summary): "Generate mind map" shows "Mind map generation failed. Check Ollama and model settings." CTO check: not a missing-summary dependency (the code falls back to cleaned text, `result.py:466`). The log shows Ollama accepting the request and returning 0 tokens (`stream done, 0 tokens received`, gemma4:e2b loaded with context 4096, input about 15,500 chars); `generate_mindmap` treats the empty answer as a failure (`text_mindmapper.py:104`) and the page shows a generic text. Summary on the same video also failed within 5 s (cause not found in the log). ROOT CAUSE found 2026-11-05 (video `jZ0pSd8iw3U`, 14,348 chars, `gemma4:e4b`; direct test against Ollama): no `num_ctx` is sent, so Ollama uses its default context of 4096 tokens. The text alone is 3,851 tokens; gemma4 is a "thinking" model, spends the few tokens left on `message.thinking`, stops with `done_reason: length` and an empty `message.content`; the app reads only `content`, so the answer is empty and the stage is `failed`. With `num_ctx: 16384` the same request returns 1,658 chars of content (`done_reason: stop`, 25 s). Not a missing-summary dependency, not the model alone. Long text sent in one call fails; a video that went through sectioned notes (`NKY9hsqHCTI`, 25,284 chars) worked. Fix to plan: send `num_ctx` sized to the input for every Ollama call (summary, mindmap, cleanup, chat) or cap the input; treat an empty `content` with a non-empty `thinking` as a distinct error with its own message. To do: show the real reason (empty answer, context too small, model missing); when the text is too long or summary is missing, offer the missing steps or a retry with another model (owner's idea: offer to run the missing steps). Belongs with NS-11 decision 5 (explicit `failed` with message); record only, do not fix now. Fixed by NS-26 (QA 2026-11-05: both videos now complete)
15. QA 2026-11-05: summary text starts with broken markdown on `jZ0pSd8iw3U` and `1C3Aj50pcnc`: `*   **\n\n## Вступление**` (a bold marker around a heading); model output, probably the prompt or a post-processing step; check the prompt and add a clean-up of the first lines
16. QA 2026-11-05: browser console shows `<g> attribute transform: Expected number, "translate(NaN,NaN) scale(...)"` from the mind map (10 of 11 buffered errors on /queue; new compared with 2026-11-01); same family as item 10 (markmap drawn while hidden or with zero size); re-check on a fresh load of a Result page
17. QA 2026-11-05: summary on a short video takes 8 s with gemma4:e4b (baseline 3 s with e2b): the summarization model in Settings is now e4b; not a defect, note for timing comparisons
Labels: `by-frontend` (item 3 may need `by-backend`) | Status: 🔵 Planned | Depends on: NS-11, NS-13, NS-14 (most of these touch the pages being split)

**NS-19 — Word list for speech-to-text** (idea, after the refactor; a new feature)
Origin: Owner, 2026-11-01 (QA baseline S5: "Claude Code" heard as "PlotCode"; the owner says no transcriber he has tried recognises this name)
Value: names and terms the owner uses often (Claude Code, Ollama, project names) come out right in transcripts
Fix (to be refined with the owner): a list of words in Settings → STT, passed to the speech engine as a hint (Whisper `initial_prompt`; check that Qwen3-ASR has an equivalent); optionally the same list added to the cleanup prompt so the LLM fixes leftover mishearings
Labels: `by-backend`, `by-frontend` | Status: 🔵 Idea | Depends on: NS-11, NS-14

**NS-20 — Qwen3-ASR fails: "Torch not compiled with CUDA enabled"** (bug, small, not caused by the refactor)
Origin: Owner, 2026-11-01 (screenshot: Processing Failed on a file with Qwen3-ASR-1.7B active)
Value: choosing Qwen3-ASR works on this machine instead of failing the job
Cause (CTO check): the backend venv has `torch 2.15.0+cpu` (CPU-only build), while the GPU (RTX A4000) is seen by ctranslate2. `services/transcriber.py:436` picks `cuda:0` for Qwen from `ctranslate2.get_cuda_device_count()`, not from `torch.cuda.is_available()`, so torch is told to use a device it cannot use. Whisper is unaffected (QA S5 passed on CUDA)
Fix: (1) code: for the Qwen engine decide the device by `torch.cuda.is_available()`, and fall back to CPU with a log line if CUDA init fails, as the Whisper path already does; test with torch mocked. (2) environment, owner's decision: install the CUDA build of torch into `app/backend/.venv` (a download of about 2.5 GB) for GPU speed; `requirements.txt` then needs a note on which torch build to install
Progress 2026-11-01: device fix `a4b14c7` and CUDA torch `2.14.1+cu126` (no CUDA wheel of 2.15.0 exists; cu130 needs driver 580+, the owner has 573.48) with the requirements note `0cebb65`; Qwen now runs on `cuda:0`. Found while testing: the Qwen path cannot read `.m4a` (`soundfile` "Format not recognised"), fix in progress (convert to wav with ffmpeg first)
Seen, not in scope: Qwen stores the language as `Russian`, Whisper as `ru` (History badges); `requirements.txt` says `qwen-asr>=0.1.0` but 0.0.6 is installed; a failed re-transcribe is only a log warning and the old transcript stays silently (belongs to NS-16)
Done: `a4b14c7` (device by torch, CPU fallback), `0cebb65` (requirements note), `79304c9` (ffmpeg wav conversion), `0749a62` (review follow-ups: `qwen-asr>=0.0.6`, ffmpeg timeout/`-nostdin`/protocol whitelist, convert before model load), `a2cc87d` (language codes for both engines: re-transcribe with large-v3 had failed silently on `language="Russian"`). Torch is now `2.14.1+cu126` in `app/backend/.venv`. QA regression 3: S5 passes with large-v3 (0:06) and Qwen (0:09), language `RU`
Left alone: `language_to_qwen_name(None)` would raise (no caller passes None today); Qwen with `uk` is silently auto-detected (warning in the log only); old results with a language name in the DB would not match the language dropdown (none exist: checked)
Labels: `by-backend`, `reviewed` | Status: ✅ Done · reviewed

**NS-22 — Three old tests depend on test order**
Origin: Code Reviewer, 2026-11-01 (NS-11 stage 0 review)
Value: the suite is reliable in any order and in parallel runs
Fix: `test_summary::test_summary_uses_cleaned_text_when_available`, `test_queue::test_queue_bulk_add`, `test_process::test_process_new_video` fail (409 instead of 200) when the whole suite runs in reverse order, also at `11d6d63~1`; make each test own its data. Also `_setup` in the baseline tests changes shared settings without restoring them
Labels: `by-backend` | Status: 🔴 Open | Order: after NS-11

**NS-23 — Downloaded files keep the video's original title** (feature, after the refactor)
Origin: Owner, 2026-11-04
Value: a saved video or audio file from YouTube is recognised by its name instead of an id
Feature: a video or audio file downloaded from YouTube is saved under the original title of that video's page (the title shown on YouTube). Local files keep their own name. To refine with the owner: characters not allowed in Windows file names, very long titles, two videos with the same title, and the file extension; the name must be reduced to a safe base name (project rule: file names from outside are never used as paths)
Labels: `by-backend` | Status: 🔵 Idea | Depends on: NS-11 (the download is part of the pipeline, see NS-17 items 12-13)

**NS-24 — Queue takes any number of videos; bulk add is easy to find** (bug to confirm + UI, after the refactor)
Origin: Owner, 2026-11-04 ("when I put many in a row, not all of them run; it seems to hit a limit and stop accepting; remove that limit. And make bulk add of URLs: 10 URLs in a column in a window in the UI, all go into the queue and are processed one after another")
Value: the owner pastes a list of links once and walks away; every link is queued and processed in turn
CTO check 2026-11-04 (code and live DB, nothing run):
- No count limit exists in `POST /api/queue/bulk` (`routers/process.py:331`) or `add_items` (`queue_service.py:66`): `urls: list[str]` has no max length; the DB holds 186 queue rows (184 done, 1 failed, 1 processing)
- The worker runs one item at a time (`queue_service.py:603`), so a long list simply takes long; a long pipeline (extract → cleanup → summary → mindmap, minutes per video) can look like "stopped accepting"
- Links that are skipped without a clear message: a duplicate inside the same batch is reported as "invalid"; a video already processed or already in the queue is skipped (`duplicates`); a URL without a recognisable video id is "invalid"
- Bulk add already exists on the Home page ("Bulk Add" panel, one URL per line) and on History; NS-17 item 4 notes it is hard to find (the textarea sits about 860 px lower than the single-URL field)
Owner's idea 2026-11-04: maybe adding links through the UI one at a time is slow, so they feel lost; wants a fast one-by-one add. CTO read `HomePage.tsx` (nothing run), which supports it:
- One URL = one request (no sleeps), so the request itself is fast; the slowness is the flow. After every successful add the page jumps to `/queue` (`navigate('/queue')`, lines 155 and 176); to add the next link the owner must go back to Home, paste, click, and be moved away again
- A link that is already processed or queued sends the owner to `/result/<id>` instead (lines 150-153, 171-174): the link seems to vanish and the result page opens
- With "extract only" and no STT the single field does NOT use the queue: it calls `/api/process` and opens the Processing page (lines 183-199), the old BG path (the two-pipeline problem of NS-11). Several links added this way in a row are not queued but each starts its own direct run, which fits "not all of them work"
Not found: any cap. The failure the owner saw is not reproduced yet; to do (0, first): quick one-by-one add: paste a link, Enter, the field clears, the page stays, a short line "added (n in queue)" or the reason for a skip, and every add goes through the queue, never the direct path; then: (1) reproduce with 20-30 distinct URLs through the UI and read the report the page shows and `data/logs/backend.log`; (2) if links vanish, find where (frontend report, backend dedup, worker); (3) make the skip reasons explicit per URL (new / already processed / already in queue / duplicate in the list / not a YouTube link); (4) make the bulk window the main add form (a textarea, one URL per line, pipeline choice, one "Add all" button); (5) a test that adds 50 URLs and gets 50 rows back in order
Owner, 2026-11-05: a "New" button in the header of the Processing Queue page (next to "Retry failed", "Clean failed", "Clear pending", "Home"). It adds a video with the default pipeline that is already chosen in Settings (`queue_default_pipeline`), without leaving the queue. Why: the owner adds a video, goes to the queue to see that it arrived, and from there adds the next one. Fits the quick one-by-one add (step 0 above): the button opens a small field for one URL (or the bulk window), Enter adds it, the row appears in the table at once, the page stays; skip reasons are shown per URL
Labels: `by-backend`, `by-frontend` | Status: 🔵 Planned | Depends on: NS-11, NS-17 item 4 (same form)

**NS-26 — Empty answers from the model: send `num_ctx`, report the real reason** (bug, small, urgent; start now, before NS-11 stage 1)
Origin: Owner, 2026-11-05 (video `jZ0pSd8iw3U`: summary and mindmap `failed`); CTO root-cause check, see NS-17 item 14
Value: summary, mindmap and the other LLM stages stop failing on long videos; when they do fail the page says why
Cause: no `num_ctx` is sent to Ollama, default context 4096; gemma4 spends the tokens left on `message.thinking`, `done_reason: length`, `message.content` empty; the app reads only `content` and ends the stage as `failed` with a generic text. Test 2026-11-05: 3,851-token prompt, default context → empty content; `num_ctx: 16384` → 1,658 chars, 25 s
Fix: (1) every Ollama chat call (summary single and sectioned, mindmap, cleanup, chat) sends `num_ctx` sized to the input (prompt estimate plus room for thinking and the answer, with a cap from a setting; one helper, not five copies); (2) an empty `content` is a distinct error with its own message: "model returned no answer (thinking used the whole context)" when `thinking` is non-empty, "model returned nothing" otherwise; the stage ends `failed` with that text on the result page instead of "Check Ollama and model settings" (the full per-stage table is NS-25); (3) tests with the Ollama call mocked: long input gets a larger `num_ctx`, empty content with thinking gives the specific message; (4) after it, QA re-runs summary and mindmap on `jZ0pSd8iw3U` and `1C3Aj50pcnc` (both failed before) and S1-S4
Not in scope: the per-stage status table (NS-25), the queue showing `done` after failed stages (NS-25), any change of models or prompts
Done 2026-11-05: `90c7437` (num_ctx helper in all four Ollama call sites), `7d26488` (empty answer = own error, shown on the result page; 3 columns `cleanup_error`, `summary_error`, `mindmap_error`, temporary until NS-25). Review: fix cleanup empty answers first (Medium) plus four Lows; follow-up commit sent to Developer (cleanup fails when most paragraphs are empty; `llm_max_num_ctx` clamped to 4096..upper bound; chat keeps `chat_num_ctx` as a floor; log truncated answers; hint in the message)
Left for later (CTO decision 2026-11-05): UI field for `llm_max_num_ctx` and the label of `chat_num_ctx` (Settings → General; with NS-17); benchmark ignores the limit; an empty answer in chat is passed through; inputs above the biggest bucket are cut by Ollama (log warning only); queue item stays `done` after failed stages (NS-25). Before the first restart on the live DB: back up `app/data/db` (rule 11), the migration only adds 3 columns and was rehearsed on a copy
Closed 2026-11-05: follow-ups `41ae0bf` (cleanup fails when most paragraphs are empty, `llm_max_num_ctx` clamped 4096..65536, chat keeps `chat_num_ctx` as a floor, truncated-answer warning, hint text) and `552d34a` + `8b45c65` (chat upper bound `max(chat_num_ctx, llm_max_num_ctx)`, `chat_num_ctx` validated, hint reworded, two tests; `8b45c65` repairs a syntax slip in `552d34a`, which does not build on its own: mind it in `git bisect`). Re-review clean. QA on the live app (2026-11-05): `jZ0pSd8iw3U` and `1C3Aj50pcnc` now get summary and mindmap, S1-S4 and a full queue run pass; the new empty-answer text itself was not seen live (only mocked tests). Tests: backend 193, MCP 12, frontend 44. Also left for NS-25: a cleanup whose paragraphs mostly failed by network error or timeout still ends `done` with the original text
Labels: `by-backend`, `reviewed` | Status: ✅ Done · reviewed | Depends on: nothing

**NS-25 — Per-stage status table and an honest queue status** (after NS-26, inside or right after NS-11)
Origin: Owner, 2026-11-05 ("a table for the four stages: type, status, failure reason, to diagnose quickly"); CTO check of `jZ0pSd8iw3U`
Value: any failed stage is visible at a glance with its reason; a queue item is `done` only when every chosen stage succeeded
Today: queue items 208 and 210 are `done` with no error although summary and mindmap failed; stage data sits in different columns of `subtitles_formatted` (cleanup has status, times, model; summary has status, times, model, mode; mindmap only a status; only extraction has an error text); no reason is stored for cleanup, summary or mindmap
Plan: one table `processing_stages` (video id, stage: extract/transcribe/cleanup/summary/mindmap, status, started, finished, model, error code, error text, attempt, queue item id), one row per run, history kept; reason codes `empty_answer`, `context_too_small`, `model_missing`, `timeout`, `no_subtitles`, `ollama_down`, `cancelled`, `unexpected`; the result page shows the four stages as a small table; the queue item ends `done` only when all chosen stages are `done`, otherwise `partial` with the failed stage named; the old columns are filled from the table or dropped in one reviewed migration (back up first, rule 11)
Labels: `by-backend`, `by-frontend` | Status: 🔵 Planned | Depends on: NS-26; fits NS-11 (state in the DB, not in module dicts)

**NS-27 — Error monitoring** (idea, after NS-25; groundwork for a multi-user service)
Origin: Owner, 2026-11-05 ("if this becomes a multi-user service we must know where things fail and why")
Value: failures can be counted and traced instead of read out of a log
Plan (to refine): a summary page over `processing_stages` (failures per stage, per model, per reason, per day); structured logs (one JSON line per stage event with request id, video id, stage, reason code) in place of text lines; request and user ids carried in every record once there are users; metrics export (for example Prometheus) only when a second user exists
Labels: `by-backend`, `by-frontend` | Status: 🔵 Idea | Depends on: NS-25

**NS-18 — Finish splitting the routers** (after NS-11)
Origin: CTO, 2026-11-01; NS-12 review ("`result.py` 665 and `process.py` 459 lines, over the 400-line limit")
Value: the rule "a file over about 400 lines is split" holds for the backend too
Fix: split `routers/result.py` and `routers/process.py` by area; pure move, no behaviour change; the known bugs seen during NS-12 stay out of the move and become their own items: `upload_cookies` `db=None` default; `trigger_mindmap`/`trigger_reextract` skip the Ollama/model checks
Labels: `by-backend` | Status: 🔵 Planned | Depends on: NS-11

---

## Phase 1: MVP - Subtitle Extraction & Formatting ✅

### Epic 1: Core Subtitle Extraction
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-1.md)

### Epic 2: Text Formatting & Presentation
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-2.md)

### Epic 3: Data Persistence
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-3.md)

### Epic 4: Error Handling & Edge Cases
**Status**: ✅ Done | **Priority**: 🟠 P1  
[View Epic →](./epics/EPIC-4.md)

### Epic 5: Web User Interface
**Status**: ✅ Done | **Priority**: 🔴 P0  
[View Epic →](./epics/EPIC-5.md)

---

## Phase 1.5: LLM Text Cleanup & UX Polish 🔄

Local LLM cleanup via Ollama. Runs on demand. No data leaves the machine.

### Epic 6: LLM Text Cleanup (Ollama)
**Description**: Manual AI cleanup trigger, spinner, polling, health check, Cleaned tab

**Status**: ✅ Done | **Priority**: 🟠 P1  
[View Epic →](./epics/EPIC-6.md)

---

### Epic 7: Settings Page — Prompts & Models Per Stage
**Description**: Web UI for editing system/user prompts and selecting models separately for cleanup and summarization stages

**Status**: ✅ Done | **Priority**: 🟠 P1  
[View Epic →](./epics/EPIC-7.md)

---

### Epic 8: Markdown Rendering (frontend only)
**Description**: Add react-markdown renderer to the Result page. Prompt part configured via Settings page (Epic 7).

**Status**: ❌ Dropped | **Priority**: 🟠 P1  
**Note**: Tested — LLM output quality inconsistent. Plain text rendering retained.

---

### Epic 9: Per-Tab Character Count
**Description**: Show separate character counts for Subtitles tab and Cleaned tab

**Status**: ✅ Done | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-9.md)

---

### Epic 10: Auto-Pipeline Toggle
**Description**: Checkbox on Home page to automatically run all three stages (Extract → Cleanup → Summarize) in sequence. Pre-flight validation checks all stages are configured before starting.

**Status**: ✅ Done | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-10.md)

---

### Epic 11: Model Selection in UI
**Description**: Covered by Epic 7 (Settings page). Inline model selector added to Result page for quick experimentation — auto-saves on change, no Save button needed.

**Status**: ✅ Done (partial — inline selector on Result page) | **Priority**: 🟡 P2  
[View Epic →](./epics/EPIC-11.md)

---

### Epic 12: Cancel Cleanup
**Description**: Stop button in UI to interrupt a running AI cleanup. In-memory cancel flag checked before each paragraph in Ollama loop. Status resets to null on cancel. Backend: `DELETE /api/result/{video_id}/cleanup`. Frontend: "✕ Stop" button while cleanup_status === 'processing'.

**Status**: ✅ Done | **Priority**: 🔴 P0

---

### Epic 13: Settings 2.0 — All Config via Web UI
**Description**: Move all user-facing settings out of config files into the DB, configurable exclusively via web. Includes: Ollama URL, cookies path, yt-dlp path. Settings page redesign with tabs (no scroll). Notification if model or prompt is missing before cleanup. Upload cookies via web. Single source of truth = DB.

**Status**: ✅ Done | **Priority**: 🟠 P1

---

### Epic 14: Cleanup Timer
**Description**: Show how long AI cleanup took. After completion — "Cleaned in X:XX" displayed in the result meta. DB-based: `cleanup_started_at` and `cleanup_finished_at` columns on `subtitles_formatted`. Written via raw SQL in `video_service.py`. Duration computed server-side in `get_result()`.

**Status**: ✅ Done | **Priority**: 🟡 P2

---

### Epic 15: LLM Summarization (Single-pass)
**Description**: Summary tab on Result page. Sends cleaned_text (or formatted_text) to Ollama in a single request. Cancel button, model selector per-tab, "Summarized in X:XX · model" in meta. Settings → Summarization unlocked.

**Status**: ✅ Done | **Priority**: 🟠 P1

---

### Epic 16: Cancel for Auto-Pipeline
**Description**: "✕ Stop pipeline" button on ProcessingPage when auto-pipeline is running (stage ② Cleaning or ③ Summarizing). Should cancel the active background job and navigate to result page with whatever is available.
- Cleanup cancel: `DELETE /api/result/{video_id}/cleanup` (already exists)
- Summary cancel: `DELETE /api/result/{video_id}/summary` (already exists)
- ProcessingPage needs to track which stage is active and call the right cancel endpoint on Stop

**Status**: ✅ Done | **Priority**: 🟡 P2

---

## Phase 2: LLM Summarization Quality 🔄

Improve summarization quality beyond single-pass. Map-reduce or chunked approach for long texts. See `docs/phase2-architecture.md`.

| Epic | Description | Status |
|------|-------------|--------|
| Epic 17: Map-Reduce Summarization | Auto-select single-pass vs map-reduce by text length; MAP (extract per chunk) + REDUCE (combine); live chunk counter in UI; force_map_reduce toggle for testing; Settings step tabs (Step 1 Extract / Step 2 Combine); always-visible method label in Result meta | ✅ Done |
| Epic 18: Hierarchical Map-Reduce | 3-level pipeline for texts > 50K chars: MAP → intermediate REDUCE per batch → final REDUCE. Fixes REDUCE overload on large inputs | 🔵 Planned |
| Epic 19: Prompt Management v2 | Language-aware prompts, per-stage templates | 🔵 Planned |
| Epic 20: Summary Quality Metrics | Show compression ratio, char count diff input/output | ✅ Done — "86% compressed" shown in Summary meta |
| Epic 21: Multi-Version Summaries | Store one summary per (video, model); view and switch between saved versions for model comparison | ⏸ Deferred — duplicates Benchmark (Epic 26) functionality. Re-evaluate if frequent model-switching on long Full Extract jobs becomes a real need. |
| Epic 22: Auto Language Detection | Detect original video language from yt-dlp metadata; "Auto (detect)" as default in Home page dropdown; manual override kept during testing | ✅ Done |
| Epic 23: Chapter-Aware Formatting | Use creator-defined YouTube chapters as semantic boundaries for subtitle grouping; `## Chapter Title` headings in formatted_text; fallback to 4s gap when no chapters | ✅ Done |
| Epic 24: Completion Notifications | Tab title changes to "✓ Done" when cleanup/summary finishes; Browser Notification when tab is hidden; permission requested lazily on first run | ✅ Done |
| Epic 25: Chapter Heading Preservation & Rendering | `## Chapter Title` headings pass through cleanup and summarization unchanged; rendered as visual subheadings in UI across all tabs. Post-fix (21.05): `normalize_chapter_headings()` in `text_utils.py` fixes inline `## ` markers without `\n\n`; applied server-side (all summarizer outputs) + client-side in `renderText.tsx` for legacy DB rows | ✅ Done |
| [Epic 26: Benchmark](./epics/EPIC-26.md) | Side-by-side N-model comparison; same mode logic as production pipeline; DB table `benchmark_runs`; `/benchmark` page + `/benchmarks` index; N-column layout; synchronized scroll; HTML export; stage selector (summary/cleanup); "📌 Original" badge for main-triggered runs; delete-run button | ✅ Done |
| [Epic 27: Full Extract (No-Reduce)](./epics/EPIC-27.md) | Lossless processing mode for long structured content: MAP per chapter (no REDUCE); auto-selected for chapter videos ≥ 24K chars; chapter progress in UI | ✅ Done |
| Epic 28: Processing Mode Management | Mode picker UI (auto-detect + manual override); unified mode selection across single-pass / map-reduce / full-extract / hierarchical | 🔵 Planned |
| [Epic 29: Parallel MAP Processing](./epics/EPIC-29.md) | Parallel paragraph/chunk/section processing via asyncio.gather() + Semaphore; preserves order via index; configurable workers matching OLLAMA_NUM_PARALLEL | ✅ Done |
| [Epic 33: Benchmark Metrics Enhancement](./epics/EPIC-33.md) | Capture real token counts and tok/s from Ollama done-message; add `prompt_tokens`, `completion_tokens`, `tokens_per_second`, `chunks_count` to BenchmarkRun; compute `compression_ratio` from existing chars; display all metrics per model column in BenchmarkPage | 🔵 Planned |
| [Epic 34: Bulk URL Queue](./epics/EPIC-34.md) | Bulk URL input on HomePage (textarea, one per line); `processing_queue` DB table; asyncio queue worker (sequential, one video at a time); configurable pipeline stages per batch (extract / +cleanup / full); Queue status page `/queue` with per-item status | ✅ Done |
| [Epic 35: Playlist Import](./epics/EPIC-35.md) | Paste YouTube playlist URL → yt-dlp flat-playlist extract → preview list with checkboxes → add selected to queue (Epic 34); auto-detect playlist URL in Bulk Add panel; 200-video limit | 🔵 Planned — depends on Epic 34 |
| [Epic 37: Suggested Questions](./epics/EPIC-37.md) | After summary is ready, LLM generates 3–5 short content-specific questions shown as clickable chips near the chat bar. Click → sends as chat message. Lazy trigger (on first Summary tab open). `suggested_questions` JSON column in DB. Lowers cold-start barrier to chat. | 🔵 Planned — depends on Epic 15 |
| [Epic 38: pytest API Tests](./epics/EPIC-38.md) | Full pytest suite for all API endpoints. In-process via `httpx.AsyncClient + ASGITransport`, in-memory SQLite DB, mocked yt-dlp (subprocess) + Ollama (respx). 8 test files: health, settings, process/status, result, cleanup, summary, queue, history. ~4–5h. | 🔵 Planned |
| [Epic 39: Chat Model Selector](./epics/EPIC-39.md) | Dedicated model selector for chat — separate from summary model. Inline dropdown in floating chat bar. Persisted in `pipeline_settings` under stage `chat`. Falls back to summary model if not set. | ✅ Done |
| Epic 40: Retry Failed Queue Item | Re-queue a failed item directly from the Queue page without going back to the Home page. "Retry" button per failed row; re-inserts original URL + pipeline stages + language into the queue. | 🔵 Planned — depends on Epic 34 |

---

## UX Polish & Bug Fixes (non-epic)

Small improvements and fixes that don't warrant a standalone epic.

| Date | Description |
|------|-------------|
| 19.05.2026 | Re-extract subtitles: `POST /api/result/{video_id}/reextract` — re-run extraction for an existing video without deleting its history |
| 19.05.2026 | VTT parser fix: decode HTML entities (`&#39;` → `'`) + collapse whitespace |
| 21.05.2026 | Chat typing animation: 3-dot bounce + spinner on the send button (yt-summarizer + llm-onpage-summarizer) |
| 21.05.2026 | History page: stage checkmarks ✓ (grey = not run, green = done) for Cleanup and Summary; type badges unified to a neutral style |
| 21.05.2026 | Result meta: always shows mode (Single Pass / Map-Reduce / Full Extract) next to model name |
| 21.05.2026 | Settings → Summarization → Map-Reduce: Step 1 / Step 2 split into horizontal tabs (scroll removed) |
| 21.05.2026 | Result meta redesign: two rows (video-info / stage-info), `•` separators, hover tooltips; classes `.meta-row`, `.meta-chip`, `.meta-sep`, `.meta-label` |
| 21.05.2026 | Result meta: `cleanup_finished_at` and `summary_finished_at` from API — finish timestamp shown at the end of each stage row |
| 21.05.2026 | Date format: `DD.MM.YYYY, HH:MM` (locale-independent) instead of `toLocaleString` |
| 04.06.2026 | **Favicon** — SVG red circle with white "YTS" (`public/favicon.svg`), wired up in `index.html` |
| 04.06.2026 | **Queue progress display** — `on_progress` callbacks connected in worker for cleanup/summary/mindmap; progress text ("paragraph 3/12", "chunk 5/20") in the banner and QueuePage table row with active-stage highlighting |
| 04.06.2026 | **Queue as sole LLM path** — HomePage autoPipeline → queue; ResultPage buttons (Clean with AI / Summarize / Mind Map / pipeline guard) → queue; `_run_mindmap_stage` in worker |
| 04.06.2026 | **Queue UX**: constant 3s polling; sort order processing→pending→failed→done, newest first within each group; QueueBadge polling 4s (was 8s) |
| 04.06.2026 | **History search** — search field by title+author, server-side `ILIKE` filtering, 350ms debounce |
| 04.06.2026 | **Favorites** — `is_favorite BOOLEAN` in `videos` (migration); `POST /api/result/{id}/favorite` toggle; `?favorites_only=true` on `/history`; ★/☆ button in ResultPage + HistoryPage rows + "☆ Favorites" filter |
| 23.05.2026 | **Known issue: chapter titles language mismatch** — ~~yt-dlp extracts `info["chapters"]` in the language of the user's YouTube interface (via cookies). Workaround: switch YouTube interface to the video's language before extracting.~~ **Resolved 23.05.2026**: YouTube API translates `info["chapters"]` to English server-side regardless of cookies, headers, or client-type (confirmed by diagnostics). Fix: `_parse_description_chapters()` — takes timecodes from `info["description"]` (never auto-translated by YouTube, always in the author's language). Fallback to `info["chapters"]` with `[CHAPTER_SOURCE]` warning in log. Script check: heading script vs subtitle language — warning on mismatch. |
| 20.06.2026 | **Queue `force=true` bug fix** — ResultPage `queueBulkAdd` calls used `force=false` (default) → existing videos silently skipped as duplicates, nothing queued. All 4 calls (`handleCleanup`, `handleSummarize` ×2, `handleMindmap`) now pass `force=true`. |
| 20.06.2026 | **Chat bar redesign** — floating centered bar: `fixed bottom-6 left-0 md:left-64 right-0` + inner `max-w-[1200px] mx-auto flex justify-center max-w-2xl`. Aligns with content card in both normal and Boxed Layout modes. `rounded-2xl shadow-2xl backdrop-blur-md`. |
| 20.06.2026 | **Mind Map tab** — `'mindmap'` added to `Tab` type; full tab in ResultPage (`subtitles \| cleaned \| summary \| mind map \| chat`); `Generate mind map` / `Regenerate mind map` button in actions bar (`account_tree` icon); empty state with large icon; `mindmapEnabled` toggle removed. |
| 20.06.2026 | **MD toggle relocated** — removed from shared tab toolbar; now lives as small pill inside content area of Summary and Cleaned tabs only. Chat assistant messages always use ReactMarkdown (no toggle). |

| Epic 36: Frontend Redesign | Tailwind CSS v4.3.1 + Material Design 3 tokens + Material Symbols Outlined icons. All 8 pages rebuilt from Stitch design files. Boxed Layout feature (floating centered container, toggle in Settings → General → Display). Dark/light mode via `.dark` class. | ✅ Done — 20.06.2026 |

---

## Phase 3: Speech-to-Text ✅

Whisper-based transcription for YouTube audio and local files. Language param from Phase 1 reused directly.

| Epic | Description | Status |
|------|-------------|--------|
| Epic 30: STT Service Layer | `services/transcriber.py` engine-agnostic API, faster-whisper, device auto-detect, model catalog + download/delete UI in Settings → STT | ✅ Done — 24.10.2026 |
| Epic 31: YouTube/URL Audio Transcription | `extract_audio()` via yt-dlp, queue worker `_run_transcribe()`, `subtitle_source='transcript'` in DB, STT checkbox on HomePage | ✅ Done — 24.10.2026 |
| Epic 32: Local File Upload | `POST /api/process/file` multipart endpoint, `data/uploads/` storage, `local_video_id="file-{uuid8}"`, drag-and-drop on HomePage Local File tab | ✅ Done — 24.10.2026 |
| Epic 41: STT Configuration & File Management | yt-dlp bundled mode toggle + version/update UI; File Storage tab (stats, clear, auto-delete policy); CUDA detection fix (`ctranslate2`); graceful CUDA→CPU fallback; `av<19` pin | ✅ Done — 25.10.2026 |
| Epic 42: STT Progress, Timing & Source Badges | Live segment progress on ProcessingPage; transcription timing columns + "Transcribed in X:XX" in ResultPage meta; STT source badge (movie/audio icon) in History | ✅ Done — 25.10.2026 |
| Epic 43: Local File Result Page | Inline Whisper model selector; Re-transcribe button with live segment progress; hide irrelevant Open video / Benchmark buttons for local files; backend re-transcribe path via `_run_reextract` | ✅ Done — 25.10.2026 |

---

## Phase 4: Integrations 🔵

Превратить YT Summarizer из браузерного инструмента в сервис, которым пользуются AI-агенты и внешние клиенты.

### Epic 44: MCP Server
**Description**: Stdio MCP Server для Claude Desktop и AI-агентов. Инструменты: `process_video`, `get_result`, `search_history`, `run_cleanup`, `run_summary`. HTTP-прокси к FastAPI — без дублирования логики. Установка за 5 минут через `claude_desktop_config.json`.

**Status**: ✅ Done — 28.10.2026 | **Priority**: 🟡 P2  
**Files**: `app/mcp_server.py`, `docs/guides/MCP_SETUP.md`  
[View Epic →](./epics/EPIC-44.md)

---

### Epic 45: Claude Desktop Connection UI

**Description**: Кнопка "Connect Claude Desktop" в Settings → Connections. Приложение само находит `claude_desktop_config.json`, добавляет запись `yt-summarizer`, делает бэкап старого файла. Пользователь не редактирует JSON вручную. Показывает статус подключения (Connected / Not connected). Обязательно для продуктового/SaaS сценария — пользователи не должны знать про конфиги.

**Status**: ✅ Done (29.10.2026) | **Priority**: 🟡 P2  
**Estimate**: ~2–3 часа  
**Depends on**: Epic 44 (MCP Server) ✅  
[View Epic →](./epics/EPIC-45.md)

---

### Epic 46: Video Download

**Description**: Скачать видео или аудио с YouTube прямо из интерфейса. Два режима: (1) кнопка Download на Result page — скачивает файл для уже обработанного видео; (2) прямое скачивание с Home page — галочка "Download" без выбора pipeline запускает `GET /api/download/direct` напрямую, без извлечения субтитров и записи в БД. Форматы: Video (MP4) / Audio (MP3), качество: Best / 1080p / 720p / 480p.

**Status**: ✅ Done — 30.10.2026 | **Priority**: 🟢 P3  
**Files**: `app/backend/routers/api.py` (`/download/direct`, `/result/{video_id}/download`), `app/frontend/src/api.ts` (`downloadDirect`, `downloadVideo`), `app/frontend/src/pages/HomePage.tsx`, `app/frontend/src/pages/ResultPage.tsx`

---

## Ideas & Deferred Improvements

Small ideas and technical improvements that don't warrant an epic. Can be implemented as needed.

| Idea | Description | Complexity |
|------|-------------|------------|
| **[Testing] pytest API** | Promoted to **[Epic 38](./epics/EPIC-38.md)**. | — |
| **[Testing] Playwright E2E** | Critical-path automation: (1) submit URL → queue → view result, (2) History page load + search + favorite, (3) Queue page with active item. Covers both frontend and backend integration in one shot. Most valuable during redesign phase — catches regressions per page. Run against dev server (`localhost:3001` + `localhost:8000`). Baseline: `npx playwright test`. | ~3–4h setup + ~1h per critical path |
| **[Testing] Visual regression (Playwright screenshots)** | After each redesign page is done — capture baseline screenshots with `toHaveScreenshot()`. Future changes auto-compare vs baseline. Especially useful after redesign branch merges to catch unintended CSS drift. Store baselines in `tests/screenshots/`. | ~1h after Playwright is wired up |
| **[Testing] pytest API tests** | FastAPI endpoint contract tests: submit URL, get result, settings CRUD, queue endpoints. Validates JSON shape, status codes, error responses. Runs without browser — fast CI step. Use `httpx.AsyncClient` with `ASGITransport`. Requires test DB (separate SQLite file). | ~3h |
| **[Testing] Vitest + React Testing Library** | Component unit tests: `TypeBadge`, `renderText()`, theme toggle, pipeline preset logic. Lowest priority — most logic lives in API calls and state. Worth adding only for pure util functions (`videoType.ts`, `renderText.tsx`). | ~1–2h, low ROI vs E2E |
| Mindmap from summary (Markmap) | Visual mindmap from `summary_text`. **Option A (experiment, ~1–2h)**: pipe existing `summary_text` with `## ` headings through `markmap-lib` + `markmap-view` — zero extra LLM call, test visual value. **Option B (~4–5h)**: dedicated LLM prompt for semantic hierarchy (`#` topic, `##` branches, `###` details), store in `mindmap_text` in DB, button on Result page. Start with A. | A: ~2h / B: ~5h |
| Suggested Questions | Promoted to **[Epic 37](./epics/EPIC-37.md)**. | — |
| Output format templates (Prompt Templates) | A set of ready-made output templates next to the Summarize button: "How-to", "Action Plan", "Author's position", "Key facts", "Pros & Cons". User picks a format — system substitutes the corresponding system prompt. Each template is a separate `pipeline_settings` entry in DB (or hardcoded with customization support). Key differentiator from competitors. | ~3–4h |
| Chat: server-side save | Move chat history saving to the backend — buffer the response in `chat_proxy`, save to DB after stream finishes regardless of client state. Requires adding `video_id` to `ChatRequest`. Current implementation loses the response if user navigates away before generation completes. | ~30 min |
| **[Hypothesis] LLM context window overflow protection** | When running the full pipeline (Extract → Cleanup → Summary) Ollama or the model may hang/crash due to context window overflow on large texts. Current mitigations: map-reduce (24K threshold), 3K chunks, 180s timeout. **Explored solutions**: (1) explicitly pass `"num_ctx": N` in every Ollama request — hard window cap, predictable truncation; (2) `GET {ollama_url}/api/ps` — check loaded model before queue start (detect OOM/unload); (3) retry with smaller chunk on 500/timeout. **Requires**: load testing on large videos (>50K chars) with different models. Do not start without tests. | ~4–6h + tests |
| README: update concept and positioning | Current README frames the tool as "watch or skip" — a quick filter for video content. As support for large texts grows (long lectures, documentaries, courses), positioning should shift: the app becomes a deep knowledge extraction tool, not just a content filter. Update Introduction, Vision, "Watch or Skip" section → broader framing. **Trigger**: Epic 18 (XL texts) or Phase 3 (STT). | ~1h |

---

## Summary Statistics

| Phase | Epics | Status |
|-------|-------|--------|
| Phase 1 — MVP | 1–5 | ✅ Done |
| Phase 1.5 — LLM Cleanup & UX | 6–16, 22–25 | ✅ Done (8 dropped) |
| Phase 2 — Summarization Quality | 17–21, 26–29, 33–34, 36–40 | 🔄 In Progress (17, 20, 22–27, 29, 34, 36, 39, 40 done; 21 deferred; 18, 19, 28, 33, 35, 37, 38 planned) |
| Phase 3 — Speech-to-Text | 30–32, 41–43 | ✅ Done |
| Phase 4 — Integrations | 44–46 | 🔄 In Progress (44–45 done; 46 planned) |

---

## Document Control

- **Version**: 1.9
- **Last Updated**: 29.10.2026
- **Status**: 🔄 Active Development
