# System Behavior — YT Summarizer

Describes **how the system works**: processing pipeline, entity lifecycles, and UI logic. For **what the system is made of** — see `CLAUDE.md`.

---

## 1. Processing Pipeline (Activity Diagram)

Overall flow: from URL input to final result.

```mermaid
flowchart TD
    A([User enters URL]) --> B{"Auto-pipeline enabled?"}

    B -->|No| C[Start: Extract]
    B -->|Yes| PRE{"Pre-flight check"}

    PRE -->|"Ollama offline / model not set"| ERR_PRE["Blocked: show list of issues"]
    PRE -->|OK| C

    C --> EXTRACT{Result}

    EXTRACT -->|Success| FT[("formatted_text saved to DB")]
    EXTRACT -->|Language unavailable| LANG["Show available languages — user selects"]
    EXTRACT -->|Other error| ERR_EX[Show error]
    LANG --> C

    FT --> AP{Auto-pipeline?}
    AP -->|No| RP[ResultPage]
    AP -->|Yes| CL[Start: Cleanup]

    CL --> CL_R{Result}
    CL_R -->|Success| CT[("cleaned_text saved to DB")]
    CL_R -->|"Fail / Ollama down"| RP

    CT --> SM[Start: Summary]

    SM --> SM_R{Result}
    SM_R -->|Success| ST[("summary_text saved to DB")]
    SM_R -->|Fail| RP

    ST --> RP
```

---

## 2. Extraction Task Lifecycle

Background task, created on URL submit.

```mermaid
stateDiagram-v2
    [*] --> pending : POST /api/process
    pending --> processing : worker picked up
    processing --> completed : subtitles extracted
    processing --> failed : yt-dlp error / language unavailable
    completed --> [*]
    failed --> [*] : user sees error
```

---

## 3. AI Cleanup Lifecycle

Status stored in `cleanup_status` column of `subtitles_formatted`.

```mermaid
stateDiagram-v2
    [*] --> null : video processed, cleanup not started

    null --> processing : POST /cleanup

    processing --> done : all paragraphs processed
    processing --> failed : Ollama unavailable / model not set
    processing --> null : user clicked Stop

    done --> processing : ↺ Re-run AI cleanup
    failed --> processing : ↺ Re-run AI cleanup

    note right of null
        cleaned_text = NULL
    end note
    note right of done
        cleaned_text populated
    end note
```

---

## 4. Summary Lifecycle

Status stored in `summary_status`. Summary uses `cleaned_text` if available, otherwise prompts to run the pipeline.

```mermaid
stateDiagram-v2
    [*] --> null : cleanup done, summary not started

    null --> pipeline_confirm : ✦ Summarize — cleanup not done
    pipeline_confirm --> cleanup_then_summary : user confirmed
    pipeline_confirm --> null : user cancelled

    cleanup_then_summary --> processing : cleanup done → auto-start summary

    null --> processing : ✦ Summarize — cleanup already done
    processing --> done : summary_text saved
    processing --> failed : Ollama unavailable / timeout
    processing --> null : user clicked Stop

    done --> processing : ↺ Re-run summary
    failed --> processing : ↺ Re-run summary

    note right of processing
        Mode selected automatically:
        · single-pass (< 24K chars)
        · map-reduce (≥ 24K, no chapters)
        · full-extract (≥ 24K, has chapters)
    end note
```

---

## 5. ResultPage UI States

Actions available to the user depending on data state.

```mermaid
stateDiagram-v2
    state "Subtitles tab" as SUB {
        [*] --> sub_ready : formatted_text present
        sub_ready --> reextracting : ↻ Re-extract
        reextracting --> sub_ready : done (cleanup + summary reset)
    }

    state "Cleaned tab" as CLN {
        [*] --> cln_empty : cleanup not started
        cln_empty --> cln_processing : ✦ Clean with AI
        cln_processing --> cln_done : success
        cln_processing --> cln_failed : error
        cln_processing --> cln_empty : Stop
        cln_done --> cln_processing : ↺ Re-run
        cln_failed --> cln_processing : ↺ Re-run
    }

    state "Summary tab" as SUM {
        [*] --> sum_empty : summary not started
        sum_empty --> sum_pipeline : ✦ Summarize — cleanup not done → confirm dialog
        sum_empty --> sum_processing : ✦ Summarize — cleanup done
        sum_pipeline --> sum_processing : auto after cleanup
        sum_processing --> sum_done : success
        sum_processing --> sum_failed : error
        sum_processing --> sum_empty : Stop
        sum_done --> sum_processing : ↺ Re-run
        sum_failed --> sum_processing : ↺ Re-run
    }

    state "Chat tab" as CHT {
        [*] --> chat_hidden : chatHistory empty (tab not visible)
        chat_hidden --> chat_visible : first exchange completed
        chat_visible --> chat_hidden : Clear chat
        chat_visible --> chat_visible : send question / delete message
    }
```

---

## 6. Stage Dependencies

```mermaid
flowchart LR
    EX["Extract — formatted_text"] -->|required| CL["Cleanup — cleaned_text"]
    CL -->|recommended| SM["Summary — summary_text"]
    SM -->|required| CH[Chat]

    EX -.->|"fallback if cleanup skipped"| SM

    style EX fill:#1e3a5f,color:#fff
    style CL fill:#1e3a5f,color:#fff
    style SM fill:#1e3a5f,color:#fff
    style CH fill:#1e3a5f,color:#fff
```

Solid arrow — recommended path. Dashed — possible, but shows a confirmation dialog to the user.
