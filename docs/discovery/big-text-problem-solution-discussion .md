Проблема у тебя на самом деле не “summarization”, а constrained hierarchical document reconstruction. И главная сложность — не качество одной генерации, а сохранение глобальной когерентности при локальной обработке. 

Сейчас почти все локальные пайплайны ломаются в трёх местах:

1. chunking режет смысл,
2. iterative summarization накапливает semantic drift,
3. LLM не умеет держать глобальную структуру документа.

Поэтому я бы вообще перестал мыслить это как “нарезать → суммаризировать → склеить”. Это почти всегда деградирует на длинных видео.

Вместо этого лучше идти в сторону multi-pass semantic reconstruction.

Базовая архитектура, которая реально может работать локально:

1. Pre-cleaning layer.
   Не пускать сырую VTT в main LLM.

Сначала дешёвый preprocessing:

* восстановление пунктуации,
* removal fillers,
* sentence boundary detection,
* deduplication near-repeated phrases,
* fixing ASR garbage.

Это можно делать:

* маленькой моделью,
* regex + heuristics,
* token classifier,
* либо специализированной punctuation restoration model.

Даже хороший summarizer сильно деградирует на ASR-мусоре.

2. Semantic segmentation вместо fixed chunking.
   Это ключевой момент.

Нельзя резать:

* по токенам,
* по времени,
* по N символов.

Нужно строить semantic boundaries:

* embeddings окон,
* cosine shift detection,
* topic change detection.

То есть:

* sliding windows,
* embeddings,
* ищешь semantic discontinuities,
* режешь только там.

Иначе ты постоянно убиваешь связность мысли.

Очень хорошо работает:

* sentence-transformers,
* jina embeddings,
* bge-small/base,
* e5-small.

Даже локально.

3. Hierarchical memory.
   Тебе нужен не “summary previous chunks”, а document state.

Например:

* glossary,
* entities,
* unresolved threads,
* active topics,
* timeline,
* claims ledger.

После каждого chunk обновляется state.

Следующий chunk обрабатывается НЕ с полным предыдущим summary, а с компактным state object.

Это резко снижает drift.

Типичная ошибка:
“summary of summaries”.

Правильнее:
“incremental knowledge graph”.

4. Separate extraction from writing.
   Это очень важный architectural split.

Сейчас большинство систем делают:
transcript → beautiful prose.

Но лучше:
transcript → atomic facts → structured representation → prose rendering.

То есть:
этап 1:

* facts,
* claims,
* examples,
* quotes,
* terminology,
* hierarchy.

этап 2:
из structured representation рендеришь:

* TLDR,
* study guide,
* full reference,
* article.

Тогда у тебя появляется:

* controllable compression,
* anti-hallucination,
* reproducibility.

И главное — один ingestion pipeline для всех режимов.

5. Retrieval during generation.
   На длинных документах нельзя полагаться только на context window.

Нужен local RAG even for one document.

Во время генерации секции:

* модель должна иметь доступ к:

  * local chunk,
  * related chunks,
  * entity references,
  * glossary,
  * chapter summary.

То есть document becomes queryable memory.

Это намного стабильнее.

6. Compression should be semantic-density-aware.
   Ты сам правильно это заметил. 

Нельзя одинаково компрессить:

* лекцию,
* интервью,
* новости,
* философский разговор,
* tutorial.

Нужен classifier контента:

* educational,
* conversational,
* news/opinion,
* procedural,
* narrative.

И от него:

* target compression ratio,
* detail retention policy.

Это очень сильно поднимает perceived quality.

Теперь про локальные модели и железо.

Для такой задачи огромная модель не обязательна.
Гораздо важнее архитектура pipeline.

На практике:
хороший 7B/14B + правильный multi-pass pipeline
часто лучше,
чем тупой single-pass 70B.

Из локальных моделей я бы смотрел:

* Qwen Qwen3 14B/32B,
* Mistral AI Mistral Small,
* Gemma 3 12B/27B,
* DeepSeek distilled models.

Для extraction:
маленькие модели часто достаточно хороши.

Для final prose rendering:
лучше отдельная более сильная модель.

То есть heterogeneous pipeline.

Очень вероятно, что тебе стоит разделить:

* extraction model,
* structuring model,
* writer model.

Ещё одна важная вещь:
не пытайся сразу делать “идеальный литературный текст”.

Сначала добейся:

* factual retention,
* structure preservation,
* deterministic output.

Красивый prose — это уже последний pass.

Иначе будешь бесконечно бороться с hallucinations и drift.

