# Эксплуатация

> «Что не измеряется — того не существует. Что не мониторится — то уже упало.»

## Хранилище

По умолчанию — `MemoryStorage` (один процесс). Для нескольких воркеров — Redis:

```python
from kremle_detect import RedisStorage

kremle = KremleFlask(app, storage=RedisStorage(url='redis://localhost:6379/0'))
```

`RedisStorage` принимает `redis_client=...` (готовый клиент) и `prefix='kremle:'`.
Инкремент счётчиков атомарный (Lua), TTL ставится один раз — fixed window.

В хранилище живут: челленджи (`challenge:<token>`, 15 минут), счётчики лимитов,
блоклист, вайтлист, кольцевой лог событий (последние 1000) и история ротации
вопросов (`recentq:<категории>`, 6 часов).

**Без Redis** несколько воркеров — это несколько независимых лимитов и сессий:
капча будет «забывать» прохождение при переходе на другой процесс.

### Async

FastAPI вызывает движок из `async def`; синхронный Redis-клиент блокировал бы
event loop. Варианты:

```python
from kremle_detect.storage import RedisStorage
from kremle_detect.storage_async import AsyncRedisStorage, AsyncStorageAdapter

# оффлоад в threadpool (по умолчанию): обычный RedisStorage
KremleFastAPI(app, async_offload=True)

# настоящий async-клиент
storage = AsyncStorageAdapter(AsyncRedisStorage(url='redis://localhost:6379/0'))
```

Лимиты — это не наказание, а дисциплина: считаем только неудачи, успех снимает
всякую вину. Кто пришёл с добрыми намерениями, никогда не упрётся в лимит.

## Rate limiting

```python
kremle = KremleFlask(
    app,
    rate_limit=10,        # 10 НЕУДАЧНЫХ проверок
    rate_window=600,      # за 10 минут
    challenge_rate_limit=60,   # 60 выдач челленджа с IP за окно
)
```

- Считаются только неудачные проверки. Успех сбрасывает счётчик — честный
  человек не блокирует себя сам.
- `rate_limit=0` — выключить.
- `challenge_rate_limit` защищает хранилище от забивания челленджами.
- Превышение → `429` с `Retry-After: <окно в секундах>`; клиенту не нужно
  угадывать паузу.

## IP, прокси, whitelist, blacklist

`X-Forwarded-For` принимается только от доверенных прокси. По умолчанию
доверяем loopback и приватным сетям (nginx на том же хосте, docker, k8s).

```python
KremleFlask(
    app,
    trusted_proxies=['10.0.0.0/8', '172.16.0.0/12'],   # None → авто, [] → никому
    whitelist=['203.0.113.0/24'],                       # эти проходят всегда
)
```

Публичный балансировщик (Cloudflare, облачный LB) нужно добавить в
`trusted_proxies` — иначе в лог уйдёт предупреждение о недоверенном адресе, а
лимиты будут считаться по IP балансировщика.

Блоклист:

```bash
kremle-detect blacklist add 203.0.113.7 --ttl 86400
kremle-detect blacklist list
kremle-detect whitelist add 198.51.100.0/24
```

`fail_threshold=N` — автоблокировка после N провалов подряд (по умолчанию 0,
выключено). `blacklist_ttl` — сколько держать (сутки по умолчанию).

## Monitor-режим

Сначала посмотреть, никого не блокируя:

```python
kremle = KremleFlask(
    app,
    policy={
        'yandex_bot': 'block',        # боты — сразу 403, капча им не поможет
        'yandex_browser': 'monitor',  # считать, но пропускать (shadow)
        'yandex_referrer': 'challenge',
    },
    sample_rate=0.1,                  # под фильтр только 10 % трафика
)
```

`monitor` увеличивает счётчик `shadow_total`, но запрос пропускает. Через сутки
`/kremle/stats` показывает, скольких живых людей заденет блокировка, — и это
обычно и есть ответ на вопрос, стоит ли оно того.

## Эксплуатация: health, stats, metrics

Все три фреймворка отдают одинаковый набор роутов (`enable_ops_routes=False` /
`KREMLE_ENABLE_OPS_ROUTES = False` — выключить):

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/kremle/health` | `200` `{"status": "ok", "version", "storage", "storage_ok"}`, `503` при недоступном хранилище |
| GET | `/kremle/stats` | JSON-снапшот счётчиков |
| GET | `/kremle/metrics` | Prometheus text |

```jsonc
// GET /kremle/stats
{
  "requests_total": 1024, "detected_total": 310, "allowed_total": 690,
  "detected_by_reason": {"yandex_bot": 4, "yandex_browser": 290},
  "actions": {"challenge": 250, "block": 4, "monitor": 56, "allow": 0},
  "challenges_issued": 250, "verify_total": 231, "pass_total": 190, "fail_total": 41,
  "blocked_by_reason": {"blacklisted": 0, "rate_limited": 23},
  "shadow_total": 56, "pass_rate": 0.82
}
```

Метрики Prometheus: `kremle_requests_total`, `kremle_allowed_total`,
`kremle_detected_total{reason}`, `kremle_action_total{action}`,
`kremle_challenges_total`, `kremle_verify_total`, `kremle_captcha_total`,
`kremle_blocked_total{reason}`.

`/kremle/health` годится для `livenessProbe`/`readinessProbe`: `503` означает, что
Redis недоступен и капча не сможет сохранить челлендж.

!!! warning "Публичные роуты"
`/kremle/stats`, `/kremle/metrics` и `/kremle/health` не требуют авторизации.
Закройте их на прокси или фаерволом, если цифры не для всех.
:::

## Callbacks и логи

```python
def on_detect(ip, reason, path):
    log.info('%s: %s на %s', ip, reason, path)

def on_pass(ip, errors, total):
    log.info('%s прошёл (%s/%s)', ip, errors, total)

def on_fail(ip, errors, total):
    log.warning('%s завалил (%s/%s)', ip, errors, total)

KremleFlask(app, on_detect=on_detect, on_pass=on_pass, on_fail=on_fail)
```

Библиотека пишет в логгер `kremle`:

```python
import logging
logging.getLogger('kremle').setLevel(logging.INFO)
```

События дублируются в кольцевой лог хранилища (последние 1000):

```bash
kremle-detect logs -n 50
```

Порядок в хозяйстве начинается с расписания: кеш вопросов обязан обновляться,
а не лежать десятилетней картошкой в подвале.

## Планировщик для вопросов

Кеш «Решу ЕГЭ» статичен: его надо обновлять, иначе задания устареют. В
репозитории есть готовый пример — ежедневный workflow, который делает
`questions sync` и перекачивает картинки:

```yaml
- run: kremle-detect questions sync -n 60 --download
```

Если `sync` падает (портал недоступен, поменялась разметка), это должно быть
видно: у нас это отдельный шаг с `::error` и хвостом лога в аннотации, а не
«зелёный» прогон, после которого капча месяц работает на встроенном банке.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
