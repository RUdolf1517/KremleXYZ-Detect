# kremle-detect

Защита сайта от пользователей Яндекс Браузера и переходов с поисковика Яндекс.
При детекции показывает капчу с вопросами из ЕГЭ по математике, физике, русскому языку и литературе.

## Установка

```bash
pip install git+https://github.com/RUdolf1517/KremleXYZ-Detect.git
```

С зависимостями для конкретного фреймворка:

```bash
pip install "git+https://github.com/RUdolf1517/KremleXYZ-Detect.git#egg=kremle-detect[flask]"
pip install "git+https://github.com/RUdolf1517/KremleXYZ-Detect.git#egg=kremle-detect[django]"
pip install "git+https://github.com/RUdolf1517/KremleXYZ-Detect.git#egg=kremle-detect[fastapi]"
```

Обновление до последней версии:

```bash
pip install --force-reinstall git+https://github.com/RUdolf1517/KremleXYZ-Detect.git
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

### Django

```python
# settings.py
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    # ...
    'kremle_detect.integrations.django_ext.KremleDjangoMiddleware',
]

KREMLE_CATEGORIES = ['math', 'physics', 'russian', 'literature']
KREMLE_QUESTION_COUNT = 15
KREMLE_MAX_ERRORS = 3

# urls.py
from kremle_detect.integrations.django_ext import kremle_urls
urlpatterns = [
    path('kremle/', kremle_urls()),
    # ...
]
```

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

### FastAPI + React (headless-режим)

Если фронтенд — SPA на React, используй `headless=True`. В этом режиме middleware **не делает редирект**, а возвращает `403 JSON` — фронт сам показывает капчу:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from kremle_detect.integrations.fastapi_ext import KremleFastAPI

app = FastAPI()

# CORS — нужен если фронт на другом порту/домене
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

kremle = KremleFastAPI(app, secret='your-secret', headless=True)
```

В headless-режиме:
- Яндекс-пользователь получает `403 {"error": "captcha_required", "challenge_url": "/kremle/challenge"}`
- `GET /kremle/challenge` возвращает JSON с вопросами (не HTML)
- `POST /kremle/verify` — без изменений

