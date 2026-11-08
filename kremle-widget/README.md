# kremle-widget

Капча для любой страницы: один `<script>` и один `<div>`. Без React, без
сборщика, без зависимостей.

```html
<div id="kremle"></div>
<script src="/kremle/widget/kremle-widget.min.js"></script>
<script>KremleWidget.mount('#kremle');</script>
```

Файл отдают сами интеграции `kremle-detect` (Flask, Django, FastAPI) — он лежит
в Python-пакете. Говорит на том же протоколе, что и React-версия:

```
GET  /kremle/challenge   → {questions, token, expires_in, max_errors, sources, attribution}
POST /kremle/verify      ← {token, answers, fingerprint}
```

## Что внутри

- 11 КБ минифицированного JS (IIFE) + ESM-сборка для сборщиков;
- фингерпринт из пяти полей: `yaBrands`, `yandexApi`, `honeypot`, `webdriver`,
  `timezone` — столько же, сколько у React-версии и HTML-шаблона;
- таймер до истечения токена, автоматическая перезагрузка челленджа,
  порог ошибок с сервера (не «угадай сам»);
- текст вопросов выводится только через `textContent`: задание из чужого
  источника не может вставить HTML или скрипт;
- honeypot-поля, которые заполняет только бот;
- атрибуция «Задания: РешуЕГЭ» со ссылкой на первоисточник.

## API

```js
const widget = KremleWidget.mount('#kremle', {
  challengeUrl: '/kremle/challenge',
  verifyUrl: '/kremle/verify',
  showTimer: true,
  showAttribution: true,
  redirectOnPass: false,
  onPass: (result) => {},
  onFail: (result) => {},
  onError: (message) => {},
})

widget.reload()    // новый челлендж
widget.retry()     // logout + новый челлендж
widget.submit()    // отправить ответы
widget.getState()  // состояние
widget.destroy()   // убрать со страницы
```

Автомонтирование по `data-`атрибутам:

```html
<script src="/kremle/widget/kremle-widget.min.js"></script>
<div data-kremle data-title="[ проверка ]" data-redirect="true"></div>
<script>KremleWidget.autoMount();</script>
```

## Окно поверх страницы

Если сервер включён с `overlay=True`, страницу не надо никуда уводить:

```html
<script src="/kremle/widget/kremle-widget.min.js"></script>
<script>KremleWidget.autoGuardOverlay(document);</script>
```

Виджет спросит `/kremle/status` и откроет капчу модальным окном поверх страницы.
Клик по фону и `Esc` окно не закрывают — закрыть окно не значит пройти проверку.
Ручной вариант:

```js
const overlay = KremleWidget.guardOverlay({ statusUrl: '/kremle/status' })
overlay.check()      // спросить статус и открыть, если pending
overlay.open()       // открыть принудительно
overlay.getState()   // 'idle' | 'pending' | 'open' | 'solved'
overlay.close()      // закрыть без прохождения
overlay.destroy()    // убрать из DOM
```

## Разработка

```bash
npm ci
npm test          # 34 теста: протокол, рендер, фингерпринт, окно поверх страницы
npm run build     # dist/kremle-widget.{js,min.js,mjs}
node scripts/check-dist.mjs   # IIFE-сборка действительно проходит капчу
```

Собранный бандл копируется в Python-пакет:

```bash
npm run build && cp dist/kremle-widget.js dist/kremle-widget.min.js \
  dist/kremle-widget.mjs ../kremle_detect/static/widget/
```

CI сверяет копию с исходниками: если бандл в репозитории отстал — сборка падает.

Документация: [Виджет без React](https://github.com/RUdolf1517/KremleXYZ-Detect/blob/main/docs/widget.md),
демо — [docs/demo.html](https://github.com/RUdolf1517/KremleXYZ-Detect/blob/main/docs/demo.html).

## Лицензия

MIT. Сатирический пафос в документации проекта — жанр, а не политическая
позиция; техническое содержание — правда и проверяется тестами.
