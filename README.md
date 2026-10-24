<div align="center">

# kremle-detect

**Капча-фильтр по браузеру.**
Яндекс Браузер, Яндекс-боты и переходы с Яндекса получают капчу с вопросами ЕГЭ.
Все остальные проходят сразу.

[Установка](#установка) · [Демо за минуту](#демо-за-минуту) · [Быстрый старт](#быстрый-старт) · [Детекция](#что-считается-яндексом) · [Вопросы](#вопросы-банк-и-решу-егэ) · [Monitor](#monitor-режим-и-сегменты) · [Эксплуатация](#эксплуатация-health-stats-metrics) · [CLI](#cli) · [Релиз](#релиз) · [Безопасность](#безопасность-что-честно) · [2.7](#что-изменилось-в-27)

[![license](https://img.shields.io/badge/license-MIT-0b3d91?style=flat-square)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square)](pyproject.toml)
[![version](https://img.shields.io/badge/version-2.7.0-111111?style=flat-square)](CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-491%20passed%20%2B%2024%20react-2ea44f?style=flat-square)](#тесты)
[![security](https://img.shields.io/badge/security-policy-0b3d91?style=flat-square)](SECURITY.md)

</div>

---

```python
from flask import Flask
from kremle_detect.integrations.flask_ext import KremleFlask

app = Flask(__name__)
app.secret_key = 'change-me'

KremleFlask(app, question_count=15, max_errors=3)
```

Две строки — и защита работает. Flask, Django, FastAPI или голое ядро.
Можно сначала посмотреть, а не блокировать: `policy={'yandex_browser': 'monitor'}`.

## Установка

```bash
pip install "kremle-detect[flask]"     # Flask
pip install "kremle-detect[django]"    # Django
pip install "kremle-detect[fastapi]"   # FastAPI
pip install "kremle-detect[all]"       # всё сразу + Redis
pip install "kremle-detect[demo]"      # демо-сервер (uvicorn)
```

React-компонент:

```bash
npm install kremle-react
```

<details>
<summary>Если пакета ещё нет в индексе (или нужен конкретный коммит)</summary>

```bash
pip install "kremle-detect[all] @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
npm install /path/to/KremleXYZ-Detect/kremle-react
```

</details>

Ядро (`detect`, `CaptchaEngine`, `MemoryStorage`) работает на чистой стандартной библиотеке — без Flask, Django и Redis. Опциональные зависимости: `flask`, `django`, `fastapi` + `jinja2`, `redis`.

<details>
<summary>Из исходников</summary>

```bash
git clone https://github.com/RUdolf1517/KremleXYZ-Detect
cd KremleXYZ-Detect
python -m venv .venv && . .venv/bin/activate
pip install -e ".[all]" pytest
python -m pytest tests/ -q
```

</details>

## Демо за минуту

Не хочется читать документацию, чтобы понять, как это выглядит?

```bash
pip install "kremle-detect[demo]"
kremle-detect serve            # → http://localhost:8000
```

Или в контейнере:

```bash
docker compose up --build      # → http://localhost:8000
```

Что внутри демо:

| Путь | Что показывает |
|---|---|
| `/` | страница-визитка и кнопка `fetch` на `/api/me` |
| `/api/me` | JSON-эндпоинт: из Яндекс Браузера приходит `403 captcha_required` |
| `/kremle/challenge` | сама капча с вопросами ЕГЭ |
| `/stats` | живые счётчики (`/kremle/stats`), обновление каждые 3 с |
| `/kremle/metrics` | Prometheus-метрики |

Посмотреть, сколько трафика задевает фильтр, ничего не блокируя:

```bash
KREMLE_DEMO_POLICY=monitor kremle-detect serve
```

Нагрузочный смоук (rps, p50/p95) — без зависимостей:

```bash
python scripts/loadtest.py -n 500 -c 20
```

## Быстрый старт

### Flask

```python
from flask import Flask
from kremle_detect.integrations.flask_ext import KremleFlask

app = Flask(__name__)
app.secret_key = 'your-secret'

kremle = KremleFlask(
    app,
    categories=['math', 'physics', 'russian', 'literature'],
    question_count=15,
    max_errors=3,
)

@app.route('/')
def index():
    return 'Добро пожаловать!'
```

`before_request`-гард включён по умолчанию. Точечная защита отдельных роутов:

```python
kremle = KremleFlask(app, auto_guard=False)

@app.route('/secret')
@kremle.protect
def secret():
    return 'секретная страница'
```

### Django

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
from kremle_detect.integrations.django_ext import kremle_urls

urlpatterns = [
    path('kremle/', kremle_urls()),
    # ...
]
```

Без `SessionMiddleware` middleware упадёт с `ImproperlyConfigured` и подсказкой, что добавить.

### FastAPI

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

`SessionMiddleware` добавляется автоматически, если её ещё нет.

### JSON-API для SPA (Flask, Django, FastAPI)

Блокирующая HTML-капча бессмысленна для `fetch`/XHR: клиент ждёт JSON, а получает
страницу. Поэтому все три интеграции отвечают `403 JSON` любому запросу, который
просит JSON (`Accept: application/json`, `X-Requested-With: XMLHttpRequest` или путь
под `/api/`, `/v1/`, `/v2/`, `/graphql`), и редиректят только обычную навигацию. Отключается через `json_api=False`
(Flask/FastAPI) или `KREMLE_JSON_API = False` (Django).

`headless=True` (Flask/FastAPI) и `KREMLE_HEADLESS = True` (Django) — режим «весь
сайт API»: JSON отдаётся всегда, даже на `Accept: text/html`.

Для SPA капча не редиректит, а возвращает `403 JSON` — фронт сам рисует форму:

```python
from fastapi.middleware.cors import CORSMiddleware
from kremle_detect.integrations.fastapi_ext import KremleFastAPI

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

kremle = KremleFastAPI(app, secret='your-secret', headless=True)
```

Что получает клиент:

```jsonc
// GET /protected  → 403
{"error": "captcha_required", "reason": "yandex_browser", "challenge_url": "/kremle/challenge"}

// GET /kremle/challenge → вопросы без ответов
{"questions": [{"q": "...", "opts": ["...", "..."], "category": "math"}],
 "token": "...", "verify_url": "/kremle/verify",
 "sources": [{"name": "РешуЕГЭ", "url": "https://...", "author": "..."}],
 "attribution": "Задания: РешуЕГЭ"}

// POST /kremle/verify → результат
{"passed": true, "errors": 1, "total": 15, "redirect": "/"}
```

Клиенты, которые просят JSON, получают и блокировку в JSON — без редиректов,
которые ломают SPA-навигацию:

```jsonc
{"error": "blocked", "action": "block", "challenge_url": null}   // 403, политика block
```

Все ответы `/kremle/challenge` и JSON-блокировки идут с `Cache-Control: no-store`.

### Голое ядро (любой фреймворк)

```python
from kremle_detect import detect, CaptchaEngine

result = detect({
    'User-Agent': request.headers.get('User-Agent', ''),
    'Referer': request.headers.get('Referer', ''),
    'Sec-CH-UA': request.headers.get('Sec-CH-UA', ''),
})
if result:
    print(result.reason)   # yandex_browser | yandex_bot | yandex_referrer | yandex_client_hints

engine = CaptchaEngine(categories=['math', 'russian'], question_count=10, max_errors=2, secret='my-secret')

challenge = engine.create_challenge()
data_for_client = challenge.to_dict()          # без правильных ответов

verification = engine.verify(challenge.token, {'0': 0, '1': 2}, ip=client_ip)
if verification['passed']:
    print('Человек подтверждён')
```

## Что считается Яндексом

| Сигнал | Где ищем | Примеры |
|---|---|---|
| Браузер | `User-Agent` | `YaBrowser`, `Yowser`, `YaApp_Android`, `YaApp_iOS`, `YandexSearch`, `YandexStation` |
| Бот | `User-Agent` | `YandexBot`, `YandexMetrika`, `YandexImages`, `YandexDirect` + 20 других |
| Реферер | `Referer` | `yandex.ru/com/by/kz/...` и все TLD, `ya.ru`, `dzen.ru`, `zen.`, `market.`, `music.`, `news.`, `mail.`, `translate.` |
| Client Hints | `Sec-CH-UA`, `Sec-CH-UA-Full-Version-List` | `"YaBrowser";v="24"` |
| JS-фингерпринт | браузер | `navigator.userAgentData`, `window.yandex`, `window.Ya`, honeypot |

Приоритет причины: `yandex_bot` → `yandex_browser` → `yandex_client_hints` → `yandex_referrer`.

```python
from kremle_detect import is_yandex_browser, is_yandex_bot, is_yandex_referrer

is_yandex_browser('Mozilla/5.0 ... YaBrowser/24.1 ...')   # True
is_yandex_bot('Mozilla/5.0 (compatible; YandexBot/3.0)')  # True
is_yandex_referrer('https://yandex.ru/search?q=test')     # True
```

## Как работает капча

1. Яндекс-пользователь ловит редирект на `/kremle/challenge` (или `403` в headless).
2. Сервер выбирает N вопросов, **перемешивает варианты ответов** и кладёт челлендж в хранилище.
   HTML/JSON содержит только вопросы и токен — правильных ответов там нет.
3. Клиент отвечает, `POST /kremle/verify` со `token`, `answers` и `fingerprint`.
4. Сервер считает ошибки: `errors <= max_errors` → проход, сессия помечается проверенной.

Важные детали:

- **Токен одноразовый.** Он удаляется после любой проверки — и успешной, и провальной.
  Повторная попытка требует нового челленджа (`{"error": "invalid_token"}`).
- **Челлендж живёт 15 минут**, потом `invalid_token`.
- **Правильные индексы перемешиваются на сервере** (`secrets.SystemRandom`), поэтому
  «всегда отправлять 0» бесполезно.
- **Строгий режим по фингерпринту.** Если JS сообщает `yaBrands`, `yandexApi` или honeypot,
  `max_errors` принудительно становится `0` — Яндекс Браузер должен сдать идеально.
  Это задуманное поведение, а не баг.
- `max_errors` не может быть больше или равен `question_count`: на старте значение
  подрезается до `question_count - 1` с `WARNING` в лог — иначе капча проходится
  без единого правильного ответа. Если пул вопросов оказался короче
  `question_count`, лимит подрезается под фактическое число вопросов.

### Сколько живёт «капча пройдена»

Отметка о прохождении хранится в сессии как `{"ok": true, "ts": ..., "exp": ..., "ip": ..., "ua": ...}`
и живёт `verified_ttl` секунд (по умолчанию сутки; `0` — бессрочно):

```python
kremle = KremleFlask(app, verified_ttl=3600, bind_ua=True, bind_ip=False)
```

- `bind_ua=True` — смена User-Agent сбрасывает прохождение. По умолчанию **выключено**:
  UA меняется при обновлении браузера, и честный пользователь не должен переспрашивать
  капчу из-за минорной версии (в Django — `KREMLE_BIND_UA = True`);
- `bind_ip=True` — привязка к IP, тоже выключена по умолчанию: мобильные сети меняют адрес;
- старый флаг `True`, записанный версией ≤ 2.6, считается **просроченным** — один раз
  перепройти, зато вечного прохода с одной сессии больше нет;
- `POST /kremle/logout` сбрасывает отметку: пользователь может перепройти капчу
  (кнопка «Попробовать снова» в шаблоне делает именно это);
- `GET /kremle/status` → `{"verified": bool, "expires_in": int|null}`.

Коды ошибок в ответе `/kremle/verify`:

| `error` | Что значит | `errors` |
|---|---|---|
| `invalid_token` | токен истёк, уже использован или отсутствует | `-1` |
| `rate_limited` | исчерпан лимит неудачных проверок с IP | `-1` |
| `blacklisted` | IP в блоклисте | `-1` |
| `invalid_answers` | `answers` — не объект | `-1` |
| — | обычный результат | `0..total` |

## Вопросы: банк и «Решу ЕГЭ»

Источник по умолчанию (`questions_source='auto'`): **кеш вопросов «Решу ЕГЭ»**, если он
есть, иначе встроенный банк. Так капча работает и без сети, и с настоящими заданиями.

```bash
kremle-detect questions sync                    # скачать задания в кеш (все категории)
kremle-detect questions sync -c math -n 100     # только математика, до 100 заданий
kremle-detect questions sync --ids 1001,1002    # конкретные задания портала
kremle-detect questions sync --images           # включить задания с рисунком
kremle-detect questions sync --dry-run          # скачать, но не записывать
kremle-detect questions cache                   # сколько в кеше и когда обновляли

kremle-detect questions check 1001              # проверить одно задание целиком
kremle-detect questions check 1001 --json       # то же машинно (для скриптов/CI)
```

### «А это задание вообще годится?» — `questions check`

Самая простая проверка того, что реально придёт с портала: одна команда, один id.

```console
$ kremle-detect questions check 1001
GET https://math-ege.sdamgia.ru/problem?id=1001

Условие: На экзамен вынесено 60 вопросов, Андрей не выучил 3 из них...
Ответ:   0,95
Картинок в условии: 0

В капчу пойдёт. Варианты:
    0. 0,9
    1. 1,95
  ✓ 2. 0,95
    3. 0,05
```

Если в условии есть рисунок, команда честно скажет об этом:

```console
$ kremle-detect questions check 314159
Условие: На рисунке изображён график функции. Найдите значение f(2).
Ответ:   3
Картинок в условии: 1
  - https://math-ege.sdamgia.ru/img/graph.png

В капчу НЕ пойдёт: есть картинка, а --images не указан.
Проверить как пригодное: kremle-detect questions check 314159 --images
```

Коды возврата: `0` — задание годится, `1` — не скачалось (сеть/прокси),
`2` — страница скачалась, но разметка не разобралась (портал сменил вёрстку),
`3` — для капчи не годится (картинка без `--images`, текстовый ответ, длинное условие).
`--json` печатает всё то же машинно — удобно для CI и баг-репортов.

### Задания с рисунком

Часть заданий «Решу ЕГЭ» без картинки не имеет смысла. По умолчанию такие задания
**отбрасываются**: горячие ссылки на портал не должны попадать в капчу молча.
Если рисунки нужны:

```bash
kremle-detect questions sync --images
```

```python
kremle = KremleFlask(app, questions_source='sdamgia', questions_images=True)
```

```python
# Django
KREMLE_QUESTIONS_IMAGES = True
```

Тогда в JSON капчи у вопроса появляется `images`:

```jsonc
{"q": "На рисунке изображён график…", "opts": ["3", "4", "5", "6"],
 "images": [{"url": "https://math-ege.sdamgia.ru/img/1.png", "alt": ""}]}
```

Шаблон капчи и React-компонент рисуют их с `referrerPolicy="no-referrer"`; если портал
не отдаёт картинку, вместо неё появляется «[рисунок не загрузился]» — капча не ломается.
Если картинки нужны локально (портал закрыл горячие ссылки), положите их в свой CDN
и подмените `url` при сборке вопросов.

Кеш лежит в `$KREMLE_CACHE_DIR` или `~/.cache/kremle-detect/sdamgia-<категория>.json`.
Свежесть — 30 дней; устаревший кеш всё равно используется (лучше старые задания, чем
пустой банк), а неудачный `sync` не затирает то, что уже скачано.

```python
kremle = KremleFlask(app, questions_source='auto')       # auto | builtin | sdamgia
```

- `auto` — кеш РешуЕГЭ → встроенный банк (молча, в лог `kremle`);
- `sdamgia` — только портал: пустой кеш = пустой банк и `WARNING` (честно, без подмены);
- `builtin` — только встроенные вопросы.

### Атрибуция обязательна

Задания принадлежат порталу «Решу ЕГЭ» (СДАМ ГИА, автор — Д. Д. Гущин и авторы портала).
Каждый вопрос несёт поле `source`, а страница капчи показывает ссылку на источник:

```jsonc
{
  "q": "На экзамен вынесено 60 вопросов...",
  "opts": ["0,95", "0,05", "0,9", "1,05"],
  "category": "math",
  "problem_id": "1001",
  "source": {
    "name": "РешуЕГЭ",
    "url": "https://math-ege.sdamgia.ru/problem?id=1001",
    "author": "Д. Д. Гущин и авторы портала"
  }
}
```

В JSON-ответе `/kremle/challenge` рядом с вопросами приходят `sources` и готовая строка
`attribution` («Задания: РешуЕГЭ»). Отключить подпись в React-компоненте можно
`showAttribution={false}`, но условия использования материалов портала — на стороне
оператора: см. [NOTICE.md](NOTICE.md).

### Как задания превращаются в варианты ответа

Провайдер запрашивает `newapi/general`, открывает страницы вариантов и собирает ссылки
на задания, затем читает `/problem?id=<id>` и разбирает условие и ответ. Числовой ответ
становится правильным вариантом, три остальных — правдоподобные искажения (сдвиг,
масштаб, смена знака). Задания с текстовым ответом и слишком длинным условием
отбрасываются: для капчи они не годятся. Сеть, разбор HTML и кеш покрыты тестами на
фикстурах, а `get=` подменяется — можно гонять провайдер без интернета.

| Категория | Описание | Встроенный банк |
|---|---|---|
| `math` | профильная математика | 15 |
| `physics` | физика | 15 |
| `russian` | каверзные вопросы по русскому | 15 |
| `literature` | русская литература | 15 |

Встроенный банк — 60 вопросов (по 15 на категорию, 4 варианта ответа). Это fallback,
а не основной источник.

```bash
kremle-detect questions --category math --count 5
kremle-detect questions -c math -n 3 --source builtin
```

### Свои вопросы

```python
MY_QUESTIONS = [
    {
        "q": "Столица России?",
        "opts": ["Москва", "Санкт-Петербург", "Новосибирск", "Казань"],
        "ans": 0,
        "category": "geo",
    },
]
```

| Поле | Тип | Требование |
|---|---|---|
| `q` | `str` | непустая строка |
| `opts` | `list` | минимум 2 варианта |
| `ans` | `int` | индекс правильного варианта, 0-based |
| `category` | `str` | необязательно — подпись на карточке |

```python
kremle = KremleFlask(app, extra_questions=MY_QUESTIONS)              # в дополнение к ЕГЭ
kremle = KremleFlask(app, extra_questions=MY_QUESTIONS, only_extra=True)  # только свои
```

Проверить список руками:

```python
from kremle_detect import validate_questions
validate_questions(MY_QUESTIONS)   # ValueError с номером и причиной
```

Все ошибки формата выбрасываются при старте, а не во время запроса.

## Хранение

По умолчанию — `MemoryStorage` (один процесс). Для нескольких воркеров — Redis:

```python
from kremle_detect import RedisStorage

kremle = KremleFlask(app, storage=RedisStorage(url='redis://localhost:6379/0'))
```

`RedisStorage` умеет `redis_client=...` (готовый клиент) и `prefix='kremle:'`.
Инкремент счётчиков атомарный (Lua), TTL ставится один раз — fixed window.

Также в хранилище живут блоклист, вайтлист и кольцевой лог событий (последние 1000).

### Асинхронность

FastAPI вызывает движок из `async def`, а синхронный Redis-клиент блокировал бы event loop.
Два варианта:

```python
from kremle_detect.storage import RedisStorage
from kremle_detect.storage_async import AsyncRedisStorage, AsyncStorageAdapter

kremle = KremleFastAPI(app, storage=RedisStorage(url='redis://localhost:6379/0'))  # уходит в threadpool

# или нативный asyncio-клиент для собственного кода:
storage = AsyncRedisStorage(url='redis://localhost:6379/0', prefix='kremle:')
await storage.increment('rate:ip', ttl=60)
await storage.aclose()

# или обёртка над своим синхронным бэкендом:
adapter = AsyncStorageAdapter(MyStorage())
```

`KremleFastAPI(..., async_offload=False)` выполняет движок прямо в event loop —
быстрее на MemoryStorage, но опасно с медленным Redis. Инкремент в `AsyncRedisStorage`
атомарный (Lua `INCR` + `EXPIRE`), как и в синхронном.

## Rate limiting

```python
kremle = KremleFlask(
    app,
    rate_limit=10,     # 10 НЕУДАЧНЫХ проверок
    rate_window=600,   # за 10 минут
)
```

- Считаются только неудачные проверки. Успешное прохождение сбрасывает счётчик —
  честный пользователь не блокирует себя сам.
- `rate_limit=0` — отключить.
- Отдельный лимит на выдачу челленджей (защита хранилища от забивания):

```python
kremle = KremleFlask(app, challenge_rate_limit=60)   # 60 челленджей за rate_window с IP
```

Превышение → `429` на `/kremle/challenge`.

## IP, прокси, whitelist, blacklist

`X-Forwarded-For` принимается только от доверенных прокси. По умолчанию доверяем
**loopback и приватным сетям** — `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, `169.254.0.0/16`, IPv6 ULA и link-local. То есть nginx на том же
хосте, docker/k8s-сеть и внутренний балансировщик работают **без настройки**.

Нужен публичный балансировщик (Cloudflare, облачный LB) — перечисли его явно:

```python
kremle = KremleFlask(
    app,
    trusted_proxies=['203.0.113.10', '198.51.100.0/24'],
)
```

```python
# Django settings.py
KREMLE_TRUSTED_PROXIES = ['203.0.113.10', '198.51.100.0/24']
```

Отключить доверие целиком (брать только адрес TCP-соединения):

```python
kremle = KremleFlask(app, trusted_proxies=[])
```

Если `X-Forwarded-For` пришёл от недоверенного адреса, в лог `kremle` уйдёт одно
предупреждение с подсказкой — так виден забытый публичный LB. Цепочка читается
справа налево, доверенные хопы пропускаются. Один и тот же резолвер используется
в гарде, в `/kremle/verify` и в статистике — IP везде совпадает.

```python
# статический вайтлист (IP и CIDR)
kremle = KremleFlask(app, whitelist=['127.0.0.1', '10.0.0.0/8', '192.168.0.0/16'])

# авто-бан после N провалов (0 — выключено)
kremle = KremleFlask(app, fail_threshold=5, blacklist_ttl=86400)
```

Управление списками из кода:

```python
engine.blacklist_add('1.2.3.4', ttl=3600)   # ttl=0 → навсегда
engine.blacklist_remove('1.2.3.4')
engine.is_blacklisted('1.2.3.4')

engine.whitelist_add('10.0.0.1')
engine.is_whitelisted('10.0.0.1')
```

## Monitor-режим и сегменты

Раньше выбор был «всё или ничего»: любой Яндекс-сигнал — капча. Теперь у каждого
сигнала своё действие (`policy`), а `sample_rate` позволяет сначала посмотреть, сколько
трафика задевает фильтр, ничего не блокируя.

```python
kremle = KremleFlask(
    app,
    policy={
        'yandex_bot':    'block',     # боты — сразу 403, капча им не поможет
        'yandex_browser': 'monitor',  # считать, но пропускать (shadow)
        'yandex_referrer': 'challenge',
    },
    sample_rate=1.0,                  # доля challenge-трафика, реально получающая капчу
)
```

| Действие | Что делает |
|---|---|
| `challenge` | показать капчу (по умолчанию для **всех** сигналов) |
| `block` | `403` без капчи: блэклист и боты |
| `monitor` | пропустить, но посчитать и записать событие `shadow` в лог |
| `allow` | игнорировать сигнал |

- Дефолт не изменился: без `policy` все сигналы требуют капчу.
- `sample_rate=0.3` — 30 % обнаруженного трафика получает капчу, остальные 70 %
  проходят и учитываются как `monitor`. Так можно измерить долю живых людей, которых
  задевает фильтр, на реальном трафике.
- `block` и `blacklist` от `sample_rate` не зависят — вероятностная блокировка не нужна.
- В `kremle-detect logs` такие события помечены `ТЕНЬ`.

```python
engine.decide(detect(headers))   # → Decision(action='monitor', reason='yandex_browser', sampled=False)
```

## Эксплуатация: health, stats, metrics

Все три фреймворка отдают одинаковый набор роутов (`enable_ops_routes=False` /
`KREMLE_ENABLE_OPS_ROUTES = False` — выключить):

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/kremle/health` | `200` со `{"status": "ok", "version", "storage", "storage_ok", ...}`, `503` при недоступном хранилище |
| GET | `/kremle/stats` | JSON-снапшот счётчиков |
| GET | `/kremle/metrics` | Prometheus text (`kremle_requests_total`, `kremle_detected_total{reason=...}`, `kremle_action_total{action=...}`…) |

```jsonc
// GET /kremle/stats
{
  "requests_total": 1024, "detected_total": 310, "allowed_total": 690,
  "detected_by_reason": {"yandex_bot": 4, "yandex_browser": 290, ...},
  "actions": {"challenge": 250, "block": 4, "monitor": 56, "allow": 0},
  "challenges_issued": 250, "verify_total": 231, "pass_total": 190, "fail_total": 41,
  "blocked_by_reason": {"blacklisted": 0, "rate_limited": 23},
  "shadow_total": 56, "pass_rate": 0.82
}
```

Счётчики живут в том же хранилище, что и челленджи, и не истекают — их можно
скрейпить Prometheus и строить графики «сколько живых людей мы задели».
`/kremle/health` годится для `livenessProbe`/`readinessProbe` и внешнего монитора:
`503` означает, что Redis недоступен и капча не сможет сохранить челлендж.

## Callbacks и логи

```python
def on_detect(result, ip):
    print(f'Яндекс-пользователь: {ip}, причина: {result.reason}')

def on_pass(ip, errors, total):
    print(f'{ip} прошёл капчу ({errors}/{total} ошибок)')

def on_fail(ip, errors, total):
    print(f'{ip} завалил капчу ({errors}/{total} ошибок)')

kremle = KremleFlask(app, on_detect=on_detect, on_pass=on_pass, on_fail=on_fail)
```

Логи — в логгер `kremle`:

```python
import logging
logging.getLogger('kremle').setLevel(logging.INFO)
```

## React-компонент

`kremle-react@2.7.0` — ESM + CJS + `'use client'` + типы, 24 теста, ставится из репозитория или из npm.
Версия npm-пакета совпадает с версией Python-пакета — один релиз, один тег.

```bash
npm install kremle-react
npm install /path/to/KremleXYZ-Detect/kremle-react   # из исходников
```

```tsx
import { KremleChallenge } from 'kremle-react'

function App() {
  return (
    <KremleChallenge
      challengeUrl="/kremle/challenge"
      verifyUrl="/kremle/verify"
      onPass={() => window.location.reload()}
      onFail={(r) => console.log(`ошибок: ${r.errors}/${r.total}`)}
    />
  )
}
```

Хук для своего UI:

```tsx
import { useKremle } from 'kremle-react'

function MyCaptcha() {
  const { questions, answers, setAnswer, submit, reload, loading, submitting, result, error } = useKremle()

  if (loading) return <div>Загрузка...</div>

  return (
    <form onSubmit={(e) => { e.preventDefault(); submit() }}>
      {questions.map((q, qi) => (
        <div key={qi}>
          <p>{q.q}</p>
          {q.opts.map((opt, oi) => (
            <label key={oi}>
              <input type="radio" name={`q${qi}`} onChange={() => setAnswer(qi, oi)} />
              {opt}
            </label>
          ))}
        </div>
      ))}
      <button type="submit" disabled={submitting}>Отправить</button>
      {result && !result.passed && <button type="button" onClick={reload}>Ещё раз</button>}
      {error && <p>{error}</p>}
    </form>
  )
}
```

Экспорты: `KremleChallenge`, `useKremle`, `collectFingerprint`, типы `KremleChallengeProps`,
`KremleQuestion`, `KremleResult`, `UseKremleOptions`, `UseKremleReturn`. Требует React ≥ 17
и JSON-режим на бэкенде. Запросы идут с `credentials: 'include'` — сессия общая с бэкендом.

- `sources`/`attribution` из `/kremle/challenge` рисуются под формой со ссылкой на
  первоисточник (`showAttribution={false}` — отключить);
- `invalid_token` — компонент сам запрашивает новый челлендж;
- `rate_limited`/`blacklisted`/`blocked` показываются человеческим текстом, а не
  «ошибок -1 из 0»;
- кнопка «Попробовать снова» делает `POST /kremle/logout` и перезагружает капчу;
- SSR-safe: `window`/`navigator` читаются только в браузере.

Подробности — [kremle-react/README.md](kremle-react/README.md).

## API-роуты

| Метод | Путь | Описание |
|---|---|---|
| GET | `/kremle/challenge` | HTML-капча; JSON при `Accept: application/json` или `headless` |
| POST | `/kremle/verify` | проверка ответов (JSON) |
| GET | `/kremle/status` | `{"verified": bool, "expires_in": int\|null}` |
| POST | `/kremle/logout` | сбросить «капча пройдена» (можно перепройти) |
| GET | `/kremle/health` | health-check для монитора |
| GET | `/kremle/stats` | счётчики в JSON |
| GET | `/kremle/metrics` | счётчики в формате Prometheus |

Ответы `/kremle/challenge` и JSON-блокировки отдаются с `Cache-Control: no-store` —
токен не должен попасть в кеш. `429` — если сработал `challenge_rate_limit` или
`rate_limited`.

## Кастомный шаблон

```python
kremle = KremleFlask(app, template='/path/to/my_captcha.html')
```

В шаблоне обязательна подстановка `{{ questions_json }}` — туда приходит JSON
`{questions, token, created_at, verify_url}`. Шаблон читается как текст (не Jinja2),
поэтому одинаково работает во всех трёх фреймворках.

## CLI

```bash
kremle-detect help
```

### Диагностика

```bash
kremle-detect check-ua "Mozilla/5.0 YaBrowser/24.1"      # exit 1, если детект
kremle-detect check-ref "https://yandex.ru/search?q=x"
kremle-detect check-hints '"YaBrowser";v="24"'
kremle-detect questions --category math --count 5
```

### Вопросы

```bash
kremle-detect questions show -c math -n 5              # из кеша РешуЕГЭ или банка
kremle-detect questions show --source builtin         # только встроенный банк
kremle-detect questions sync -c math -n 100           # обновить кеш
kremle-detect questions sync --ids 1001,1002 --dry-run
kremle-detect questions cache                         # состояние кеша
```

### Блоклист и вайтлист

```bash
kremle-detect blacklist list   --redis redis://localhost:6379/0
kremle-detect blacklist add    1.2.3.4 --ttl 3600
kremle-detect blacklist add    1.2.3.4 --ttl 0          # навсегда
kremle-detect blacklist remove 1.2.3.4

kremle-detect whitelist list
kremle-detect whitelist add    10.0.0.1
kremle-detect whitelist remove 10.0.0.1
```

### Версия

```bash
kremle-detect --version      # kremle-detect 2.7.0
```

### Демо-сервер

```bash
kremle-detect serve                  # FastAPI + капча + /stats на localhost:8000
kremle-detect serve --port 9000
KREMLE_DEMO_POLICY=monitor kremle-detect serve     # shadow: ничего не блокировать
```

Нужен экстра `pip install "kremle-detect[demo]"` (fastapi + uvicorn).

### Логи событий

```bash
kremle-detect logs -n 200
kremle-detect logs --no-color
```

События: `ПРОШЁЛ`, `ПРОВАЛ`, `ДЕТЕКТ`, `ТЕНЬ` (monitor), `ЗАБЛОК`. URL Redis — флагом
`--redis` или переменной окружения `KREMLE_REDIS_URL`.

## Релиз

Версия живёт в трёх местах и должна совпадать: `pyproject.toml`, `kremle_detect/__init__.py`
и `kremle-react/package.json`. Публикация — по тегу:

```bash
# 1. проверить, что всё зелёное
pytest tests/ -q

# 2. версия во всех трёх файлах + запись в CHANGELOG.md
# 3. тег и пуш — дальше всё делает .github/workflows/release.yml
git tag v2.7.0 && git push origin v2.7.0
```

Workflow соберёт wheel/sdist, сверит версию с тегом, поставит wheel в чистый venv
и дёрнет `kremle-detect --version`, затем опубликует PyPI (trusted publishing, OIDC,
без токенов) и npm (`--provenance`), и создаст GitHub Release с артефактами
и текстом из CHANGELOG. GitHub Release появляется даже если индекс не настроен —
по нему видно, что именно сломалось.

Что должно быть настроено один раз:

- **PyPI**: Account → Publishing → pending publisher
  (`kremle-detect`, owner `RUdolf1517`, repo `KremleXYZ-Detect`, workflow `release.yml`,
  environment `pypi`).
- **npm**: repository secret `NPM_TOKEN` (granular token с правом publish).
- Если OIDC недоступен — секрет `PYPI_API_TOKEN` и раскомментировать `password`
  в шаге публикации.

## Безопасность: что честно

Это фильтр от **живых людей**, а не антибот. Полезно знать заранее:

- `User-Agent` и `Sec-CH-UA` подделываются в два клика — детекция обходится.
- `fingerprint` приходит от клиента: бот может отправить пустой объект и снять строгий режим.
- 15 вопросов ЕГЭ — серьёзный барьер для человека, но LLM/поиск отвечает на них быстро.
- Блокировка по браузеру — это отказ в доступе живым людям; в ЕС/РФ это как минимум
  спорно с точки зрения антимонопольного/пользовательского законодательства.
- Переходы из поиска — самый ценный трафик, капча на них снижает и позиции, и конверсию.

Что реально защищено в 2.7: подделка `X-Forwarded-For` больше не обходит rate limit и не
подставляет чужой IP в блоклист; неудачные попытки не блокируют честных пользователей;
один челлендж = одна попытка; «пройдено» истекает; битый JSON не валит сервер; инкремент
счётчиков в Redis атомарный. Плюс появился способ измерить цену фильтра: `monitor`
и `sample_rate` считают задетых людей, не отказывая им в доступе.

Блокировка по браузеру остаётся целью проекта, а не дефектом. Но прежде чем включать
её на весь трафик, посмотрите `/kremle/stats` в monitor-режиме: цифра «столько-то
процентов посетителей — живые люди на Яндекс Браузере» обычно и есть ответ на вопрос,
стоит ли оно того.

### Как сообщить и что не считается багом

Политика раскрытия, область действия и модель угроз — в [SECURITY.md](SECURITY.md).
Коротко: блокировка живых людей на Яндекс Браузере, строгий режим по
`YaBrowser`-сигналам и отказ пускать без капчи — **не уязвимости**, это продукт.

`/kremle/stats`, `/kremle/metrics` и `/kremle/health` — публичные роуты, они отдают
цифры без авторизации. Закройте их на прокси или фаерволом, если это нежелательно.


## Что изменилось в 2.7

Полный список — в [CHANGELOG.md](CHANGELOG.md). Кратко:

| Было | Стало |
|---|---|
| капча блокировала и обычный `fetch`/SPA (HTML вместо JSON) | `403 JSON` с `captcha_required` + `challenge_url`, редирект только для навигации |
| «капча пройдена» = `True` в сессии навсегда | TTL `verified_ttl`, привязка к IP/UA, `POST /kremle/logout` |
| встроенный банк из 60 вопросов | по умолчанию кеш настоящих заданий «Решу ЕГЭ» с атрибуцией |
| всё или ничего: любой сигнал → капча | `policy` на сигнал (`challenge`/`block`/`monitor`/`allow`) + `sample_rate` |
| мониторинг только по логам | `/kremle/health`, `/kremle/stats`, `/kremle/metrics` |
| синхронный Redis в async-приложении | `AsyncRedisStorage`, `AsyncStorageAdapter`, `async_offload` в FastAPI |
| Django: без headless-режима и ops-роутов | паритет с Flask/FastAPI (`KREMLE_HEADLESS`, `KREMLE_ENABLE_OPS_ROUTES`) |
| React-пакет не собирался и не тестировался | `kremle-react@2.7.0`: сборка, типы, `'use client'`, 24 теста |
| задания с рисунком молча терялись | парсер собирает `images`, `sync --images`, рендер в шаблоне и React |
| «что придёт с портала?» — только руками в браузере | `kremle-detect questions check <id>` + `--json` для CI |
| потрогать можно было только через свой сайт | `kremle-detect serve` и `docker compose up` — демо с `/stats` |
| Redis проверялся фейком | живой Redis в CI + e2e на настоящем HTTP + нагрузочный смоук |

Ломающих изменений нет: без явной настройки политика остаётся `challenge` для всех
сигналов, а старый флаг «пройдено» просто истекает один раз.

## Что изменилось в 2.6

| Было | Стало |
|---|---|
| `X-Forwarded-For` принимался от всех | только от loopback/приватных сетей и `trusted_proxies` |
| rate limit считал все попытки | только неудачные, успех сбрасывает счётчик |
| токен сгорал только после успеха | одноразовый: сгорает после любой проверки |
| `max_errors >= question_count` проходился всегда | значение подрезается с предупреждением в лог |
| Flask-гард брал `remote_addr`, verify — XFF | один резолвер IP везде |
| FastAPI: битый JSON → 500 | `400 {"error": "invalid_json"}` |
| `path('kremle/', kremle_urls())` в Django падал | возвращается `include(...)`, роуты резолвятся |
| `errors: -1` показывался как «ошибок -1 из 0» | понятные сообщения о блокировке/истечении |
| `blacklist add --ttl 0` → сутки | `0` = навсегда |
| `random` для перемешивания | `secrets.SystemRandom` |

Ломающих изменений нет. За nginx/docker/k8s ничего настраивать не нужно —
приватные и локальные прокси доверенные по умолчанию. Внешний LB виден по
предупреждению в логе (или задай `trusted_proxies` сразу). Дырявый
`max_errors >= question_count` больше не мешает запуску: лимит подрезается
до безопасного значения.

## Тесты

```bash
python -m pytest tests/ -q      # 491 тестов
```

Покрыто: детекция, ядро капчи, валидация настроек, одноразовые токены, rate limit,
резолвинг IP, политика сегментов и `sample_rate`, метрики и health, TTL «пройдено»,
провайдер «Решу ЕГЭ» (разбор HTML, дистракторы, кеш, fallback), Flask/Django/FastAPI
(JSON-гард и разбор `Accept`, monitor, ops-роуты, logout), `AsyncRedisStorage`/
`AsyncStorageAdapter` на фейковом клиенте и CLI вопросов.

```bash
cd kremle-react && npm test && npm run typecheck && npm run build   # 24 теста + сборка
```

Что ещё есть в тестах:

```bash
# живой Redis (нужен docker run -p 6379:6379 redis:7)
KREMLE_TEST_REDIS_URL=redis://localhost:6379/15 pytest -m redis

# без Docker: in-memory двойник с поддержкой Lua (pip install "fakeredis[lua]")
KREMLE_TEST_REDIS_FAKE=1 pytest -m redis

# e2e на настоящем HTTP-сервере (uvicorn в потоке, реальные куки)
pytest tests/test_e2e.py

# нагрузочный смоук (нужен `kremle-detect serve`)
python scripts/loadtest.py -n 500 -c 20
```

CI гоняет Python 3.9–3.13 с сервисом Redis (и **падает**, если Redis-тесты
молча скипнулись), порог покрытия 85 %, сборку wheel с проверкой содержимого,
`pip-audit`/`npm audit`, тесты и сборку React-пакета. Отдельные workflow:
публикация по тегу `v*` (PyPI + npm) и ежедневная проверка живого портала
«Решу ЕГЭ».

## Лицензия

MIT — см. [LICENSE](LICENSE).
