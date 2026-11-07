# Голое ядро

> «Ядро без единой внешней зависимости — это не аскетизм, это суверенитет.»

Интеграций три, а фреймворков больше. Ядро не зависит ни от одного из них:
`CaptchaEngine` умеет создать челлендж и проверить ответы, а показать HTML и
разобрать запрос — ваша задача.

Интеграций три, а фреймворков больше — и правильно: ядро одно, обёрток много,
каждый работает со своим инструментом, а не переучивается под чужой.

## Detection

```python
from kremle_detect import detect

result = detect({
    'User-Agent': 'Mozilla/5.0 ... YaBrowser/24.1 ...',
    'Referer': 'https://yandex.ru/search/?text=...',
    'Sec-CH-UA': '"Yandex";v="24"',
})

if result:
    print(result.reason)   # yandex_browser | yandex_bot | yandex_referrer | yandex_client_hints
```

`detect()` ничего не делает с запросом: возвращает результат или `None`.
Решение (капча, блок, пропуск) принимает ваш код.

## Капча

```python
from kremle_detect import CaptchaEngine

engine = CaptchaEngine(
    categories=['math', 'russian'],
    question_count=10,
    max_errors=2,
    secret='my-secret-key',          # обязательно свой, не дефолтный
)

challenge = engine.create_challenge()
data_for_client = challenge.to_dict(max_errors=engine.max_errors)
# → {'questions': [...], 'token': '...', 'expires_in': 899, 'max_errors': 2, ...}

verification = engine.verify(challenge.token, {'0': 0, '1': 2}, ip=client_ip)
if verification['passed']:
    print('Человек подтверждён')
```

Что важно знать:

- в `data_for_client` **нет правильных ответов** — `safe_questions` вырезает `ans`;
- токен одноразовый: сгорает после любой проверки, повторная попытка получит
  `invalid_token`;
- `verify()` возвращает `{'passed', 'errors', 'total', 'max_errors'}` —
  `max_errors` фактический, с учётом строгого режима и подрезки;
- `expires_in` — сколько секунд осталось жить челленджу (по умолчанию 900).

## Показать HTML

```python
from pathlib import Path
import json

template = Path('kremle_captcha.html').read_text(encoding='utf-8')
html = template.replace('{{ questions_json }}', json.dumps(data_for_client, ensure_ascii=False))
```

Шаблон по умолчанию лежит в пакете:

```python
from importlib.resources import files
template = (files('kremle_detect') / 'templates' / 'kremle_captcha.html').read_text(encoding='utf-8')
```

Обратите внимание: подстановка — простая замена строки, поэтому текст вопроса
с `</script>` внутри нужно экранировать самому (в 2.10 это будет делать
библиотека, см. [issue #27](https://github.com/RUdolf1517/KremleXYZ-Detect/issues/27)).

## Сессия «капча пройдена»

Формат отметки — обычный словарь, его можно положить в любую сессию: Flask,
Django, Starlette или свою.

```python
from kremle_detect.session import (
    SESSION_KEY, build_verification, is_verified, remaining_seconds,
)

# после успешной проверки
session[SESSION_KEY] = build_verification(ip=client_ip, ua=user_agent, ttl=86400)

# на каждом запросе
if is_verified(session.get(SESSION_KEY), ip=client_ip, ua=user_agent):
    ...   # пропускаем

left = remaining_seconds(session.get(SESSION_KEY))   # сколько ещё действует
```

`is_verified` проверяет срок и, если включены привязки, IP и отпечаток
`User-Agent`. Старый флаг `session['kremle_ok'] = True`, записанный версией
≤ 2.6, считается просроченным: один раз перепройти — зато вечного прохода с
одной куки больше нет.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
