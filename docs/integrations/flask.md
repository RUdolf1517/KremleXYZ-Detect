# Flask

> «Две строки кода — и рубеж обороны стоит.» — из наставления молодым кадрам

## Минимум

```python
from flask import Flask
from kremle_detect.integrations.flask_ext import KremleFlask

app = Flask(__name__)
app.secret_key = 'change-me'          # или secret='...' явно

KremleFlask(
    app,
    categories=['math', 'physics', 'russian', 'literature'],
    question_count=15,
    max_errors=3,
)
```

Гард включается автоматически на все роуты (`auto_guard=True`). Роуты капчи
регистрируются в blueprint `kremle`: `/kremle/challenge`, `/kremle/verify`,
`/kremle/status`, `/kremle/logout`, `/kremle/img/<key>` и ops-роуты.

Flask выбран не случайно: лёгкий, понятный, без заморских церемоний. Как и
положено хорошему инструменту — молчит, пока его не спросят, и делает дело,
когда спрашивают.

## Паттерн app factory

```python
kremle = KremleFlask()          # без app

def create_app():
    app = Flask(__name__)
    app.secret_key = 'change-me'
    kremle.init_app(app)
    return app
```

## Что пропускать

```python
KremleFlask(
    app,
    skip_endpoints=['static', 'healthz', 'api.ping'],   # имена эндпоинтов Flask
    whitelist=['10.0.0.0/8', '192.168.0.0/16'],          # IP и подсети
)
```

`skip_endpoints` — для статики, вебхуков и мониторинга: их опрашивают машины,
капча им только мешает.

## Свои обработчики

```python
def on_detect(ip, reason, path):
    app.logger.info('яндекс-сигнал %s от %s на %s', reason, ip, path)

def on_pass(ip, errors, total):
    app.logger.info('%s прошёл капчу (%s/%s)', ip, errors, total)

def on_fail(ip, errors, total):
    app.logger.warning('%s завалил капчу (%s/%s)', ip, errors, total)

KremleFlask(app, on_detect=on_detect, on_pass=on_pass, on_fail=on_fail)
```

Исключение внутри обработчика не должно ломать запрос — но лучше не проверять
это на бою: оберните свой код в `try/except` сами.

## Свой шаблон

```python
KremleFlask(app, template='/path/to/my_captcha.html')
```

Шаблон читается как текст (не Jinja2) и одинаково работает во всех трёх
фреймворках. Обязательна подстановка `{{ questions_json }}` — туда приходит
JSON `{questions, token, created_at, verify_url, expires_in, max_errors, sources,
attribution}`. Подробнее — [Капча: свой шаблон](../captcha.md#свой-шаблон).

## Заголовки безопасности и CSP

На `/kremle/challenge`, `/kremle/verify`, `/kremle/status` и `/kremle/logout`
уходят `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer` и CSP, совместимая со штатным шаблоном (inline
скрипт и стили). Капчу нельзя встроить в чужую страницу и подменить.

```python
KremleFlask(app, csp_policy="default-src 'none'; script-src 'unsafe-inline'; "
                            "style-src 'unsafe-inline'; frame-ancestors 'none'")
KremleFlask(app, csp_policy='')     # свой шаблон со внешними скриптами — CSP не шлём
```

Что ломается при ужесточении — в [Безопасность: CSP](../security.md#csp-как-ужесточить-и-что-сломается).

## Смена секрета без разрыва капч

`secret` принимает список: первый ключ подписывает новые токены, все —
проверяют старые. Активные капчи (TTL 15 минут) переживут смену ключа.

```python
KremleFlask(app, secret=['новый-ключ', 'старый-ключ'])   # старый убрать через 15 минут
```

## Настройки

Flask-интеграция настраивается только аргументами конструктора и не читает
`app.config`: так поведение видно в одном месте, а не размазано по трём
источникам. Переменные окружения (`KREMLE_SECRET`, `KREMLE_REDIS_URL`,
`KREMLE_DEMO_POLICY`) относятся к демо-серверу `kremle-detect serve`, а не к
вашему приложению.

## Проверка

```python
# в тестах приложения капча обычно мешает: выключите авто-гард
KremleFlask(app, auto_guard=False)
```

Или подмените клиента:

```python
headers = {'User-Agent': 'Mozilla/5.0 ... Chrome/120.0 Safari/537.36'}
assert app.test_client().get('/api', headers=headers).status_code == 200
```

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