React-компонент для фронтенда: [kremle-react](#react-компонент)

### Использование ядра напрямую (любой фреймворк)

```python
from kremle_detect import detect, CaptchaEngine

# Детекция Яндекс-пользователей
result = detect({
    'User-Agent': request.headers.get('User-Agent', ''),
    'Referer': request.headers.get('Referer', ''),
    'Sec-CH-UA': request.headers.get('Sec-CH-UA', ''),
})

if result:
    print(result.reason)  # 'yandex_browser', 'yandex_bot', 'yandex_referrer', 'yandex_client_hints'

# Капча
engine = CaptchaEngine(
    categories=['math', 'russian'],
    question_count=10,
    max_errors=2,
    secret='my-secret',
)

challenge = engine.create_challenge()
data_for_client = challenge.to_dict()  # отдать на фронт

# После ответа пользователя
verification = engine.verify(challenge.token, {'0': 0, '1': 2, ...})
if verification['passed']:
    print('Человек подтверждён')
```

## Свои вопросы

### Шаг 1 — создать файл с вопросами

Создай в своём проекте отдельный файл, например `questions.py`:

```
myproject/
├── app.py          ← основное приложение
├── questions.py    ← сюда пишешь свои вопросы
└── ...
```

В файле `questions.py` объяви список:

```python
MY_QUESTIONS = [
    {
        "q": "Столица России?",
        "opts": ["Москва", "Санкт-Петербург", "Новосибирск", "Казань"],
        "ans": 0,
        "category": "geo",
    },
    {
        "q": "Сколько планет в Солнечной системе?",
        "opts": ["7", "8", "9", "10"],
        "ans": 1,
    },
    # ... сколько угодно вопросов
]
```

### Шаг 2 — подключить в приложении

**Flask** — в `app.py`:

```python
from kremle_detect.integrations.flask_ext import KremleFlask
from questions import MY_QUESTIONS

kremle = KremleFlask(
    app,
    extra_questions=MY_QUESTIONS,   # свои вопросы добавятся к встроенным
)
```

Если нужны **только** свои вопросы (без встроенных ЕГЭ):

```python
kremle = KremleFlask(
    app,
    extra_questions=MY_QUESTIONS,
    only_extra=True,
)
```

**Django** — в `settings.py`:

```python
from questions import MY_QUESTIONS

KREMLE_EXTRA_QUESTIONS = MY_QUESTIONS
KREMLE_ONLY_EXTRA = False   # True — только свои вопросы
```

**FastAPI** — в `main.py`:

```python
from kremle_detect.integrations.fastapi_ext import KremleFastAPI
from questions import MY_QUESTIONS

kremle = KremleFastAPI(
    app,
    extra_questions=MY_QUESTIONS,
)
```

### Формат вопроса

Каждый вопрос — словарь. Три обязательных поля:

| Поле   | Тип    | Требование                                             |
|--------|--------|--------------------------------------------------------|
| `q`    | `str`  | Непустая строка — текст вопроса                        |
| `opts` | `list` | Список строк, **минимум 2** варианта ответа            |
| `ans`  | `int`  | Индекс правильного варианта в `opts`, начиная с **0** |

Одно необязательное поле:

| Поле       | Тип   | Описание                                          |
|------------|-------|---------------------------------------------------|
| `category` | `str` | Подпись категории на карточке вопроса (любая строка) |

Как работает `ans` — индекс в списке `opts`:

```python
"opts": ["Неверно", "Верно", "Не знаю"],
#             0         1        2
"ans": 1   # правильный ответ — "Верно"
```

### Что нельзя

```python
# ❌ ans выходит за пределы списка opts (здесь допустимо только 0 или 1)
{"q": "Вопрос?", "opts": ["А", "Б"], "ans": 2}

# ❌ менее двух вариантов ответа
{"q": "Вопрос?", "opts": ["Единственный"], "ans": 0}

# ❌ пустой текст вопроса
{"q": "", "opts": ["А", "Б"], "ans": 0}

# ❌ ans — не целое число
{"q": "Вопрос?", "opts": ["А", "Б"], "ans": "0"}
```

Все ошибки выбрасываются при старте приложения (`ValueError`), а не во время запроса — неправильный вопрос не дойдёт до пользователя.

### Проверить список вручную перед запуском

```python
from kremle_detect.questions import validate_questions
from questions import MY_QUESTIONS

validate_questions(MY_QUESTIONS)  # бросает ValueError с описанием ошибки
print("Все вопросы корректны")
```

## Категории вопросов

| Категория    | Описание                                      |
|-------------|-----------------------------------------------|
| `math`       | Задания из ЕГЭ по профильной математике       |
| `physics`    | Задания из ЕГЭ по физике                      |
| `russian`    | Каверзные вопросы по русскому языку            |
| `literature` | Сложные вопросы по русской литературе          |

По 15 вопросов в каждой категории, итого 60 вопросов в банке.

## Детекция

Модуль определяет пользователей Яндекса по нескольким сигналам:

- **User-Agent** — YaBrowser, YaApp, YandexSearch, YandexStation
- **Яндекс-боты** — YandexBot, YandexMetrika, YandexImages и 20+ ботов
- **Referer** — переходы с yandex.ru/com/by/kz и всех TLD, ya.ru, dzen.ru, zen.yandex, market.yandex и др.
- **Client Hints** — заголовки Sec-CH-UA с маркером YaBrowser/Yandex
- **JS fingerprint** — клиентская проверка через `navigator.userAgentData`, `window.yandex`, `window.Ya`

## Redis (production)

По умолчанию челленджи хранятся в памяти (подходит для одного процесса).
Для production с несколькими воркерами — используй Redis:

```python
from kremle_detect import RedisStorage

kremle = KremleFlask(
    app,
    storage=RedisStorage(url='redis://localhost:6379/0'),
)
```

## Rate limiting

Защита от брутфорса — ограничение попыток `/kremle/verify` с одного IP:

```python
kremle = KremleFlask(
    app,
    rate_limit=10,     # макс. 10 попыток
    rate_window=600,   # за 10 минут
)
```

`rate_limit=0` — отключить.

## IP whitelist

Пропускать определённые IP/подсети без проверки:

```python
kremle = KremleFlask(
    app,
    whitelist=['127.0.0.1', '10.0.0.0/8', '192.168.0.0/16'],
)
```

## Кастомный шаблон капчи

```python
kremle = KremleFlask(app, template='/path/to/my_captcha.html')
```

В шаблоне используй `{{ questions_json }}` — туда подставятся данные.

## Callbacks (webhooks)

```python
def on_detect(result, ip):
    print(f'Яндекс-пользователь: {ip}, причина: {result.reason}')

def on_pass(ip, errors, total):
    print(f'{ip} прошёл капчу ({errors}/{total} ошибок)')

def on_fail(ip, errors, total):
    print(f'{ip} завалил капчу ({errors}/{total} ошибок)')

kremle = KremleFlask(
    app,
    on_detect=on_detect,
    on_pass=on_pass,
    on_fail=on_fail,
)
```

## Логирование

Все события пишутся в логгер `kremle`:

```python
import logging
logging.getLogger('kremle').setLevel(logging.INFO)
```

## React-компонент

Для SPA на React установи `kremle-react` из папки `kremle-react/` в репозитории:

```bash
npm install /path/to/KremleXYZ-Detect/kremle-react
# или после публикации на npm:
# npm install kremle-react
```

**Готовый компонент:**

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

**Хук для кастомного UI:**

```tsx
import { useKremle } from 'kremle-react'

function MyCaptcha() {
  const { questions, answers, setAnswer, submit, loading, result } = useKremle()

  if (loading) return <div>Загрузка...</div>

  return (
    <form onSubmit={(e) => { e.preventDefault(); submit() }}>
      {questions.map((q, qi) => (
        <div key={qi}>
          <p>{q.q}</p>
          {q.opts.map((opt, oi) => (
            <label key={oi}>
              <input type="radio" onChange={() => setAnswer(qi, oi)} />
              {opt}
            </label>
          ))}
        </div>
      ))}
      <button type="submit">Отправить</button>
    </form>
  )
}
```

Экспорты пакета: `KremleChallenge`, `useKremle`, типы `KremleResult`, `KremleQuestion`.

Требует: React ≥ 17, FastAPI с `headless=True`.

## API роуты

| Метод | Путь                | Описание                                            |
|-------|--------------------|----------------------------------------------------|
| GET   | `/kremle/challenge` | HTML-страница капчи (или JSON в headless-режиме)  |
| POST  | `/kremle/verify`    | Проверка ответов (JSON)                            |
| GET   | `/kremle/status`    | Статус верификации сессии (JSON)                  |

## CLI

После установки доступна команда `kremle-detect`. Для работы с блоклистом, вайтлистом и логами нужен Redis.

```bash
# Полный список команд
kremle-detect help
```

### Диагностика

```bash
kremle-detect check-ua "Mozilla/5.0 YaBrowser/24.1"
kremle-detect check-ref "https://yandex.ru/search?q=test"
kremle-detect check-hints '"YaBrowser";v="24"'
kremle-detect questions --category math --count 5
```

### Блоклист

```bash
kremle-detect blacklist list   --redis redis://localhost:6379/0
kremle-detect blacklist add    1.2.3.4 --redis redis://localhost:6379/0
kremle-detect blacklist add    1.2.3.4 --ttl 3600   # заблокировать на 1 час
kremle-detect blacklist remove 1.2.3.4 --redis redis://localhost:6379/0
```

### Вайтлист

```bash
kremle-detect whitelist list   --redis redis://localhost:6379/0
kremle-detect whitelist add    1.2.3.4 --redis redis://localhost:6379/0
kremle-detect whitelist remove 1.2.3.4 --redis redis://localhost:6379/0
```

### Логи событий

```bash
kremle-detect logs              --redis redis://localhost:6379/0
kremle-detect logs -n 200       # последние 200 событий
kremle-detect logs --no-color   # без цвета (для grep/pipe)
```

Типы событий: `ПРОШЁЛ` (капча пройдена), `ПРОВАЛ` (не прошёл), `ДЕТЕКТ` (Яндекс-пользователь пойман), `ЗАБЛОК` (IP заблокирован или rate limit).

Redis URL можно задать через переменную окружения вместо флага `--redis`:

```bash
export KREMLE_REDIS_URL=redis://localhost:6379/0
kremle-detect logs
kremle-detect blacklist list
```

## Лицензия

MIT
