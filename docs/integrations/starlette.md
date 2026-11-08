# Starlette

> «Лёгкий каркас — не значит беззащитный: замок вешают на дверь, а не на дом.»

```bash
pip install "kremle-detect[starlette]"
```

Starlette — основа FastAPI, но живёт и сама по себе. Интеграция — ASGI-middleware
плюс готовые роуты капчи; протокол, заголовки и поведение те же, что у
[FastAPI](fastapi.md).

## Минимум

```python
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from kremle_detect.integrations.asgi_ext import KremleStarlette

async def index(request):
    return PlainTextResponse('привет')

app = Starlette(routes=[Route('/', index)])

kremle = KremleStarlette(
    app,
    secret='свой-длинный-ключ',
    categories=['math', 'physics', 'russian', 'literature'],
    question_count=15,
    max_errors=3,
)
```

`SessionMiddleware` добавляется автоматически, если её ещё нет: без сессии
«капча пройдена» нечем запомнить. Если у вас своя — интеграция её не трогает.

## Что появляется в приложении

| Путь | Что делает |
|---|---|
| `GET /kremle/challenge` | HTML-капча или JSON (по `Accept`) |
| `POST /kremle/verify` | проверка ответов |
| `GET /kremle/status` | `{verified, expires_in}` |
| `POST /kremle/logout` | сбросить прохождение |
| `GET /kremle/widget/<name>` | виджет без React |
| `GET /kremle/img/<key>` | рисунок задания из кеша |
| `GET /kremle/health` / `stats` / `metrics` | эксплуатация (`enable_ops_routes=False` — выключить) |

Полный список и коды ошибок — [API](../api.md).

## Настройки

Аргументы конструктора — те же, что у Flask/FastAPI-интеграций:

```python
KremleStarlette(
    app,
    skip_paths=['/healthz', '/webhooks/'],
    whitelist=['10.0.0.0/8'],
    trusted_proxies=['127.0.0.1'],
    policy={'yandex_bot': 'block', 'yandex_browser': 'monitor'},
    json_api=True,              # fetch/SPA получают 403 в JSON
    headless=False,             # True — весь сайт API
    csp_policy=None,            # своя CSP для роутов капчи
    mixed_ratio=0.5,            # своё + «Решу ЕГЭ» (questions_source='own+sdamgia')
    sticky_referrer=True,       # долг капчи живёт в сессии, а не в одном запросе
    sticky_ttl=900,             # сколько секунд помнить долг
    adaptive=True,              # ужесточение после серии провалов
    overlay=False,              # True — капча окном поверх страницы
)
```

`overlay=True` пропускает переход по ссылке (оболочка сайта), но не `fetch` и не
API — подробности в разделе [Капча поверх страницы](../overlay.md).

## Проверка в тестах

```python
from starlette.testclient import TestClient

client = TestClient(app, follow_redirects=False)
assert client.get('/', headers={'User-Agent': 'Mozilla/5.0 Chrome/120'}).status_code == 200
assert client.get('/', headers={'User-Agent': 'Mozilla/5.0 YaBrowser/24.1'}).status_code == 302
assert client.get('/kremle/challenge').headers['x-frame-options'] == 'DENY'
```

## Starlette в проде

- держите `SessionMiddleware` с `https_only=True` и `same_site='lax'` на своей
  стороне, если ставите её сами;
- за обратным прокси передайте `trusted_proxies` — иначе `X-Forwarded-For`
  игнорируется (и это правильно: подделывать IP снаружи нельзя);
- несколько воркеров — только с Redis (`storage=RedisStorage(...)`).

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
