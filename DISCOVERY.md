# DISCOVERY.md

## YT Summarizer - Discovery Phase Documentation

This document captures the discovery process, design decisions, alternatives considered, and key assumptions for the YT Summarizer project.

---

## 1. Problem Definition

### The Problem
Users need to quickly understand YouTube video content without committing to watching the entire video. Currently:
- **Time waste**: Users watch entire videos to determine relevance
- **Cognitive load**: Too much information to process upfront
- **No quick preview**: Impossible to decide if video is worth watching before investing time

### Pain Points
- Decision paralysis: "Is this video worth my time?"
- No way to skim video content quickly
- Can't reference specific parts without re-watching
- Transcript extraction is manual and tedious

### Target User
- Knowledge workers who consume many YouTube videos
- Researchers, students, professionals
- Anyone who wants to be selective about video consumption

---

## 2. Solution Overview

### Core Insight
Convert YouTube subtitles into clean, readable text format → User can scan content quickly → User makes informed decision about watching.

### Future Enhancement
Use LLM to extract key points → Further reduce time needed to understand content.

### Solution Scope (MVP)
1. Extract subtitles from YouTube videos
2. Format into readable text (100% accurate, no alterations)
3. Store for reference
4. Display in web interface
5. Show processing history

---

## 3. Design Decisions & Rationale

### Decision 1: Subtitle Extraction Method

#### Question
How to extract subtitles from YouTube videos?

#### Options Considered

| Option | Pros | Cons | Status |
|--------|------|------|--------|
| **YouTube API** | Official, reliable, documented | Requires API key, authentication, quota limits, maintenance | ❌ Rejected |
| **yt-dlp** | No auth needed, active maintenance, works reliably, no quotas | Indirect method (not official API) | ✅ **Chosen** |
| **youtube-transcript-api** | Python library, simple | Less features, less maintenance | ❌ Alternative |
| **Puppeteer/Selenium** | Scrapes actual page | Slow, fragile, resource-intensive | ❌ Rejected |

#### Decision: **yt-dlp**
**Rationale**: 
- No API key management → simpler deployment
- No authentication overhead → better UX
- Active maintenance (fork of youtube-dl)
- Handles edge cases well
- Reliable for our use case
- Future-proof (maintained by community)

**Trade-off**: Using unofficial method, but acceptable for this use case.

---

### Decision 2: Technology Stack - Frontend

#### Question
What framework for web UI?

#### Options Considered

| Option | Pros | Cons | Status |
|--------|------|------|--------|
| **React + TypeScript** | Large ecosystem, component reusability, strong typing, familiar | Learning curve for some, bigger bundle | ✅ **Chosen** |
| **Vue + TypeScript** | Simpler syntax, good docs | Smaller ecosystem | ❌ Alternative |
| **Svelte** | Small bundle, reactive | Smaller community | ❌ Alternative |
| **Vanilla JS** | No dependencies | Hard to maintain as app grows | ❌ Rejected |

#### Decision: **React + TypeScript**
**Rationale**:
- Strong typing prevents bugs
- Large ecosystem (UI libraries, tools)
- Components easy to extend later
- Familiar to most developers
- Good for team collaboration (if team grows)

**Trade-off**: Slightly larger initial bundle, but flexibility for future features.

---

### Decision 3: Technology Stack - Backend

#### Question
What framework for REST API and business logic?

#### Options Considered

| Option | Pros | Cons | Status |
|--------|------|------|--------|
| **FastAPI (Python)** | Modern, async support, automatic docs, yt-dlp compatible, great for LLM later | Different language from frontend | ✅ **Chosen** |
| **Node.js/Express** | Same language as frontend, unified stack | Not ideal for subprocess calls (yt-dlp), LLM integration harder | ❌ Alternative |
| **Django (Python)** | Mature, batteries-included | Heavier, less async-native | ❌ Alternative |
| **Go** | Fast, compiled, good for CLI | Overkill, adds complexity | ❌ Rejected |

#### Decision: **FastAPI (Python)**
**Rationale**:
- Async/await native → handles long-running operations well
- Works perfectly with yt-dlp (Python library)
- Great for future LLM integration (Python ecosystem is best for AI)
- Automatic API documentation (Swagger UI)
- Modern, minimal boilerplate
- Excellent error handling

**Trade-off**: Different language from frontend (but clean separation of concerns).

---

### Decision 4: Database Choice

#### Question
What database for storing subtitles and metadata?

#### Options Considered

| Option | Pros | Cons | Status |
|--------|------|------|--------|
| **SQLite** | Simple, file-based, no setup, good for MVP | Not suitable for high concurrency | ✅ **Chosen (MVP)** |
| **PostgreSQL** | Powerful, scalable, better for production | Overkill for MVP, requires deployment | ⚠️ Future migration |
| **MongoDB** | Flexible schema, good for varied data | Not ideal for relational data (ours is relational) | ❌ Rejected |
| **Firebase** | No backend needed, real-time | Vendor lock-in, limited control | ❌ Rejected |

