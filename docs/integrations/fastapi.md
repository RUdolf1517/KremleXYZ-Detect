# FastAPI

> «Скорость — это тоже дисциплина: быстро ответил — значит, не подвёл.»

FastAPI стоит на Starlette, поэтому рядом живут две родственные интеграции —
[Starlette](starlette.md) (то же ядро без FastAPI) и [Litestar](litestar.md)
(тот же протокол на другом фреймворке).

## Минимум

```python
from fastapi import FastAPI
from kremle_detect.integrations.fastapi_ext import KremleFastAPI

app = FastAPI()

kremle = KremleFastAPI(
    app,
    categories=['math', 'physics'],
    question_count=10,
    secret='your-secret',
)

@app.get('/')
async def index():
    return {'message': 'Добро пожаловать!'}
```

`SessionMiddleware` добавляется автоматически, если её ещё нет (нужна для куки
капчи). Если у вас уже своя — библиотека её не трогает.

Между прочим, движок синхронный — и это не отсталость, а основательность:
HMAC считается предсказуемо, кеш вопросов читается честно, никакой гонки.

## Заголовки безопасности и CSP

Роуты капчи отвечают с `X-Frame-Options: DENY`, `X-Content-Type-Options:
nosniff`, `Referrer-Policy: no-referrer` и CSP. Политика настраивается:

```python
KremleFastAPI(app, csp_policy='')                    # не отправлять CSP
KremleFastAPI(app, csp_policy="default-src 'self'")  # своя политика
```

Разбор политики по умолчанию и последствий ужесточения —
[Безопасность: CSP](../security.md#csp-как-ужесточить-и-что-сломается).

## Ротация секрета

```python
KremleFastAPI(app, secret=['новый-ключ', 'старый-ключ'])
```

Первый ключ подписывает, все проверяют: капчи, выданные до смены, доживают свой
TTL. Дефолтный `kremle-default-secret` пишет WARNING в лог при старте.

## Асинхронность и event loop

FastAPI вызывает движок из `async def`, а движок синхронный: он считает HMAC,
читает кеш вопросов и обращается к хранилищу. Синхронный Redis-клиент внутри
`async def` блокировал бы event loop, поэтому по умолчанию включён оффлоад:

```python
KremleFastAPI(app, async_offload=True)    # по умолчанию: работа в threadpool
KremleFastAPI(app, async_offload=False)   # вызывать движок прямо в loop
```

Для настоящего async-хранилища:

```python
from kremle_detect.storage_async import AsyncRedisStorage, AsyncStorageAdapter

storage = AsyncStorageAdapter(AsyncRedisStorage(url='redis://localhost:6379/0'))
```

`AsyncStorageAdapter` даёт синхронный интерфейс поверх async-хранилища и
работает вместе с `async_offload`. Нативный async-движок — в [роадмапе](https://github.com/RUdolf1517/KremleXYZ-Detect/blob/main/ROADMAP.md)
(3.0): он требует ломающих изменений.

## Headless / JSON

Если весь сервис — API, HTML-капча бессмысленна:

```python
KremleFastAPI(app, headless=True)
```

`GET /kremle/challenge` отдаёт JSON вместо страницы. Подробнее —
[SPA и JSON](spa.md).

## Middleware без привязки к app

```python
from kremle_detect.integrations.fastapi_ext import KremleFastAPI

kremle = KremleFastAPI()          # без app
...
kremle.init_app(app)              # в lifespan / create_app
```

## OpenAPI

Роуты капчи попадают в схему как обычные эндпоинты. Чтобы они не мозолили
глаза в публичной документации API:

```python
KremleFastAPI(app, enable_ops_routes=False)
```

Это выключит только health/stats/metrics — ручки капчи остаются, они нужны
людям.

## Проверка

```bash
uvicorn myapp:app --reload
curl -H 'User-Agent: Mozilla/5.0 ... YaBrowser/24.1 ...' localhost:8000/
curl -H 'User-Agent: Mozilla/5.0 ... Chrome/120.0 ...' localhost:8000/
```

Первая команда должна вернуть `403` с `challenge_url`, вторая — `200`.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
