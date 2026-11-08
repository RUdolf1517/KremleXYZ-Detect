# Виджет без React

> «Не всякой странице нужен реактор. Иногда достаточно лампочки.»

Капча ставится на любую страницу двумя строками: `<div>` и `<script src>`.
Ни Node, ни сборщика, ни React — бандл уже лежит в wheel и отдаётся роутом
`/kremle/widget/kremle-widget.min.js` (11 КБ, IIFE).

## Минимум

```html
<div id="kremle"></div>
<script src="/kremle/widget/kremle-widget.min.js"></script>
<script>KremleWidget.mount('#kremle');</script>
```

Тот же сниппет из Python — чтобы не собирать строку руками в шаблоне:

```python
from kremle_detect.widget import widget_snippet

snippet = widget_snippet()          # <div id="kremle" data-kremle></div> + <script>...
```

## Никакого JS на странице

Достаточно одного `<script src>` и атрибута — виджет сам найдёт контейнер:

```html
<script src="/kremle/widget/kremle-widget.min.js"></script>
<div data-kremle
     data-challenge-url="/kremle/challenge"
     data-verify-url="/kremle/verify"
     data-title="[ проверка ]"
     data-redirect="true"></div>
<script>KremleWidget.autoMount();</script>
```

| `data-` атрибут | Что задаёт |
|---|---|
| `data-challenge-url` | откуда брать вопросы (по умолчанию `/kremle/challenge`) |
| `data-verify-url` | куда отправлять ответы (`/kremle/verify`) |
| `data-logout-url` | сброс сессии перед новой попыткой (выводится из verify) |
| `data-title` | заголовок капчи |
| `data-redirect="true"` | перейти по `redirect` после успеха (обычное поведение сайта) |

## Окно поверх страницы

Если сервер включён с `overlay=True`, страницу не надо никуда уводить: виджет
спросит `/kremle/status` и откроет капчу модальным окном поверх.

```html
<script src="/kremle/widget/kremle-widget.min.js"></script>
<script>
  KremleWidget.autoGuardOverlay(document, { reloadOnPass: true })
</script>
```

`autoGuardOverlay` ждёт DOM и ничего не делает, если `pending` в статусе нет.
Ручной вариант — `guardOverlay({...})` с методами `check`, `open`, `close`,
`destroy`, `getState`. Клик по фону и `Esc` окно не закрывают: закрыть окно —
не значит пройти капчу, долг остаётся. Подробности — [Капча поверх страницы](overlay.md).

## Настройки

```js
const widget = KremleWidget.mount('#kremle', {
  challengeUrl: '/kremle/challenge',
  verifyUrl: '/kremle/verify',
  title: '[ проверка ]',
  description: 'Подтвердите, что вы человек — и проходите.',
  submitText: 'проверить',
  retryText: 'начать заново',
  showTimer: true,           // обратный отсчёт до истечения токена
  showAttribution: true,     // подпись «Задания: РешуЕГЭ» со ссылкой
  redirectOnPass: false,     // true — сами делаем location.assign
  onPass: (result) => console.log('прошёл', result),
  onFail: (result) => console.log('провал', result.errors, result.max_errors),
  onError: (message) => console.log('сеть/сервер', message),
});

widget.reload();       // новый челлендж
widget.retry();        // logout + новый челлендж
widget.submit();       // отправить ответы (если кнопка своя)
widget.getState();     // {questions, answers, token, result, ...}
widget.destroy();      // убрать капчу со страницы
```

`KremleWidget.mount()` возвращает объект с методами выше — этого хватает, чтобы
встроить капчу в свою форму: рисуете свой интерфейс, а отправку и таймер берёте
у виджета.

## Протокол

Тот же, что у Flask/Django/FastAPI/Starlette/Litestar и `kremle-react`, — никаких отдельных
эндпоинтов:

```
GET  /kremle/challenge   → {questions, token, expires_in, max_errors, sources, attribution}
POST /kremle/verify      ← {token, answers: {"0": 2, ...}, fingerprint}
                         → {passed, errors, total, max_errors, redirect, error}
```

Фингерпринт — пять полей (`yaBrands`, `yandexApi`, `honeypot`, `webdriver`,
`timezone`), ровно как у React-версии и HTML-шаблона. Полный User-Agent и список
брендов не отправляются.

## Куда положить файл

| Способ | Как |
|---|---|
| Свой роут (по умолчанию) | `<script src="/kremle/widget/kremle-widget.min.js">` — файл отдают интеграции |
| Своя статика | скопировать `kremle_detect/static/widget/kremle-widget.min.js` в `static/` и указать свой путь |
| CDN/bundler | `import { mount } from 'kremle-widget'` — ESM-сборка `kremle-widget.mjs` |

Если файла нет (пакет собран без виджета, например из старой ветки), роут
отвечает `404` с подсказкой `cd kremle-widget && npm run build`.

## CSP

Виджет вставляет инлайновый `<style>` в свои элементы и грузится с вашего же
домена, поэтому политика по умолчанию подходит: `script-src` должен разрешать
`/kremle/widget/…`, `style-src` — инлайновые стили. Подробности —
[Безопасность: CSP](security.md#csp-как-ужесточить-и-что-сломается).

## Атрибуция

Задания «Решу ЕГЭ» — чужой контент. Подпись «Задания: РешуЕГЭ» со ссылкой на
источник включена по умолчанию (`showAttribution: true`) и отключается только
если вы этого действительно хотите.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
