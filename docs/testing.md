# Тесты

> «Что не проверено — того не существует. Что проверено наполовину — существует
> наполовину, а падает целиком.»

```bash
python -m pytest tests/ -q      # 776 passed, 17 skipped
```

Покрыто: детекция, ядро капчи, валидация настроек, одноразовые токены, rate limit,
резолвинг IP, политика сегментов и `sample_rate`, метрики и health, TTL «пройдено»,
провайдер «Решу ЕГЭ» (разбор HTML, дистракторы, кеш, fallback), Flask/Django/FastAPI
(JSON-гард и разбор `Accept`, monitor, ops-роуты, logout), `AsyncRedisStorage` /
`AsyncStorageAdapter` на фейковом клиенте и CLI вопросов. Coverage — 92 %, порог в
CI — 85 %.

```bash
cd kremle-react && npm test && npm run typecheck && npm run build   # 27 тестов + сборка
cd kremle-widget && npm test && npm run build                      # 23 теста + IIFE-сборка
ruff check .                                                        # линтер
```

## Отдельные наборы

```bash
# живой Redis (нужен docker run -p 6379:6379 redis:7)
KREMLE_TEST_REDIS_URL=redis://localhost:6379/15 pytest -m redis

# без Docker: in-memory двойник с поддержкой Lua (pip install "fakeredis[lua]")
KREMLE_TEST_REDIS_FAKE=1 pytest -m redis

# e2e на настоящем HTTP-сервере (uvicorn в потоке, реальные куки)
pytest tests/test_e2e.py

# нагрузочный смоук (нужен `kremle-detect serve`)
python scripts/loadtest.py -n 500 -c 20
```

## Что гоняет CI

Python 3.9–3.13 с сервисом Redis (и **падает**, если Redis-тесты молча
скипнулись), порог покрытия 85 %, сборку wheel с проверкой содержимого,
`pip-audit`/`npm audit`, тесты и сборку React-пакета, `mkdocs build --strict`.
Отдельные workflow: публикация по тегу `v*` (PyPI + npm) и ежедневная проверка
живого портала «Решу ЕГЭ».

## Правила для новых тестов

- Тест не ходит в сеть: `get=` подменяется, портал — фикстурами, Redis — `fakeredis`.
- Тест воспроизводит баг **до** фикса и проходит после — иначе это не тест, а
  декорация.
- Тест, который «иногда падает», равен отсутствию теста: флаки лечатся, а не
  перезапускаются.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
