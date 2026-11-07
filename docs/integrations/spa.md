# SPA и JSON

Блокирующая HTML-капча бессмысленна для `fetch`/XHR: клиент ждёт JSON, а получает
страницу. Все три интеграции отвечают **`403` JSON** любому запросу, который
просит JSON:

- заголовок `Accept: application/json`;
- заголовок `X-Requested-With: XMLHttpRequest`;
- путь `/api/...` (эвристика, настраивается `json_api=`).

```jsonc
// GET /protected  → 403
{"error": "captcha_required", "reason": "yandex_browser", "challenge_url": "/kremle/challenge"}
```

Никаких редиректов — SPA-навигация от них ломается.

## Headless-режим

Если весь сервис — API, включите headless: `/kremle/challenge` сразу отдаёт JSON.

```python
# Flask / FastAPI
KremleFlask(app, headless=True)
KremleFastAPI(app, headless=True)
```

```python
# Django
KREMLE_HEADLESS = True
```

## Сценарий

```js
// 1. запрос к защищённому ресурсу
const res = await fetch('/api/me', { headers: { Accept: 'application/json' } })
if (res.status === 403) {
  const { challenge_url } = await res.json()

  // 2. получить челлендж
  const challenge = await (await fetch(challenge_url, {
    headers: { Accept: 'application/json' },
    credentials: 'include',
  })).json()
  // { questions: [...], token, expires_in, max_errors, verify_url }

  // 3. показать вопросы, собрать ответы
  // 4. отправить
  const result = await (await fetch(challenge.verify_url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: challenge.token, answers: { '0': 1, '1': 3 } }),
  })).json()
  // { passed: true, errors: 1, total: 15, max_errors: 3, redirect: '/' }
}
```

Куки важны: `credentials: 'include'` и `SESSION` на сервере — именно там живёт
отметка «капча пройдена».

## React

Готовая реализация того же сценария — `kremle-react`:

```tsx
import { KremleChallenge } from 'kremle-react'

export function Gate() {
  return (
    <KremleChallenge
      onPass={(r) => console.log('пройдено', r.errors, r.total)}
      onFail={(r) => console.log('провал', r.errors, r.max_errors)}
    />
  )
}
```

Компонент сам грузит челлендж, шлёт ответы, показывает таймер по `expires_in`
и честный результат по `max_errors`. Подробнее — [React-компонент](https://github.com/RUdolf1517/KremleXYZ-Detect#react-компонент).

## Коды ответов `/kremle/verify`

| `error` | Когда | `errors` |
|---|---|---|
| — | обычная проверка | `0..total` |
| `invalid_token` | токен истёк, использован или отсутствует | `-1` |
| `rate_limited` | исчерпан лимит неудачных попыток с IP | `-1` |
| `blacklisted` | IP в блоклисте | `-1` |
| `invalid_answers` | `answers` — не объект | `-1` |

При `429` в ответе есть `Retry-After` — окно лимита в секундах, клиенту не нужно
угадывать паузу.
