# Поведенческая модель — YT Summarizer

Документ описывает **как работает система**: пайплайн обработки, жизненный цикл сущностей и логику интерфейса. Для понимания **из чего состоит система** — см. `CLAUDE.md`.

---

## 1. Пайплайн обработки (Activity Diagram)

Общий поток: от ввода URL до итогового результата.

```mermaid
flowchart TD
    A([Пользователь вводит URL]) --> B{Автопайплайн\nвключён?}

    B -->|Нет| C[Запуск: Extract]
    B -->|Да| PRE{Предварительная\nпроверка}

    PRE -->|Ollama offline\nили модель не задана| ERR_PRE[Блокировка:\nпоказать список проблем]
    PRE -->|OK| C

    C --> EXTRACT{Результат}

    EXTRACT -->|Успех| FT[(formatted_text\nсохранён в БД)]
    EXTRACT -->|Язык недоступен| LANG[Показать доступные языки\nПользователь выбирает]
    EXTRACT -->|Другая ошибка| ERR_EX[Показать ошибку]
    LANG --> C

    FT --> AP{Автопайплайн?}
    AP -->|Нет| RP[ResultPage]
    AP -->|Да| CL[Запуск: Cleanup]

    CL --> CL_R{Результат}
    CL_R -->|Успех| CT[(cleaned_text\nсохранён в БД)]
    CL_R -->|Fail / Ollama упал| RP

    CT --> SM[Запуск: Summary]

    SM --> SM_R{Результат}
    SM_R -->|Успех| ST[(summary_text\nсохранён в БД)]
    SM_R -->|Fail| RP

    ST --> RP
```

---

## 2. Жизненный цикл задачи извлечения (Task)

Фоновая задача, создаётся при сабмите URL.

```mermaid
stateDiagram-v2
    [*] --> pending : POST /api/process
    pending --> processing : воркер подхватил
    processing --> completed : субтитры извлечены
    processing --> failed : ошибка yt-dlp\nили язык недоступен
    completed --> [*]
    failed --> [*] : пользователь видит ошибку
```

---

## 3. Жизненный цикл AI Cleanup

Статус хранится в колонке `cleanup_status` таблицы `subtitles_formatted`.

```mermaid
stateDiagram-v2
    [*] --> null : видео обработано,\ncleanup не запускался

    null --> processing : POST /cleanup

    processing --> done : все параграфы обработаны
    processing --> failed : Ollama недоступен\nили модель не задана
    processing --> null : пользователь нажал Stop

    done --> processing : ↺ Re-run AI cleanup
    failed --> processing : ↺ Re-run AI cleanup

    note right of null
        cleaned_text = NULL
    end note
    note right of done
        cleaned_text заполнен
    end note
```

---

## 4. Жизненный цикл Summary

Статус хранится в колонке `summary_status`. Summary использует `cleaned_text` если доступен, иначе запрашивает запуск пайплайна.

```mermaid
stateDiagram-v2
    [*] --> null : cleanup завершён,\nsummary не запускался

    null --> pipeline_confirm : ✦ Summarize\n[cleanup не выполнен]
    pipeline_confirm --> cleanup_then_summary : пользователь подтвердил
    pipeline_confirm --> null : пользователь отказался

    cleanup_then_summary --> processing : cleanup done →\naвто-старт summary

    null --> processing : ✦ Summarize\n[cleanup уже done]
    processing --> done : summary_text сохранён
    processing --> failed : Ollama недоступен\nили таймаут
    processing --> null : пользователь нажал Stop

    done --> processing : ↺ Re-run summary
    failed --> processing : ↺ Re-run summary

    note right of processing
        Режим выбирается автоматически:
        · single-pass (< 24K символов)
        · map-reduce (≥ 24K, без глав)
        · full-extract (≥ 24K, есть главы)
    end note
```

---

## 5. Состояния интерфейса ResultPage

Какие действия доступны пользователю в зависимости от состояния данных.

```mermaid
stateDiagram-v2
    state "Subtitles tab" as SUB {
        [*] --> sub_ready : formatted_text есть
        sub_ready --> reextracting : ↻ Re-extract
        reextracting --> sub_ready : завершено\n(cleanup + summary сброшены)
    }

    state "Cleaned tab" as CLN {
        [*] --> cln_empty : cleanup не запускался
        cln_empty --> cln_processing : ✦ Clean with AI
        cln_processing --> cln_done : успех
        cln_processing --> cln_failed : ошибка
        cln_processing --> cln_empty : Stop
        cln_done --> cln_processing : ↺ Re-run
        cln_failed --> cln_processing : ↺ Re-run
    }

    state "Summary tab" as SUM {
        [*] --> sum_empty : summary не запускался
        sum_empty --> sum_pipeline : ✦ Summarize\n[cleanup не done]\n→ confirm dialog
        sum_empty --> sum_processing : ✦ Summarize\n[cleanup done]
        sum_pipeline --> sum_processing : авто после cleanup
        sum_processing --> sum_done : успех
        sum_processing --> sum_failed : ошибка
        sum_processing --> sum_empty : Stop
        sum_done --> sum_processing : ↺ Re-run
        sum_failed --> sum_processing : ↺ Re-run
    }

    state "Chat tab" as CHT {
        [*] --> chat_hidden : chatHistory пустой\n(вкладка не видна)
        chat_hidden --> chat_visible : первый обмен завершён
        chat_visible --> chat_hidden : Clear chat
        chat_visible --> chat_visible : отправить вопрос\nудалить сообщение
    }
```

---

## 6. Взаимозависимости этапов

```mermaid
flowchart LR
    EX[Extract\nformatted_text] -->|обязательно| CL[Cleanup\ncleaned_text]
    CL -->|рекомендуется| SM[Summary\nsummary_text]
    SM -->|требуется| CH[Chat]

    EX -.->|fallback если\ncleanup пропущен| SM

    style EX fill:#1e3a5f,color:#fff
    style CL fill:#1e3a5f,color:#fff
    style SM fill:#1e3a5f,color:#fff
    style CH fill:#1e3a5f,color:#fff
```

Жирная стрелка — рекомендуемый путь. Пунктир — возможный, но предупреждает пользователя через диалог подтверждения.
