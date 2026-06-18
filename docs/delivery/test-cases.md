# Test Cases — YT Summarizer

Functional test cases for regression testing of critical system behaviors.  
Format: Given / When / Then. Status filled in on each manual run.

---

## TC-001 · Chapter heading language matches video language

**Scope**: subtitle_extractor · chapter source priority  
**Priority**: 🔴 P0 — affects the entire pipeline (formatted_text → cleaned_text → summary → mindmap)  
**Added**: 23.05.2026  
**Reason**: YouTube API translates `info["chapters"]` to English regardless of cookies,
Accept-Language, and player_client. Confirmed by diagnostics (`tools/debug_chapters.py`, 6 configurations).

---

### TC-001-A: Russian video with timecodes in description

**Preconditions**:
- Video in Russian
- Author included timecodes in video description (chapter list with timestamps)
- Example: `https://www.youtube.com/watch?v=RagM_T1HCuo`

**Given** user extracts subtitles from a Russian-language video  
**When** extraction completes  
**Then**:
- Chapter headings in `formatted_text` are in Russian (`## Хаос и бег по минному полю` — "Chaos and running through a minefield")
- Chapter headings in `cleaned_text` are in Russian (LLM preserves them unchanged)
- Chapter headings in `summary_text` are in Russian
- Chapter headings in mindmap are in Russian
- Server log does NOT contain `[CHAPTER_SOURCE]` lines

**Fail criteria**:
- Any heading in English (`## Chaos and running through a minefield`)
- Presence of `[CHAPTER_SOURCE] ... falling back to YouTube API chapters` in log

---

### TC-001-B: Video without timecodes in description → fallback to YouTube chapters

**Preconditions**:
- Video in any language
- Description contains no timecodes (or fewer than 2 timestamps)
- `info["chapters"]` from YouTube exists

**Given** video description contains no timecodes  
**When** extraction completes  
**Then**:
- Chapters taken from `info["chapters"]` (may be in English — expected behavior)
- Log contains `[CHAPTER_SOURCE] ... falling back to YouTube API chapters (may be translated)`
- Formatting is intact, text is split by chapters

**Fail criteria**:
- Exception during metadata construction
- Text not split into chapters when `info["chapters"]` is present

---

### TC-001-C: Video with no chapters at all → gap-based fallback

**Preconditions**:
- Video without author timecodes in description
- `info["chapters"]` is empty or absent

**Given** video has neither description timecodes nor YouTube chapters  
**When** extraction completes  
**Then**:
- `formatted_text` split by 4-second pauses (gap-based, existing logic)
- `has_chapters = False` in result
- Log does NOT contain `[CHAPTER_SOURCE]`
- UI shows no `##` headings

**Fail criteria**:
- Empty `## ` headings present in text
- Extraction error

---

### TC-001-D: Script mismatch detection

**Preconditions**:
- Video in Russian (`language = "ru"`)
- Chapters taken from `info["chapters"]` (English — fallback case)

**Given** subtitle language is Russian, chapter headings are in Latin script (English)  
**When** extraction completes  
**Then**:
- Log contains `[CHAPTER_SOURCE] ... chapter titles are in latin script but subtitle language is 'ru' (expected cyrillic)`
- Warning contains `video_id` for identification

**Fail criteria**:
- Warning does not appear on actual language mismatch

---

### TC-001-E: English video — headings in English, no warnings

**Preconditions**:
- Video in English (`language = "en"`)
- Description contains English timecodes

**Given** user extracts subtitles from an English-language video  
**When** extraction completes  
**Then**:
- Chapter headings in English — correct behavior
- Log does NOT contain `[CHAPTER_SOURCE]` warnings (english = latin = match)

**Fail criteria**:
- False positive `[CHAPTER_SOURCE]` for English videos

---

## TC-002 · Auto-detection of subtitle language

> Test case for Epic 22. Add expanded version on regression.

**Status**: Baseline tested during Epic 22 development.

---

## Running diagnostics manually

```bash
# Check chapters from different sources for any video:
python tools/debug_chapters.py "VIDEO_URL"

# With explicit cookies path:
python tools/debug_chapters.py "VIDEO_URL" "app/data/cookies.txt"
```

Script runs 6 yt-dlp configurations and separately outputs timecodes from the description.  
Expected result for a Russian video: all 6 configurations → English chapters, "Description timecodes" block → Russian.

---

## Log tags for monitoring

| Tag | Location | Meaning |
|-----|----------|---------|
| `[CHAPTER_SOURCE]` | `subtitle_extractor.py` | Issue with chapter heading source or language |

Quick grep in logs:
```bash
grep "\[CHAPTER_SOURCE\]" backend.log
```
