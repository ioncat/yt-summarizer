# Project Bootstrap Guide for Claude Code

Use this guide at the start of any new project. Go step by step. Do not move to the next step without user confirmation.

---

## Rules for Claude Code

- Do not rush. Wait for user confirmation before each next step.
- Ask clarifying questions before creating documents.
- Do not start implementation until explicitly asked.
- Propose, then wait for "+++" or explicit approval.

---

## Step 1: Understand the Problem

Ask the user:
1. What problem does this project solve?
2. Who is the target user?
3. What is the main goal / value for the user?

Create `README.md` — basic project description (2-3 sentences, placeholder).  
Create `CLAUDE.md` — minimal, to be updated throughout.  
Create `docs/requirements.md` — empty placeholder for now.

---

## Step 2: Discovery — Clarify the Solution

Ask the user:
1. What is the core functionality? (What does the app do?)
2. What are the main user flows?
3. Any known constraints or preferences? (tech stack, integrations, platforms)
4. Are there related existing projects to reference?

Gather answers over multiple rounds — don't rush into documentation.

---

## Step 3: Discovery — Clarify Technical Decisions

Ask the user:
1. **Type of application**: CLI / Web UI / API / Mobile?
2. **Language & Framework**: Frontend? Backend?
3. **Database**: What kind of data? Relational or not?
4. **Storage format**: How should data be stored / exported?
5. **Authentication**: Needed or not?
6. **Deployment**: Local / Server / Docker / Cloud?

For each decision, propose options with pros/cons and wait for user to choose.

---

## Step 4: Create DISCOVERY.md

File: `DISCOVERY.md`

Sections to include:
1. **Problem Definition** — problem, pain points, target user
2. **Solution Overview** — core insight, solution scope (MVP)
3. **Design Decisions & Rationale** — for each key decision:
   - Question
   - Options considered (table: option / pros / cons / status)
   - Decision + rationale + trade-off
4. **Architecture Decisions** — design principles, key choices
5. **Rejected Ideas & Why** — what was explicitly left out
6. **Key Assumptions** — user, technical, business
7. **Risks & Mitigation** — probability / impact / mitigation
8. **Future Considerations** — phases beyond MVP
9. **Open Questions** — anything unresolved

---

## Step 5: Create PROJECT_PLAN.md

File: `PROJECT_PLAN.md`

Sections to include:
1. **Vision & Motivation** — why this project exists
2. **Product Goals** — per phase (MVP, Phase 2, Phase 3...)
3. **Technology Stack** — table: layer / technology
4. **Architecture Overview** — ASCII diagram showing components and data flow
5. **Database Schema** — SQL table definitions with all fields
6. **API Design** — base URL, endpoints with request/response examples
7. **Frontend Structure** — folder tree with component breakdown
8. **Backend Structure** — folder tree with service breakdown
9. **Development Phases** — milestones per phase with Definition of Done
10. **Critical Success Criteria** — checkboxes per phase
11. **Future Considerations** — features not in MVP
12. **Notes for Development** — important reminders

---

## Step 6: Update docs/requirements.md

File: `docs/requirements.md`

Write one User Story per feature using format:
```
As a <user role>
I want <capability>
So that <business value>
```

With Acceptance Criteria per story.

Group stories by phase (Phase 1 MVP, Phase 2, Phase 3...).

Add Non-Functional Requirements at the end:
- Performance
- Reliability
- Usability
- Security
- Maintainability

---

## Step 7: Create Backlog Structure

Ask user to provide `docs/product-delivery-conventions.md` if available.

### BACKLOG.md (navigation index)
File: `backlog/BACKLOG.md`

Contents:
- Overview of all epics per phase
- For each epic: name, short description, status, priority, story list, link to file
- Summary statistics (total epics, total stories)
- Development order
- How to use the backlog

### Epic Files (one per epic)
Files: `backlog/epics/EPIC-N.md`

Each epic file contains:
1. **Epic header**: Summary, Business Value, Scope (Included / Not Included)
2. **User Stories** — all stories for this epic, each with:
   - Title
   - User Story statement (As a / I want / So that)
   - Acceptance Criteria (Given / When / Then)
   - Edge Cases
   - Out of Scope
   - Notes for Engineering
   - Dependencies
   - Analytics / Events (optional)
