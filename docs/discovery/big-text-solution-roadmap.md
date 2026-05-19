# Solution Roadmap — Big-Text Processing

Поэтапный план движения от текущего map-reduce / full-extract pipeline к "document compiler" архитектуре, описанной в [big-text-problem-solution-discussion](big-text-problem-solution-discussion%20.md).

Это **research-проект для себя**, спешки нет. Каждая фаза замкнута — после неё система остаётся работоспособной, ценность приращается. Эпики и backlog-айтемы оформляются по мере созревания, не сразу.

## Vision

Превратить текущий pipeline `chunk → MAP → REDUCE / full_extract` в **document compiler**:

```
raw transcript
    ↓ pre-clean (non-LLM)
clean text
    ↓ semantic segmentation
semantic chunks (topic-bounded)
    ↓ extraction (per chunk + state)
Intermediate Representation
    ↓ rendering
TL;DR | summary | full reference | study guide
```

Принципы (из discussion-документа):

1. Не пускать ASR-мусор в main LLM
2. Резать по семантическим границам, не по символам
3. Держать document state, а не «summary of summaries»
4. Разделить extraction и writing
5. Retrieval по своему же документу при генерации
6. Компрессия зависит от типа контента

---

## Current state (что есть сейчас)

| Компонент | Реализация | Соответствие принципам |
|---|---|---|
| Subtitle extraction | yt-dlp + VTT parser | — |
| Pre-cleaning | LLM paragraph-by-paragraph (`text_cleaner.py`) | Принцип 1: частично. LLM перебор для базовой задачи |
| Chunking | Fixed 3K chars OR YouTube chapters | Принцип 2: только chapters → semantic. Без chapters — fixed. |
| Summarization modes | Single-pass / Map-Reduce / Full Extract | Принцип 4: Full Extract близок к extraction-only, но без IR |
| Memory | Нет | Принцип 3: ❌ |
| Retrieval | Нет | Принцип 5: ❌ |
| Content classifier | Нет (есть только размер + chapters) | Принцип 6: ❌ |

---

## Phase A — Pre-cleaning без LLM (1-2 недели)

### Goal

Снять с LLM грязную работу по punctuation/fillers/dedup. Раньше или позже LLM всё равно справляется, но тратит время и иногда ошибается.

### What's added

- **Punctuation restoration:** локальная модель (`silero/punctuation` для русского, `oliverguhr/fullstop-punctuation-multilang-large` для en). Запускается до `text_cleaner.py`.
- **Filler removal:** regex / token classifier. Список филлеров по языкам в конфиге. ~95% случаев ловятся без LLM.
- **Near-duplicate deduplication:** levenshtein / cosine на соседних предложениях с порогом. Убирает повторы как `"вот значит" "значит вот"`.
- **Sentence boundary detection:** spacy или nltk для границ предложений.

### Pipeline change

```diff
- formatted_text  →  LLM cleanup (per paragraph)  →  cleaned_text
+ formatted_text  →  pre-clean (non-LLM)  →  pre-cleaned  →  LLM cleanup (optional, lighter prompt)  →  cleaned_text
```

LLM-cleanup остаётся опциональным «последним проходом». Если pre-clean справился — LLM пропускаем (огромная экономия времени).

### Done when

- 80% случаев не требуют LLM cleanup вообще
- Pre-clean занимает <10 сек на 100K символов
- Качество ≥ текущего LLM cleanup на gemma3:4b

### Risks

- Punctuation restoration на русском — небольшой выбор моделей. Возможно потребуется обучить свою или использовать LLM в этой узкой задаче.

---

## Phase B — Semantic segmentation (1-2 недели)

### Goal

Заменить fixed-char chunking на резку по семантическим границам. Прекратить рубить мысль на полуслове.

### What's added

- **Embedding model:** `bge-small-en` для en, `intfloat/multilingual-e5-small` для мультиязычного. Лёгкая, быстрая, локально.
- **Sliding window:** строим embeddings на окнах из N (например 5) предложений.
- **Cosine shift detection:** считаем cosine между соседними окнами. Resky drop = topic boundary.
- **Adaptive chunk size:** chunks теперь разного размера — от 800 до 5000 символов в зависимости от topic stability.

### Pipeline change

```diff
- text  →  split every 3K chars  →  chunks  →  MAP / REDUCE
+ text  →  embed sliding windows  →  detect boundaries  →  semantic chunks  →  MAP / REDUCE
```

Для chapter-видео этот шаг можно пропустить — главы УЖЕ semantic boundaries. Semantic seg включается только для flat-видео без глав.

### Done when

- Chunks не режут предложения посередине
- Каждый chunk содержит one coherent topic (visible по выводу)
- Boundary detection занимает <30 сек на 100K символов

### Risks

- Embedding модели грузят GPU/RAM. Может конкурировать с LLM. Решение: малая модель + CPU-инференс через onnx
- Многоязычные embeddings слабее чем монолингвальные

---

## Phase C — Intermediate Representation (2-3 недели)

### Goal

Разделить extraction от writing. Один pipeline для всех output-режимов.

