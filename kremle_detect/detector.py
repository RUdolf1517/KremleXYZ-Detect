# -*- coding: utf-8 -*-
"""
Детекция пользователей Яндекс Браузера, Яндекс-ботов и переходов с Яндекса.

Фреймворк-агностичный модуль: работает с обычным dict заголовков.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

# ── User-Agent паттерны ──────────────────────────────────────────────────────

# Яндекс Браузер (десктоп + мобильный)
_RE_YABROWSER = re.compile(
    r'YaBrowser|'           # основной маркер
    r'YowserBrowser|'       # старое название
    r'Yowser|'              # ещё старее
    r'YaApp_Android|'       # приложение Яндекс (Android)
    r'YaApp_iOS|'           # приложение Яндекс (iOS)
    r'YaSearchBrowser|'     # Яндекс Поиск (отдельное приложение)
    r'YandexSearch|'        # поисковое приложение
    r'YandexStation',       # Яндекс Станция (WebView)
    re.IGNORECASE,
)

# Яндекс боты (краулер, метрика, картинки и т.д.)
_RE_YABOT = re.compile(
    r'YandexBot|'
    r'YandexAccessibilityBot|'
    r'YandexMobileBot|'
    r'YandexDirectDyn|'
    r'YandexScreenshotBot|'
    r'YandexImages|'
    r'YandexVideo|'
    r'YandexVideoParser|'
    r'YandexMedia|'
    r'YandexBlogs|'
    r'YandexFavicons|'
    r'YandexWebmaster|'
    r'YandexPagechecker|'
    r'YandexImageResizer|'
    r'YandexAdNet|'
    r'YandexDirect|'
    r'YandexMetrika|'
    r'YandexTurbo|'
    r'YandexTracker|'
    r'YandexSitelinks|'
    r'YandexCalendar|'
    r'YandexNews|'
    r'YandexOntoDB|'
    r'YandexMarket|'
    r'YandexVertis|'
    r'YandexForDomain|'
    r'YandexSpravBot|'
    r'YandexRCA',
    re.IGNORECASE,
)

# ── Referer паттерны ─────────────────────────────────────────────────────────

# Все домены Яндекса: yandex.TLD и ya.ru
_YANDEX_TLDS = (
    'ru', 'com', 'by', 'kz', 'ua', 'net', 'fr', 'tr', 'az',
    'ee', 'lt', 'lv', 'md', 'tj', 'tm', 'uz', 'co.il', 'com.tr',
    'com.ge', 'com.am',
)
_tlds_pattern = '|'.join(re.escape(t) for t in _YANDEX_TLDS)

_RE_YANDEX_REFERER = re.compile(
    rf'https?://(www\.)?(yandex\.({_tlds_pattern})|ya\.ru)'
    r'(/search|/clck|/\?|/yandsearch|$)',
    re.IGNORECASE,
)

# Дзен, Кью, Маркет — другие сервисы Яндекса
_RE_YANDEX_SERVICES = re.compile(
    r'https?://(www\.)?(zen\.yandex\.\w+|dzen\.ru|'
    r'market\.yandex\.\w+|music\.yandex\.\w+|'
    r'news\.yandex\.\w+|mail\.yandex\.\w+|'
    r'translate\.yandex\.\w+)',
    re.IGNORECASE,
)

# ── Client Hints ─────────────────────────────────────────────────────────────

_RE_CH_YANDEX = re.compile(r'YaBrowser|Yandex', re.IGNORECASE)


# ── Публичные функции ────────────────────────────────────────────────────────

def is_yandex_browser(ua: str) -> bool:
    """True если User-Agent содержит маркеры Яндекс Браузера."""
    return bool(_RE_YABROWSER.search(ua))


def is_yandex_bot(ua: str) -> bool:
    """True если User-Agent содержит маркеры Яндекс-бота."""
    return bool(_RE_YABOT.search(ua))


def is_yandex_referrer(referer: str) -> bool:
    """True если Referer указывает на Яндекс (поиск или сервисы)."""
    if not referer:
        return False
    return bool(_RE_YANDEX_REFERER.search(referer) or _RE_YANDEX_SERVICES.search(referer))


def is_yandex_client_hints(headers: Dict[str, str]) -> bool:
    """
    Проверяет Client Hints (Sec-CH-UA, Sec-CH-UA-Full-Version-List).
    Современные Chromium-браузеры (включая YaBrowser) отправляют эти заголовки.
    """
    for key in ('Sec-CH-UA', 'Sec-CH-UA-Full-Version-List'):
        val = headers.get(key, '')
        if val and _RE_CH_YANDEX.search(val):
            return True
    return False


class DetectResult:
    """Результат детекции — какие именно сигналы сработали."""
    __slots__ = ('browser', 'bot', 'referrer', 'client_hints')

    def __init__(self, browser: bool, bot: bool, referrer: bool, client_hints: bool):
        self.browser = browser
        self.bot = bot
        self.referrer = referrer
        self.client_hints = client_hints

    @property
    def detected(self) -> bool:
        return self.browser or self.bot or self.referrer or self.client_hints

    @property
    def reason(self) -> Optional[str]:
        if self.bot:
            return 'yandex_bot'
        if self.browser:
            return 'yandex_browser'
        if self.client_hints:
            return 'yandex_client_hints'
        if self.referrer:
            return 'yandex_referrer'
        return None

    def __bool__(self) -> bool:
        return self.detected

    def __repr__(self) -> str:
        return f'DetectResult(detected={self.detected}, reason={self.reason!r})'


def detect(headers: Dict[str, str]) -> DetectResult:
    """
    Основная функция детекции. Принимает словарь HTTP-заголовков.

    Пример:
        headers = {
            'User-Agent': request.headers.get('User-Agent', ''),
            'Referer': request.headers.get('Referer', ''),
            'Sec-CH-UA': request.headers.get('Sec-CH-UA', ''),
        }
        result = detect(headers)
        if result:
            print(result.reason)
    """
    ua = headers.get('User-Agent', '')
    referer = headers.get('Referer', '')

    return DetectResult(
        browser=is_yandex_browser(ua),
        bot=is_yandex_bot(ua),
        referrer=is_yandex_referrer(referer),
        client_hints=is_yandex_client_hints(headers),
    )


def detect_from_request(request) -> DetectResult:
    """
    Удобная обёртка: принимает объект request с атрибутом .headers
    (Flask, Django, FastAPI — у всех есть .headers).
    """
    h = request.headers
    headers = {
        'User-Agent': h.get('User-Agent', '') or h.get('HTTP_USER_AGENT', ''),
        'Referer': h.get('Referer', '') or h.get('HTTP_REFERER', ''),
        'Sec-CH-UA': h.get('Sec-CH-UA', '') or h.get('HTTP_SEC_CH_UA', ''),
        'Sec-CH-UA-Full-Version-List': (
            h.get('Sec-CH-UA-Full-Version-List', '')
            or h.get('HTTP_SEC_CH_UA_FULL_VERSION_LIST', '')
        ),
    }
    return detect(headers)
