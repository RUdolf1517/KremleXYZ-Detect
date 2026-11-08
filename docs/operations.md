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

## Адаптивная сложность

Блокировка — крайняя мера, а не первая: человек мог просто ошибиться. Поэтому
до блоклиста включается ужесточение.

```python
kremle = KremleFlask(
    app,
    adaptive=True,                  # по умолчанию включено
    adaptive_threshold=3,           # 3 провала подряд — первая ступень
    adaptive_extra_questions=2,     # +2 вопроса и -1 к порогу ошибок
)
```

| Провалов подряд | Вопросов | Порог ошибок |
|---|---|---|
| 0–2 | 5 | 2 |
| 3–5 | 7 | 1 |
| 6+ | 9 | 0 |

- **Первый провал ничего не меняет.** Серия считается, но капча та же.
- **Успех обнуляет серию** и возвращает обычную сложность.
- Серия живёт 30 минут и считается по IP: вернувшийся через час человек
  начинает с чистого листа.
- Ступеней не больше трёх (`ADAPTIVE_MAX_LEVEL`): бесконечно длинная капча
  перестаёт быть проходимой, дальше работают `rate_limit` и блоклист.
- Порог, по которому выдан челлендж, едет вместе с ним — и клиент видит
  правду, и `verify` судит по обещанному, а не по текущим настройкам. Смена
  конфига посреди раздачи ничего не «прощает» задним числом.
- `adaptive=False` — выключить (тогда поведение как в 2.11).

Django: `KREMLE_ADAPTIVE`, `KREMLE_ADAPTIVE_THRESHOLD`,
`KREMLE_ADAPTIVE_EXTRA_QUESTIONS`. Остальные интеграции принимают те же
аргументы конструктора.

Проверить руками:

```python
engine.difficulty('203.0.113.7')
# {'level': 1, 'question_count': 7, 'max_errors': 1}
```

## Долг капчи: реферер не одноразовый

Реферер поисковика приходит ровно с одним запросом — тем, где человек нажал
ссылку. Дальше браузер подставляет уже свой адрес, а набранный руками адрес
не несёт `Referer` вовсе. Если решением не поделиться с сессией, получается
так: капча показана, человек стирает `/kremle/challenge` из адресной строки —
и гуляет по сайту. Это не «внимательность пользователя», это дыра.

Поэтому решение `challenge` по рефереру записывается в сессию как **долг**:

```python
KremleFlask(
    app,
    sticky_referrer=True,   # по умолчанию включено
    sticky_ttl=900,         # сколько секунд помнить долг
)
```

Как это работает:

- долг ставится только тогда, когда политика вернула `challenge` — при
  `monitor` его нет, при `block` он не нужен;
- пока долг висит, любой следующий запрос этой сессии получает капчу, даже
  если в нём нет ни одного сигнала;
- снимает долг только успешный `verify` (или истечение `sticky_ttl`);
- `POST /kremle/logout` долг **не** снимает: иначе выход стал бы кнопкой
  «отмени капчу»;
- посторонний посетитель того же IP ничего не замечает: долг живёт в сессии,
  а не в общем хранилище. Офис за одним NAT-адресом не наказывается;
- повторные срабатывания считаются в метриках как
  `count_detect(reason, 'challenge')` — в `stats` видно, что долг реально
  работает, а не просто «когда-то был один сигнал».

Django: `KREMLE_STICKY_REFERRER` (по умолчанию `True`) и `KREMLE_STICKY_TTL`
(по умолчанию `900`). Остальные интеграции принимают те же аргументы
конструктора. Выключить совсем — `sticky_referrer=False`: поведение станет
как в 2.11, с одноразовым сигналом.

Посмотреть на долг из своего кода:

```python
from kremle_detect.session import pending_reason

reason = pending_reason(session)     # 'yandex_referrer' или None
```

---

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
| GET | `/kremle/health` | `200` `{"status": "ok", ...}`, `503` при недоступном хранилище; `status: degraded` — когда сломан кеш вопросов |
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

### Что именно знает health

