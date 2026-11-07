<div align="center">

# kremle-detect

**Капча-фильтр по браузеру.**
Яндекс Браузер, Яндекс-боты и переходы с Яндекса получают капчу с вопросами ЕГЭ.
Все остальные проходят сразу.

[Установка](docs/install.md) · [Быстрый старт](docs/integrations/flask.md) · [Детекция](docs/detection.md) · [Капча](docs/captcha.md) · [Вопросы](docs/questions.md) · [Эксплуатация](docs/operations.md) · [Безопасность](docs/security.md) · [FAQ](docs/faq.md) · [Роадмап](ROADMAP.md)

[![license](https://img.shields.io/badge/license-MIT-0b3d91?style=flat-square)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square)](pyproject.toml)
[![version](https://img.shields.io/badge/version-2.9.0-111111?style=flat-square)](CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-625%20passed%20%2B%2026%20react-2ea44f?style=flat-square)](docs/testing.md)
[![security](https://img.shields.io/badge/security-policy-0b3d91?style=flat-square)](SECURITY.md)

`#капча` `#яндекс` `#антибот` `#flask` `#django` `#fastapi` `#react` `#python` `#security` `#rate-limiting`

</div>

> **«Капча — всенародное дело».** Пока западные подписки продают вам защиту и
> забирают данные, здесь всё своё: вопросы из русской школы, ключи у себя,
> данные не покидают контур. ЕГЭ сдавали все — сдадут и боты.

## За державу

Проект вырос из русской школы задач: математика, физика, русский язык,
литература — то, что человек должен знать, и то, что машина обязана выучить
прежде, чем получить доступ. Ни одной внешней зависимости у ядра, ни одного
запроса к чужим сервисам ради «улучшения продукта», ни одной строки телеметрии.
Так и надо работать: тихо, надёжно, по-своему.

## Быстрый старт

```python
from flask import Flask
from kremle_detect.integrations.flask_ext import KremleFlask

app = Flask(__name__)
app.secret_key = 'change-me'

KremleFlask(app, question_count=15, max_errors=3)
```

Две строки — и рубеж обороны стоит. Flask, Django, FastAPI или голое ядро —
выбирайте по инструменту, а не по указке.

Можно сначала посмотреть, а не блокировать: `policy={'yandex_browser': 'monitor'}`.
Демо за минуту — [в установке](docs/install.md#демо-за-минуту).

## Духовные скрепы проекта

| Скрепа | Как исполняется |
|---|---|
| **Суверенитет** | ядро без зависимостей, никакой телеметрии, ключи только ваши, `detect()` — чистая функция |
| **Традиционные ценности** | вопросы ЕГЭ, а не «выберите все квадратики с светофором» |
| **Соборность** | один шаблон и один протокол для Flask, Django, FastAPI и React |
| **Преемственность** | API не ломается в 2.x; всё, что ломает, копится до 3.0 |
| **Правда в отчётности** | 625 тестов, coverage 92 %, порог в CI — 85 %, никаких «почти зелёных» |
| **Почитание старших** | задания портала «Решу ЕГЭ» с обязательной атрибуцией |
| **Нестяжательство** | новая зависимость — только если без неё никак |
| **Оборона, а не нападение** | фильтр защищает свой сайт, а не ходит по чужим |

## Пятилетка за три года

- **2.9.0** — честный результат, таймер, ротация вопросов, доступность *(сдано)*;
- **2.10** — безопасность: экранирование, CSP, секрет и ротация, SBOM *(очередь)*;
- **2.11** — охват: vanilla-виджет, образ в GHCR, сайт документации, переключатель источников вопросов;
- **2.12** — эксплуатация: health со свежестью кеша, адаптивная сложность, mypy;
- **3.0** — платформа: plugin API источников, нативный async-движок.

Подробно, с приёмкой по каждому пункту — [ROADMAP.md](ROADMAP.md).

## Документация

README — это вывеска. Вся документация живёт в [`docs/`](docs/index.md) и
собирается в сайт (`mkdocs build --strict` в CI: битые ссылки роняют сборку).

| Раздел | О чём |
|---|---|
| [docs/index.md](docs/index.md) | карта документации |
| [docs/install.md](docs/install.md) | extras, установка из git, демо, Docker, смоук |
| [docs/detection.md](docs/detection.md) | что считается Яндексом: UA, реферер, Client Hints, фингерпринт |
| [docs/integrations/](docs/integrations/flask.md) | [Flask](docs/integrations/flask.md) · [Django](docs/integrations/django.md) · [FastAPI](docs/integrations/fastapi.md) · [голое ядро](docs/integrations/bare-core.md) · [SPA и JSON](docs/integrations/spa.md) |
| [docs/react.md](docs/react.md) | `kremle-react`: компонент, хук, таймер, атрибуция |
| [docs/captcha.md](docs/captcha.md) | токен, порог ошибок, таймер, ротация, доступность, свой шаблон |
| [docs/questions.md](docs/questions.md) | банк, «Решу ЕГЭ», свои вопросы, дистракторы |
| [docs/images.md](docs/images.md) | задания с рисунком, локальный кеш, проверка без Яндекса |
| [docs/operations.md](docs/operations.md) | Redis, лимиты, прокси, monitor-режим, health/stats/metrics, callbacks |
| [docs/api.md](docs/api.md) | все роуты, коды ошибок, `Retry-After`, `no-store` |
| [docs/cli.md](docs/cli.md) | `kremle-detect`: диагностика, вопросы, блоклист, демо, логи |
| [docs/security.md](docs/security.md) | что защищено, что пока нет, требования к продакшену |
| [docs/development.md](docs/development.md) | окружение, структура, релизный цикл |
| [docs/testing.md](docs/testing.md) | наборы тестов, Redis, e2e, нагрузочный смоук |
| [docs/release.md](docs/release.md) | тег, PyPI OIDC, npm trusted publishing и staged |
| [docs/faq.md](docs/faq.md) | `invalid_token`, 429, «ошибка соединения», воркеры |

Правила приёма изменений — [CONTRIBUTING.md](CONTRIBUTING.md). Полная история
версий — [CHANGELOG.md](CHANGELOG.md). Политика раскрытия уязвимостей —
[SECURITY.md](SECURITY.md).

```bash
pip install mkdocs-material
mkdocs serve            # локальный сайт на http://127.0.0.1:8000
mkdocs build --strict   # проверка ссылок, как в CI
```

## Кадры решают всё

Проект держится на трёх китах, и ни один не заменяется лозунгом:

1. **Код** — 6 500 строк библиотеки, 6 300 строк тестов — почти один к одному. Тест
   пишется до фикса, а не после отчёта.
2. **Интеграции** — Flask, Django, FastAPI, голое ядро, React, CLI, демо-сервер.
   Паритет роутов и настроек, без «в этом фреймворке почти работает».
3. **Эксплуатация** — Redis, лимиты, прокси, health/stats/metrics, Prometheus,
   ежедневная проверка живого портала.

## Лицензия

MIT — см. [LICENSE](LICENSE). Берите, ставьте, дорабатывайте под себя. Но
чужие задания не присваивайте: атрибуция «Задания: Решу ЕГЭ» остаётся на месте.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
