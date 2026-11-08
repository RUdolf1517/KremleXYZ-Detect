# React-компонент

> «Кто сказал, что предохранитель не может быть красивым?»

`kremle-react@2.12.0` — ESM + CJS + `'use client'` + типы, 27 тестов. Собран на
React 19, TypeScript 7 и jsdom 30 (`npm install` — Node ≥ 22). Версия npm-пакета
совпадает с версией Python-пакета: один релиз, один тег.

```bash
npm install kremle-react
npm install /path/to/KremleXYZ-Detect/kremle-react   # из исходников
```

## Фингерпринт: пять полей

`collectFingerprint()` собирает ровно то, что влияет на решение, — и ничего
сверх этого:

```ts
{ yaBrands, yandexApi, honeypot, webdriver, timezone }
```

`yaBrands` (`navigator.userAgentData.brands` и `YaBrowser` в UA), `yandexApi`
(`window.yandex`/`Ya`/`YaBrowser`) и `honeypot` включают строгий режим на
сервере; `webdriver` и `timezone` — грубые приметы автоматизации. Полный список
брендов и язык интерфейса не отправляются: решение по ним не принимается, а
данные — уже персональные. С 2.10 поля `brands` и `lang` убраны.

Нужна капча без React и без сборки — см. [виджет без React](widget.md): тот же
протокол, тот же фингерпринт, один `<script src>`.

## Готовая капча

```tsx
import { KremleChallenge } from 'kremle-react'

function App() {
  return (
    <KremleChallenge
      challengeUrl="/kremle/challenge"
      verifyUrl="/kremle/verify"
      onPass={() => window.location.reload()}
      onFail={(r) => console.log(`ошибок: ${r.errors}/${r.total}`)}
    />
  )
}
```

## Свой UI на хуке

```tsx
import { useKremle } from 'kremle-react'

function MyCaptcha() {
  const { questions, answers, setAnswer, submit, reload, loading, submitting, result, error } =
    useKremle()

  if (loading) return <div>Загрузка...</div>

  return (
    <form onSubmit={(e) => { e.preventDefault(); submit() }}>
      {questions.map((q, qi) => (
        <div key={qi}>
          <p>{q.q}</p>
          {q.opts.map((opt, oi) => (
            <label key={oi}>
              <input type="radio" name={`q${qi}`} onChange={() => setAnswer(qi, oi)} />
              {opt}
            </label>
          ))}
        </div>
      ))}
      <button type="submit" disabled={submitting}>Отправить</button>
      {result && !result.passed && <button type="button" onClick={reload}>Ещё раз</button>}
      {error && <p>{error}</p>}
    </form>
  )
}
```

## Что экспортируется

`KremleChallenge`, `useKremle`, `collectFingerprint` и типы `KremleChallengeProps`,
`KremleQuestion`, `KremleResult`, `UseKremleOptions`, `UseKremleReturn`.

Требует React ≥ 17 и JSON-режим на бэкенде (см. [SPA и JSON](integrations/spa.md)).
Запросы идут с `credentials: 'include'` — сессия общая с бэкендом.

## Поведение

- `sources`/`attribution` из `/kremle/challenge` рисуются под формой со ссылкой на
  первоисточник (`showAttribution={false}` — отключить);
- `invalid_token` — компонент сам запрашивает новый челлендж;
- `rate_limited`/`blacklisted`/`blocked` показываются человеческим текстом, а не
  «ошибок -1 из 0»;
- кнопка «Попробовать снова» делает `POST /kremle/logout` и перезагружает капчу;
- провал объясняется через `max_errors` с сервера: «ошибок 4 из 3 допустимых»;
- по `expires_in` показывается обратный отсчёт, краснеющий за минуту до конца;
- SSR-safe: `window`/`navigator` читаются только в браузере.

Подробности и история версий — [kremle-react/README.md](https://github.com/RUdolf1517/KremleXYZ-Detect/blob/main/kremle-react/README.md).

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
