# Epic 22: Auto Language Detection

**Phase**: 1.5 — UX Polish  
**Status**: ✅ Done  
**Priority**: 🟡 P2

## Goal

Eliminate manual language selection on the Home page for the common case.
When user submits a URL without specifying a language, the backend detects
the original language from video metadata automatically.

---

## User Stories

---

### US-2201: Backend auto-detects language from video metadata

**As a** user who wants to extract subtitles  
**I want** the app to detect the video's original language automatically  
**So that** I don't need to manually select a language before submitting

#### Acceptance Criteria

**Given** I select "Auto (detect)" in the language dropdown and submit a URL  
**When** the backend processes the video  
**Then** the original language is detected from yt-dlp metadata and subtitles are extracted in that language

**Given** the detected language is saved  
**When** I open the Result page  
**Then** the Language field in meta shows the detected language (e.g. "EN", "RU")

**Given** language auto-detection fails (no metadata available)  
**When** the backend processes the video  
**Then** fallback language "ru" is used and the Result page shows it

#### Edge Cases

- Video has no `automatic_captions` and no `subtitles` → fallback to `language` field in metadata → fallback to `"ru"`
- Detected language is not EN/RU/UK (e.g. `"de"`) → still works, yt-dlp downloads it, shown as-is on Result page
- `automatic_captions` has only machine-translated variants (no `*-orig`) → take first key from `automatic_captions`
- yt-dlp metadata call fails → surface error to user, prompt to select language manually

#### Out of Scope

- Detecting language from audio (Whisper — Phase 3)
- Restricting detected languages to EN/RU/UK only
- Showing confidence score or multiple language candidates

#### Notes for Engineering

Detection logic (priority order):
1. First key ending in `-orig` in `automatic_captions` → strip `-orig` suffix
2. First key in `subtitles` (manually uploaded captions)
3. First key in `automatic_captions`
4. `language` field from top-level metadata
5. Hardcoded fallback `"ru"`

Implementation requires **two yt-dlp calls** when `language == "auto"`:
- Call 1: `--skip-download --print-json` (lightweight, metadata only) → detect language
- Call 2: existing combined call with detected language

Risk: two YouTube requests → slightly higher 429 probability. Acceptable since
call 1 has no download and is fast.

`subtitle_extractor.py`: add `_detect_language(metadata: dict) -> str` helper.
Call it inside `extract_subtitles()` when `language == "auto"`.

---

### US-2202: "Auto (detect)" as default option in language selector

**As a** user on the Home page  
**I want** "Auto (detect)" to be the default language option  
**So that** I can submit a URL without thinking about language selection

#### Acceptance Criteria

**Given** I open the Home page  
**When** I look at the language selector  
**Then** "Auto (detect)" is selected by default (not "Russian")

**Given** I want to override the detected language  
**When** I open the language selector  
**Then** I see EN / RU / UK options alongside "Auto (detect)"

**Given** I select "Auto (detect)" and submit  
**When** the form is submitted  
**Then** `language: "auto"` is sent to the backend

#### Edge Cases

- User manually selects RU/EN/UK → behavior identical to today, no auto-detection
- `localStorage` has a previously saved language (e.g. "ru") → still use "auto" as new default (reset old default)

#### Out of Scope

- Removing the language selector from Home page (deferred — see note below)
- Showing detected language on Home page before submit

#### Notes for Engineering

- `HomePage.tsx`: add `{ value: "auto", label: "Auto (detect)" }` as first option
- Change default state from `"ru"` to `"auto"`
- If `localStorage` stored old default — clear or ignore for language field
- API contract: `language: "auto"` passes through to backend unchanged

---

## ⚠️ Deferred Cleanup Task

**After successful testing** (auto-detection proves reliable across a range of videos):
- Remove the language dropdown from Home page entirely
- Hardcode `language: "auto"` in the submit handler
- Keep manual override only on Result page ("Re-process in language X")

This cleanup is intentionally deferred to validate detection quality first.
Track as separate task — do not implement until auto-detection is confirmed working.
