# kremle-detect

**Капча-фильтр по браузеру.** Яндекс Браузер, Яндекс-боты и переходы с Яндекса
получают капчу с вопросами ЕГЭ. Все остальные проходят сразу.

Библиотека не «антибот» и не обещает им быть: она отсекает живых людей с
конкретным браузером и поисковым переходом. Об этом честно написано в разделе
[Безопасность](security.md) — прочитайте его до включения на боевом трафике.

## Тридцать секунд до первой капчи

```python
from flask import Flask
from kremle_detect.integrations.flask_ext import KremleFlask

app = Flask(__name__)
app.secret_key = 'change-me'

KremleFlask(app, question_count=15, max_errors=3)
```

Две строки — и фильтр работает. Дальше по вкусу:

- посмотреть, не блокируя: `policy={'yandex_browser': 'monitor'}` —
  [Monitor-режим](operations.md#monitor-режим);
- своя капча в SPA: [JSON-API](integrations/spa.md);
- свои вопросы вместо ЕГЭ: [Вопросы](questions.md#свои-вопросы).

## Куда дальше

| Раздел | О чём |
|---|---|
| [Установка](install.md) | extras, демо за минуту, Docker |
| [Flask](integrations/flask.md) · [Django](integrations/django.md) · [FastAPI](integrations/fastapi.md) | быстрый старт по фреймворкам |
| [Голое ядро](integrations/bare-core.md) | любой фреймворк, без интеграции |
| [SPA и JSON](integrations/spa.md) | `fetch`, 403 в JSON, headless-режим |
| [Капча](captcha.md) | токен, порог ошибок, таймер, ротация, доступность |
| [Вопросы](questions.md) | встроенный банк, «Решу ЕГЭ», картинки, свои задания |
| [Эксплуатация](operations.md) | хранилище, лимиты, health/stats/metrics, прокси, callbacks |
| [Безопасность](security.md) | что защищено, что нет, как сообщить об уязвимости |
| [Разработка](development.md) | тесты, линтер, релизный цикл |
| [FAQ](faq.md) | частые вопросы и грабли |

## Что уже работает

```bash
pip install "kremle-detect[all]"      # Flask + Django + FastAPI + Redis
kremle-detect serve                    # демо на http://localhost:8000
kremle-detect questions sync -n 50     # скачать задания «Решу ЕГЭ» в кеш
```

- **Интеграции:** Flask, Django, FastAPI — паритет роутов и настроек.
- **Капча:** вопросы ЕГЭ, картинки в заданиях, честный результат, таймер,
  доступная разметка, ротация вопросов.
- **Эксплуатация:** Redis, rate limit, IP за прокси, блоклист, health/stats/metrics,
  Prometheus.
- **React:** `npm install kremle-react` — тот же протокол, свои темы.

Версия 2.9.0. Что дальше — в [ROADMAP.md](https://github.com/RUdolf1517/KremleXYZ-Detect/blob/main/ROADMAP.md).
