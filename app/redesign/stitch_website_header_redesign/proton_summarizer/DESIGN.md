---
name: Nexus Summarizer
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#564241'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#897270'
  outline-variant: '#dcc0bf'
  surface-tint: '#a03e40'
  primary: '#81272b'
  on-primary: '#ffffff'
  primary-container: '#a03e40'
  on-primary-container: '#ffcdcb'
  inverse-primary: '#ffb3b1'
  secondary: '#4c616c'
  on-secondary: '#ffffff'
  secondary-container: '#cfe6f3'
  on-secondary-container: '#526772'
  tertiary: '#08521d'
  on-tertiary: '#ffffff'
  tertiary-container: '#286b33'
  on-tertiary-container: '#a2e9a3'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdad8'
  primary-fixed-dim: '#ffb3b1'
  on-primary-fixed: '#410007'
  on-primary-fixed-variant: '#81272a'
  secondary-fixed: '#cfe6f3'
  secondary-fixed-dim: '#b4cad7'
  on-secondary-fixed: '#071e27'
  on-secondary-fixed-variant: '#354a54'
  tertiary-fixed: '#acf4ad'
  tertiary-fixed-dim: '#91d793'
  on-tertiary-fixed: '#002107'
  on-tertiary-fixed-variant: '#08521e'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
  status-online: '#286b33'
  status-online-container: '#60a465'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 16px
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.05em
  tag-uppercase:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 12px
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 1.5rem
  section-gap: 2.5rem
  stack-gap: 1rem
  container-padding-mobile: 1rem
  container-padding-desktop: 2rem
  sidebar-width: 16rem
---

## Brand & Style
Nexus Summarizer embodies a **Corporate Modern** aesthetic tailored for high-productivity environments. The brand personality is efficient, technical, and reliable, aiming to evoke a sense of organized intelligence. 

The visual style utilizes a systematic approach to hierarchy, combining a neutral foundational palette with high-fidelity accent colors. It balances the density of a developer tool with the accessibility of a premium SaaS product. Design elements prioritize clarity and function, using subtle micro-interactions (like pulse animations for system health) to signal "live" processing without distracting from the primary task of data ingestion and summarization.

## Colors
The palette is built on a "Fidelity" color logic where the primary crimson (`#a03e40`) acts as the "action" anchor, signaling importance and branding. Secondary slate tones provide a professional, low-fatigue environment for long-form reading. 

The system uses a refined neutral scale for "Surface" management, distinguishing between background (`#f8f9fa`) and various container levels to create structural separation without relying on heavy borders. Success states and system health use a distinct tertiary green to provide immediate visual confirmation of uptime and reliability.

## Typography
The system relies exclusively on **Inter** to maintain a utilitarian and highly legible workspace. Typography is used as the primary driver of hierarchy; weight variations (from 400 to 700) distinguish between metadata, labels, and core content. 

Tight letter spacing is applied to large headlines to maintain a modern, "locked-in" feel, while labels utilize increased tracking and uppercase styling for better scannability at small sizes. The scale is designed to compress gracefully for mobile, ensuring that dashboard titles remain impactful on smaller viewports.

## Layout & Spacing
The layout follows a **Hybrid Fixed-Fluid Grid** model. A fixed sidebar (`16rem`) handles global navigation, while the main content area utilizes a fluid 12-column grid capped at a maximum width of `1200px` for optimal readability.

Margins and gutters are standardized to `1.5rem` (`24px`). Spacing follows a strict 4px unit system. Vertically, sections are separated by a consistent `2.5rem` gap to provide breathing room between disparate data visualizations and input forms. On mobile devices, the sidebar collapses into a hidden drawer, and horizontal padding reduces to `1rem` to maximize screen real estate.

## Elevation & Depth
Depth is conveyed primarily through **Tonal Layering** and **Low-Contrast Outlines** rather than aggressive shadows. 

1.  **Level 0 (Background):** The lowest layer (`#f8f9fa`), used for the canvas.
2.  **Level 1 (Surface-Container):** Slightly darker or lighter containers (`#f3f4f5`) used for the sidebar and secondary widgets to create subtle differentiation.
3.  **Level 2 (Active Cards):** High-priority input areas use the brightest surface (`#ffffff`) combined with a `shadow-sm` and a thin `outline-variant` border.
4.  **Interactive Elements:** Buttons and inputs use a focus ring of `primary/20` to create a "glow" effect, simulating physical engagement without breaking the flat aesthetic.

## Shapes
The shape language is **Soft** and professional. Standard UI elements (inputs, buttons, cards) use a `0.5rem` (`8px`) corner radius. Larger layout containers or distinct dashboard widgets transition to `0.75rem` (`12px`) for a more modern, approachable feel. 

Pill shapes are reserved exclusively for circular indicators (system status dots) and avatars. This mixture of soft rectangles and perfect circles creates a geometric tension that feels both precise and friendly.

## Components
-   **Buttons:** Primary buttons are high-contrast (Primary/On-Primary) with a bold weight. Secondary buttons use `surface-container-high` backgrounds to recede visually. All buttons utilize a subtle `active:scale-95` transition to provide tactile feedback.
-   **Inputs & Selects:** Use `surface-container-low` with a defined `outline-variant`. On focus, the border transitions to the primary color with a soft 2px ring.
-   **Cards:** Dashboard cards feature a 1px border and a very light shadow. Content within cards should follow a structured "Stack" (Vertical) or "Asymmetric Row" (Horizontal) layout.
-   **Status Indicators:** Small 8px circles with a "pulse" animation signal real-time activity.
-   **Tags:** Compact, high-density labels using a background of `surface-container-highest` and capitalized bold typography for categorization.
-   **Navigation:** Sidebar items use a `primary-container` fill to indicate the active state, with clear Material Symbol icons aligned left.