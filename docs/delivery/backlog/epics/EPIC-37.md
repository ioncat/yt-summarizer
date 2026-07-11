# Epic 37: Suggested Questions for Chat

**Status:** 🔵 Planned  
**Phase:** 2 — UX / Chat  
**Depends on:** Epic 15 (Summarization), Epic 28 (Chat tab)  
**Blocks:** —

---

## Strategic Context

After a summary is generated, users often don't know where to start a conversation. A blank chat input is a cold-start problem: the user has to formulate a relevant question from scratch, with no indication of what the content contains or what's worth asking.

YouTube's built-in AI summarizer solves this with suggested questions — 3 clickable chips that appear below the summary. Each chip is a question tailored to the video's content. One tap sends it to chat.

This feature lowers the barrier to interacting with video content. Instead of thinking up a question, the user can pick one from a ready set and immediately get a useful answer.

---

## Goal

After a summary is generated, the system produces 3–5 suggested questions that reveal the video's key ideas. Questions appear as clickable chips near the chat input area. Clicking a chip sends it as a chat message.

---

## Design Notes

### Where questions appear

Chips are shown at the bottom of the **Summary tab**, just above the floating chat bar. They disappear once the user sends their first message (chat has started, prompting is no longer needed). They reappear if the chat is cleared.

### When questions are generated

**Lazy trigger** — generated the first time the user opens the Summary tab after a summary is done (or after summary finishes while the tab is open). Not generated automatically on summary completion to avoid an extra LLM call when the user doesn't open the tab.

Alternative: **eager trigger** — generate immediately after `finish_summary`. Simpler, slightly more expensive. Decision deferred to implementation.

### Input to LLM

Summary text + video title. Not the full transcript — too large and unnecessary for generating navigational questions.

### Question quality criteria

Generated questions should:
- Be specific to this video's content (not generic "What is the main idea?")
- Cover different angles (cause, consequence, example, comparison, deeper dive)
- Be short (under 12 words)
- Match the video's language (same model used for summary)

Bad: `"What does the author say?"` — too generic  
Good: `"Как Кремль использует риторику затяжной войны для давления на Запад?"` — specific, actionable

### Number of questions

3–5. Frontend shows all; if fewer than 3 are returned, show what's available without placeholders.

---

## User Stories

### US-3701: Generate suggested questions after summary

**Given** a video has `summary_text` in DB  
**When** `POST /api/result/{video_id}/suggested-questions` is called  
**Then**  
- Backend calls Ollama with `summary_text` + `video.title` and a prompt asking for 3–5 short questions  
- Response is parsed into a JSON array of strings  
- Stored in `subtitles_formatted.suggested_questions` (JSON column, nullable)  
- `suggested_questions_status`: `null | processing | done | failed`  
- API returns `{ questions: string[], status: string }`

**Edge Cases:**
- Ollama returns malformed JSON → retry once, then status `failed`, questions null
- Summary text too short (<200 chars) → skip generation, questions null (not useful for very short summaries)
- Model not configured → status `failed`, questions null (same as summary behavior)
- Video has no summary yet → 409 `{ error: "summary not available" }`

**Out of Scope:** regenerating questions on summary re-run (questions remain until manually refreshed).

**Notes for Engineering:**  
- Use the summarization model (same `pipeline_settings` stage, or a dedicated `questions` stage — TBD)  
- Single Ollama call, non-streaming, 30s timeout  
- JSON parsing: look for `["...", "..."]` array in response; if LLM wraps in prose, extract with regex  
- Store in same `subtitles_formatted` row as `summary_text`  
- `_migrate_db()`: add `suggested_questions TEXT`, `suggested_questions_status TEXT`

---

### US-3702: Display question chips in Summary tab

**Given** `suggested_questions` is a non-empty array and `activeTab === 'summary'`  
**When** the Summary tab is rendered  
**Then**  
- A row of chip buttons appears above the floating chat bar (or just below the summary content)  
- Each chip shows the question text, truncated at ~60 chars with ellipsis if longer  
- Full question shown in `title` tooltip on hover  
- Chips are hidden once `chatHistory.length > 0`  
- Chips reappear if chat is cleared (`Clear chat`)

