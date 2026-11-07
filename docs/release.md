# Релиз и публикация

> «Сдать объект — значит подписать каждый лист. Не подписал — не сдал.»

Версия живёт в трёх местах и обязана совпадать: `pyproject.toml`,
`kremle_detect/__init__.py` и `kremle-react/package.json`. Публикация — по тегу.

```bash
# 1. проверить, что всё зелёное
pytest tests/ -q

# 2. версия во всех трёх файлах + запись в CHANGELOG.md
# 3. тег и пуш — дальше всё делает .github/workflows/release.yml
git tag v2.9.0 && git push origin v2.9.0
```

Workflow соберёт wheel/sdist, сверит версию с тегом, поставит wheel в чистый venv
и дёрнет `kremle-detect --version`, затем опубликует PyPI (trusted publishing,
OIDC, без токенов) и npm (`--provenance`), и создаст GitHub Release с артефактами
и текстом из CHANGELOG. GitHub Release появляется даже если индекс не настроен —
по нему видно, что именно сломалось.

Что настраивается один раз:

- **PyPI**: Account → Publishing → pending publisher (`kremle-detect`, owner
  `RUdolf1517`, repo `KremleXYZ-Detect`, workflow `release.yml`, environment `pypi`).
- **npm**: trusted publishing, подробности ниже.
- Если OIDC на PyPI недоступен — секрет `PYPI_API_TOKEN` и раскомментировать
  `password` в шаге публикации.

## npm: trusted publishing (OIDC)

Пакет `kremle-react` публикуется **без токенов**: npm доверяет конкретному
workflow, а CLI получает короткоживущий OIDC-токен на время джоба.

Настроено один раз (npmjs.com → `kremle-react` → Settings → **Trusted Publisher**):

| Поле | Значение |
|---|---|
| Organization or user | `RUdolf1517` |
| Repository | `KremleXYZ-Detect` |
| Workflow filename | `release.yml` |
| Environment name | пусто |
| Allowed actions | ✅ `npm publish` (иначе только staged-режим) |

Требования, уже выполненные в workflow: Node ≥ 22.14, npm CLI ≥ 11.5.1
(`npm install -g npm@latest`), `id-token: write`, публичный репозиторий —
provenance (`slsa.dev/provenance/v1`) генерируется автоматически.
`NODE_AUTH_TOKEN` в шаг публикации **не передаётся**: если OIDC сломается, job
упадёт с `ENEEDAUTH` сразу, а не через 90 дней, когда истечёт токен.

**Про первый релиз.** Самую первую версию пакета нельзя опубликовать через OIDC —
trusted publisher настраивается на странице пакета, которой ещё нет
([npm/cli#8544](https://github.com/npm/cli/issues/8544)). Поэтому 2.7.0 уехала
granular-токеном (он удалён), а 2.7.1 — первая версия, которую валидирует TP.
Неподтверждённая конфигурация истекает через **2 суток**.

Проверить, что публикация прошла именно по OIDC:

```bash
curl -s https://registry.npmjs.org/-/npm/v1/attestations/kremle-react@2.9.0 \
  | grep -o 'slsa.dev/provenance/v1'
```

**Если всё-таки нужен токен** (например, для первого релиза нового пакета):
granular token с правом Read and write на пакет, **Bypass 2FA** включён, срок — 7
дней (максимум для write-токенов — 90). Секрет `NPM_TOKEN`, после публикации
удалить.

## Staged publishing

Если в конфигурации отмечен только `npm stage publish`, `npm publish` не публикует
сразу: версия уходит на подтверждение, а в реестре появляется заглушка
`0.0.0-stage`. Workflow это ловит и печатает `warning`.

Подтверждение:

```bash
npm stage list kremle-react
npm stage approve <stageId>          # спросит 2FA-код
```

или в браузере: npmjs.com → `kremle-react` → **Staged publishes** → **Approve**.
Требуется 2FA владельца — из CI это сделать нельзя. Workflow после публикации сам
проверяет реестр и, если версия ждёт подтверждения, печатает warning в
аннотациях: «зелёного» джоба без публикации не бывает.

Если подтверждать каждый релиз не хочется, есть два пути (оба требуют действий в
браузере, потому что существующую конфигурацию нельзя редактировать):

1. **Добавить вторую связь** (их может быть до 10): Trusted Publisher → GitHub
   Actions с теми же полями, но с галкой **Allow npm publish**. Новая связь
   валидируется следующим релизом, старая stage-only остаётся безвредной.
2. **Пересоздать связь**: удалить текущую, создать заново с `Allow npm publish` и
   подтвердить публикацией **в течение 2 суток**.

## Как закрыть публикацию по токенам

Когда TP подтверждён, стоит запретить старый путь: npmjs.com → `kremle-react` →
Settings → **Publishing access** → *Require two-factor authentication and disallow
bypass 2fa tokens* → Update Package Settings. По документации это не влияет на
trusted publishers, но убивает возможность опубликовать по утёкшему токену.

## Проверка после релиза

Реестры проверяются по API, а не по красивой странице «опубликовано»:

```bash
curl -s https://pypi.org/pypi/kremle-detect/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
curl -s https://registry.npmjs.org/kremle-react | python3 -c "import json,sys; print(json.load(sys.stdin)['dist-tags']['latest'])"
```

Если npm отдаёт предыдущую версию — публикация в staged, см. выше.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
