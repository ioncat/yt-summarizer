# Epic 9: Per-Tab Character Count

## Summary
Currently the Result page shows a single `Characters:` count for the whole video. With two tabs (Subtitles and Cleaned), each may have different character counts — the cleaned version is typically shorter (filler words removed). Show the count for whichever tab is active.

## Business Value
Character count helps users estimate reading time and content density. Showing the count for the current tab makes it immediately meaningful — e.g. "Cleanup removed 800 characters of filler."

## Scope

### Included
- Character count in the metadata block updates when the user switches tabs
- Backend returns both `char_count` (formatted text) and `cleaned_char_count` (cleaned text)
- "Characters" label stays in the same position in the meta row

### Not Included
- Word count, sentence count, reading time estimate (future US)
- Diff view showing what was removed (future)

---

## User Stories

### US-801: Show Character Count for Active Tab

**Title**: Character count reflects the currently visible text

**User Story**:
```
As a user
I want to see the character count for the text I'm currently reading
So that I can compare the length of the original and cleaned versions
```

**Acceptance Criteria**:

**Given**: Result page is open

**When**: User switches between Subtitles and Cleaned tabs

**Then**:
- "Characters:" in the metadata row updates to reflect active tab's text length
- Subtitles tab → count of `formatted_text`
- Cleaned tab → count of `cleaned_text`
- If Cleaned text doesn't exist yet → shows Subtitles count regardless of tab

**Edge Cases**:
1. Cleanup running → show Subtitles count (Cleaned not ready)
2. Cleanup failed → show Subtitles count
3. `cleaned_text` length = 0 → show 0, not Subtitles count

**Notes for Engineering**:
- Add `cleaned_char_count: number | null` to `ResultResponse` API schema
- In `get_result()` (video_service.py): add `"cleaned_char_count": len(fmt.cleaned_text) if fmt and fmt.cleaned_text else None`
- In `ResultPage.tsx`: `const displayCount = activeTab === 'cleaned' && result.cleaned_char_count != null ? result.cleaned_char_count : result.char_count`
- Replace `{result.char_count.toLocaleString()}` with `{displayCount?.toLocaleString()}`
- No DB migration needed — count computed on the fly

---

## Dependencies

- Epic 6 (Cleaned tab, `cleanup_status`)
- Epic 5 (Result page meta block)

## Status

**Status**: 🟡 Next  
**Priority**: 🟡 P2
