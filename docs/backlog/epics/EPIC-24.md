# Epic 24: Completion Notifications

**Phase**: 1.5 — UX Polish  
**Status**: ✅ Done  
**Priority**: 🟡 P2

## Goal

Notify the user when a background AI operation (cleanup or summarization) finishes,
even if they have switched to another browser tab. Two complementary mechanisms:
tab title change (always works) and Browser Notification API (works when tab is hidden).

---

## User Stories

---

### US-2401: Tab title change on completion

**As a** user who switched to another tab while cleanup or summarization runs  
**I want** to see a visual indicator in the tab bar when the operation finishes  
**So that** I know to come back without having to watch the tab

#### Acceptance Criteria

**Given** cleanup or summarization is running  
**When** the operation transitions from `processing` to `done`  
**Then** the tab title changes to `✓ AI Cleanup complete` or `✓ Summary complete`

**Given** the title was changed to show completion  
**When** 10 seconds pass  
**Then** the title reverts to the original page title

**Given** the user returns to the tab  
**When** the `visibilitychange` event fires  
**Then** the title is immediately restored to the original

#### Edge Cases

- Page unmounts before timeout fires → cleanup useEffect restores original title
- Multiple completions in sequence → each fires its own title change + 10s timer

---

### US-2402: Browser push notification on completion

**As a** user who switched to another tab while cleanup or summarization runs  
**I want** to receive a browser notification when the operation finishes  
**So that** I am notified even if the tab is not visible

#### Acceptance Criteria

**Given** the user starts cleanup or summarization for the first time  
**When** the operation begins  
**Then** the browser requests notification permission (lazy — not on page load)

**Given** notification permission is granted and the tab is hidden  
**When** cleanup or summarization finishes  
**Then** a browser notification fires with the operation name and video title as body

**Given** the tab is visible when the operation finishes  
**When** completion is detected  
**Then** no browser notification is shown (tab title change is sufficient)

**Given** notification permission is denied  
**When** cleanup or summarization finishes  
**Then** only the tab title change fires; no error shown

#### Edge Cases

- Permission already granted from previous session → no re-prompt
- Permission `"default"` → request on first cleanup/summary start
- Tab visible at completion → skip browser notification, title still changes

#### Out of Scope

- Backend push (WebSocket / SSE)
- Notifications for extraction stage
- Notification sound
- Notification preferences in Settings

#### Notes for Engineering

All logic in `ResultPage.tsx`:
- `notify(title, body?)` helper — sets `document.title`, fires `new Notification()` if permitted and `document.hidden`
- `requestNotifyPermission()` — calls `Notification.requestPermission()` if `permission === 'default'`
- Called from `handleCleanup()` and `handleSummarize()` before starting the operation
- `notify()` called inside `loadResult()` on `processing → done` transition (same place tab auto-switching happens)
- `originalTitleRef` stores original title on mount; restored on unmount and on `visibilitychange`
