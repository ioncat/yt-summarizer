# Product Delivery Conventions

## User Stories & Backlog Standards

This document defines the standard for writing, reviewing, and
delivering user stories for the Dental Appointment Scheduling Platform.

The goal of these conventions is to ensure: - shared understanding
between Product and Engineering, - predictable delivery, - minimal
ambiguity during implementation, - consistent quality of backlog items.

This document is considered a **working contract** for the team.

------------------------------------------------------------------------

## 1. General Principles

-   User Stories describe **user value**, not implementation.
-   Each User Story represents a **vertical slice** of functionality.
-   Implementation details are handled via **tasks / subtasks**, not
    separate stories.
-   All stories must be understandable without verbal explanation.
-   Ambiguity is treated as a defect.

------------------------------------------------------------------------

## 2. User Story Structure (Mandatory)

Every User Story must follow the structure below.

### Title

Short, descriptive title reflecting user value.

### User Story
```
As a `<user role>`
I want `<capability>`
So that `<business value>`
```
### Acceptance Criteria

Written in Given / When / Then format and describing observable
behavior.

### Edge Cases

Concrete non-happy-path scenarios.

### Out of Scope

Explicitly states what is NOT included.

### Notes for Engineering

Implementation guidance without prescribing solutions.

### Dependencies (Optional)

Other stories or epics.

### Analytics / Events (Optional)

Signals required for validation.

------------------------------------------------------------------------

## 3. Definition of Ready

-   Story statement complete
-   Acceptance Criteria defined
-   Edge Cases listed
-   Out of Scope explicit
-   Notes for Engineering present
-   No open questions

------------------------------------------------------------------------

## 4. Definition of Done

-   Acceptance Criteria met
-   Edge Cases handled
-   QA verification complete
-   PO accepts

------------------------------------------------------------------------


## 5. What This Document Is NOT

-   Technical specification
-   Architecture document
-   Substitute for communication
