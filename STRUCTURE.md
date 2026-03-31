# kremle-detect v2.1

Python-библиотека для защиты сайта от пользователей Яндекс Браузера и переходов с Яндекса.
Капча с вопросами ЕГЭ. Поддержка Flask, Django, FastAPI + голое ядро для любого фреймворка.

---

## Структура

```
KremleXYZ-Detect/
├── kremle_detect/                   Python-пакет
│   ├── __init__.py                  Публичный API
│   ├── detector.py                  Детекция (UA, боты, referer, Client Hints)
│   ├── captcha.py                   Ядро: CaptchaEngine, Challenge, rate limiting, callbacks
│   ├── storage.py                   Бэкенды хранения: MemoryStorage, RedisStorage
│   ├── questions/                   Банк вопросов (60 шт.)
│   │   ├── __init__.py              get_questions(), validate_questions()
│   │   ├── math.py                  15 заданий — ЕГЭ математика
│   │   ├── physics.py               15 заданий — ЕГЭ физика
│   │   ├── russian.py               15 вопросов — русский язык
│   │   └── literature.py            15 вопросов — литература
│   ├── integrations/                Интеграции с фреймворками
│   │   ├── __init__.py
│   │   ├── flask_ext.py             KremleFlask (whitelist, шаблон, callbacks)
│   │   ├── django_ext.py            KremleDjangoMiddleware + kremle_urls()
│   │   └── fastapi_ext.py           KremleFastAPI
│   └── templates/
│       └── kremle_captcha.html      HTML капчи + JS fingerprint
├── tests/                           78 тестов (pytest)
│   ├── test_detector.py             Детекция UA/referer/hints
│   ├── test_captcha.py              Engine, rate limit, callbacks, storage
│   └── test_questions.py            Категории, валидация, формат
├── pyproject.toml
├── README.md
├── LICENSE                          MIT
├── STRUCTURE.md                     Этот файл
└── .gitignore
```

---

## Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                    kremle_detect (ядро)                       │
│                                                              │
│  detector.py ──► detect(headers) → DetectResult              │
│  captcha.py  ──► CaptchaEngine → Challenge                   │
│                  ├─ rate limiting (по IP)                     │
│                  ├─ callbacks (on_detect/on_pass/on_fail)     │
│                  └─ logging (kremle logger)                   │
│  storage.py  ──► MemoryStorage | RedisStorage                │
│  questions/  ──► get_questions(categories, count)            │
└──────┬──────────────────┬──────────────────┬─────────────────┘
       │                  │                  │
  flask_ext          django_ext         fastapi_ext
  KremleFlask        Middleware          KremleFastAPI
  + IP whitelist     + IP whitelist      + IP whitelist
  + custom template  + custom template   + custom template
```

---

## Ключевые фичи v2.1

- **Redis**: `RedisStorage(url='redis://...')` — для production с несколькими воркерами
- **Rate limiting**: макс. N попыток /verify с одного IP за M секунд
- **IP whitelist**: список IP/CIDR, которые пропускаются без проверки
- **Callbacks**: `on_detect`, `on_pass`, `on_fail` — хуки на события
- **Логирование**: `logging.getLogger('kremle')` — все события
- **JS fingerprint**: клиентская детекция через `navigator.userAgentData`, `window.yandex`
- **Кастомный шаблон**: `template='/path/to/my.html'`
- **Свои вопросы**: `extra_questions=[...]`, `only_extra=True`
- **78 тестов**: детекция, капча, storage, rate limit, callbacks, вопросы
