# kremle-detect v2.6.0

Python-библиотека, которая показывает капчу с вопросами ЕГЭ пользователям Яндекс Браузера,
Яндекс-ботам и переходам с Яндекса. Flask, Django, FastAPI + голое ядро для любого фреймворка.

---

## Структура

```
KremleXYZ-Detect/
├── kremle_detect/                   Python-пакет
│   ├── __init__.py                  Публичный API, __version__ = '2.6.0'
│   ├── detector.py                  Детекция (UA, боты, referer, Client Hints)
│   ├── captcha.py                   Ядро: CaptchaEngine, Challenge, лимиты, callbacks
│   ├── storage.py                   MemoryStorage, RedisStorage, EventLog
│   ├── ip.py                        Резолвинг IP, авто/явные trusted proxies, IP/CIDR
│   ├── questions/                   Банк вопросов (60 шт.)
│   │   ├── __init__.py              get_questions(), validate_questions()
│   │   ├── math.py                  15 заданий — ЕГЭ математика
│   │   ├── physics.py               15 заданий — ЕГЭ физика
│   │   ├── russian.py               15 вопросов — русский язык
│   │   └── literature.py            15 вопросов — литература
│   ├── integrations/
│   │   ├── flask_ext.py             KremleFlask (before_request, protect, blueprint)
│   │   ├── django_ext.py            KremleDjangoMiddleware + kremle_urls()
│   │   └── fastapi_ext.py           KremleFastAPI (middleware + роуты, headless)
│   ├── cli.py                       kremle-detect: диагностика, списки, логи
│   └── templates/
│       └── kremle_captcha.html      HTML капчи + JS-фингерпринт
├── kremle-react/                    React-компонент и хук (tsup, TypeScript)
├── tests/                           214 тестов
│   ├── test_detector.py             Детекция UA/referer/hints
│   ├── test_captcha.py              Challenge, engine, storage, callbacks
│   ├── test_engine_security.py      Валидация настроек, одноразовые токены, лимиты
│   ├── test_ip.py                   client_ip, trusted proxies, IP/CIDR
│   ├── test_flask_integration.py    Гард, verify, сессия, spoof XFF
│   ├── test_django_integration.py   Middleware, views, кеш движка
│   ├── test_fastapi_headless.py     Headless-режим, 403/400/429
│   ├── test_redis_storage.py        RedisStorage на фейковом клиенте
│   └── test_questions.py            Категории, валидация, формат
├── .github/workflows/ci.yml         Тесты 3.9–3.13, сборка wheel, билд React
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
│  storage.py  ──► MemoryStorage | RedisStorage                │
│  questions/  ──► get_questions(categories, count)            │
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
      │                    ├─ errors <= max_errors → pass, session["kremle_ok"]
      │                    └─ иначе → fail, счётчик, токен удалён
      ▼
 redirect / 403 JSON / {"passed": ...}
```

---

## Ключевое в 2.6

- **Доверие к IP**: XFF читается только от loopback/приватных сетей или явного
  `trusted_proxies`; один резолвер на гард и на verify.
- **Лимиты, которые не бьют по людям**: считаются только неудачные проверки,
  успех сбрасывает счётчик; отдельный лимит на выдачу челленджей.
- **Одноразовые токены**: повтор требует нового челленджа.
- **Мягкая валидация конфига**: числа проверяются на старте, `max_errors` подрезается
  под `question_count` и фактический пул вопросов (с предупреждением в лог).
- **Атомарный Redis**: `INCR` + `EXPIRE` одним Lua-скриптом.
- **Одинаковое поведение интеграций**: 400 на битый JSON, `no-store` на капче,
  429 при флуде челленджами.
- **214 тестов** и CI, который ставит все extras (раньше fastapi-тесты молча скипались),
  собирает wheel и билдит React-пакет.