#### Decision: **SQLite (MVP), PostgreSQL (future)**
**Rationale**:
- MVP: SQLite is perfect for single-user app, no deployment overhead
- Future: Easy to migrate to PostgreSQL when scaling
- Schema is relational (videos → subtitles relationship)
- Can start local, move to server later

**Trade-off**: Limited concurrency now, but acceptable for MVP phase.

---

### Decision 5: Text Storage Format

#### Question
How to store formatted text in database?

#### Options Considered

| Option | Pros | Cons | Status |
|--------|------|------|--------|
| **Markdown** | Human-readable, structured, easy to render, can export to multiple formats | Extra parsing needed | ✅ **Chosen** |
| **Plain text** | Simple, universal | No structure, harder to enhance later | ❌ Alternative |
| **HTML** | Rich formatting, works in browser | Verbose, harder to read in DB | ❌ Alternative |
| **JSON** | Flexible, hierarchical | Verbose, harder to read | ❌ Alternative |

#### Decision: **Markdown**
**Rationale**:
- Human-readable in database
- Easy to render in UI
- Can be exported to multiple formats (PDF, DOCX, HTML)
- Structured but simple
- Future LLM integration works better with markdown

**Trade-off**: Slight parsing overhead, but worth it for flexibility.

---

### Decision 6: Deployment & Architecture

#### Question
Monolithic or microservices? Single repo or multiple?

#### Options Considered

| Option | Pros | Cons | Status |
|--------|------|------|--------|
| **Single repo (monorepo)** | Easy to manage, shared documentation, single deployment | Can become complex as grows | ✅ **Chosen** |
| **Separate repos** | Clear separation, easier to scale | Harder to manage, version mismatches | ❌ Alternative |
| **Microservices** | Scalable, independent deployment | Overkill for MVP, operational complexity | ❌ Rejected |

#### Decision: **Single Monorepo**
**Rationale**:
- Easy to start and manage
- Shared documentation
- Single source of truth for requirements
- Can split into separate repos later if needed

**Trade-off**: May need refactoring if grows significantly.

---

## 4. Architecture Decisions

### Application Architecture

#### Principle: Modularity & Extensibility
Design so that speech-to-text can be added later without major refactoring.

#### Key Design Choices

1. **Service-Oriented Backend**
   - Subtitle extraction service (swappable, can add speech-to-text)
   - Text formatting service (independent)
   - Database service (isolated)
   - Task management (for async processing)

2. **Async Processing**
   - Subtitle extraction is long-running
   - Use async/await to keep UI responsive
   - Task queue for future scalability

3. **Clean API Design**
   - Backend exposes clean REST API
   - Frontend agnostic to backend internals
   - Easy to add new processing steps

### Language Support

#### Question
Which languages to support?

#### Options Considered

| Languages | Pros | Cons | Status |
|-----------|------|------|--------|
| **Russian, English, Ukrainian** | Core user base (you), similar scripts, logical grouping | Limited initially, can expand | ✅ **Chosen** |
| **Just English** | Simpler, universal | Doesn't serve Russian users | ❌ Rejected |
| **10+ languages** | Comprehensive | Too complex for MVP, diminishing returns | ❌ Future phase |

#### Decision: **Russian, English, Ukrainian (MVP)**
**Rationale**:
- Primary user is Russian speaker
- English is global standard
- Ukrainian is linguistically similar
- Good balance between scope and complexity
- Easy to expand to more languages later

**Trade-off**: Limited initially, but manageable expansion path.

---

### Content Accuracy Requirement

#### Question
How strict should accuracy be?

#### Options Considered

| Approach | Definition | Pros | Cons | Status |
|----------|-----------|------|------|--------|
| **100% accurate** | Zero alterations, additions, or omissions. Exactly as spoken in subtitles. | Highest integrity, no surprises | Time-consuming formatting | ✅ **Chosen** |
| **95% accurate** | Minor formatting changes for readability | Faster to implement | Risk of misrepresentation | ❌ Rejected |
| **Semantic accuracy** | Preserve meaning, but reword for clarity | Useful but not original | Defeats purpose of transcript | ❌ Rejected |

#### Decision: **100% Accuracy**
**Rationale**:
- User trust is paramount
- Subtitles are source of truth
- Any alterations defeat the purpose
- Non-negotiable requirement

**Trade-off**: Slightly more complex formatting logic, but essential.

---

## 5. Rejected Ideas & Why

### Idea 1: Add subtitle translation
**Status**: ❌ Rejected for MVP  
**Reason**: Out of scope, adds complexity. Focus on extraction first. Can add translation later via LLM integration (Phase 2).

### Idea 2: Real-time collaborative editing
**Status**: ❌ Rejected for MVP  
**Reason**: Adds significant complexity. Not a core requirement. Could add if user base demands it.

