# YT Summarizer - Product Backlog

Navigation and overview of all epics and user stories for YT Summarizer, organized by development phase.

---

## Phase 1: MVP - Subtitle Extraction & Formatting

Core functionality to extract YouTube subtitles and format them into readable text.

### Epic 1: Core Subtitle Extraction
**Description**: User can submit YouTube video URL and receive extracted subtitles

**Status**: 🟡 Ready for Implementation | **Priority**: 🔴 P0  
**User Stories**: US-101, US-102, US-103, US-104  
[View Epic →](./epics/EPIC-1.md)

---

### Epic 2: Text Formatting & Presentation
**Description**: Convert raw subtitles into clean, properly formatted markdown text

**Status**: 🟡 Ready for Implementation | **Priority**: 🔴 P0  
**User Stories**: US-201, US-202, US-203, US-204  
[View Epic →](./epics/EPIC-2.md)

---

### Epic 3: Data Persistence
**Description**: Save extracted subtitles and metadata to database for later retrieval

**Status**: 🟡 Ready for Implementation | **Priority**: 🔴 P0  
**User Stories**: US-301, US-302, US-303, US-304  
[View Epic →](./epics/EPIC-3.md)

---

### Epic 4: Error Handling & Edge Cases
**Description**: Handle all error scenarios gracefully with clear, user-friendly messages

**Status**: 🟡 Ready for Implementation | **Priority**: 🟠 P1  
**User Stories**: US-401, US-402, US-403, US-404, US-405  
[View Epic →](./epics/EPIC-4.md)

---

### Epic 5: Web User Interface
**Description**: Build intuitive web interface for interacting with the application

**Status**: 🟡 Ready for Implementation | **Priority**: 🔴 P0  
**User Stories**: US-501, US-502, US-503, US-504, US-505  
[View Epic →](./epics/EPIC-5.md)

---

## Phase 2: LLM Integration & Self-Raising

*(Details to be defined after Phase 1 completion)*

Extract key points and summaries from formatted text using LLM models.

**Expected Epics**:
- LLM Integration
- Prompt Management
- Summary Generation
- Key Points Extraction

---

## Phase 3: Speech-to-Text Fallback

*(Details to be defined after Phase 1 + Phase 2 completion)*

Add speech-to-text processing for videos without subtitles (architecture-ready in Phase 1).

**Expected Epics**:
- Audio Extraction
- Speech-to-Text Processing
- Fallback Mechanism

---

## Summary Statistics

### Phase 1 (MVP)
- **Total Epics**: 5
- **Total User Stories**: 21
- **Estimated Effort**: 4-6 weeks (team-dependent)
- **Priority**: All P0-P1 (Critical/High)

### Development Order
1. **Epic 1** (Core Extraction) - Foundation
2. **Epic 2** (Text Formatting) - Value delivery
3. **Epic 3** (Data Persistence) - User value
4. **Epic 4** (Error Handling) - Quality & stability
5. **Epic 5** (Web UI) - User experience

---

## Backlog Management Notes

- Each epic contains all its user stories in a single file for easy reference
- User stories follow Product Delivery Conventions (see product-delivery-conventions.md)
- Stories include: Title, User Story statement, Acceptance Criteria, Edge Cases, Out of Scope, Notes for Engineering, Dependencies
- Definition of Ready and Definition of Done specified for each story
- Analytics/Events documented for tracking and validation

---

## How to Use This Backlog

1. **Browse Epics**: Start with [Phase 1 Epics](#phase-1-mvp---subtitle-extraction--formatting)
2. **View Details**: Click "View Epic" link to open full epic file
3. **Read User Stories**: Each epic contains all its stories with full details
4. **Implementation**: Follow dependency order for smooth development
5. **Tracking**: Update epic status as work progresses

---

## Document Control

- **Version**: 1.0
- **Last Updated**: 2024-04-18
- **Status**: ✅ Ready for Development
- **Owner**: Product & Engineering Team