Самое перспективное направление для твоего кейса, как мне кажется:
“document compiler”.

Не summarizer.

То есть:
input:
raw transcript.

Intermediate Representation:

* semantic sections,
* entities,
* claims,
* examples,
* citations to timestamps,
* topic graph.

Output:
rendered document mode.

Это уже ближе к тому, как работают компиляторы или static analyzers, а не чат-боты.

---

# Questions

Critical questions and unresolved points raised by the roadmap discussion. To be answered before / during implementation. User adds answers inline under each question.

## Blockers — нужно решить ДО Phase A

### Q1. Evaluation strategy — как измерять улучшения?

Без ground truth (правильное summary не существует) — как сравнивать качество между фазами? Текущие метрики (compression %, время) недостаточны для качества. Нужен либо набор тестовых видео с экспертной разметкой, либо автоматические proxy-метрики (entity preservation, claim retention, named-entity recall). Без evaluation каждая новая фаза = "subjective feels better". Это нужно решить ПЕРВЫМ.

**Answer:**

---

### Q2. Russian language stack viability

Punctuation restoration (`silero/punctuation`), embeddings (`multilingual-e5-small`), token classifiers для filler removal — все они работают на русском? Качество на YouTube auto-subs (разговорная речь, не news) непредсказуемо. Может потребоваться обучать модели или fallback на LLM.

**Answer:**

---

### Q3. JSON schema enforcement strategy

Phase C (IR layer) требует надёжного JSON output от LLM. Варианты: GBNF grammar в Ollama (стабильно, но не все модели хорошо работают под constraint) vs pydantic validation + retry (дороже по времени). Решение архитектурное, не откладываемое до C.

**Answer:**

---

## Общие архитектурные

### Q4. Reversibility / fallback

Если новая фаза на каком-то видео хуже текущей — есть ли откат? Параллельное хранение результатов обоих pipeline через Benchmark? Держим ли legacy-mode toggle?

**Answer:**

---

### Q5. Timestamps preservation

В VTT есть time-stamps на уровне subtitle entry. Сейчас они отбрасываются после `text_formatter`. Для IR (Phase C) нужны citations to timestamps. Решить когда и где их сохранять.

**Answer:**

---

## Phase A (pre-clean)

### Q6. Где останавливать LLM-cleanup vs non-LLM?

Если non-LLM делает 95% работы, оставшийся 5% — что? Сложные случаи (анаколуфы, переходы говорящих). Возможно non-LLM достаточно — LLM-pass вообще не нужен. Тестировать на текущих cleaned_text.

**Answer:**

---

### Q7. Punctuation restoration качество на разговорной речи

Готовые модели обучены на news/wiki. YouTube auto-subs — разговорная речь, технические термины, аббревиатуры, иностранные слова кириллицей. Риск: хуже чем текущий LLM cleanup.

**Answer:**

---

## Phase B (semantic segmentation)

### Q8. Sliding window параметры

Размер окна (3 / 5 / 10 предложений)? Шаг? Перекрытие? Параметры драматически меняют результат — нужны эксперименты.

**Answer:**

---

### Q9. Cosine shift threshold

Жёсткий порог (например 0.7) — режет слишком часто или редко? Адаптивный (percentile from distribution) vs hysteresis? Без тюнинга на реальных видео не понять.

**Answer:**

---

### Q10. Gradual vs abrupt topic transitions

Discussion предполагает резкие boundaries. В лекциях темы переходят плавно — speaker связывает мысли. Может не быть чётких границ. Что делаем тогда — синтетические boundaries по равным интервалам?

**Answer:**

---

## Phase C (IR)

### Q11. Schema fixedness

Один JSON schema для всех типов контента или per content type? Лекция и интервью требуют разных полей (claims vs quotes). Возможно schema per class.

**Answer:**

---

### Q12. Atomic facts granularity

"Phrase-level", "sentence-level" или "claim-level"? Слишком мелко — теряем контекст. Слишком крупно — теряем точность. Решается экспериментами, не теоретически.

**Answer:**

---

## Phase D-E (deferred, но влияют на C)

### Q13. Document state — schema и compaction

После 100 секций state может вырасти неуправляемо. Как сжимаем? Какие entities выбрасываем? Это часть архитектуры IR — нельзя оставить полностью на потом.

**Answer:**

---

### Q14. Vector store choice

chromadb (Python, full-featured, медленнее) vs lancedb (Rust, быстрее, новая) vs qdrant (отдельный сервис, не embedded). Решение влияет на dependencies проекта.









**Answers:**

---

