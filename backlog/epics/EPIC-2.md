# Epic 2: Text Formatting & Presentation

## Summary
Convert raw subtitles into clean, properly formatted markdown text that reads naturally.

## Business Value
Transforms raw subtitle data into readable content that users can quickly scan and understand.

## Scope

### Included
- Remove timestamps and formatting elements
- Apply proper capitalization (sentence starts with capital letter)
- Preserve and apply punctuation correctly (periods, commas, exclamation marks, quotes)
- Structure text in logical paragraphs
- Preserve speaker names if available
- Handle different punctuation styles (direct/indirect speech)
- Output as markdown format
- Ensure 100% accuracy (no content alterations)

### Not Included
- Saving formatted text (Epic 3)
- Displaying in UI (Epic 5)
- Translating or paraphrasing (out of scope)
- LLM-based summarization (Phase 2)

---

## User Stories

### US-201: Format Subtitles into Clean Markdown Text

**Title**: Convert raw subtitles into properly formatted markdown

**User Story**:
```
As a backend system
I want to format raw subtitles into markdown
So that users receive readable, well-structured text
```

**Acceptance Criteria**:

**Given**: Raw subtitles with timestamps received from US-102

**When**: Text formatting service processes subtitles

**Then**:
- All timestamps removed
- Text converted to markdown format
- Proper paragraph structure applied
- Output is valid markdown
- 100% of original content preserved
- No content distortions or alterations

**Edge Cases**:
1. Single-word subtitles → Still formatted properly
2. Very long consecutive text → Broken into readable paragraphs
3. All caps text → Preserved as-is (intentional emphasis)
4. Mixed language text → Handled correctly
5. Subtitles with metadata (speaker:) → Parsed and preserved

**Out of Scope**: Translation, content modification, multiple output formats at this stage

**Notes for Engineering**:
- Input: `[{timestamp: "00:00:10", text: "Hello world"}, ...]`
- Output: Markdown string with proper structure
- Rules for paragraph breaks: natural pauses, speaker changes, topic shifts
- Consider line breaks in original subtitles
- Preserve markdown special characters if present
- Return format:
```json
{
  "formatted_text": "# Markdown formatted text...",
  "char_count": 5421,
  "paragraph_count": 12
}
```

**Dependencies**: US-102

**Analytics**: Track formatting_time, paragraph_count, char_count

---

### US-202: Apply Proper Capitalization and Punctuation

**Title**: Ensure text follows proper capitalization and punctuation rules

**User Story**:
```
As a user
I want text formatted with proper capitalization and punctuation
So that it reads like professionally written content
```

**Acceptance Criteria**:

**Given**: Unformatted raw subtitles

**When**: Formatting service processes text

**Then**:
- Every sentence starts with capital letter
- Proper punctuation at sentence ends (period, question mark, exclamation mark)
- Commas placed correctly
- Quotation marks balanced
- Ellipsis (...) handled correctly
- Apostrophes correct (contractions, possessives)

**Edge Cases**:
1. Text already capitalized → Preserve
2. Text all lowercase → Capitalize appropriately
3. Text all CAPS → Preserve (intentional emphasis)
4. Mixed case (proper nouns) → Preserve correctly
5. Multiple punctuation marks (?! or ??) → Handle correctly
6. Missing punctuation between sentences → Infer and add

**Out of Scope**: Grammar correction, word choice improvement, style changes

**Notes for Engineering**:
- Use language-specific rules (Russian, English, Ukrainian have different capitalization)
- Consider sentence boundaries (period, question mark, exclamation)
- Handle abbreviations (e.g., "Mr.", "Dr.")
- Don't modify original capitalization of proper nouns or intentional emphasis
- Test with diverse text samples

**Dependencies**: US-201

**Analytics**: Track corrections_made, capitalization_changes, punctuation_changes

---

### US-203: Structure Text in Logical Paragraphs

**Title**: Organize text into readable paragraphs

**User Story**:
```
As a user
I want text organized in logical paragraphs
So that it's easy to read and scan
```

**Acceptance Criteria**:

**Given**: Formatted text with proper punctuation

**When**: Text is organized into paragraphs

**Then**:
- Natural pauses become paragraph breaks
- Speaker changes create new paragraphs
- Topic shifts result in new paragraphs
- Paragraphs have reasonable length (not too long, not single sentences)
- Logical flow maintained

**Edge Cases**:
1. Very short sentences → Group into larger paragraphs
2. Very long monologue → Break into readable chunks
3. Multiple speakers → Each speaker gets new paragraph
4. Repeated patterns → Maintain structure, don't collapse

**Out of Scope**: Creating bullet points, creating lists, outline structure

**Notes for Engineering**:
- Paragraph breaks at: natural pauses (... or multiple periods), speaker changes, topic shifts
- Min paragraph length: 20 characters, Max reasonable length: 500 characters
- Consider original subtitle line breaks as hints
- Test readability with diverse content

**Dependencies**: US-201, US-202

**Analytics**: Track paragraph_count, avg_paragraph_length

---

### US-204: Display Formatted Text in Web UI

**Title**: Present formatted text in web interface to user

**User Story**:
```
As a user
I want to see formatted text displayed in the web interface
So that I can read and interact with it
```

**Acceptance Criteria**:

**Given**: Formatted markdown text from backend

**When**: User views results page

**Then**:
- Text displays with proper formatting
- Markdown elements rendered (bold, italic, headings if present)
- Text is readable with good typography
- Copy-to-clipboard button available
- Can select and copy text
- Responsive on different screen sizes

**Edge Cases**:
1. Very long text → Loads without lag
2. Special characters → Display correctly
3. Text with code blocks → Render properly
4. Mobile device → Text readable and scrollable

**Out of Scope**: Text editing, spell checking, exporting to other formats (yet)

**Notes for Engineering**:
- Frontend: React component for text display
- Use markdown renderer library (react-markdown or similar)
- Implement copy-to-clipboard with user feedback
- Lazy load for very long texts
- Responsive CSS (mobile-first)
- Line height and font size for readability
- Consider dark mode support

**Dependencies**: US-201, US-202, US-203

**Analytics**: Track text_viewed, copy_clicked, time_on_results

---

## Acceptance Criteria (Epic Level)

- All original content preserved (100% accuracy)
- No timestamps or timing information in output
- Proper markdown structure with headings, paragraphs
- Correct capitalization and punctuation throughout
- Text reads naturally, as if typed in Word document
- Output is valid markdown
- Processing time acceptable (< 10 seconds for typical 10k character transcript)

## Technical Notes

- Input: Raw subtitles {timestamp, text} from Epic 1
- Output: Formatted markdown string
- Rules for capitalization and punctuation need to be documented
- Consider edge cases (multiple speakers, special characters, etc)
- Preserve line breaks where they represent natural pauses

## Dependencies

**Depends on**: Epic 1 (Core Subtitle Extraction)

## Status

**Status**: 🟡 Ready for Implementation  
**Owner**: TBD  
**Priority**: 🔴 P0 (Critical)
