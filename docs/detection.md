# Детекция: что считается Яндексом

> «Врага надо знать в лицо — но ещё лучше знать его `User-Agent`.»

Проверка идёт по четырём независимым каналам. Достаточно любого: браузер узнаётся
и по заголовку, и по реферальной строке, и по Client Hints, и по JS-фингерпринту.

| Сигнал | Где ищем | Примеры |
|---|---|---|
| Браузер | `User-Agent` | `YaBrowser`, `Yowser`, `YaApp_Android`, `YaApp_iOS`, `YandexSearch`, `YandexStation` |
| Бот | `User-Agent` | `YandexBot`, `YandexMetrika`, `YandexImages`, `YandexDirect` + 20 других |
| Реферер | `Referer` | `yandex.ru/com/by/kz/...` и все TLD, `ya.ru`, `dzen.ru`, `zen.`, `market.`, `music.`, `news.`, `mail.`, `translate.` |
| Client Hints | `Sec-CH-UA`, `Sec-CH-UA-Full-Version-List` | `"YaBrowser";v="24"` |
| JS-фингерпринт | браузер | `navigator.userAgentData`, `window.yandex`, `window.Ya`, honeypot |

Приоритет причины: `yandex_bot` → `yandex_browser` → `yandex_client_hints` →
`yandex_referrer`. Бот — первым: капча ему не поможет, ему место в `block`.

## Функции

```python
from kremle_detect import detect, is_yandex_browser, is_yandex_bot, is_yandex_referrer

is_yandex_browser('Mozilla/5.0 ... YaBrowser/24.1 ...')   # True
is_yandex_bot('Mozilla/5.0 (compatible; YandexBot/3.0)')  # True
is_yandex_referrer('https://yandex.ru/search?q=test')     # True

result = detect({
    'User-Agent': request.headers.get('User-Agent', ''),
    'Referer': request.headers.get('Referer', ''),
    'Sec-CH-UA': request.headers.get('Sec-CH-UA', ''),
})
if result:
    print(result.reason)   # yandex_browser | yandex_bot | yandex_referrer | yandex_client_hints
```

`detect()` — чистая функция: ничего не читает, никуда не пишет, никого не
блокирует. Решение принимает ваш код или политика (см. [Эксплуатация](operations.md#monitor-режим)).

## Проверить сигнал руками

```bash
kremle-detect check-ua "Mozilla/5.0 YaBrowser/24.1"      # exit 1, если детект
kremle-detect check-ref "https://yandex.ru/search?q=x"
kremle-detect check-hints '"YaBrowser";v="24"'
```

Код возврата `1` — сигнал найден: удобно вставлять в свои смоук-тесты и
деплой-проверки, не поднимая приложение.

## Почему сигналов несколько

Один `User-Agent` подделывается в два клика. Реферер подделывается сложнее, Client
Hints приходят только от настоящего браузера, а JS-фингерпринт — уже изнутри
страницы. По отдельности каждый канал слаб, вместе они дают ту самую «тень
подозрения», по которой и работает весь проект.

Честно: детекция обходится. Она и не должна быть непробиваемой — она должна
отделять обычный визит от необычного с разумной точностью, а цену ошибки считает
monitor-режим.

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
