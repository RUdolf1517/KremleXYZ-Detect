# Релиз и публикация

> «Сдать объект — значит подписать каждый лист. Не подписал — не сдал.»

Версия живёт в трёх местах и обязана совпадать: `pyproject.toml`,
`kremle_detect/__init__.py` и `kremle-react/package.json`. Публикация — по тегу.

```bash
# 1. проверить, что всё зелёное
pytest tests/ -q

# 2. версия во всех трёх файлах + запись в CHANGELOG.md
# 3. тег и пуш — дальше всё делает .github/workflows/release.yml
git tag v2.12.0 && git push origin v2.12.0
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

## SBOM и подпись артефактов

Рядом с `kremle_detect-*.whl` в релизе лежат:

| Файл | Что это |
|---|---|
| `sbom-python.cdx.json` | CycloneDX-1.6 SBOM Python-пакета со всеми extras |
| `sbom-npm.cdx.json` | CycloneDX-1.5 SBOM `kremle-react` (`npm sbom`) |
| `<артефакт>.sig` + `<артефакт>.pem` | подпись и сертификат sigstore (keyless) |

SBOM снимается с **установленного** wheel (`cyclonedx-py environment`), а не с
`pyproject.toml`: в отчёт попадают реальные версии зависимостей. Подпись — через
OIDC GitHub Actions, приватного ключа нигде нет.

Проверить подпись:

```bash
cosign verify-blob \
  --certificate kremle_detect-<версия>-py3-none-any.whl.pem \
  --signature   kremle_detect-<версия>-py3-none-any.whl.sig \
  --certificate-identity-regexp '^https://github.com/RUdolf1517/KremleXYZ-Detect/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  kremle_detect-<версия>-py3-none-any.whl
```

Если sigstore недоступен, шаг подписи не валит релиз: артефакты публикуются без
`.sig`, а в логе остаётся `::warning`. Так же ведёт себя установка
`cosign-installer` — публикация важнее подписи, но молчать об этом workflow не
будет.

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

## Сайт документации и демо

`docs/**` собирается в сайт воркфлоу `Pages` (`.github/workflows/pages.yml`) при
каждом пуше в `main`, который трогает `docs/**`, `mkdocs.yml` или сам воркфлоу.
Источник публикации — артефакт из Actions, а не ветка `gh-pages`: собранный сайт
не должен жить отдельным набором файлов, который отстаёт от кода (ручной
`gh-pages` успел застрять на версии 2.3.4, пока пакет ушёл на 2.11).

Что делает сборка:

1. `mkdocs build --strict` — битая ссылка или страница вне `nav` валят сборку;
2. проверка, что в `site/` лежат `demo.html` и `assets/kremle-widget.min.js` —
   демо едет вместе с документацией, а не отдельной ссылкой в никуда;
3. `upload-pages-artifact` и публикация `deploy-pages`;
4. после деплоя — `curl` по живому адресу: главная, `demo.html`, бандл виджета и
   обе новые страницы интеграций должны отдать `200`. Зелёный джоб означает
   «страница правда открывается», а не «команда отработала».

### Включение Pages (один раз, нужны права администратора)

1. <https://github.com/RUdolf1517/KremleXYZ-Detect/settings/pages>;
2. **Build and deployment → Source: GitHub Actions** (не «Deploy from a branch»:
   артефакт из Actions публикуется только при этом источнике);
3. **Actions → Pages → Run workflow** — или любой пуш в `docs/**`.

Тот же шаг через API, если под рукой токен с правами администратора:

```bash
gh api -X POST /repos/RUdolf1517/KremleXYZ-Detect/pages -f build_type=workflow
gh api /repos/RUdolf1517/KremleXYZ-Detect/pages -q '.build_type'   # → workflow
```

Воркфлоу не гадает, а спрашивает у API `build_type` и ведёт себя по факту:

| `build_type` | Что происходит |
|---|---|
| `workflow` | сайт собирается и публикуется, затем проверяется `curl`-ом |
| `none` | сборка зелёная, публикации нет, в логе `::warning` со ссылкой на настройки |
| `legacy` | то же предупреждение: источник — ветка, артефакт из Actions не подойдёт |
| `unknown` | токену не хватило прав прочитать настройки — тоже предупреждение, без деплоя |

Адрес: <https://rudolf1517.github.io/KremleXYZ-Detect/>. Главная и
`demo.html` живут под префиксом `/KremleXYZ-Detect/`, внутренние ссылки
mkdocs-material относительные, так что проектному сайту (project pages)
ничего не ломает. Пока Pages не включён, `main` не краснеет: сборка остаётся
артефактом `github-pages`.

Сайт включён и публикуется с каждой правкой в `docs/**` (источник —
*GitHub Actions*, `build_type=workflow`). Ручной запуск без правки:
**Actions → Pages → Run workflow**; `workflow_dispatch` требует права
`actions: write` — токену без него остаётся пуш в `docs/**`.

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
