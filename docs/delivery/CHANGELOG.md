# Changelog

Reverse-chronological, append-only. Format: see `documentation-conventions.md`.

## 2026-10-31

- **api.py split (NS-12)**: 1,644-line `routers/api.py` split into 7 routers plus an 18-line aggregator; pure move, 52 routes and OpenAPI schema unchanged. Reviewed: clean after one fix (restored yt-dlp update error log). Commits: `54c43ae`, `41329dd`.
- **Housekeeping (NS-07, NS-09, NS-10)**: fixed hard-coded model count in tests (all 69+10+18 green); stale `processing` statuses reset on startup + try/except/finally on stage functions; `.env` path fixed to repo root (absolute via `Path(__file__).resolve()`). NS-06 already tracked; NS-08 local-only (launcher files gitignored). Reviewed: clean. Commits: `e8be8a1`, `729218e`, `c9b0a92`.
- **Security minimum (NS-01–05)**: bind backend to 127.0.0.1; cookie upload basename-only + 5 MB cap; yt-dlp URL whitelist (https + YouTube hosts) + `--` before every user URL; markmap HTML escaped; uploads/cookies/db gitignored. Reviewed: clean. Commit: `db66a96`.
- **Project created from TeamKit**: rules, roles and addenda in place; New Start backlog (NS-01–14) written.
