# Epic 39: Separate Model Selector for Chat

**Status:** ✅ Done  
**Phase:** 2 — UX / Chat  
**Depends on:** Epic 28 (Chat tab)  
**Blocks:** —

---

## Problem

Chat currently uses `summaryModel` — the model configured for summarization. This is an accidental coupling: chat and summarization are different tasks that may benefit from different models (e.g., a fast 3B model for conversational chat vs. a larger model for summarization). There is no UI signal that chat is using the summary model; users discover this only if they read the code.

---

## Goal

Add a dedicated model selector for chat. Persisted in `pipeline_settings` under stage `chat`. Inline selector in the chat action bar on Result page, consistent with the existing cleanup and summary selectors (Epic 11 pattern). Auto-saves on change.

---

## User Stories

### US-3901: Chat uses its own model setting

**Given** a user has selected different models for summarization and chat  
**When** they send a chat message  
**Then** the chat request uses the model configured for the `chat` stage, not the summary model

**Edge Cases:**
- Chat model not set → fall back to summary model (prevents breaking existing users on first load)
- Ollama offline → selector disabled with tooltip (same as cleanup/summary selectors)

**Out of Scope:** system/user prompt customization for chat (not needed now).

**Notes for Engineering:**
- Stage name: `"chat"` in `pipeline_settings` — no DB migration needed (stored by name)
- `get_all_settings()` in `video_service.py`: add `chat` to the list of fetched stages
- `GET /api/settings` response: add `chat: {model, system_prompt, user_prompt_template}`
- `PUT /api/settings/chat` already works via the generic stage handler — no new endpoint
- `AllSettings` type in `api.ts`: add `chat` field
- `ResultPage.tsx`: `chatModel` state, loaded from `s.chat.model`, fallback to `summaryModel` if null

---

### US-3902: Inline model selector in chat bar

**Given** the chat bar is visible  
**When** the user opens the Result page  
**Then** a model dropdown appears in the chat action bar, consistent in style with the cleanup and summary selectors

**Edge Cases:**
- Models list empty (Ollama offline) → selector disabled, tooltip "Ollama offline"
- Chat model not yet saved → selector shows empty/placeholder; first send uses fallback

**Out of Scope:** Settings page chat section (inline selector is sufficient).

**Notes for Engineering:**
- Placement: right side of chat input bar, before Send button
- Style: same `.model-select-inline` pattern as cleanup/summary inline selectors
- Auto-saves on `onChange` via `PUT /api/settings/chat` — no Save button
- `saveChatModel(newModel)` mirrors `saveSummaryModel()` / `saveCleanupModel()` pattern

---

## Acceptance Criteria

**Given** Ollama is online  
**When** the user opens Result page with the Chat bar visible  
**Then** a model dropdown appears in the chat input area

**Given** the user selects a model in the chat dropdown  
**When** a chat message is sent  
**Then** that model is used (not the summary model)

**Given** chat model is null (not yet set)  
**When** a chat message is sent  
**Then** falls back to summary model gracefully — no error, no broken state

---

## Complexity Estimate

~1–2 hours:
- Backend: `get_all_settings` + `GET /api/settings` response (~20 min)
- Frontend: `chatModel` state + selector UI + load/save + fallback (~1h)
