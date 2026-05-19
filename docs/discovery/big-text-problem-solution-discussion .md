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

**Answer:**

---

## Phase F + cross-cutting

### Q15. Content classifier — обучающие данные

Few-shot prompt без обучения vs fine-tune классификатор? "Lecture vs interview" — субъективно, кто размечает? Возможно проще убрать classifier, дать пользователю выбрать compression policy руками.

**Answer:**

---

### Q16. Heterogeneous pipeline — реалистично ли держать 2-3 модели?

14B + 4B = ~13GB RAM минимум для keep-alive. Switching между моделями в Ollama = unload + reload = 30-60 сек. На потребительском железе еле помещается. Возможно одна модель + разные промпты.

**Answer:**
