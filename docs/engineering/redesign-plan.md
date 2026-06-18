# Redesign Plan — feature/redesign

Branch: `feature/redesign`
Design source: `stitch_yt_summarizer_UIkit.zip` + `stitch_yt_summarizer_pages.zip`
Design system name: Nexus Summarizer (Corporate Modern)

## Steps

- [ ] **Step 1** — CSS variables + Inter font
  - Update `:root` palette to Nexus color tokens
  - Update dark mode palette
  - Switch `body` font-family to Inter (Google Fonts)
  - Commit: `style: apply Nexus color tokens and Inter font`

- [ ] **Step 2** — Sidebar layout
  - Restructure `App.tsx`: remove top nav, add fixed left sidebar (~160px)
  - Add top utility bar (Systems Health + icons)
  - Update `.container` max-width to match new content area
  - Commit: `feat: sidebar navigation layout`

- [ ] **Step 3** — Base components
  - Cards: white bg, border, shadow-sm, border-radius 8px
  - Buttons: primary (red fill), secondary (surface-container-high), border-radius 8px, active:scale-95
  - Inputs/Selects: surface-container-low bg, outline-variant border, focus → primary
  - Badges/Tags: surface-container-highest bg, uppercase label-sm
  - Commit: `style: redesign base components`

- [ ] **Step 4** — Pages
  - [ ] HomePage
  - [ ] ResultPage
  - [ ] HistoryPage
  - [ ] QueuePage
  - [ ] SettingsPage
  - Commit per page

- [ ] **Step 5** — Dark mode
  - Update `[data-theme="dark"]` tokens to match Nexus dark palette
  - Verify all pages
  - Commit: `style: dark mode Nexus palette`

## Rollback

```bash
git checkout master          # instant full rollback
# or per-file:
git checkout master -- app/frontend/src/index.css app/frontend/src/App.tsx
```

## Key design tokens (light)

| Token | Value |
|---|---|
| background | #f8f9fa |
| surface (cards) | #ffffff |
| surface-container-low | #f3f4f5 |
| surface-container | #edeeef |
| surface-container-high | #e7e8e9 |
| surface-container-highest | #e1e3e4 |
| primary (accent) | #a03e40 |
| on-primary | #ffffff |
| on-surface (text) | #191c1d |
| on-surface-variant (muted) | #564241 |
| outline-variant (border) | #dcc0bf |
| outline (border strong) | #897270 |
| tertiary (ok/green) | #286b33 |
| error | #ba1a1a |
