# Solution Roadmap — Big-Text Processing

Поэтапный план движения от текущего map-reduce / full-extract pipeline к "document compiler" архитектуре.

Это **research-проект для себя**, спешки нет. Каждая фаза замкнута — после неё система работоспособна, ценность приращается.

**Roadmap описывает не только ЧТО делается на каждой фазе, но и ПОЧЕМУ** — мотивации, альтернативы, тех решения. Каждое значимое решение даётся с обоснованием и (где применимо) ссылкой на вопрос из [Q&A в discussion](big-text-problem-solution-discussion%20.md#questions).

---

## Vision

Превратить текущий pipeline `chunk → MAP → REDUCE / full_extract` в **document compiler**:

```
raw transcript
    ↓ pre-clean (hybrid: heuristics + light LLM)
clean text
    ↓ semantic segmentation
semantic chunks (topic-bounded)
    ↓ extraction (per chunk + document state)
Intermediate Representation (claims, entities, examples, quotes)
    ↓ rendering
TL;DR | summary | full reference | study guide
```

**Принципы** (из discussion):

1. Не пускать ASR-мусор в main LLM
2. Резать по семантическим границам, не по символам
3. Держать document state, а не «summary of summaries»
4. Разделить extraction и writing
5. Retrieval по своему же документу при генерации
6. Компрессия зависит от типа контента

---

## Recommended order of work

Перед началом любой architectural experiments — стабилизировать фундамент. Иначе невозможно объективно оценивать изменения.

1. **Stabilize current pipeline** — закрыть текущие баги, протестить Epic 26/27/29
2. **Add measurement layer** — определить proxy-метрики и failure taxonomy (Foundation 1)
3. **Build benchmark harness** — `evaluate.py` + 5 selected videos
4. **Только потом — architecture experiments** (Phase A → B → C ...)

Без baseline measurements Phase A/B/C невозможно объективно оценивать. Это причина почему Foundation 1 = блокер.

---

## Current state

| Компонент | Реализация | Соответствие принципам |
|---|---|---|
| Subtitle extraction | yt-dlp + VTT parser | — |
| Pre-cleaning | LLM paragraph-by-paragraph (`text_cleaner.py`) | Принцип 1: частично |
| Chunking | Fixed 3K chars OR YouTube chapters | Принцип 2: только chapters → semantic |
| Summarization modes | Single-pass / Map-Reduce / Full Extract | Принцип 4: Full Extract близок |
| Memory | Нет | Принцип 3: ❌ |
| Retrieval | Нет | Принцип 5: ❌ |
| Content adaptation | Только по размеру + chapters | Принцип 6: ❌ |

---

## Cross-cutting foundations (делаются до или во время A)

Это **не отдельные фазы**, а инфраструктурные изменения, которые поддерживают все остальные фазы. Без них последующая работа невозможна или невалидна.

### Foundation 1: Evaluation infrastructure (BLOCKER)

**Goal:** объективно сравнивать качество между версиями pipeline.

**What's added:**

- **Benchmark suite — 3–5 carefully selected cases**, не random:
  - Dense technical lecture
  - Chaotic interview / podcast
  - Structured tutorial
  - News / opinion piece
  - Long-form discussion
- Три ожидаемых output: TL;DR, summary, full reference на каждое
- **Quantitative proxy-метрики:**
  - Named entity recall (entities из source присутствуют в output)
  - Number / date preservation
  - Quote preservation
  - Semantic similarity (cosine между embeddings source secs vs output)
  - Section coherence
  - Hallucination rate (source-grounded verification — каждое утверждение в output должно иметь source)
- **Qualitative failure taxonomy** — категории типичных деградаций:
  - Hallucination (выдумки модели)
  - Dropped entities (потерянные сущности)
  - Broken chronology (нарушенный порядок событий)
  - Duplicated ideas (одна мысль повторяется разными словами)
  - Lost section boundaries (структура размылась)
  - Incoherent transitions (рваные переходы между частями)
  - Overcompression (слишком сжато, потеря смысла)
  - Undercompression (вода не убрана)
- Скрипт `evaluate.py`: прогоняет pipeline на benchmark, выдаёт numeric report + классификацию failures по таксономии
- Regression check: новая фаза прогоняется автоматически перед merge

**Why initial benchmark — 5 carefully selected, не 30 random (из Q1):**

- 30 random видео = evaluation сам по себе становится отдельным проектом (45+ ручных оценок для 3 modes)
- 5 carefully selected покрывают спектр типов контента, на которых pipeline должен работать
- Цель initial benchmark: **поймать regression, увидеть qualitative failures, валидировать proxy metrics** — не построить большой test set
- Когда инфраструктура (метрики, harness) стабильна — scale до 15–30 без переделок

**Why failure taxonomy, а не только метрики:**

Numeric metrics показывают что качество упало, не объясняют почему. Таксономия даёт vocabulary для discussion ("текущий выход страдает от overcompression и broken chronology") и ускоряет iteration — каждая фаза адресует конкретные failure modes. Без таксономии итерируем вслепую.

**Done when:**

- Скрипт прогоняет текущий pipeline на 5 selected videos
- Выдаёт numeric report по proxy-метрикам
- Каждый output классифицирован по failure taxonomy (вручную или semi-automated)
- Метрики стабильны при повторных прогонах (детерминизм где возможен)

---

### Foundation 2: Timestamps preservation

**Goal:** сохранять временные метки от VTT-источника до финального output.

**What's added:**

- `text_formatter.py`: каждый paragraph (или sentence) получает поле `time_range: (start, end)`
- Хранение: расширить `SubtitleFormatted` либо отдельная таблица `paragraph_timestamps`
- IR (Phase C) использует это для `source_ts` в claims/facts/quotes

**Why now, не в Phase C (из Q5):**

Если внедрять позже — придётся ретроактивно восстанавливать привязку, что неточно. Timestamps дешевле сохранять с самого начала. Phase C будет иметь к ним доступ из коробки.

**Why per paragraph, а не per sentence:**

Параграфы — текущая единица в `subtitles_formatted`. Sentences = более точная гранулярность, но требует sentence splitter (он будет в Phase A). Стартуем с paragraph-level, повышаем точность когда есть splitter.

**Done when:** `formatted_text` JSON содержит range на каждый абзац, API его возвращает.

---

### Foundation 3: Reversibility — pipeline-wide toggle + Benchmark

**Goal:** уметь сравнивать новый pipeline со старым на одном видео без destructive replacement.

**What's added:**

- **Pipeline-wide toggle в Settings → General:**
  - `Legacy pipeline` (текущий map-reduce / full-extract)
  - `Experimental semantic pipeline` (новые фазы по мере появления)
- `pipeline_version` поле в `benchmark_runs` — фиксирует какая итерация pipeline дала результат
- При запуске Summary / Cleanup из Result page — используется выбранный pipeline
- Benchmark page остаётся source of truth для side-by-side сравнения

**Why pipeline-wide toggle, не per-stage (из Q4):**

- Per-stage toggles (отдельные switches для pre-cleaning / semantic seg / IR / rendering) = combinatorial explosion. Сложно дебажить, невозможно reproducible benchmark
- Pipeline-wide = два чёткие режима. Можно сравнить целиком, есть chosen baseline. Простая architecture
- Per-stage toggles пригодятся позже, когда experimental pipeline стабилизируется и нужно профилировать конкретные шаги — это premature complexity сейчас

**Why используем существующий Benchmark вместо нового UI:**

Benchmark уже даёт side-by-side с историей и метаданными. Не нужно строить второй сравнительный интерфейс. Просто добавить `pipeline_version` колонку.

**Done when:**

- Settings → General → "Pipeline" dropdown с двумя опциями
- `benchmark_runs.pipeline_version` присутствует и заполняется
- Можно запустить summary на видео двумя pipeline (legacy + experimental) и увидеть оба результата в Benchmark page

---

## Phase A — Hybrid pre-cleaning (1-2 недели после Foundation 1+2)

### Goal

Заменить чистый LLM-cleanup на гибрид: heuristics для механической работы + small punctuation model для recovery + lightweight LLM correction только на двусмысленные случаи.

### What's added

1. **Heuristic pass (non-LLM):**
   - Filler removal: regex по списку филлеров на языке (ru/en)
   - Near-duplicate dedup: levenshtein / cosine между соседними предложениями, порог настраиваемый
   - Sentence boundary detection: spacy/nltk
   - Normalization: пробелы, регистр имен, числа
2. **Punctuation restoration:** небольшая модель (`silero/punctuation` для ru, `oliverguhr/fullstop-...` для en) на pre-cleaned tokens
3. **LLM correction pass (optional):** только на сегментах где heuristic+punctuation выдали low-confidence результат. Используется существующий `text_cleaner.py`, но с гораздо более узким scope

### Pipeline change

```diff
- formatted_text  →  LLM cleanup (per paragraph)  →  cleaned_text
+ formatted_text  →  heuristics  →  punctuation restoration  →  LLM correction (selective)  →  cleaned_text
```

### Why hybrid, а не pure non-LLM (из Q2 + Q7)

Готовые punctuation модели обучены на news/wiki, не на YouTube ASR (разговорная речь, технические термины, иностранные слова в кириллице). На наших данных они дают draft-качество, не production. LLM нужен для clean-up их ошибок — но узко, не на каждом параграфе.

### Why LLM correction selective, а не на всё (из Q6)

Если LLM переписывает каждый параграф — теряется экономия от non-LLM этапов. LLM включается только на сегментах с маркерами проблем: незакрытые квоты, обрывки предложений, явные ASR-сбои. Это резко снижает время обработки и стабилизирует output.

### Why heuristics для filler/dedup, а не LLM (из Q6)

Эти задачи механические — regex и cosine справляются за миллисекунды с точностью ~95%. LLM на них = overkill и недетерминизм.

### Done when

- 80% параграфов проходят без LLM correction
- Total pre-clean time <1 мин на 100K символов (vs текущие часы LLM-cleanup)
- Качество ≥ текущего LLM-cleanup на проверочных видео (Foundation 1 даёт numbers)

### Risks

- RU punctuation модели слабые → LLM correction может оказаться на 30-40% параграфов, а не 5-10% (Q2)
- Heuristic dedup может убрать legitimate повторы (риторические, для эмфазиса)

---

## Phase B — Semantic segmentation (1-2 недели)

### Goal

Заменить fixed-char chunking на cuts по semantic boundaries. Прекратить рубить мысль.

### What's added

- **Embedding model:** `multilingual-e5-small` или `bge-m3` (из Q2). Локально, через `sentence-transformers`
- **Sliding window:** размер 5–8 предложений, шаг 2–4, перекрытие ~50% (параметры из Q8)
- **Boundary detection:** adaptive threshold через percentile from local distribution + hysteresis (Q9)
- **Min/max section size** constraints: section не короче N sentences и не длиннее M chars
- **Soft boundaries:** если transition gradual — merge соседние candidates, или synthetic boundary только по max section size (Q10)

### Pipeline change

```diff
- text  →  split every 3K chars  →  chunks  →  MAP / REDUCE
+ text  →  embed sliding windows  →  detect adaptive boundaries  →  semantic chunks  →  MAP / REDUCE
```

Для chapter-видео шаг пропускается — главы УЖЕ semantic boundaries. Semantic seg только для flat-видео.

### Why concrete parameter defaults (из Q8)

Без стартовых значений нельзя начать тюнить. Window 5–8 sentences = достаточно контекста для определения topic, но не размывает transitions. Overlap 50% = стандарт для sliding window text segmentation.

### Why adaptive threshold, а не hard cutoff (из Q9)

Topic shift — relative problem, не absolute. На двух разных видео cosine distribution разная. Percentile-based (например, cut на нижних 10% similarity) адаптируется автоматически. Hysteresis (раз вошли в "section X", не выходим пока similarity не упадёт ниже более низкого порога) убирает дребезжание.

### Why soft boundaries + min/max size (из Q10)

В лекциях много gradual transitions — нет одного резкого порога. Без min/max constraint получаем либо сверх-короткие фрагменты (на каждом shift), либо гигантские секции (если transitions слишком плавные).

### Why embeddings локально, не cloud (из roadmap "won't do")

Проект research-only, без cloud dependencies. `multilingual-e5-small` ~470MB, работает на CPU за секунды. Не блокер.

### Done when

- Chunks не режут предложения
- Каждый chunk one coherent topic (визуальная инспекция + benchmark)
- Boundary detection <30 сек на 100K символов

### Risks

- RU embedding качество на разговорной речи может уступать английскому (Q2)
- Tuning параметров — итеративный, требует evaluation infrastructure (Foundation 1)

---

## Phase C — Intermediate Representation (2-3 недели)

### Goal

Разделить extraction (из transcript в structured data) и rendering (из structured data в prose). Один pipeline — все output-режимы.

### What's added

- **Core universal schema (JSON):**
  ```json
  {
    "section_id": "string",
    "topic": "string",
    "claims": [{"text": "...", "source_ts": [start, end]}],
    "entities": [{"name": "...", "type": "..."}],
    "examples": ["..."],
    "quotes": [{"speaker": "...", "text": "..."}],
    "terminology": [{"term": "...", "def": "..."}],
    "topics": ["..."]
  }
  ```
- **Per content type extensions:** опциональные поля для конкретных типов:
  - Interview: `dialogue_pairs`, `questions`
  - Lecture: `definitions`, `prerequisites`
  - Tutorial: `steps`, `commands`, `expected_output`
- **Extraction prompt:** строгий, требует JSON output, low temperature
- **Validation pipeline:** pydantic + retry + auto-repair (Q3)
- **Renderer:** `render(ir, mode)` где mode ∈ `{tldr, summary, full, study_guide}`. Renderer = deterministic compilation из IR + lightweight LLM для prose-склейки

### Pipeline change

```diff
- chunks  →  MAP (summary text)  →  REDUCE (final text)
+ semantic chunks  →  extract IR (per chunk)  →  merge IR  →  render(mode)
```

Existing Full Extract и Map-Reduce переписываются поверх IR. Full Extract = `render(ir, "full")`. Map-Reduce = `render(ir, "summary")`. TL;DR = `render(ir, "tldr")`. Из одной обработки — три режима output.

### Claim — определение и extraction methodology

**Distinct claim** = атомарное verifiable semantic unit. Должен быть:

- **Attributable** — можно указать source segment / timestamp
- **Semantically independent** — имеет смысл вне контекста других claims
- **Retrievable** — можно найти по similarity к запросу
- **Compressible** — может быть выражен одной фразой без потери смысла

**Пример хорошего claim:**

> "React Server Components reduce client bundle size"

**Пример плохого claim (opinion / noisy):**

> "React is good and modern"

— субъективно, не verifiable, не attributable к конкретному факту.

**Extraction methodology (из Q12):**

Извлечение claims = LLM-pass, но **строго constrained**:

- НЕ "extract every claim from huge chunk" (модель начнёт editorializing)
- Извлечение **per semantic segment** (output Phase B), bounded output size
- Extraction prompt запрещает:
  - Paraphrase (переформулировку — должна быть близко к оригиналу)
  - Synthesis (объединение разных claims в один)
  - Merging distant ideas (claims из разных частей текста)

### Why claim-level granularity, не sentence/phrase (из Q12)

- **Sentence-level** слишком привязан к transcript. Теряется при перефразировании, плохая dedup
- **Phrase-level** разрушает семантику ("в 2020 году" сам по себе не информация)
- **Claim-level** = атомарное утверждение, сохраняющее context для retrieval, dedup, compression. Optimal balance

### Why core schema + extensions, не отдельные per type (из Q11)

- Полностью отдельные schemas разрывают pipeline — каждый шаг должен знать тип контента заранее
- Универсальное ядро + опциональные расширения = downstream code работает с известными полями, но не теряет специфику

### Why pydantic + retry, не GBNF grammar (из Q3)

- GBNF ломает некоторые модели — generation quality падает под constraint
- GBNF плохо масштабируется на сложные schemas (наша IR не тривиальная)
- Pydantic validation + auto-repair pass даёт architectural flexibility и более стабильный pipeline. Цена — лишние retries на 10-15% случаев

### Why renderer = deterministic + light LLM (вместо чистой prose generation)

- Deterministic компиляция из IR в текст даёт reproducibility (одна и та же IR → одинаковый output)
- LLM только для prose-склейки между атомами — переходных фраз, стилистики
- Anti-hallucination: всё что в финальном тексте есть в IR (можно проверить regression-тестом)

### Done when

- Один pass по видео даёт валидную IR
- Из IR <5 сек собирается любой output-режим
- Hallucination rate (Foundation 1 метрика) ≤ baseline

### Risks

- LLM JSON output flakiness — основной враг (Q3)
- IR schema потребует ревизии после первых видео (planning IR априори без данных = риск over-engineering)

---

## Phase D — Hierarchical document state (deferred, после A+B+C)

### Goal

Document state вместо "summary of summaries". Снять semantic drift на длинных текстах.

### What's added

- **Tiered state object** (из Q13):
  - Active entities (упомянутые в последних N секциях)
  - Glossary (определения терминов из IR)
  - Unresolved references (упоминания без определения)
  - Running topic summaries (тематические треды через документ)
- **Compaction policy:**
  - Decay by relevance (давно не упомянутые entities выпадают)
  - Merge duplicates (один entity под разными названиями)
  - Summarize inactive branches (тред закрыт — сжимается до summary)
- **Update prompt:** после каждого chunk LLM обновляет state, не пересоздаёт

### Why tiered, не flat state (из Q13)

Flat state бесконтрольно растёт на 100+ секциях. Tiered с decay поддерживает constant size. Старые entities не теряются полностью — переходят в "long-term memory" (отдельный store), доступный через retrieval (Phase E).

### Why deferred

Это major shift, требует A+B+C как фундамент. Сначала validate что IR работает, потом строим memory layer поверх.

---

## Phase E — Local retrieval (deferred, после D)

### Goal

Document становится queryable memory. Во время генерации модель достаёт связанные chunks по similarity.

### What's added

- **Vector store: lancedb** (Q14)
- Indexing: IR + chunks + entities embeddings при ingestion
- Query layer: при генерации section X → top-K relevant chunks/claims по similarity

### Why lancedb (из Q14)

- Embedded (no separate service)
- Rust-based, быстрый
- Lightweight по dependencies
- **Альтернативы отвергнуты:** chromadb тяжелее и медленнее, qdrant требует отдельный сервис (наш проект — local-first)

### Why deferred

После D. До этого нет смысла в retrieval — IR ещё не готова, state не структурирован.

---

## Phase F — Content adaptation via user intent (orthogonal, упрощённая)

### Goal

Разная compression policy для разных типов контента.

### What's added

- **Не ML classifier**, а:
  - Heuristic baseline classification (по metadata: длительность, наличие глав, channel, keywords) — даёт guess
  - **User override в UI**: пользователь подтверждает или меняет тип через dropdown в Settings или per-video
- Per-class compression policy: lecture = lossless, news = aggressive
- Per-class style hint в render prompt

### Why no ML classifier (из Q15)

- Обучающие данные для классификатора нужно размечать вручную — премат оптимизация
- Lecture vs interview граница субъективна — даже human disagreement высокий
- **User intent важнее objective content type** — один и тот же лекторий пользователь может хотеть как TL;DR (быстро понять) или full reference (изучить). Это нельзя угадать без user input

### Why orthogonal, не sequential

Эта фаза не зависит от A-E. Можно делать когда удобно, эффект моментальный (промпт-level изменение).

---

## Heterogeneous pipeline (sequential, not concurrent)

### Decision (из Q16)

Не держим 2-3 модели в памяти параллельно. Используем **sequential pipeline**:

- **Small model** (4B) для extraction phase (per-chunk IR)
- **Stronger model** (14B) для final rendering pass на готовой IR (намного короче чем raw transcript)
- Минимизация reload frequency: батчим same-stage tasks
- Avoid model thrashing

### Why sequential vs parallel keep-alive (из Q16)

Concurrent keep-alive двух моделей = ~13GB RAM минимум. На consumer hardware еле помещается. Sequential = используем full memory для одной модели за раз, reload между стадиями (30-60 сек overhead × несколько раз за обработку = приемлемо).

### Альтернативный взгляд

**"Одна хорошая 14B + правильная архитектура часто выгоднее, чем 3 mediocre"** (из Q16). Может оказаться что разделение моделей не даёт прироста — одна 14B на всех стадиях достаточно. Это эмпирический вопрос для Phase C+.

---

## Когда переходить от фазы к фазе

Не по календарю — **по сигналам**. Foundation 1 (Evaluation) даёт numeric criteria:

- **Foundation 1 готов?** → numeric report по текущему pipeline есть. Известен baseline для регрессии
- **Foundation 2 готов?** → timestamps в `formatted_text`. Phase C сможет их использовать
- **Foundation 3 готов?** → benchmark side-by-side версий pipeline работает
- **Phase A готова?** → Hallucination rate, time-per-100K стабильно лучше baseline. LLM correction на <30% параграфов
- **Phase B готова?** → Section coherence (metric из Foundation 1) выросла. Chunks не режут предложения визуально
- **Phase C готова?** → Все три режима (TLDR/summary/full) собираются из одной IR. Hallucination rate ≤ baseline. Reproducibility (тот же IR → тот же output)
- **Phase D/E?** → Только если на длинных видео (>200K chars) есть видимый drift на C-результате
- **Phase F?** → Когда A/B/C даёт стабильный quality, и нужно адаптировать по типу

Между фазами — реальное использование на разных видео. Если pipeline хорошо обслуживает 80% — выгода от следующей фазы под вопросом.

---

## Что НЕ делаем (явно)

- ❌ Не пишем сразу всю архитектуру. Поэтапно
- ❌ Не выкидываем существующий map-reduce / full-extract — работает пока новый не превосходит по метрикам
- ❌ Не вводим cloud-зависимости (RAG через cloud API, embeddings через OpenAI)
- ❌ Не превращаем в production-сервис. Research-проект для себя
- ❌ Не оптимизируем под GPU > 24GB VRAM. Только consumer-железо
- ❌ Не делаем ML classifier для content type (Q15) — heuristic + user override
- ❌ Не делаем GBNF для JSON enforcement (Q3) — pydantic + retry
- ❌ Не держим 2+ модели concurrent в памяти (Q16) — sequential

---

## Связанные документы

- [big-text-problem-statement.md](big-text-problem-statement.md) — формулировка проблемы
- [big-text-problem-solution-discussion.md](big-text-problem-solution-discussion%20.md) — обсуждение принципов решения + Q&A (source of this roadmap)
- [../guides/USER_GUIDE.md](../guides/USER_GUIDE.md) — текущие режимы обработки
- [../../CLAUDE.md](../../CLAUDE.md) — техническая архитектура
- [../delivery/backlog/BACKLOG.md](../delivery/backlog/BACKLOG.md) — существующие эпики
