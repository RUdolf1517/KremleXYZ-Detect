# kremle-detect v2.7.0

Python-библиотека, которая показывает капчу с вопросами ЕГЭ пользователям Яндекс Браузера,
Яндекс-ботам и переходам с Яндекса. Flask, Django, FastAPI + голое ядро для любого фреймворка.

---

## Структура

```
KremleXYZ-Detect/
├── kremle_detect/                   Python-пакет
│   ├── __init__.py                  Публичный API, __version__ = '2.7.0'
│   ├── detector.py                  Детекция (UA, боты, referer, Client Hints)
│   ├── captcha.py                   Ядро: CaptchaEngine, Challenge, лимиты, callbacks
│   ├── policy.py                    Действия сегментов (challenge/block/monitor/allow), сэмплирование
│   ├── metrics.py                   Счётчики, snapshot(), prometheus(), health_payload()
│   ├── session.py                   TTL «капча пройдена», привязка к IP/UA
│   ├── storage.py                   MemoryStorage, RedisStorage, EventLog
│   ├── storage_async.py             AsyncRedisStorage, AsyncStorageAdapter (threadpool)
│   ├── ip.py                        Резолвинг IP, авто/явные trusted proxies, IP/CIDR
│   ├── questions/                   Банк вопросов
│   │   ├── __init__.py              get_questions(source=..., allow_images=...)
│   │   ├── sdamgia.py               Клиент «Решу ЕГЭ»: API, HTML-парсер, кеш, sync
│   │   ├── math.py                  15 заданий — ЕГЭ математика
│   │   ├── physics.py               15 заданий — ЕГЭ физика
│   │   ├── russian.py               15 вопросов — русский язык
│   │   └── literature.py            15 вопросов — литература
│   ├── integrations/
│   │   ├── _common.py               JSON-гард: wants_json, challenge_payload, no-store
│   │   ├── flask_ext.py             KremleFlask (before_request, protect, blueprint)
│   │   ├── django_ext.py            KremleDjangoMiddleware + kremle_urls()
│   │   └── fastapi_ext.py           KremleFastAPI (middleware + роуты, headless)
│   ├── cli.py                       kremle-detect: диагностика, списки, логи, serve
│   ├── demo.py                      Демо-приложение (FastAPI + /stats)
│   └── templates/
│       └── kremle_captcha.html      HTML капчи + JS-фингерпринт
├── kremle-react/                    React-компонент и хук (tsup, TypeScript)
├── tests/                           499 тестов
│   ├── test_detector.py             Детекция UA/referer/hints
│   ├── test_captcha.py              Challenge, engine, storage, callbacks
│   ├── test_engine_security.py      Валидация настроек, одноразовые токены, лимиты
│   ├── test_ip.py                   client_ip, trusted proxies, IP/CIDR
│   ├── test_flask_integration.py    Гард, verify, сессия, spoof XFF
│   ├── test_django_integration.py   Middleware, views, кеш движка
│   ├── test_fastapi_headless.py     Headless-режим, 403/400/429
│   ├── test_redis_storage.py        RedisStorage на фейковом клиенте
│   ├── test_questions.py            Категории, валидация, формат
│   ├── test_policy.py               Сегменты, monitor, sample_rate
│   ├── test_metrics.py              Счётчики, Prometheus, health
│   ├── test_session.py              TTL «пройдено», привязка к IP/UA
│   ├── test_sdamgia.py              Парсер заданий, дистракторы, кеш, sources
│   ├── test_flask_ops.py            JSON-гард, ops-роуты, logout (Flask)
│   ├── test_fastapi_ops.py          То же для FastAPI
│   ├── test_django_ops.py           Паритет Django
│   ├── test_storage_async.py        AsyncRedisStorage на фейковом клиенте
│   ├── test_cli_questions.py        show / sync / cache
│   ├── test_common.py               Accept, JSON-payload, no-store
│   ├── test_cli.py                  Диагностика, списки, логи, serve
│   ├── test_demo.py                 Демо-страницы и полный цикл
│   ├── test_e2e.py                  Живой HTTP-сервер (uvicorn), куки, logout
│   └── test_redis_live.py           Redis/Lua/TTL на настоящем сервере (маркер redis)
├── .github/workflows/
│   ├── ci.yml                       Тесты 3.9–3.13 + Redis, покрытие, wheel, React, audit
│   ├── release.yml                  Публикация по тегу: PyPI (OIDC), npm (provenance), Release
│   └── sdamgia-live.yml             Ежедневная проверка живого «Решу ЕГЭ»
├── scripts/loadtest.py              Нагрузочный смоук (rps, p50/p95)
├── Dockerfile                       Демо-образ
├── docker-compose.yml               Демо + профиль Redis
├── SECURITY.md                      Политика раскрытия и модель угроз
├── NOTICE.md                        Атрибуция заданий «Решу ЕГЭ»
├── pyproject.toml
├── CHANGELOG.md
├── README.md
├── LICENSE                          MIT
└── STRUCTURE.md                     Этот файл
```