## Phase F + cross-cutting

### Q15. Content classifier — обучающие данные

Few-shot prompt без обучения vs fine-tune классификатор? "Lecture vs interview" — субъективно, кто размечает? Возможно проще убрать classifier, дать пользователю выбрать compression policy руками.

**Answer:**

---

### Q16. Heterogeneous pipeline — реалистично ли держать 2-3 модели?

14B + 4B = ~13GB RAM минимум для keep-alive. Switching между моделями в Ollama = unload + reload = 30-60 сек. На потребительском железе еле помещается. Возможно одна модель + разные промпты.

**Answer:**

# Q1. Evaluation strategy — как измерять улучшения?

Нужен hybrid evaluation.

База:
- 15–30 эталонных видео разных типов (лекции, интервью, новости, tutorials)
- 3 output modes: TLDR / structured / full-reference
- human evaluation только на small benchmark set

Автоматические proxy-метрики:
- named entity recall,
- number/date preservation,
- quote preservation,
- semantic similarity,
- section coherence,
- hallucination rate через source-grounded verification.

Главное: evaluation должен быть regression-safe. Любая новая фаза прогоняется на benchmark suite автоматически.

---

# Q2. Russian language stack viability

В целом viable.

Лучше всего сейчас работают:
- multilingual-e5,
- bge-m3,
- jina embeddings.

С punctuation хуже. Русская разговорная речь + ASR garbage ломают готовые модели.

Практически:
- embeddings можно брать готовые,
- punctuation/filler cleanup — вероятно hybrid heuristics + LLM fallback,
- чисто non-LLM pipeline вряд ли даст production-quality prose.

---

# Q3. JSON schema enforcement strategy

Лучше: pydantic validation + retry + repair pass.

GBNF хорош для простых схем, но:
- ломает некоторые модели,
- ухудшает generation quality,
- плохо масштабируется на complex IR.

Практически:
1. permissive JSON generation,
2. validation,
3. auto-repair,
4. retry only failed fields.

Это стабильнее архитектурно.

---

# Q4. Reversibility / fallback

Да, нужен.

Минимум:
- legacy pipeline toggle,
- benchmark comparison mode,
- side-by-side outputs during development.

Новые фазы должны быть composable, а не destructive replacement.

---

# Q5. Timestamps preservation

Нельзя терять timestamps после preprocessing.

Правильно:
- sentence/segment inherits timestamp range,
- IR хранит source references,
- prose output optionally embeds citations.

Timestamp mapping должен жить с самого начала pipeline.

---

# Q6. Где останавливать LLM-cleanup vs non-LLM?

Non-LLM должен делать:
- normalization,
- filler cleanup,
- dedup,
- sentence splitting.

LLM нужен только для:
- ambiguous reconstruction,
- semantic repair,
- discourse cleanup.

Если LLM переписывает весь текст — слишком дорого и нестабильно.

---

# Q7. Punctuation restoration качество на разговорной речи

Готовые модели не будут consistently good на YouTube ASR.

Поэтому:
- punctuation model = first-pass draft,
- потом lightweight LLM correction.

Иначе будет:
- wrong clause boundaries,
- broken technical phrases,
- over-punctuation.

---

# Q8. Sliding window параметры

Начинать pragmatic:
- window: 5–8 sentences,
- overlap: 50%,
- step: 2–4 sentences.

Меньше — noisy segmentation.
Больше — размываются transitions.

Дальше только empirical tuning.

---

# Q9. Cosine shift threshold

Жёсткий threshold почти наверняка плохая идея.

Лучше:
- adaptive threshold,
- local distribution analysis,
- hysteresis,
- minimum section length constraints.

Topic segmentation — relative problem, не absolute.

---

# Q10. Gradual vs abrupt topic transitions

Да, многие transitions gradual.

Поэтому boundaries должны быть:
- soft,
- probabilistic,
- optionally overlapping.

Если transition неявный:
- section merge,
- либо synthetic boundary по max section size.

Иначе будут гигантские sections без структуры.

---

# Q11. Schema fixedness

Лучше:
- core universal schema,
- optional extensions per content type.

Например:
- entities,
- claims,
- examples,
- quotes,
- topics.

А дальше:
- interview-specific,
- lecture-specific,
- tutorial-specific fields.

Полностью отдельные schemas усложнят pipeline.

---

# Q12. Atomic facts granularity

Оптимально: claim-level.

Sentence-level слишком tied к transcript.
Phrase-level разрушает semantics.

Claim-level даёт:
- retrieval,
- deduplication,
- controllable compression.

