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

Можно добавить свои вопросы в дополнение к встроенным (или вместо них):

```python
my_questions = [
    {
        "q": "Столица России?",
        "opts": ["Москва", "Питер", "Новосибирск", "Екатеринбург"],
        "ans": 0,  # индекс правильного варианта
    },
    {
        "q": "Сколько будет 2 + 2?",
        "opts": ["4", "5", "22", "3"],
        "ans": 0,
    },
]

# Смешать свои вопросы с встроенными
engine = CaptchaEngine(extra_questions=my_questions)

# Только свои вопросы (встроенные отключены)
engine = CaptchaEngine(extra_questions=my_questions, only_extra=True)
```

Формат вопроса:
- `q` — текст вопроса (строка)
- `opts` — список вариантов ответа (минимум 2)
- `ans` — индекс правильного варианта в `opts` (начиная с 0)

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

## API роуты

| Метод | Путь                | Описание                           |
|-------|--------------------|------------------------------------|
| GET   | `/kremle/challenge` | HTML-страница капчи               |
| POST  | `/kremle/verify`    | Проверка ответов (JSON)           |
| GET   | `/kremle/status`    | Статус верификации сессии (JSON)  |

## Лицензия

MIT
