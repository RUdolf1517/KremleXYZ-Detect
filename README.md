<div align="center">

# kremle-detect

**Капча-фильтр по браузеру.**
Яндекс Браузер, Яндекс-боты и переходы с Яндекса получают капчу с вопросами ЕГЭ.
Все остальные проходят сразу.

[Установка](#установка) · [Быстрый старт](#быстрый-старт) · [Детекция](#что-считается-яндексом) · [Вопросы](#банк-вопросов) · [CLI](#cli) · [2.6](#что-изменилось-в-26)

[![license](https://img.shields.io/badge/license-MIT-0b3d91?style=flat-square)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square)](pyproject.toml)
[![version](https://img.shields.io/badge/version-2.6.0-111111?style=flat-square)](CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-201%20passed-2ea44f?style=flat-square)](#тесты)

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

## Установка

```bash
pip install "kremle-detect @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
```

С зависимостями конкретного фреймворка:

```bash
pip install "kremle-detect[flask]   @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
pip install "kremle-detect[django]  @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
pip install "kremle-detect[fastapi] @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
pip install "kremle-detect[all]     @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
```

Обновление:

```bash
pip install --force-reinstall "kremle-detect @ git+https://github.com/RUdolf1517/KremleXYZ-Detect.git"
```

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

### FastAPI + React (headless)

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
{"questions": [{"q": "...", "opts": ["...", "..."]}], "token": "...", "created_at": 0}

// POST /kremle/verify → результат
{"passed": true, "errors": 1, "total": 15, "redirect": "/"}
```

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
- `max_errors` обязан быть **меньше** `question_count`, иначе капча проходится без
  единого правильного ответа — такой конфиг падает с `ValueError` на старте.

Коды ошибок в ответе `/kremle/verify`:

| `error` | Что значит | `errors` |
|---|---|---|
| `invalid_token` | токен истёк, уже использован или отсутствует | `-1` |
| `rate_limited` | исчерпан лимит неудачных проверок с IP | `-1` |
| `blacklisted` | IP в блоклисте | `-1` |
| `invalid_answers` | `answers` — не объект | `-1` |
| — | обычный результат | `0..total` |

## Банк вопросов

| Категория | Описание | Вопросов |
|---|---|---|
| `math` | профильная математика | 15 |
| `physics` | физика | 15 |
| `russian` | каверзные вопросы по русскому | 15 |
| `literature` | русская литература | 15 |

```bash
kremle-detect questions --category math --count 5
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

`X-Forwarded-For` по умолчанию **не** используется: подделать его может кто угодно.
За nginx/CDN укажи, каким прокси доверять:

```python
kremle = KremleFlask(
    app,
    trusted_proxies=['127.0.0.1', '10.0.0.0/8'],
)
```

```python
# Django settings.py
KREMLE_TRUSTED_PROXIES = ['127.0.0.1', '10.0.0.0/8']
```

Цепочка читается справа налево, доверенные хопы пропускаются. Один и тот же резолвер
используется в гарде, в `/kremle/verify` и в статистике — IP везде совпадает.

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

```bash
npm install /path/to/KremleXYZ-Detect/kremle-react
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

Экспорты: `KremleChallenge`, `useKremle`, типы `KremleChallengeProps`, `KremleQuestion`,
`KremleResult`, `UseKremleOptions`, `UseKremleReturn`. Требует React ≥ 17 и FastAPI
с `headless=True`. Запросы идут с `credentials: 'include'` — сессия общая с бэкендом.

## API-роуты

| Метод | Путь | Описание |
|---|---|---|
| GET | `/kremle/challenge` | HTML-капча или JSON в headless-режиме |
| POST | `/kremle/verify` | проверка ответов (JSON) |
| GET | `/kremle/status` | `{"verified": bool}` для текущей сессии |

Ответы `/kremle/challenge` отдаются с `Cache-Control: no-store` — токен в HTML
не должен попасть в кеш. `429` — если сработал `challenge_rate_limit`.

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

### Логи событий

```bash
kremle-detect logs -n 200
kremle-detect logs --no-color
```

События: `ПРОШЁЛ`, `ПРОВАЛ`, `ДЕТЕКТ`, `ЗАБЛОК`. URL Redis — флагом `--redis` или
переменной окружения `KREMLE_REDIS_URL`.

## Безопасность: что честно

Это фильтр от **живых людей**, а не антибот. Полезно знать заранее:

- `User-Agent` и `Sec-CH-UA` подделываются в два клика — детекция обходится.
- `fingerprint` приходит от клиента: бот может отправить пустой объект и снять строгий режим.
- 15 вопросов ЕГЭ — серьёзный барьер для человека, но LLM/поиск отвечает на них быстро.
- Блокировка по браузеру — это отказ в доступе живым людям; в ЕС/РФ это как минимум
  спорно с точки зрения антимонопольного/пользовательского законодательства.
- Переходы из поиска — самый ценный трафик, капча на них снижает и позиции, и конверсию.

Что реально защищено в 2.6: подделка `X-Forwarded-For` больше не обходит rate limit и не
подставляет чужой IP в блоклист; неудачные попытки не блокируют честных пользователей;
один челлендж = одна попытка; битый JSON не валит сервер; инкремент счётчиков в Redis атомарный.

## Что изменилось в 2.6

Полный список — в [CHANGELOG.md](CHANGELOG.md). Кратко:

| Было | Стало |
|---|---|
| `X-Forwarded-For` принимался от всех | только от `trusted_proxies` |
| rate limit считал все попытки | только неудачные, успех сбрасывает счётчик |
| токен сгорал только после успеха | одноразовый: сгорает после любой проверки |
| `max_errors >= question_count` проходился всегда | `ValueError` на старте |
| Flask-гард брал `remote_addr`, verify — XFF | один резолвер IP везде |
| FastAPI: битый JSON → 500 | `400 {"error": "invalid_json"}` |
| `path('kremle/', kremle_urls())` в Django падал | возвращается `include(...)`, роуты резолвятся |
| `errors: -1` показывался как «ошибок -1 из 0» | понятные сообщения о блокировке/истечении |
| `blacklist add --ttl 0` → сутки | `0` = навсегда |
| `random` для перемешивания | `secrets.SystemRandom` |

Совместимость: если у тебя маленький `question_count` (например 3) и `max_errors=3`,
конфиг теперь не запустится — это была дыра. За прокси добавь `trusted_proxies`,
иначе все клиенты будут выглядеть одним IP.

## Тесты

```bash
python -m pytest tests/ -q      # 201 тест
```

Покрыто: детекция, ядро капчи, валидация настроек, одноразовые токены, rate limit,
резолвинг IP, Flask-интеграция, Django-интеграция, FastAPI headless, RedisStorage
на фейковом клиенте. CI гоняет Python 3.9–3.13, собирает wheel и проверяет, что
шаблон попал в пакет, плюс билд React-пакета.

## Лицензия

MIT — см. [LICENSE](LICENSE).
