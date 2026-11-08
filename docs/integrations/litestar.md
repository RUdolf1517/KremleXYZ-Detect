# Litestar

> «Один фреймворк — хорошо. Два — надёжнее: начальство любит, когда работа
> продублирована.»

```bash
pip install "kremle-detect[litestar]"
```

Litestar собирает приложение из обработчиков и middleware, поэтому интеграция
возвращает их вам, а не правит `Litestar(...)` за спиной. Протокол тот же, что у
[Starlette](starlette.md) и [FastAPI](fastapi.md).

## Минимум

```python
from litestar import Litestar, get
from litestar.stores.memory import MemoryStore

from kremle_detect.integrations.asgi_ext import KremleLitestar

@get('/')
async def index() -> dict:
    return {'ok': True}

kremle = KremleLitestar(
    secret='свой-длинный-ключ',
    categories=['math', 'physics', 'russian', 'literature'],
    question_count=15,
    max_errors=3,
)

app = Litestar(
    route_handlers=[index, *kremle.route_handlers],
    middleware=kremle.middleware,
    stores={'sessions': MemoryStore()},      # без хранилища нет сессий
)
app.state.kremle = kremle                    # необязательно: доступ к движку
```

`kremle.middleware` — список из двух элементов: guard (блокирует) и
`ServerSideSessionConfig().middleware` (помнит прохождение). Порядок менять
нельзя: guard опирается на сессию.

`stores` обязателен, иначе Litestar падает на старте. В проде вместо
`MemoryStore` — `RedisStore`:

```python
from litestar.stores.redis import RedisStore
from redis.asyncio import Redis

stores={'sessions': RedisStore(redis=Redis.from_url('redis://localhost:6379/0'))}
```

Несколько воркеров без общего хранилища = капча проходится заново на каждом.

## Уже собранное приложение

```python
kremle.init_app(app)      # init=False — роуты Litestar добавит и сам
```

Имя `init_app` знакомо тем, кто подключал Flask-расширения; никакой магии —
просто дописывает те же обработчики в приложение.

## Что появляется в приложении

| Путь | Что делает |
|---|---|
| `GET /kremle/challenge` | HTML-капча или JSON (по `Accept`) |
| `POST /kremle/verify` | проверка ответов |
| `GET /kremle/status` | `{verified, expires_in}` |
| `POST /kremle/logout` | сбросить прохождение |
| `GET /kremle/widget/<name>` | виджет без React |
| `GET /kremle/img/<key>` | рисунок задания из кеша |
| `GET /kremle/health` / `stats` / `metrics` | эксплуатация |

Полный список и коды ошибок — [API](../api.md).

## Настройки

Те же, что у остальных интеграций: `skip_paths`, `whitelist`,
`trusted_proxies`, `policy`, `json_api`, `headless`, `csp_policy`,
`mixed_ratio`, `enable_ops_routes`, `storage`, `sticky_referrer`, `sticky_ttl`,
`adaptive`, `adaptive_threshold`, `adaptive_extra_questions`.

Middleware идут в порядке «сессии → guard»: guard читает `scope['session']`,
поэтому сессия должна быть снаружи. Перепутать местами легко, а последствие
неочевидное — «капча пройдена» просто не запоминается, и человек проходит её
заново на каждой странице. `kremle.middleware` уже собран правильно.

```python
kremle = KremleLitestar(
    secret=...,
    policy={'yandex_bot': 'block', 'yandex_browser': 'monitor'},
    skip_paths=['/healthz'],
    headless=True,          # всё приложение — JSON-API
)
```

`request: Request` и `Response` аннотируются внутри интеграции: Litestar
разбирает сигнатуры обработчиков, и без аннотаций он выдаёт предупреждения о
грядущем 3.0. Вам об этом думать не нужно.

## Проверка в тестах

```python
from litestar.testing import TestClient

with TestClient(app) as client:
    assert client.get('/', headers={'User-Agent': 'Mozilla/5.0 Chrome/120'}).status_code == 200
    assert client.get('/', headers={'User-Agent': 'Mozilla/5.0 YaBrowser/24.1'}).status_code == 403
```

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
