# Установка

> «Поставил пакет — и спи спокойно: за тебя уже всё продумали.»

## Пакет

```bash
pip install kremle-detect                       # только ядро (Flask/Django/FastAPI — отдельно)
pip install "kremle-detect[flask]"              # Flask
pip install "kremle-detect[django]"             # Django
pip install "kremle-detect[fastapi]"            # FastAPI + Starlette SessionMiddleware
pip install "kremle-detect[redis]"              # RedisStorage
pip install "kremle-detect[all]"                # всё сразу
pip install "kremle-detect[demo]"               # демо-сервер на uvicorn
```

Python **3.9+**. Зависимостей у ядра нет вообще: Flask, Django, FastAPI нужны
только если вы их сами используете.

Если пакета ещё нет в индексе (или нужен конкретный коммит):

```bash
pip install "kremle-detect[all] @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
npm install /path/to/KremleXYZ-Detect/kremle-react
```

Из исходников:

```bash
git clone https://github.com/RUdolf1517/KremleXYZ-Detect
cd KremleXYZ-Detect
python -m venv .venv && . .venv/bin/activate
pip install -e ".[all]" pytest
python -m pytest tests/ -q
```

## Импортозамещение

`pip install kremle-detect` — и никакой западной капчи с ежемесячной подпиской.
Свои вопросы, свои ключи, свой кеш. Даже картинки качаются в локальное
хранилище, а не тянутся через чужие CDN: страница капчи не должна зависеть от
того, работает ли чья-то заграничная инфраструктура.

## React-компонент

```bash
npm install kremle-react
```

ESM + CJS + типы, peer-зависимости `react >= 17`. Собран на React 19, но
работает и на 17/18.

## Демо за минуту

Не хочется читать документацию, чтобы понять, как это выглядит:

```bash
pip install "kremle-detect[demo]"
kremle-detect serve            # → http://localhost:8000
```

| Путь | Что показывает |
|---|---|
| `/` | страница-визитка и кнопка `fetch` на `/api/me` |
| `/api/me` | JSON-эндпоинт: из Яндекс Браузера приходит `403 captcha_required` |
| `/kremle/challenge` | сама капча с вопросами |
| `/stats` | живые счётчики, обновление каждые 3 секунды |
| `/kremle/metrics` | Prometheus-метрики |

Проверить капчу можно **из любого браузера, кроме Яндекс Браузера**: из него
вы попадёте на собственную капчу, и это ожидаемо.

Совсем без установки — [статическое демо](demo.html): страница с настоящим
виджетом, вопросы и ответы зашиты внутрь. Ничего не запускает, ничего не
блокирует, открывается в любом браузере.

Посмотреть, сколько трафика задевает фильтр, ничего не блокируя:

```bash
KREMLE_DEMO_POLICY=monitor kremle-detect serve
```

## Демо без интернета

Встроенный банк вопросов работает офлайн: ни одного запроса наружу, ни одной
внешней зависимости у ядра. Суверенитет так суверенитет.

## Docker

Без сборки — готовый образ из GHCR:

```bash
docker run -p 8000:8000 ghcr.io/rudolf1517/kremle-detect:latest
# → http://localhost:8000
```

Из репозитория, одной командой:

```bash
docker compose up              # возьмёт latest из GHCR или соберёт локально
docker compose pull && docker compose up     # точно без сборки
docker compose --profile redis up            # демо + Redis
```

Теги образа: `latest` и `X.Y.Z` — по релизному тегу, `edge` — с каждой сборки
`main`. Собираются `linux/amd64` и `linux/arm64` (Raspberry Pi, Mac на ARM).
Контейнер работает не от root, кеш вопросов живёт в томе `/data`, healthcheck
ходит на `/kremle/health`.

Образ — демо/песочница. Для продакшена берите его же, но задайте свой ключ
(`-e KREMLE_SECRET=...`), смонтируйте кеш вопросов (`kremle-detect questions sync`)
и закройте ops-роуты на прокси — подробности в
[сниппетах](snippets.md#docker-compose).

## Проверка установки

```bash
kremle-detect --version
kremle-detect check-ua "Mozilla/5.0 ... YaBrowser/24.1 ..."
kremle-detect questions -c math -n 3 --source builtin
```

Если `check-ua` показывает `yandex_browser`, а вопросы печатаются — ядро на месте.

## Нагрузочный смоук

Без зависимостей, кроме стандартной библиотеки:

```bash
python scripts/loadtest.py -n 500 -c 20
```

Печатает rps и p50/p95 выдачи капчи. Полезно перед включением фильтра на
боевом трафике: капча — не бесплатная операция, она читает кеш вопросов и
считает HMAC.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