```jsonc
// GET /kremle/health — здоровый экземпляр
{
  "status": "ok",
  "version": "2.12.0",
  "storage": "redis", "storage_ok": true,
  "reasons": [],
  "questions": {
    "source": "own+sdamgia",
    "count": 214,          // сколько вопросов доступно прямо сейчас
    "own": 60,             // из своего банка
    "cached": 154,         // из кеша «Решу ЕГЭ» (с учётом фильтра картинок)
    "categories": ["math", "physics"],
    "age_hours": 6.5,      // возраст самого старого файла кеша
    "stale": false,
    "stale_after_hours": 48,
    "missing_cache": [],
    "reason": null
  },
  "ts": 1794124008.12
}
```

`status` равен `degraded`, если сломано хоть что-то, а `reasons` перечисляет, что
именно: `storage`, `questions:no_cache`, `questions:stale_cache`,
`questions:empty`. Код ответа при этом остаётся `200`, пока живо хранилище:
устаревший кеш — повод посмотреть на cron, а не гасить под. `503` — только когда
хранилище не отвечает (капча не сможет сохранить челлендж).

Это ровно та дыра, которую закрывает 2.12: раньше тихо умерший `kremle-detect
questions sync` не был виден ничем — кеш месячной давности отдавался, а health
бодро писал `ok`. Теперь `age_hours` растёт, `stale` становится `true` после
48 часов, и мониторинг ловит это по `status != ok`.

Порог настраивается на уровне вызова:

```python
engine.questions_health(stale_after_hours=24)   # строже для боевого контура
```

Правила, по которым считается `reason`:

| Режим | Нет кеша | Кеш старше порога |
|---|---|---|
| `own` | — | — (кеш не используется) |
| `auto` | не деградирует: работает встроенный банк | `stale_cache` |
| `sdamgia` | `no_cache` | `stale_cache` |
| `own+sdamgia` | `no_cache` | `stale_cache` |

`age_hours` берётся по **самому старому** файлу кеша: если обновилась половина
категорий, синхронизация всё равно сломана.

`/kremle/health` годится для `livenessProbe`/`readinessProbe` по коду ответа
(`503`), а для алертов «синхронизация отстала» — по `status`/`reasons`.

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

## Трассировка и JSON-логи

Смотреть в логи — хорошо; видеть, сколько заняла конкретная капча у конкретного
человека — лучше. Для этого есть OpenTelemetry, но только как extras:
библиотека, которая тянет агент в обязательные зависимости, — библиотека,
которую не поставят.

```bash
pip install "kremle-detect[otel]"
export KREMLE_OTEL_ENDPOINT=http://localhost:4318   # OTLP/HTTP (Jaeger, Tempo)
kremle-detect serve
```

Без `KREMLE_OTEL_ENDPOINT` (или без extras) всё работает как раньше: спаны —
пустые заглушки, ни одного лишнего импорта в горячем пути.

Что видно в трейсе:

| Спан | Атрибуты |
|---|---|
| `kremle.challenge` | `questions`, `max_errors`, `source` |
| `kremle.verify` | `passed`, `errors`, `total`, `max_errors`, `error` |

IP и токен челленджа туда **не** попадают: первый — персональные данные,
второй — секрет, по которому проходят капчу. Связать лог с трейсом можно по
`trace_id`, он есть в JSON-логе.

```bash
export KREMLE_LOG_JSON=1
kremle-detect serve
```

```json
{"ts": "2026-10-24T12:00:00.123+00:00", "level": "INFO", "logger": "kremle",
 "message": "Challenge created: token=1f4c9a0b7e2d1234 questions=5",
 "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"}
```

Своими руками, без переменных окружения:

```python
from kremle_detect.telemetry import setup_tracing, setup_json_logs

setup_tracing(service_name='my-site', endpoint='http://localhost:4318')
setup_json_logs()          # логгер kremle — в JSON, уровень INFO
```

`setup_json_logs()` выключает `propagate`: иначе та же запись уедет в корневой
обработчик обычным текстом, и в потоке получится смесь форматов.

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
