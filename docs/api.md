# API-роуты

> «У каждой двери должен быть номер. У каждой двери — свой устав.»

Все три интеграции отдают одинаковый набор роутов с префиксом `/kremle/`.

| Метод | Путь | Описание |
|---|---|---|
| GET | `/kremle/challenge` | HTML-капча; JSON при `Accept: application/json` или `headless` |
| POST | `/kremle/verify` | проверка ответов (JSON) |
| GET | `/kremle/status` | `{"verified": bool, "expires_in": int\|null, "pending": bool, "reason": str\|null, "challenge_url": str\|null, "overlay": bool}` |
| POST | `/kremle/logout` | сбросить «капча пройдена» (можно перепройти) |
| GET | `/kremle/health` | health-check для монитора |
| GET | `/kremle/stats` | счётчики в JSON |
| GET | `/kremle/metrics` | счётчики в формате Prometheus |
| GET | `/kremle/img/<key>` | рисунок задания из локального кеша (`Cache-Control: immutable`) |

## Кеширование

Ответы `/kremle/challenge` и JSON-блокировки отдаются с `Cache-Control: no-store` —
токен не должен попасть в кеш ни браузера, ни прокси. Рисунки задания, наоборот,
`immutable`: ключ — первые 32 hex-символа sha256 от адреса, содержимое не меняется.

## Лимиты и коды

`429` — если сработал `challenge_rate_limit` или `rate_limited`. В ответе есть
`Retry-After` с окном лимита в секундах (по умолчанию 600): клиенту не нужно
угадывать паузу.

Коды ошибок `/kremle/verify`:

| `error` | Что значит | `errors` |
|---|---|---|
| — | обычный результат | `0..total` |
| `invalid_token` | токен истёк, уже использован или отсутствует | `-1` |
| `rate_limited` | исчерпан лимит неудачных проверок с IP | `-1` |
| `blacklisted` | IP в блоклисте | `-1` |
| `invalid_answers` | `answers` — не объект | `-1` |
| `no_questions` | банк вопросов пуст, челлендж собрать не из чего | `0` |

## Тело ответов

```jsonc
// GET /kremle/status (2.13.0: добавлены поля для окна поверх страницы)
{"verified": false, "expires_in": null, "pending": true,
 "reason": "yandex_referrer", "challenge_url": "/kremle/challenge", "overlay": true}
```

`verified` считается по тем же правилам, что и в гарде: TTL отметки, `bind_ip`,
`bind_ua`. Если гард снова требует капчу, `/kremle/status` тоже говорит
`verified: false` — иначе окно поверх страницы не открывалось бы после смены IP.

```jsonc
// GET /kremle/challenge (JSON-режим)
{"questions": [{"q": "...", "opts": ["...", "..."], "category": "math"}],
 "token": "...", "verify_url": "/kremle/verify",
 "expires_in": 899, "max_errors": 3,
 "sources": [{"name": "РешуЕГЭ", "url": "https://...", "author": "..."}],
 "attribution": "Задания: РешуЕГЭ"}

// POST /kremle/verify
{"passed": true, "errors": 1, "total": 15, "max_errors": 3, "redirect": "/"}

// GET /protected → 403 (JSON-гард)
{"error": "captcha_required", "reason": "yandex_browser", "challenge_url": "/kremle/challenge"}

// GET /protected → 403 (политика block)
{"error": "blocked", "action": "block", "challenge_url": null}
```

## Health, stats, metrics

Ответы и поля — в разделе [Эксплуатация](operations.md#эксплуатация-health-stats-metrics).
Коротко: `/kremle/health` → `200` при живом хранилище и `503` при недоступном;
полезна для `livenessProbe`/`readinessProbe` и внешнего монитора. В теле есть блок
`questions` (сколько вопросов и насколько свеж кеш «Решу ЕГЭ») и список
`reasons`; `status: degraded` при устаревшем кеше, но код по-прежнему `200`.

## Телеметрия

Всё необязательное и по умолчанию выключено (extras `[otel]`):

```python
from kremle_detect.telemetry import setup_tracing, setup_json_logs

setup_tracing(service_name='my-site', endpoint='http://localhost:4318')
setup_json_logs()
```

Спаны `kremle.challenge` и `kremle.verify`, поля и приватность — в разделе
[Трассировка и JSON-логи](operations.md#трассировка-и-json-логи).

!!! warning "Публичные роуты"
    `/kremle/stats`, `/kremle/metrics` и `/kremle/health` по умолчанию не требуют
    авторизации. Закройте их на прокси или выключите (`enable_ops_routes=False`),
    если цифры не для всех.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
