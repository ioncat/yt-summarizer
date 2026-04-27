# Epic 13: Settings 2.0 — All Config via Web UI

Move all user-facing settings out of config files into the database, configurable exclusively via the web UI.

---

## User Stories

### US-1301: Configure Ollama URL via Web

**As a** user  
**I want to** set the Ollama server URL in the web UI  
**So that** I don't need to edit config files or restart the server

### US-1302: Configure yt-dlp and Cookies Path via Web

**As a** user  
**I want to** set yt-dlp path and cookies file path in the web UI  
**So that** all tool paths are managed in one place

### US-1303: Upload Cookies File via Web

**As a** user  
**I want to** upload my cookies.txt directly from the browser  
**So that** I don't need to manually copy files to the server

### US-1304: Warning Banners for Missing Config

**As a** user  
**I want to** see clear warnings when required settings are missing  
**So that** I know why cleanup is unavailable before trying to run it

---

## Implementation Notes

- **DB**: `app_settings` table — key-value store (`ollama_url`, `ytdlp_path`, `cookies_path`)
- **Seeding**: `_seed_app_settings()` populates from `config.py` on first launch
- **config.py**: infrastructure-only after this epic (host, port, DB path, CORS)
- **API**: `GET /api/settings` returns `{app, cleanup, summarization}`; `PUT /api/settings/app`; `POST /api/settings/upload-cookies`
- **Frontend**: Settings page redesigned with tabs (General / AI Cleanup / Summarization)
- Notification banners on Home and Result pages when model or Ollama URL is missing

---

## Status

**Status**: ✅ Done  
**Completed**: 2026-04-25  
**Priority**: 🟠 P1