---

## Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                    kremle_detect (ядро)                       │
│                                                              │
│  detector.py ──► detect(headers) → DetectResult              │
│  ip.py       ──► client_ip(peer, xff, trusted_proxies)       │
│  captcha.py  ──► CaptchaEngine → Challenge                   │
│                  ├─ одноразовые токены (TTL 15 мин)           │
│                  ├─ rate limit по неудачным попыткам          │
│                  ├─ лимит выдачи челленджей                   │
│                  ├─ callbacks (on_detect/on_pass/on_fail)     │
│                  └─ logging ('kremle')                        │
│  policy.py   ──► decide(hits) → challenge|block|monitor|allow │
│  session.py  ──► «пройдено» с TTL, привязкой к IP/UA          │
│  metrics.py  ──► счётчики → /stats, /metrics, /health         │
│  storage.py  ──► MemoryStorage | RedisStorage                │
│  storage_async.py ──► AsyncRedisStorage | AsyncStorageAdapter│
│  questions/  ──► get_questions(source=auto|builtin|sdamgia)   │
│                  └─ sdamgia.py: кеш «Решу ЕГЭ» + атрибуция    │
└──────┬──────────────────┬──────────────────┬─────────────────┘
       │                  │                  │
  flask_ext          django_ext         fastapi_ext
  KremleFlask        Middleware          KremleFastAPI
  + protect()        + kremle_urls()     + headless
  + IP whitelist     + IP whitelist      + IP whitelist
  + custom template  + custom template   + custom template
       └──────────────────┴──────────────────┘
                          │
                  kremle-react (SPA)
```

---

## Поток проверки

```
Яндекс-пользователь
      │
      ▼
 before_request / middleware ──нет сигналов──► контент
      │ есть сигнал
      ▼
 GET /kremle/challenge ──► engine.create_challenge()
      │                    ├─ выбор вопросов
      │                    ├─ перемешивание вариантов (SystemRandom)
      │                    └─ storage.set(challenge:token, TTL)
      ▼
 HTML/JSON без правильных ответов
      │
      ▼
 POST /kremle/verify ──► blacklist? rate_limit? token жив?
      │                    ├─ errors <= max_errors → pass, session["kremle_ok"]={ok,exp,ip,ua}
      │                    └─ иначе → fail, счётчик, токен удалён
      ▼
 redirect / 403 JSON / {"passed": ...}
      │
      ▼
 GET /kremle/status → {verified, expires_in}   POST /kremle/logout → перепройти
```

---

## Ключевое в 2.7

- **Monitor-режим и сегменты**: у каждого сигнала своё действие
  (`challenge`/`block`/`monitor`/`allow`), `sample_rate` переводит часть капчи
  в shadow. По умолчанию — `challenge` для всех, как раньше.
- **JSON-гард**: `fetch`/XHR/SPA получают `403 {"error": "captcha_required"}`,
  а не HTML-страницу. `headless` — весь сайт как API.
- **«Пройдено» с TTL**: `verified_ttl`, опциональная привязка к IP/UA, `/kremle/logout`,
  старый флаг `True` считается просроченным.
- **Живые вопросы**: `questions_source='auto'` — кеш заданий «Решу ЕГЭ» с атрибуцией,
  fallback на встроенный банк; `kremle-detect questions sync` обновляет кеш.
- **Эксплуатация**: `/kremle/health`, `/kremle/stats`, `/kremle/metrics` (Prometheus).
- **Async**: `AsyncRedisStorage`, `AsyncStorageAdapter`, threadpool в FastAPI.
- **499 Python-тестов + 24 React** и CI, который собирает wheel и React-пакет.