---

# Q13. Document state — schema и compaction

State должен быть tiered.

Хранить:
- active entities,
- glossary,
- unresolved references,
- running topic summaries.

Compaction:
- decay by relevance,
- merge duplicates,
- summarize inactive branches.

Иначе state uncontrollably grows.

---

# Q14. Vector store choice

Для local-first проекта:
- lancedb выглядит наиболее рационально.

Причины:
- embedded,
- быстрый,
- lightweight,
- хороший fit для local pipelines.

Qdrant — overkill.
Chroma — удобный, но часто тяжёлый и медленный.

---

# Q15. Content classifier — обучающие данные

Сначала не нужен ML classifier.

Проще:
- heuristic/prompt classification,
- plus manual override by user.

User intent важнее “объективного” content type.

Fine-tuning classifier — premature optimization.

---

# Q16. Heterogeneous pipeline — реалистично ли держать 2-3 модели?

Постоянно loaded — скорее нет для consumer hardware.

Но sequential pipeline реалистичен:
- small model for extraction,
- stronger model for final rendering.

Главное:
- minimize reload frequency,
- batch same-stage tasks,
- avoid model thrashing.

На практике одна хорошая 14B + strong architecture часто выгоднее, чем 3 mediocre models.

** Additional Questions **
Оставшиеся неясности
Q1 в практике: кто курирует 15–30 эталонных видео? Это серьёзная работа (3 modes × N видео = 45+ ручных оценок). Возможно начать с 3–5 видео для proof-of-concept, потом расширять

Q12 claim-level: "claim" концептуально ясно, но операционно — как извлекать? Один LLM-pass per chunk с инструкцией "list every distinct claim"? Что считается distinct?

Q4 legacy toggle: на каком уровне? Per-video, per-stage, или pipeline-wide flag в Settings? Если per-video — Benchmark уже это даёт. Если global — нужен Settings field

Что предлагаю прямо сейчас
Обновить big-text-solution-roadmap.md — переписать с учётом ответов. Phase 0 добавить, Phase A расширить, конкретные параметры в B/C/F. Это документ
Не лезть в код пока — есть актуальные тесты текущего pipeline (full extract, parallel map) которые нужно довести
Phase 0 (evaluation) как первый практический шаг — выбрать 3–5 видео, определить proxy-метрики, написать скрипт-замеры. Это полезно даже без новых фаз — текущий pipeline тоже надо измерять

** Answers **

Q1 — да, начинать надо не с 30 видео, а с 3–5 carefully selected cases.

Причём не random:
- dense technical lecture,
- chaotic interview/podcast,
- structured tutorial,
- news/opinion,
- long-form discussion.

Цель initial benchmark:
- поймать regression,
- увидеть qualitative failures,
- валидировать proxy metrics.

И только потом scale benchmark set.

Иначе evaluation itself станет отдельным проектом.

---

Q12 — claim extraction практически почти наверняка будет LLM-pass.

Но не:
"extract every claim from huge chunk".

Лучше:
- semantic segment,
- extraction per segment,
- bounded output size.

Distinct claim = atomic verifiable semantic unit.

Пример:
"React Server Components reduce client bundle size"
— один claim.

"React is good and modern"
— opinion/noisy claim.

То есть claim должен быть:
- attributable,
- semantically independent,
- retrievable,
- compressible.

На практике extraction prompt должен быть очень constrained:
- no paraphrase,
- no synthesis,
- no merging distant ideas.

Иначе model instantly starts editorializing.

---

Q4 — legacy toggle лучше делать pipeline-wide initially.

Причины:
- проще architecture,
- проще debugging,
- reproducible benchmarks,
- меньше combinatorial explosion.

То есть:
Settings:
- Legacy pipeline
- Experimental semantic pipeline

Per-stage toggles пригодятся позже, но сейчас это premature complexity.

Benchmark mode уже покрывает side-by-side comparison.

---

И да, твой proposed order выглядит правильным.

Сейчас самое разумное:
1. Stabilize current pipeline,
2. Add measurement layer,
3. Build benchmark harness,
4. Только потом architecture experiments.

Потому что без baseline measurements Phase A/B/C невозможно объективно оценивать.

---

Я бы ещё добавил в Phase 0 одну очень важную вещь:
failure taxonomy.

Не только metrics, но и типы деградации:
- hallucination,
- dropped entities,
- broken chronology,
- duplicated ideas,
- lost section boundaries,
- incoherent transitions,
- overcompression,
- undercompression.

Это потом сильно ускорит iteration.
