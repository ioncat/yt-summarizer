# Changelog

Reverse-chronological, append-only. Format: see `documentation-conventions.md`.

## 2026-11-01

- **Qwen3-ASR works (NS-20)**: the Qwen engine picks its device through torch and falls back to CPU; CUDA build of torch installed (`2.14.1+cu126`); audio is converted to wav with ffmpeg first, so `.m4a`/`.mp4`/`.mkv` work; both engines accept language codes and names (re-transcribe with large-v3 had failed silently on `Russian`); `requirements.txt` fixed (`qwen-asr>=0.0.6`, torch note). Reviewed: clean after follow-ups. Commits: `a4b14c7`, `0cebb65`, `79304c9`, `0749a62`, `a2cc87d`.
- **ResultPage split (NS-14)**: 1,280-line `ResultPage.tsx` split into 10 files under `components/result/` (page now 424 lines); 14 smoke tests added first; pure move, 114 DOM snapshots identical before and after. Reviewed: clean. Commits: `dee1c7f`, `6c05d60`.
- **SettingsPage split (NS-13)**: 1,585-line `SettingsPage.tsx` split into 9 files under `components/settings/` (page now 300 lines); 8 smoke tests added first; pure move. Reviewed: clean. Commits: `dfdb205`, `ab8bb82`.

## 2026-10-31

- **api.py split (NS-12)**: 1,644-line `routers/api.py` split into 7 routers plus an 18-line aggregator; pure move, 52 routes and OpenAPI schema unchanged. Reviewed: clean after one fix (restored yt-dlp update error log). Commits: `54c43ae`, `41329dd`.
- **Housekeeping (NS-07, NS-09, NS-10)**: fixed hard-coded model count in tests (all 69+10+18 green); stale `processing` statuses reset on startup + try/except/finally on stage functions; `.env` path fixed to repo root (absolute via `Path(__file__).resolve()`). NS-06 already tracked; NS-08 local-only (launcher files gitignored). Reviewed: clean. Commits: `e8be8a1`, `729218e`, `c9b0a92`.
- **Security minimum (NS-01–05)**: bind backend to 127.0.0.1; cookie upload basename-only + 5 MB cap; yt-dlp URL whitelist (https + YouTube hosts) + `--` before every user URL; markmap HTML escaped; uploads/cookies/db gitignored. Reviewed: clean. Commit: `db66a96`.
- **Project created from TeamKit**: rules, roles and addenda in place; New Start backlog (NS-01–14) written.