3. **Epic-level Acceptance Criteria**
4. **Technical Notes**
5. **Dependencies** (other epics)
6. **Status** (Ready / In Progress / Done) + Priority (P0/P1/P2)

### Naming convention
- Epics: `EPIC-1.md`, `EPIC-2.md`, ...
- User Stories inside each epic: `US-101`, `US-102` (first digit = epic number)

---

## Step 8: Design Repository Structure

Propose this standard structure:

```
project-name/
├── backend/              # API server
│   ├── services/
│   ├── routes/
│   ├── models/
│   ├── utils/
│   ├── tests/
│   └── Dockerfile
│
├── frontend/             # Web UI
│   ├── src/
│   └── Dockerfile
│
├── data/                 # All data-related
│   ├── db/               # Database files (gitignored)
│   └── migrations/       # Schema and migrations (committed)
│
├── docs/                 # Documentation
├── backlog/              # Product backlog
│
├── .gitignore
├── .gitattributes
├── .env.example
├── Makefile
├── docker-compose.yml        # Production
├── docker-compose.dev.yml    # Development (hot reload)
├── README.md
├── CLAUDE.md
├── DISCOVERY.md
└── PROJECT_PLAN.md
```

Adjust based on project needs (e.g., no frontend for API-only projects).

---

## Step 9: Create Config Files

### .gitignore
Always exclude:
- `data/db/*.sqlite` — database files
- `.env` — secrets (keep `.env.example`)
- `__pycache__/`, `*.pyc`, `.venv/` — Python artifacts
- `node_modules/`, `dist/`, `build/` — Node artifacts
- `.DS_Store`, `Thumbs.db`, `.idea/`, `.vscode/` — OS and IDE files
- `*.log` — log files

### .gitattributes
```
* text=auto eol=lf
*.bat text eol=crlf
```

### .env.example
Include all environment variables with placeholder values. Group by section:
- Backend (host, port, debug)
- Database (path/connection string)
- CORS
- Processing timeouts
- Future integrations (commented out)

### Makefile
Provide commands:
- `make dev` — run backend + frontend together
- `make backend` — backend only
- `make frontend` — frontend only
- `make install` — install all dependencies
- `make docker-up` — start dev containers
- `make docker-down` — stop containers
- `make clean` — remove generated files
- `make help` — list all commands (default target)

### docker-compose.yml (production)
- backend service with port mapping and data volume
- frontend service depending on backend

### docker-compose.dev.yml (development)
- Same as production but with source volume mounts for hot reload
- DEBUG=true environment variable

---

## Step 10: First Git Commits

### Commit 1 — Documentation
Stage and commit all documentation files:
```
git init
git add .
git commit -m "Initial commit: Discovery and Delivery documentation"
```

Include in message: what was created, tech stack summary.

### Commit 2 — Project Structure
Stage and commit structure files:
```
git commit -m "chore: project structure, gitignore, docker, makefile"
```

Include in message: what folders and config files were added.

---

## Update CLAUDE.md Throughout

Keep CLAUDE.md updated as decisions are made. Final CLAUDE.md should include:
- Project overview (1 paragraph)
- Technology stack table
- Project folder structure
- Current development phase
- Key requirements summary
- API endpoints quick reference
- Database schema quick reference
- Before starting development checklist
- Important notes for development
- References to key documents

---

## Checklist

- [ ] README.md created
- [ ] DISCOVERY.md created (all sections)
- [ ] PROJECT_PLAN.md created (all sections)
- [ ] docs/requirements.md created
- [ ] BACKLOG.md created (navigation index)
- [ ] All epics created with user stories inside
- [ ] Repository structure created
- [ ] .gitignore created
- [ ] .gitattributes created
- [ ] .env.example created
- [ ] Makefile created
- [ ] docker-compose.yml created
- [ ] docker-compose.dev.yml created
- [ ] CLAUDE.md updated with full context
- [ ] Initial commits done (documentation + structure)
