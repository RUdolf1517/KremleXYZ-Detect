# kremle-detect v2.0

Python-библиотека для защиты сайта от пользователей Яндекс Браузера и переходов с Яндекса.
Капча с вопросами ЕГЭ. Поддержка Flask, Django, FastAPI + голое ядро для любого фреймворка.

---

## Структура

```
KremleXYZ-Detect/
├── kremle_detect/                   Python-пакет
│   ├── __init__.py                  Публичный API: detect, CaptchaEngine, ...
│   ├── detector.py                  Детекция Яндекса (UA, боты, referer, Client Hints)
│   ├── captcha.py                   Ядро капчи: Challenge, CaptchaEngine
│   ├── questions/                   Банк вопросов по категориям
│   │   ├── __init__.py              get_questions(), CATEGORIES
│   │   ├── math.py                  15 заданий — ЕГЭ профильная математика
│   │   ├── physics.py               15 заданий — ЕГЭ физика
│   │   ├── russian.py               15 вопросов — русский язык
│   │   └── literature.py            15 вопросов — литература
│   ├── integrations/                Интеграции с фреймворками
│   │   ├── __init__.py
│   │   ├── flask_ext.py             KremleFlask — расширение для Flask
│   │   ├── django_ext.py            KremleDjangoMiddleware + kremle_urls()
│   │   └── fastapi_ext.py           KremleFastAPI — для FastAPI/Starlette
│   └── templates/
│       └── kremle_captcha.html      HTML-страница капчи (универсальная)
├── pyproject.toml                   Конфигурация пакета (setuptools)
├── README.md                        Документация
├── LICENSE                          MIT
├── STRUCTURE.md                     Этот файл
└── .gitignore
```

---

## Архитектура

```
┌─────────────────────────────────────────────────┐
│              kremle_detect (ядро)                │
│                                                  │
│  detector.py ──► detect(headers) → DetectResult  │
│  captcha.py  ──► CaptchaEngine → Challenge       │
│  questions/  ──► get_questions(categories, count) │
└────────┬──────────────┬──────────────┬───────────┘
         │              │              │
    flask_ext      django_ext     fastapi_ext
    KremleFlask    Middleware      KremleFastAPI
```

Ядро **не зависит** от фреймворков. Интеграции — тонкие обёртки,
которые подключают детекцию и капчу к конкретному фреймворку.

---

## Детекция (detector.py)

Сигналы:
- **User-Agent**: YaBrowser, YaApp_Android/iOS, YandexSearch, YandexStation
- **Яндекс-боты**: YandexBot, YandexMetrika, YandexImages, YandexDirect и 20+ других
- **Referer**: yandex.{ru,com,by,kz,...}, ya.ru, dzen.ru, zen.yandex.*, market.yandex.*
- **Client Hints**: Sec-CH-UA / Sec-CH-UA-Full-Version-List с YaBrowser/Yandex

Результат — `DetectResult` с полями `browser`, `bot`, `referrer`, `client_hints` и свойством `reason`.

---

## Капча (captcha.py)

- `CaptchaEngine(categories, question_count, max_errors, secret)` — главный класс
- `create_challenge()` → `Challenge` — набор вопросов с HMAC-токеном
- `verify(token, answers)` → `{passed, errors, total}`
- Токены живут 1 час, одноразовые (удаляются после успешной верификации)

---

## Категории вопросов

| Ключ         | Файл            | Содержание                          |
|-------------|-----------------|-------------------------------------|
| `math`       | math.py          | ЕГЭ профиль: производные, логарифмы, тригонометрия |
| `physics`    | physics.py       | ЕГЭ: законы Ньютона, термодинамика, оптика |
| `russian`    | russian.py       | Ударения, орфография, «н/нн», предлоги |
| `literature` | literature.py    | Авторы, произведения, стих. размеры, литер. приёмы |
