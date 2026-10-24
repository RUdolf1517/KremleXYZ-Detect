# kremle-react

React-компонент и хук для капчи [`kremle-detect`](https://github.com/RUdolf1517/KremleXYZ-Detect).

Работает с бэкендом на FastAPI (`headless=True`), Flask или Django с `json_api`
(по умолчанию включено): компонент запрашивает вопросы у `/kremle/challenge`
и отправляет ответы на `/kremle/verify`.

- SSR-safe (Next.js / Remix): никаких обращений к `window` при рендере
- honeypot-поля и `navigator.userAgentData` в фингерпринте
- атрибуция источника вопросов («Решу ЕГЭ») со ссылкой
- автоматически запрашивает новый челлендж, если токен истёк
- ESM + CJS + типы, без обязательных зависимостей кроме React

## Установка

```bash
npm install kremle-react
# или из репозитория
npm install /path/to/KremleXYZ-Detect/kremle-react
```

React ≥ 17, Node ≥ 18 для сборки.

## Использование

```tsx
import { KremleChallenge } from 'kremle-react'

export function App() {
  return (
    <KremleChallenge
      challengeUrl="/kremle/challenge"
      verifyUrl="/kremle/verify"
      onPass={(r) => console.log('пройдено', r.errors, r.total)}
      onFail={(r) => console.log('провал', r.error ?? r.errors)}
      onError={(message) => console.warn(message)}
    />
  )
}
```

Свой UI на хуке:

```tsx
import { useKremle } from 'kremle-react'

export function MyCaptcha() {
  const {
    questions, sources, answers, setAnswer, submit,
    retry, loading, submitting, result, error, allAnswered,
  } = useKremle({ challengeUrl: '/kremle/challenge', verifyUrl: '/kremle/verify' })

  if (loading) return <p>Загрузка…</p>

  return (
    <form onSubmit={(e) => { e.preventDefault(); void submit() }}>
      {questions.map((q, qi) => (
        <fieldset key={qi}>
          <legend>{q.q}</legend>
          {q.opts.map((opt, oi) => (
            <label key={oi}>
              <input
                type="radio"
                name={`q${qi}`}
                checked={answers[String(qi)] === oi}
                onChange={() => setAnswer(qi, oi)}
              />
              {opt}
            </label>
          ))}
        </fieldset>
      ))}

      <button type="submit" disabled={!allAnswered || submitting}>
        {submitting ? 'Проверяем…' : 'Отправить'}
      </button>

      {error && <p role="alert">{error}</p>}
      {result && !result.passed && (
        <button type="button" onClick={retry}>Ещё раз</button>
      )}
      {sources.length > 0 && (
        <p>
          Задания: <a href={sources[0].url}>{sources[0].name}</a>
        </p>
      )}
    </form>
  )
}
```

## props

| Prop | Тип | По умолчанию | Описание |
|---|---|---|---|
| `challengeUrl` | `string` | `/kremle/challenge` | откуда брать вопросы |
| `verifyUrl` | `string` | `/kremle/verify` | куда отправлять ответы |
| `logoutUrl` | `string` | выводится из `verifyUrl` | сброс «капча пройдена» |
| `autoReloadOnExpired` | `boolean` | `true` | новый челлендж при `invalid_token` |
| `onPass` / `onFail` | `(result) => void` | — | колбэки результата |
| `onError` | `(message) => void` | — | сетевая ошибка |
| `title` | `string` | `[ проверка ]` | заголовок |
| `description` | `string` | — | текст под заголовком |
| `showAttribution` | `boolean` | `true` | подпись источника вопросов |
| `disableHoneypot` | `boolean` | `false` | скрыть скрытые поля (не рекомендуется) |
| `className` / `style` | | — | оформление |

Хук возвращает: `questions`, `sources`, `attribution`, `token`, `answers`,
`setAnswer`, `submit`, `reload`, `retry`, `loading`, `submitting`, `result`,
`error`, `allAnswered`.

## Формат ответа сервера

```jsonc
// GET /kremle/challenge
{
  "questions": [{ "q": "…", "opts": ["…"], "category": "math" }],
  "token": "…",
  "verify_url": "/kremle/verify",
  "sources": [{ "name": "РешуЕГЭ", "url": "https://sdamgia.ru/", "author": "…" }],
  "attribution": "Задания: РешуЕГЭ"
}

// POST /kremle/verify
{ "passed": false, "errors": -1, "total": 0, "error": "rate_limited" }
```

Компонент понимает коды `invalid_token`, `rate_limited`, `blacklisted`,
`blocked`, `invalid_answers` и показывает человеческий текст вместо
«ошибок -1 из 0».

## SSR

Компонент безопасен при серверном рендере: вопросы загружаются в `useEffect`,
`window`/`navigator` читаются только в браузере. В Next.js `app` router
добавьте `'use client'` в файл, где рендерится `<KremleChallenge />`.

## Разработка

```bash
npm install
npm test            # vitest + jsdom, 22 теста
npm run typecheck   # tsc --noEmit
npm run build       # ESM + CJS + .d.ts
```

## Лицензия

MIT.
