# kremle-detect

Защита сайта от пользователей Яндекс Браузера и переходов с поисковика Яндекс.
При детекции показывает капчу с вопросами из ЕГЭ по математике, физике, русскому языку и литературе.

## Установка

```bash
pip install kremle-detect
```

С зависимостями для конкретного фреймворка:

```bash
pip install kremle-detect[flask]
pip install kremle-detect[django]
pip install kremle-detect[fastapi]
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

## API роуты

| Метод | Путь                | Описание                           |
|-------|--------------------|------------------------------------|
| GET   | `/kremle/challenge` | HTML-страница капчи               |
| POST  | `/kremle/verify`    | Проверка ответов (JSON)           |
| GET   | `/kremle/status`    | Статус верификации сессии (JSON)  |

## Лицензия

MIT
