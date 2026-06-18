# Epic 8: Markdown Output & Rendering

## Summary
The LLM cleanup prompt should be updated to explicitly instruct the model to output clean Markdown (paragraphs, bold for emphasis). The frontend should render this Markdown properly using `react-markdown` instead of displaying it as plain `pre-wrap` text.

**Key insight**: Markdown formatting is primarily a **prompt engineering task** — if the LLM outputs proper Markdown, all that's needed on the frontend is a renderer. The two concerns are separable but ship together.

## Business Value
Currently the `formatted-text` block shows raw text with `\n\n` gaps visible and any `**bold**` symbols rendered literally. Proper Markdown rendering + correct LLM output makes the result look like a polished document, not raw subtitle dump.

## Scope

### Included
- Update `text_cleaner.py` prompt to explicitly request Markdown output (paragraphs, bold for key terms)
- Add `react-markdown` to frontend, replace plain text block on Result page
- Both Subtitles and Cleaned tabs use the same renderer

### Not Included
- User editing of Markdown
- Export to HTML/PDF (separate epic)
- Syntax highlighting for code blocks (not relevant for subtitles)

---

## User Stories

### US-701: Update Cleanup Prompt to Output Markdown

**Title**: LLM outputs clean Markdown formatting

**User Story**:
```
As a developer
I want the cleanup LLM to format its output as Markdown
So that the result is structured and ready for rendering
```

**Acceptance Criteria**:
- Cleanup prompt includes explicit instruction: output Markdown with paragraphs separated by blank lines, bold for emphasis on key terms or names
- Model does not add `\`\`\`` code blocks or unnecessary headers
- Paragraph structure preserved from input
- Output can be directly passed to a Markdown renderer

**Notes for Engineering**:
- Edit `_user_prompt()` in `text_cleaner.py`
- Add to rules: "8. Format output as Markdown: separate paragraphs with a blank line, use **bold** for important names or terms."
- Test with a few sample paragraphs — model behaviour varies

---

### US-702: Render Markdown in Result Page

**Title**: Result page displays text as rendered Markdown

**User Story**:
```
As a user
I want to see the text formatted with proper paragraphs and emphasis
So that the content is easy to read
```

**Acceptance Criteria**:

**Given**: Result page shows either Subtitles or Cleaned tab

**When**: Text content loads

**Then**:
- Paragraphs are spaced correctly (not squashed together)
- `**bold**` renders as **bold** (no raw asterisks visible)
- No raw Markdown syntax symbols visible in output
- Long text scrolls smoothly
- HTML characters (`<`, `>`) are safely escaped — no XSS

**Edge Cases**:
1. `formatted_text` is null → empty state, no crash
2. Very long text → renders without freezing
3. Text from old videos (no Markdown) → renders as plain paragraphs, no breakage

**Notes for Engineering**:
- `npm install react-markdown`
- Replace `<div className="formatted-text">{displayText}</div>` with:
  `<ReactMarkdown className="formatted-text">{displayText ?? ''}</ReactMarkdown>`
- `react-markdown` does not render raw HTML by default — XSS safe
- May need to add CSS: `.formatted-text p { margin-bottom: 1em; }`

---

## Dependencies

- Epic 6 (Cleaned tab exists, `displayText` shared between tabs)

## Status

**Status**: ❌ Dropped  
**Priority**: 🟠 P1  
**Note**: Tested react-markdown + Markdown prompt rule — LLM output inconsistent. Plain text rendering retained.
