# Changelog

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Версионирование: [SemVer](https://semver.org/lang/ru/).

## [2.7.0] — 2026-10-24

Релиз про эксплуатацию: видеть, что происходит, не блокировать вслепую и не
ломать SPA. Ломающих изменений нет — политика по умолчанию остаётся `challenge`
для всех сигналов.

### Добавлено

- **Monitor-режим (shadow).** `policy={'yandex_browser': 'monitor'}` пропускает
  трафик, но считает его и пишет событие `shadow` в лог (в `kremle-detect logs`
  помечено `ТЕНЬ`). Ничего не блокируется — видно, сколько живых людей задевает фильтр.
- **Сегменты вместо «всё или ничего».** `policy` задаёт действие на сигнал:
  `challenge` / `block` / `monitor` / `allow`. По умолчанию — `challenge` для всех.
  `block` отдаёт `403` без капчи (боты, блэклист).
- **`sample_rate`** — доля обнаруженного трафика, которой реально показывается капча;
  остальные проходят как `monitor`. `0` — полный shadow-режим, `1` — как раньше.
  `block` и блэклист от сэмплирования не зависят.
- **JSON-ответ для API.** Запросы с `Accept: application/json` или
  `X-Requested-With: XMLHttpRequest` получают `403 {"error": "captcha_required",
  "action": "challenge", "challenge_url": "/kremle/challenge", "reason": ...}`
  вместо HTML-редиректа. Для `block` — `{"error": "blocked", "challenge_url": null}`.
  Путь под `/api/`, `/v1/`, `/v2/`, `/graphql` считается API и без заголовков.
  Отключается `json_api=False` / `KREMLE_JSON_API = False`. `headless=True`
  (Flask/FastAPI) и `KREMLE_HEADLESS = True` (Django) — весь сайт как API.
  JSON-блокировки отдаются с `Cache-Control: no-store`.
- **TTL у «капча пройдена».** В сессии лежит `{"ok", "ts", "exp", "ip", "ua"}`,
  срок — `verified_ttl` (по умолчанию сутки, `0` — бессрочно). Опциональная привязка
  к IP (`bind_ip`) и User-Agent (`bind_ua`, по умолчанию выключена). Старый флаг
  `True` из версий ≤ 2.6 считается просроченным.
- **`POST /kremle/logout`** — сбросить прохождение и перепройти. `GET /kremle/status`
  теперь отдаёт `{"verified": bool, "expires_in": int|null}`.
- **Вопросы «Решу ЕГЭ» по умолчанию** (`questions_source='auto'`): клиент
  `newapi/general` → страницы вариантов → `/problem?id=<id>`, разбор условия и ответа,
  кеш в `$KREMLE_CACHE_DIR`/`~/.cache/kremle-detect` на 30 дней, устаревший кеш
  используется, неудачный `sync` не затирает скачанное. Атрибуция обязательна:
  каждый вопрос несёт `source` (`name`/`url`/`author`), в `/kremle/challenge` приходят
  `sources` и `attribution` («Задания: РешуЕГЭ»), в HTML-капче — блок `#sources`.
  Числовые ответы превращаются в 4 варианта (правильный + 3 искажения), текстовые
  и длинные задания отбрасываются.
- **Health-check и метрики.** `/kremle/health` (`200`/`503` по доступности хранилища,
  версия, тип хранилища, политика), `/kremle/stats` (JSON-снапшот: запросы, детекции
  по причинам, действия, выдачи, verify, pass/fail, блокировки, `pass_rate`,
  `shadow_total`), `/kremle/metrics` (Prometheus). Счётчики не истекают.
  Выключаются `enable_ops_routes=False` / `KREMLE_ENABLE_OPS_ROUTES = False`.
- **Асинхронность.** `AsyncRedisStorage` (redis.asyncio, атомарный `INCR`+`EXPIRE`
  через Lua, `aclose()`) и `AsyncStorageAdapter` (threadpool через anyio).
  `KremleFastAPI` вызывает движок через threadpool (`async_offload`, включено).
- **CLI.** `kremle-detect questions show|sync|cache`, `--source auto|builtin|sdamgia`,
  `--ids 1001,1002`, `--dry-run`; старые флаги `questions -c math -n 5` работают.
- **Django — паритет с Flask/FastAPI:** JSON-гард, `KREMLE_HEADLESS`,
  `KREMLE_ENABLE_OPS_ROUTES`, health/stats/metrics, logout, TTL «пройдено».
- **React-пакет `kremle-react@1.1.0`:** собирается (ESM+CJS+`.d.ts`), 22 теста
  (vitest + jsdom), `useKremle`, `collectFingerprint`, атрибуция источника,
  авто-перезапрос при `invalid_token`, человеческие тексты для `rate_limited`/
  `blacklisted`/`blocked`, кнопка «Попробовать снова» через `POST /kremle/logout`.

### Исправлено

- **`bind_ua` был `True` в ядре и Flask, но `False` в FastAPI/Django.** Единый дефолт —
  `False`: обновление браузера меняет UA и не должно требовать перепройти капчу.
- **Страница варианта «Решу ЕГЭ» — источник id заданий, а не `larinVariants[].id`.**
  `id` в `newapi/general` — идентификатор варианта; качать по нему `/problem?id=`
  нельзя. Добавлены `parse_problem_ids()`, `variant_hrefs()` и `discover_problem_ids()`
  с fallback на ближайшие id банка, если портал сменит вёрстку.
- **Парсер задания терял условие.** Вложенные `div` в `pbody` сбивали счётчик
  вложенности — теперь условие берётся из первого `pbody`, ответ из `div.answer`.
- **`get=` в провайдере фиксировался на этапе импорта** — подменить HTTP в тестах
  и в CLI было нельзя. Теперь `get=None` → `http_get` в момент вызова.
- **`actions.allow` в `/kremle/stats` всегда был 0**, хотя `allowed_total` рос.
- **Flask/FastAPI/Django не ставили `no-store` на JSON-блокировки** — 403 мог
  закешироваться прокси.

### Тесты

420 Python-тестов (было 214) и 22 теста React: политика сегментов и `sample_rate`,
метрики/health/`prometheus`, TTL и logout, провайдер «Решу ЕГЭ» на фикстурах HTML,
JSON-гард и ops-роуты во всех трёх фреймворках, `AsyncRedisStorage` на фейковом
клиенте, CLI вопросов.

## [2.6.0] — 2026-10-24

Релиз про безопасность и доверие к входным данным. Ломающих изменений нет:
типовые деплои (nginx, docker, k8s) продолжают работать без настройки.

### Безопасность

- **`X-Forwarded-For` больше не принимается от всех.** Новый параметр
  `trusted_proxies` (Flask/FastAPI) и настройка `KREMLE_TRUSTED_PROXIES` (Django).
  По умолчанию доверяем **loopback и приватным сетям** (`127.0.0.0/8`, `10.0.0.0/8`,
  `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, IPv6 ULA/link-local) —
  nginx на том же хосте, docker и k8s работают из коробки. `trusted_proxies=[]`
  отключает доверие, список IP/CIDR заменяет авто-набор (для публичных LB).
  Если XFF пришёл от недоверенного адреса — одно предупреждение в лог `kremle`.
  Цепочка разбирается справа налево, доверенные хопы пропускаются. Раньше смена
  `X-Forwarded-For` полностью обнуляла rate limit и позволяла подставить чужой IP
  в блоклист.
- **Один резолвер IP на всю интеграцию.** Flask-гард брал `request.remote_addr`,
  а `/kremle/verify` — `X-Forwarded-For`, из-за чего whitelist/blacklist/rate limit
  смотрели на разные адреса. Теперь везде `kremle_detect.ip.client_ip`.
- **`max_errors` не может быть `>= question_count`.** Такой конфиг пропускал любого
  без единого правильного ответа. Теперь значение подрезается до `question_count - 1`
  с `WARNING` в лог, а если пул вопросов оказался короче — лимит подрезается под
  фактическое число вопросов (`min(max_errors, questions - 1)`). Приложение
  продолжает запускаться.
- **Токен челленджа одноразовый.** Удаляется после любой проверки, а не только после
  успешной. Раньше один токен давал бесконечные попытки угадать.
- **Инкремент счётчиков в Redis атомарный** (Lua: `INCR` + `EXPIRE`). Падение процесса
  между командами больше не оставляет ключ без TTL (вечный бан/лимит).
- **Перемешивание через `secrets.SystemRandom`** вместо глобального `random`.
- **Ограничение на выдачу челленджей** (`challenge_rate_limit`, по умолчанию 60 за окно):
  защищает MemoryStorage/Redis от забивания анонимными запросами `/kremle/challenge`.
- `Cache-Control: no-store` на странице капчи — токен не попадает в кеш.

### Исправлено

- **Django-интеграция не работала вообще.** `kremle_urls()` возвращал список из трёх
  паттернов, а `path()` распаковывал его как `(urlconf_module, app_name, namespace)`,
  из-за чего `reverse('kremle_verify')` и редирект на капчу падали с `TypeError`.
  Теперь возвращается `include(...)`.
- **Rate limit блокировал честных пользователей.** Считались все проверки, включая
  успешные: после N проходов пользователь получал `rate_limited`. Теперь считаются
  только неудачные, успех сбрасывает счётчик.
- **FastAPI: битое JSON-тело давало 500.** Теперь `400 {"error": "invalid_json"}`,
  как в Django. Массив вместо объекта — тоже 400.
- **`answers` не-объект** (например, список) больше не роняет проверку —
  возвращается `{"error": "invalid_answers"}`.
- **UI капчи** показывал «Ошибок: -1 из 0» для заблокированных/истёкших токенов и
  сравнивал ошибки с захардкоженным `10` вместо `max_errors`. Теперь у каждого кода
  ошибки свой текст, «кремлебот» — при ошибках больше половины.
- **`kremle-detect blacklist add IP --ttl 0`** («навсегда») молча превращался в 86400;
  теперь `0` означает «навсегда», как в API.
- **Django: кеш движка по `id(settings)`** не замечал `override_settings` в тестах.
  Ключ кеша теперь учитывает значения `KREMLE_*`.
- **Django: отсутствие `SessionMiddleware`** давало невнятный `AttributeError` —
  теперь `ImproperlyConfigured` с инструкцией.

### Изменено

- `check_rate_limit()` только читает счётчик (peek) и не расходует попытку.
- `trusted_proxies=None` — авто-режим (loopback + приватные сети), `[]` — не доверять
  никому, список — заменить авто-набор. Новые хелперы: `resolve_trusted_proxies()`,
  `DEFAULT_TRUSTED_NETWORKS`.
- `BaseStorage.get_counter()` — новое обязательное для переопределения место
  (`MemoryStorage`/`RedisStorage` реализуют).
- `CaptchaEngine` валидирует `question_count`, `max_errors`, `rate_limit`,
  `rate_window`, `challenge_rate_limit`, `fail_threshold`, `blacklist_ttl`
  при создании.
- Версия приведена к единой: `pyproject.toml` и `__version__` = `2.6.0`
  (было 2.5.0 и 2.3.0 соответственно).
- CI ставит все extras, гоняет 3.9–3.13, собирает wheel, проверяет наличие
  HTML-шаблона в пакете и билд `kremle-react`.

### Добавлено

- `kremle_detect/ip.py`: `client_ip()`, `ip_matches()`, `parse_trusted_proxies()`.
- Параметры `trusted_proxies` и `challenge_rate_limit` во всех интеграциях,
  `KREMLE_TRUSTED_PROXIES` и `KREMLE_CHALLENGE_RATE_LIMIT` в Django.
- Тесты: `test_ip.py`, `test_engine_security.py`, `test_flask_integration.py`,
  `test_django_integration.py`, `test_redis_storage.py`; 91 → 214 тестов.
  Flask- и Django-интеграции раньше не были покрыты вообще.
- Этот CHANGELOG и переписанный README.

### Совместимость

Миграция не требуется.

- **Прокси.** nginx на том же хосте, docker и k8s-сеть доверенные по умолчанию —
  настраивать ничего не нужно. Если перед приложением публичный балансировщик
  (Cloudflare, облачный LB), в логе `kremle` появится предупреждение о недоверенном
  адресе — добавь его в `trusted_proxies`. Совсем отключить доверие: `trusted_proxies=[]`.
- **`max_errors`.** Конфиг с `max_errors >= question_count` продолжает работать,
  но лимит молча (с предупреждением в лог) подрезается до безопасного значения.
- **Токены.** Клиенты, которые переиспользуют токен после провала, получат
  `invalid_token`: запрашивай новый челлендж на каждую попытку.
- **Rate limit** считает неудачные проверки, а не все. Значение по умолчанию (10)
  менять не нужно.

## [2.5.0] и раньше

Истории изменений нет — до 2.6.0 changelog не вёлся.
