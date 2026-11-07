# CLI

> «Инструмент должен быть в руках, а не в инструкции на стене.»

```bash
kremle-detect help
```

## Диагностика

```bash
kremle-detect check-ua "Mozilla/5.0 YaBrowser/24.1"      # exit 1, если детект
kremle-detect check-ref "https://yandex.ru/search?q=x"
kremle-detect check-hints '"YaBrowser";v="24"'
kremle-detect questions --category math --count 5
```

Код возврата `1` — сигнал найден, `0` — нет. Удобно для смоук-проверок в деплое.

## Вопросы

```bash
kremle-detect questions show -c math -n 5              # из кеша РешуЕГЭ или банка
kremle-detect questions show --source builtin         # только встроенный банк
kremle-detect questions sync -c math -n 100           # обновить кеш
kremle-detect questions sync --ids 1001,1002          # только конкретные задания
kremle-detect questions sync --ids 1001,1002 --dry-run
kremle-detect questions sync --images --download      # рисунки в локальный кеш
kremle-detect questions check 1001 --download         # один рисунок проверить и скачать
kremle-detect questions cache                         # состояние кеша
kremle-detect questions images [--prune МиБ|--clear]  # кеш рисунков: размер и чистка
```

Подробности — [Вопросы](questions.md) и [Задания с рисунком](images.md).

## Блоклист и вайтлист

```bash
kremle-detect blacklist list   --redis redis://localhost:6379/0
kremle-detect blacklist add    1.2.3.4 --ttl 3600
kremle-detect blacklist add    1.2.3.4 --ttl 0          # навсегда
kremle-detect blacklist remove 1.2.3.4

kremle-detect whitelist list
kremle-detect whitelist add    10.0.0.1
kremle-detect whitelist remove 10.0.0.1
```

Адрес Redis — флагом `--redis` или переменной `KREMLE_REDIS_URL`.

## Демо-сервер

```bash
kremle-detect serve                  # FastAPI + капча + /stats на localhost:8000
kremle-detect serve --port 9000
KREMLE_DEMO_POLICY=monitor kremle-detect serve     # shadow: ничего не блокировать
kremle-detect serve --sample-image                 # встроенное задание с SVG-рисунком
kremle-detect serve --images                       # задания с рисунком из кеша
```

Нужен экстра `pip install "kremle-detect[demo]"` (fastapi + uvicorn).

## Логи событий

```bash
kremle-detect logs -n 200
kremle-detect logs --no-color
```

События: `ПРОШЁЛ`, `ПРОВАЛ`, `ДЕТЕКТ`, `ТЕНЬ` (monitor), `ЗАБЛОК`. Кольцевой лог
хранит последние 1000 записей в том же хранилище, что и всё остальное.

## Версия

```bash
kremle-detect --version      # kremle-detect 2.11.0
```

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
