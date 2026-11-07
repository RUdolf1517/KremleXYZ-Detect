# Разработка

> «Ремесло передаётся от мастера к подмастерью: смотри, делай, потом спрашивай.»

Полные правила приёма изменений — в
[CONTRIBUTING.md](https://github.com/RUdolf1517/KremleXYZ-Detect/blob/main/CONTRIBUTING.md).
Здесь — короткая версия для тех, кто просто хочет запустить тесты.

## Окружение

```bash
git clone https://github.com/RUdolf1517/KremleXYZ-Detect.git
cd KremleXYZ-Detect
python -m venv .venv
. .venv/bin/activate
pip install -e ".[all,test]"
```

`.[all]` нужен, потому что тесты покрывают Flask, Django, FastAPI и Redis:
без extras часть тестов будет пропущена (`importorskip`), и вы не увидите
поломку интеграции.

## Тесты

```bash
pytest -q                                   # всё
pytest tests/test_captcha.py -q             # один файл
pytest -q --cov=kremle_detect --cov-report=term-missing
ruff check .
```

Текущее состояние: **625 passed / 17 skipped**, coverage 92 %. Порог в CI — 85 %.

Тесты не ходят в сеть: `get=` подменяется, Redis — `fakeredis`, портал
«Решу ЕГЭ» — фикстурами. Если ваш тест требует интернета, он не примут.

## React

```bash
cd kremle-react
npm install
npm run typecheck     # tsc --noEmit
npm test              # vitest
npm run build         # tsup + tsc для .d.ts
```

## Структура

```
kremle_detect/
├── detector.py            детекция (UA, боты, referer, Client Hints)
├── captcha.py             ядро: CaptchaEngine, Challenge, лимиты, callbacks
├── policy.py              действия сегментов, сэмплирование
├── metrics.py             счётчики, snapshot(), prometheus()
├── session.py             TTL «капча пройдена», привязка к IP/UA
├── storage.py             MemoryStorage, RedisStorage, EventLog
├── storage_async.py       AsyncRedisStorage, AsyncStorageAdapter
├── images.py              кеш картинок, SSRF-защита, prune
├── questions/             встроенный банк + провайдер «Решу ЕГЭ»
├── integrations/          Flask, Django, FastAPI, общие хелперы
├── templates/             шаблон капчи (один на все фреймворки)
├── demo.py                демо-приложение
└── cli.py                 kremle-detect
```

Релиз — это не праздник с фейерверком, а сдача объекта госкомиссии: всё
проверено, всё подписано, всё задокументировано.

## Релиз

Один релиз — один тег, версии Python-пакета и npm совпадают.

1. `pyproject.toml`, `kremle_detect/__init__.py`, `kremle-react/package.json`
   (+ lock) — одна и та же версия.
2. `CHANGELOG.md`: секция `[Unreleased]` → `[X.Y.Z] — дата`.
3. README: раздел «Что изменилось в X.Y» и бейдж версии.
4. Тесты, ruff, сборка React — локально.
5. PR → ревью → merge в `main`.
6. `git tag -a vX.Y.Z -m "..."` и `git push origin vX.Y.Z`.
7. Workflow `release.yml` собирает wheel+sdist, публикует в PyPI (OIDC) и npm
   (trusted publishing), создаёт GitHub Release.
8. Проверить реестры **по API**, а не по странице: `/pypi/kremle-detect/json` и
   `registry.npmjs.org/kremle-react`.

npm может принять публикацию и оставить её в staged — тогда `latest` ещё
указывает на предыдущую версию: подтвердить через сайт npm (Staged publishes).

## Документация

```bash
pip install mkdocs-material
mkdocs serve      # http://127.0.0.1:8000
mkdocs build --strict
```

`--strict` — обязательный режим в CI: битые ссылки между страницами роняют
сборку. Так документация не отстанет от кода, как это случилось со старым
`gh-pages` (последняя версия на нём была 2.3.4).

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
