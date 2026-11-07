# Установка

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

Посмотреть, сколько трафика задевает фильтр, ничего не блокируя:

```bash
KREMLE_DEMO_POLICY=monitor kremle-detect serve
```

## Docker

```bash
docker compose up --build      # → http://localhost:8000
```

Образ — демо/песочница. Для продакшена собирайте свой и монтируйте кеш вопросов
(`kremle-detect questions sync`), иначе после рестарта контейнера задания
останутся только встроенные.

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