**Edge Cases:**
- `suggested_questions_status === 'processing'` → show skeleton shimmer (3 placeholder chips) while loading  
- `suggested_questions_status === 'failed'` → show nothing (silent failure, no error chip)  
- Summary tab not active → chips not rendered (DOM not present, no layout impact on other tabs)

**Out of Scope:** chips on Cleaned or Subtitles tabs.

**Notes for Engineering:**  
- Chips: `button` elements with `role="button"`, `title={fullQuestion}`, truncate via CSS `max-w-[240px] truncate`  
- Placement: inside summary tab content wrapper, below text, above chat bar  
- Style: `bg-surface-container border border-outline-variant rounded-full px-3 py-1 text-label-sm text-on-surface hover:bg-surface-container-high` — pill shape consistent with MD3 design system

---

### US-3703: Send question chip as chat message

**Given** question chips are visible  
**When** the user clicks a chip  
**Then**  
- The question text is sent as a chat message (same as typing it and pressing Send)  
- Chat tab becomes active  
- Chips hide (chat has started)  
- Response streams in normally

**Edge Cases:**
- Ollama is offline when chip is clicked → same error handling as regular chat send  
- User clicks two chips rapidly → second click ignored while first is processing

**Out of Scope:** pre-filling the input without sending (ambiguous UX, adds complexity).

**Notes for Engineering:**  
- Reuse existing `handleChatSend(question)` function  
- Trigger: `onClick={() => handleChatSend(question)}`

---

### US-3704: Trigger generation (lazy or eager)

**Given** a summary finishes (`summary_status === 'done'`)  
**When** the user opens the Summary tab for the first time after summary completion  
**Then**  
- `POST /api/result/{video_id}/suggested-questions` is called automatically  
- Chips show skeleton while loading  
- Chips populate when done

**Alternative (eager):**  
- `finish_summary()` in `api.py` enqueues question generation as a background task immediately after summary completes  
- No frontend trigger needed  
- Trade-off: extra LLM call even if user never opens Summary tab

**Decision:** start with **lazy** (frontend-triggered on tab open). Switch to eager if the delay feels jarring in user testing.

**Edge Cases:**
- User opens Summary tab before summary is done → no trigger (wait for summary_status === 'done')
- `suggested_questions` already populated (from a previous run) → skip the call, show existing chips

**Out of Scope:** manual "Regenerate questions" button (can be added later).

---

## Prompt Specification (draft)

**System:**
```
You are a question generator. Given a video summary and title, produce exactly 5 short questions a viewer might ask to learn more about the content. Questions must be specific to this video, not generic. Each question must be under 12 words. Return a JSON array only: ["question 1", "question 2", ...]. No explanation, no prose.
```

**User:**
```
Title: {video_title}

Summary:
{summary_text}
```

Store the prompt in `pipeline_settings` under a new stage name `questions` so it can be customized via Settings → (new sub-tab or existing Summarization tab extension).

---

## Acceptance Criteria

**Given** a video with a completed summary  
**When** the user opens the Summary tab  
**Then** 3–5 question chips load and appear below the summary text

**Given** question chips are visible  
**When** the user clicks a chip  
**Then** the question is sent as a chat message and the Chat tab becomes active

**Given** the chat has started (`chatHistory.length > 0`)  
**When** the user views the Summary tab  
**Then** question chips are hidden

**Given** the user clicks "Clear chat"  
**When** the Summary tab is viewed  
**Then** question chips reappear

---

## Complexity Estimate

~3–4 hours:
- Backend: new endpoint + DB migration + Ollama call + JSON parse (~1.5h)
- Frontend: chips component + lazy trigger + hide logic + click-to-send (~1.5h)
- Prompt tuning + testing on 3–4 real videos (~1h)
