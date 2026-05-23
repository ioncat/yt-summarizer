# SaaS Transition Plan — YT Summarizer

Документ отслеживает эволюцию от локального инструмента к публичному SaaS-сервису:
анализ конкурентов, gap-анализ, технические и продуктовые задачи.

> **Статус**: ранняя стадия исследования. Решение о публичном запуске не принято.

---

## 1. Конкурентный анализ

### 1.1 youtube-transcript.io

**URL**: https://www.youtube-transcript.io/

**Позиционирование**: извлечение и обработка субтитров YouTube.

**UX / Processing flow** (скриншот, май 2026):
- Пошаговый прогресс с чекбоксами: Booting crawler → Processing result → Extracting transcripts → Processing transcripts
- Тёмный UI, минималистичный дизайн
- Ощущение "живого процесса" — пользователь видит что происходит

**Наблюдения (processing screen)**:
- Используют собственный crawler (не yt-dlp напрямую)
- Pipeline визуализирован как checklist, не как spinner — снижает anxiety ожидания
- Нет упоминания AI cleanup или summarization на первом экране — вероятно, платные фичи

**Result screen — layout** (скриншот, май 2026):
3-колоночный layout:
- **Левая колонка**: превью видео (thumbnail + YouTube embed), название, канал, длительность (20m52s raw, 27m58s processed?), Channel ID / Video ID, счётчик Free Credits (0 of 25 used, resets in 9 days)
- **Центральная колонка**: транскрипт с таймстемпами, главы (Chapter headings, напр. "Introduction"), поиск по транскрипту, Copy Transcript (главная CTA), Download, Language badge, Word Count + Character count, Filter Profanity toggle, Autoscroll toggle
- **Правая колонка — Insights**: AI-summary с буллетами, Topics tags (fitness, bodybuilding, nutrition, science), Actions panel

**Actions (правая колонка)**:
- 💬 Chat with the transcript (free Beta)
- Key Quotes
- Q&A
- Flash Cards

**Pricing model**:
- Credit-based: 25 бесплатных кредитов, сброс каждые 9 дней
- Upgrade → (платные планы)
- "Automate with our API" — API доступ как отдельный оффер (кнопка в header)
- Bulk → (вероятно пакетная обработка)

**Сравнение с нами**:

| Фича | youtube-transcript.io | YT Summarizer |
|------|----------------------|---------------|
| Транскрипт с таймстемпами | ✅ кликабельные | ✅ без таймстемпов в UI |
| Главы | ✅ | ✅ (из yt-dlp метаданных) |
| Поиск по тексту | ✅ | ✗ |
| AI Summary (Insights) | ✅ буллеты + темы | ✅ более детальный (map-reduce) |
| Chat с контентом | ✅ Beta | ✅ |
| Key Quotes | ✅ | ✗ |
| Q&A | ✅ | ✗ частично через Chat |
| Flash Cards | ✅ | ✗ |
| Filter Profanity | ✅ | ✗ |
| API | ✅ | ✗ |
| Bulk processing | ✅ | ✗ |
| Free tier | 25 кредитов/мес | локально, без лимитов |
| Benchmark моделей | ✗ | ✅ уникально |
| AI Cleanup (paragraph-level) | ✗ | ✅ уникально |

**Ключевые выводы**:
- Их сильная сторона: **образовательные инструменты** (Flash Cards, Q&A, Key Quotes) — ориентация на студентов
- Наша сильная сторона: **качество обработки текста** (cleanup, map-reduce, full-extract, benchmark)
- Gap с нашей стороны: поиск по транскрипту, образовательные фичи, API, bulk

**Что нужно изучить дополнительно**:
- [ ] Реальное качество их AI Summary vs наш map-reduce
- [ ] Pricing: стоимость 1 кредита, что входит в paid план
- [ ] Ограничения по длине видео на free tier

---

### 1.2 [Placeholder — следующий конкурент]

> Добавить после следующей серии скриншотов.

---

## 2. Gap-анализ: мы vs конкуренты

| Фича | YT Summarizer (сейчас) | Конкуренты |
|------|------------------------|------------|
| Извлечение субтитров | ✅ yt-dlp, мультиязык, авто-detect | ✅ |
| AI Cleanup | ✅ Ollama (local) | ❓ |
| AI Summary (single/map-reduce/full-extract) | ✅ | ❓ редко |
| Chat с видео | ✅ | ❓ редко |
| Benchmark моделей | ✅ | ✗ |
| История | ✅ | ✅ |
| Публичный доступ | ✗ локально | ✅ |
| Авторизация / multi-user | ✗ | ✅ |
| Облачный LLM (OpenAI / Anthropic) | ✗ только Ollama | вероятно ✅ |
| API | ✗ | ❓ |
| Экспорт (PDF, DOCX) | ✗ | ❓ |

---

## 3. Что нужно изменить для публичного SaaS

### 3.1 Обязательно (блокеры)

- **Авторизация**: user accounts, сессии, изоляция данных
- **Мультитенантность**: каждый юзер видит только свои видео
- **Облачный LLM**: Ollama — локальный инструмент, не масштабируется. Нужна интеграция с OpenAI / Anthropic / Groq
- **Инфраструктура**: Docker → managed hosting (Railway, Fly.io, AWS), managed PostgreSQL вместо SQLite
- **Rate limiting + очереди**: защита от злоупотреблений, фоновые воркеры (Celery / ARQ)
- **Cookies проблема**: yt-dlp требует YouTube cookies для обхода 429 — в multi-user среде это нетривиально

### 3.2 Важно для продукта

- **Pricing / free tier**: лимиты по видео в день/месяц
- **Billing**: Stripe интеграция
- **LLM cost tracking**: считать токены per user для биллинга
- **Мониторинг и логирование**: Sentry, метрики

### 3.3 Желательно

- **API для разработчиков**: REST + API keys
- **Экспорт**: PDF, DOCX, Markdown download
- **Webhook**: notify when summary is ready
- **Публичные/шаренные ссылки на результат**

---

## 4. Позиционирование (будущее)

Текущий README: "watch or skip" — фильтр контента.

По мере реализации XL-текстов (Epic 18), STT fallback (Phase 3) и облачного LLM — позиционирование смещается:

> **YT Summarizer → инструмент глубокого извлечения знаний из видео.**
> Не просто "смотреть или пропустить", а: конспект лекции, база знаний из курса,
> поиск по большим видео, Q&A с контентом.

Целевая аудитория расширяется: исследователи, студенты, журналисты, продакты.

---

## 5. Следующие шаги исследования

- [ ] Пройти полный flow youtube-transcript.io (бесплатно и платно)
- [ ] Изучить ещё 2–3 конкурента (screenpipe, kome.ai, tactiq?)
- [ ] Оценить стоимость облачного LLM на типичном use case (10 мин видео)
- [ ] Proof-of-concept: заменить Ollama на Anthropic API в text_cleaner / text_summarizer
