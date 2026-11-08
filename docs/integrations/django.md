# Django

> «Дисциплина — основа порядка. Порядок — основа государства. Middleware —
> основа дисциплины.»

## Подключение

```python
# settings.py
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',   # должен идти раньше
    # ...
    'kremle_detect.integrations.django_ext.KremleDjangoMiddleware',
]

KREMLE_CATEGORIES = ['math', 'physics', 'russian', 'literature']
KREMLE_QUESTION_COUNT = 15
KREMLE_MAX_ERRORS = 3
```

```python
# urls.py
from django.urls import path
from kremle_detect.integrations.django_ext import kremle_urls

urlpatterns = [
    path('kremle/', kremle_urls()),
    # ...
]
```

Без `SessionMiddleware` middleware падает с `ImproperlyConfigured` и подсказкой,
что именно добавить, — не с загадочным `AttributeError` на середине запроса.

Django — это про порядок: всё в настройках, всё на своих местах. Настройки с
префиксом `KREMLE_` лежат в `settings.py`, как и положено, а не разбросаны по
переменным окружения и чужим конфигам.

## Настройки

Все параметры — с префиксом `KREMLE_`, имя в точности повторяет аргумент
`CaptchaEngine`:

| Настройка | По умолчанию | Что делает |
|---|---|---|
| `KREMLE_CATEGORIES` | все четыре | категории встроенных вопросов |
| `KREMLE_QUESTION_COUNT` | `15` | вопросов в челлендже |
| `KREMLE_MAX_ERRORS` | `3` | допустимое число ошибок |
| `KREMLE_SECRET` | `SECRET_KEY` | ключ HMAC для токенов |
| `KREMLE_STORAGE` | `MemoryStorage` | объект хранилища или `None` |
| `KREMLE_RATE_LIMIT` | `10` | неудачных проверок с IP за окно |
| `KREMLE_RATE_WINDOW` | `600` | окно лимита, секунды |
| `KREMLE_CHALLENGE_RATE_LIMIT` | `60` | выдач челленджа с IP за окно |
| `KREMLE_TRUSTED_PROXIES` | авто | кому верить в `X-Forwarded-For` |
| `KREMLE_POLICY` | `None` | действия по сегментам |
| `KREMLE_SAMPLE_RATE` | `1.0` | доля трафика под фильтром |
| `KREMLE_METRICS_ENABLED` | `True` | вести счётчики |
| `KREMLE_VERIFIED_TTL` | `86400` | сколько живёт «капча пройдена» |
| `KREMLE_BIND_IP` / `KREMLE_BIND_UA` | `False` | привязка прохождения к IP/UA |
| `KREMLE_HEADLESS` | `False` | отдавать JSON вместо HTML |
| `KREMLE_ENABLE_OPS_ROUTES` | `True` | health/stats/metrics |
| `KREMLE_EXTRA_QUESTIONS` | `None` | свои вопросы |
| `KREMLE_ONLY_EXTRA` | `False` | использовать только свои |
| `KREMLE_FAIL_THRESHOLD` | `0` | провалов до автоблокировки |
| `KREMLE_BLACKLIST_TTL` | `86400` | сколько держать в блоклисте |
| `KREMLE_SKIP_PATHS` | `['/admin/', '/static/']` | пути без фильтра |
| `KREMLE_WHITELIST` | `[]` | IP и подсети, которые проходят всегда |
| `KREMLE_QUESTIONS_SOURCE` | `'auto'` | откуда брать вопросы |
| `KREMLE_QUESTIONS_IMAGES` | `False` | показывать задания с рисунком |
| `KREMLE_IMAGES_CACHE_DIR` / `KREMLE_IMAGES_PREFIX` | `~/.cache/kremle-detect/images` / `/kremle/img/` | кеш картинок и префикс URL |
| `KREMLE_CSP_POLICY` | `None` | своя CSP для роутов капчи (`''` — не отправлять) |
| `KREMLE_STICKY_REFERRER` | `True` | держать «долг капчи» в сессии, а не только в первом запросе |
| `KREMLE_STICKY_TTL` | `900` | сколько секунд живёт долг капчи |
| `KREMLE_ADAPTIVE` | `True` | ужесточать капчу после серии провалов |
| `KREMLE_ADAPTIVE_THRESHOLD` | `3` | провалов подряд до первой ступени |
| `KREMLE_ADAPTIVE_EXTRA_QUESTIONS` | `2` | сколько вопросов добавляет ступень |

`KREMLE_SECRET` понимает список: `KREMLE_SECRET = ['новый-ключ', 'старый-ключ']` —
первый подписывает, все проверяют, поэтому смена ключа не обрывает капчи,
выданные до неё. Дефолтный ключ (и `SECRET_KEY`, взятый как секрет) пишет
WARNING в лог.

На роутах капчи всегда уходят `X-Frame-Options: DENY`, `X-Content-Type-Options:
nosniff` и `Referrer-Policy: no-referrer`; CSP настраивается `KREMLE_CSP_POLICY`
(подробности — [Безопасность: CSP](../security.md#csp-как-ужесточить-и-что-сломается)).

Переменные окружения Django читает сам, отдельный парсер библиотека не
подсовывает: если нужен `django-environ` — используйте его.

## Redis

```python
# settings.py
from kremle_detect import RedisStorage

KREMLE_STORAGE = RedisStorage(url='redis://localhost:6379/0', prefix='kremle:')
```

Несколько воркеров без Redis — это несколько независимых лимитов и сессий:
капча будет «забывать» прохождение при каждом попадании на другой воркер.

## Тесты

```python
# settings_test.py
KREMLE_ENABLE_OPS_ROUTES = False

@pytest.fixture(autouse=True)
def _no_captcha(settings):
    settings.KREMLE_WHITELIST = ['127.0.0.1']
```

Или подменяйте `User-Agent` в клиенте на обычный Chrome — тогда детекция
ничего не находит и капча не показывается.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