### What's added

- **IR schema (JSON):** для каждой semantic section:
  ```json
  {
    "topic": "string",
    "claims": ["string"],
    "facts": [{"text": "...", "source_ts": 123}],
    "examples": ["..."],
    "entities": ["..."],
    "quotes": [{"speaker": "...", "text": "..."}],
    "terminology": [{"term": "...", "def": "..."}]
  }
  ```
- **Extraction prompt:** строгий, требует JSON output, низкая temperature, schema validation.
- **Renderer:** функция `render(ir, mode)` где mode = `tldr | summary | full | study_guide`. Без LLM — детерминированная сборка из IR + лёгкая модель для prose-склейки.

### Pipeline change

```diff
- chunks  →  MAP (summary text)  →  REDUCE (final text)
+ semantic chunks  →  extract IR (per chunk)  →  merge IR  →  render(mode)
```

Existing modes (Map-Reduce, Full Extract) переписываются поверх IR. Full Extract = render(ir, "full"). Map-Reduce = render(ir, "summary"). TL;DR = render(ir, "tldr"). Все три из одного ingestion.

### Done when

- Один pass по видео даёт IR
- Из IR за <5 сек собирается любой output-режим
- Anti-hallucination проверка: все claims в финальном тексте присутствуют в IR

### Risks

- JSON schema enforcement — модели часто ломают формат. Нужны retries / structured output API (Ollama поддерживает grammar-constrained generation через GBNF)
- IR требует ревизии после первых видео — какие поля действительно полезны

---

## Phase D — Hierarchical memory (deferred, после A+B+C)

### Goal

Document state вместо "summary of summaries". Снять semantic drift.

### What's added

- **State object** обновляется после каждого chunk:
  - active topics
  - entities seen
  - unresolved threads / open questions
  - timeline of claims
- **Chunk N processed with:** chunk text + compact state object (не предыдущие summaries)
- **State merges** через специальный update-prompt

### Out of scope

Эта фаза — большой шаг, требует A+B+C как фундамент. Пока в дальний план.

---

## Phase E — Retrieval (deferred)

### Goal

Local RAG по одному документу. Во время генерации модель достаёт связанные chunks по запросу.

### What's added

- Vector store (chromadb / lancedb / qdrant local)
- Indexing IR + chunks при ingestion
- Query layer: "при генерации секции X дай мне 3 наиболее релевантных chunks"

### Out of scope

Тоже big shift. После C.

---

## Phase F — Content classifier (orthogonal)

### Goal

Compression policy зависит от типа контента.

### What's added

- Lightweight classifier (5-7 классов: lecture / interview / news / tutorial / narrative / opinion / mixed)
- Per-class compression target (lecture = lossless, news = aggressive compression)
- Per-class style hint в prompt

Можно делать независимо от A-E, мелкая фича.

---

## Heterogeneous pipeline (cross-cutting)

Из discussion: extraction model ≠ structuring model ≠ writer model.

В нашем случае это означает:

- **Extraction:** маленькая быстрая модель (qwen3:4b, gemma3:4b). Из IR будет получено всё нужное.
- **Writer (renderer prose):** более сильная модель (qwen2.5:14b, gemma3:12b). Только для финального prose-pass, на готовой IR — намного короче чем raw transcript.

Memory pressure: переключение моделей в Ollama стоит время. Solution: `OLLAMA_KEEP_ALIVE` + достаточно RAM/VRAM для двух одновременно.

---

## Когда переходить от фазы к фазе

Не по календарю — по сигналам.

- **Закончили A?** → не возвращаемся к LLM cleanup. Pre-clean справляется. Перешли на B.
- **Закончили B?** → chunks больше не режут предложения. Map-Reduce качество ощутимо выросло. Готовы к C.
- **Закончили C?** → один pipeline, три режима output. Тут можно остановиться надолго — D/E это уже academic полировка.

Между фазами — реальное использование на разных видео. Если pipeline хорошо обслуживает 80% видео — выгода от следующей фазы под вопросом.

---

## Что НЕ делаем (явно)

- ❌ Не пишем сразу всю архитектуру. Поэтапно
- ❌ Не выкидываем существующий map-reduce / full-extract — он будет работать пока новый pipeline не докажет качество
- ❌ Не вводим cloud-зависимости (RAG через cloud API, embeddings через OpenAI)
- ❌ Не превращаем в production-сервис. Это research-проект для себя
- ❌ Не оптимизируем под GPU > 24GB VRAM. Только consumer-железо

---

## Связанные документы

- [big-text-problem-statement.md](big-text-problem-statement.md) — формулировка проблемы
- [big-text-problem-solution-discussion.md](big-text-problem-solution-discussion%20.md) — обсуждение принципов решения (source of this roadmap)
- [../USER_GUIDE.md](../USER_GUIDE.md) — текущие режимы обработки
- [../../CLAUDE.md](../../CLAUDE.md) — техническая архитектура
- [../backlog/BACKLOG.md](../backlog/BACKLOG.md) — существующие эпики (пересечения с этим roadmap)