### Idea 3: Automatic summarization in Phase 1
**Status**: ❌ Rejected for MVP  
**Reason**: Separate from MVP. Core MVP is extraction + formatting. Summarization is Phase 2 (LLM integration).

### Idea 4: Support for other video platforms (TikTok, etc)
**Status**: ❌ Rejected for MVP  
**Reason**: YouTube-specific tool. Scope creep. Can add other platforms later if demand exists.

### Idea 5: Video playback in web UI
**Status**: ❌ Rejected for MVP  
**Reason**: Not needed for MVP goal (quick content review via text). Adds complexity. Can add later.

---

## 6. Key Assumptions

### User Assumptions
1. **User has internet connection** for YouTube access
2. **User primarily watches Russian/English/Ukrainian content**
3. **User prefers clean text over original subtitle format**
4. **User wants quick way to decide if video is worth watching**
5. **User has browser for web UI access**

### Technical Assumptions
1. **yt-dlp will continue to work** reliably (community-maintained)
2. **YouTube won't block yt-dlp** in foreseeable future (but prepared to adapt)
3. **SQLite is sufficient** for Phase 1 (single-user, small dataset)
4. **Most videos have English or Russian subtitles** available
5. **Subtitle quality is good enough** for reliable extraction

### Business Assumptions
1. **MVP is proof of concept**, full build-out depends on validation
2. **User feedback will drive Phase 2 & 3 features**
3. **No monetization pressure** in MVP phase
4. **Time investment is acceptable** for Phase 1 (2-3 weeks estimated)

---

## 7. Risks & Mitigation

### Risk 1: yt-dlp becomes unmaintained
**Probability**: Low  
**Impact**: High (can't extract subtitles)  
**Mitigation**: Monitor community activity, have plan to use YouTube API if needed

### Risk 2: YouTube blocks yt-dlp
**Probability**: Low  
**Impact**: High (entire app breaks)  
**Mitigation**: Keep YouTube API as fallback option, maintain clean architecture

### Risk 3: Text formatting is complex
**Probability**: Medium  
**Likelihood**: Some videos have unusual punctuation, formatting  
**Mitigation**: Test with diverse videos, document edge cases, iterate on formatting rules

### Risk 4: Database migration needed later
**Probability**: Medium  
**Impact**: Medium (SQLite → PostgreSQL)  
**Mitigation**: Design schema to be migration-friendly, use ORM patterns

### Risk 5: Scope creep (users ask for more features)
**Probability**: High  
**Impact**: Low (have clear phase separation)  
**Mitigation**: Document phases clearly, manage expectations, defer to Phase 2/3

---

## 8. Future Considerations (Not in MVP)

### Phase 2: LLM Integration
- Extract key points from formatted text
- Generate summaries
- Customizable prompts for different use cases
- Support local and external LLMs

### Phase 3: Speech-to-Text Fallback
- Extract audio when subtitles unavailable
- Local speech-to-text processing (e.g., Whisper)
- Fallback mechanism

### Future Enhancements
- Export to PDF/DOCX
- Full-text search in subtitles
- Batch processing multiple videos
- API integration for third-party tools
- Mobile app
- Sharing/collaboration features
- Quality metrics and logging

---

## 9. Success Criteria for Discovery Phase

- ✅ Problem clearly defined
- ✅ Solution approach identified
- ✅ Technology stack chosen and justified
- ✅ Alternatives documented
- ✅ Key requirements identified
- ✅ Architecture designed
- ✅ Risks identified and mitigated
- ✅ Phases clearly separated
- ⏳ Ready for Delivery phase

---

## 10. Open Questions & Clarifications

*(Add here any questions that came up during development that need clarification)*

---

## 11. Appendix: Decision Matrix

### Overall Technology Decision Scoring

| Factor | Weight | React | FastAPI | yt-dlp | SQLite | Score |
|--------|--------|-------|---------|--------|--------|-------|
| **Simplicity** | 20% | 3/5 | 4/5 | 5/5 | 5/5 | 4.25 |
| **Scalability** | 15% | 4/5 | 4/5 | 3/5 | 2/5 | 3.35 |
| **Maintainability** | 20% | 4/5 | 5/5 | 4/5 | 5/5 | 4.50 |
| **Future-proof** | 20% | 5/5 | 5/5 | 4/5 | 3/5 | 4.25 |
| **Community** | 15% | 5/5 | 4/5 | 4/5 | 4/5 | 4.25 |
| **LLM Integration** | 10% | 3/5 | 5/5 | 4/5 | 4/5 | 4.10 |

**Overall**: 4.25/5 - Strong technology fit for project goals

---

## Document Status

- **Created**: 2024-04-18
- **Status**: ✅ Complete Discovery Phase
- **Next Phase**: Delivery (Backlog with Epics & User Stories)
- **Review**: Ready for team feedback
