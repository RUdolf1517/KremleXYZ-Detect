# -*- coding: utf-8 -*-
"""Тесты детекции Яндекс-пользователей."""

from kremle_detect import (
    detect,
    is_yandex_browser,
    is_yandex_bot,
    is_yandex_referrer,
    is_yandex_client_hints,
)


class TestIsYandexBrowser:
    def test_yabrowser_desktop(self):
        ua = 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0 YaBrowser/24.1.0 Safari/537.36'
        assert is_yandex_browser(ua) is True

    def test_yabrowser_mobile(self):
        ua = 'Mozilla/5.0 (Linux; Android 13) YaBrowser/23.11.2 Mobile'
        assert is_yandex_browser(ua) is True

    def test_yaapp_android(self):
        assert is_yandex_browser('YaApp_Android/23.81') is True

    def test_yaapp_ios(self):
        assert is_yandex_browser('YaApp_iOS/100.0') is True

    def test_yandex_search(self):
        assert is_yandex_browser('YandexSearch/7.55') is True

    def test_yandex_station(self):
        assert is_yandex_browser('Mozilla/5.0 YandexStation/2.0') is True

    def test_chrome_normal(self):
        ua = 'Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36'
        assert is_yandex_browser(ua) is False

    def test_firefox(self):
        assert is_yandex_browser('Mozilla/5.0 Firefox/121.0') is False

    def test_empty(self):
        assert is_yandex_browser('') is False


class TestIsYandexBot:
    def test_yandexbot(self):
        assert is_yandex_bot('Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)') is True

    def test_yandex_metrika(self):
        assert is_yandex_bot('YandexMetrika/2.0') is True

    def test_yandex_images(self):
        assert is_yandex_bot('YandexImages/3.0') is True

    def test_yandex_direct(self):
        assert is_yandex_bot('YandexDirect/1.0') is True

    def test_googlebot(self):
        assert is_yandex_bot('Googlebot/2.1') is False

    def test_normal_browser(self):
        assert is_yandex_bot('Mozilla/5.0 Chrome/120') is False


class TestIsYandexReferrer:
    def test_yandex_ru_search(self):
        assert is_yandex_referrer('https://yandex.ru/search?q=test') is True

    def test_yandex_com(self):
        assert is_yandex_referrer('https://yandex.com/search?q=hello') is True

    def test_yandex_kz(self):
        assert is_yandex_referrer('https://yandex.kz/search?q=test') is True

    def test_ya_ru(self):
        assert is_yandex_referrer('https://ya.ru/?q=test') is True

    def test_dzen_ru(self):
        assert is_yandex_referrer('https://dzen.ru/article') is True

    def test_zen_yandex(self):
        assert is_yandex_referrer('https://zen.yandex.ru/media') is True

    def test_market_yandex(self):
        assert is_yandex_referrer('https://market.yandex.ru/product/123') is True

    def test_google(self):
        assert is_yandex_referrer('https://google.com/search?q=test') is False

    def test_empty(self):
        assert is_yandex_referrer('') is False

    def test_none_like(self):
        assert is_yandex_referrer('https://example.com') is False


class TestIsYandexClientHints:
    def test_sec_ch_ua_yabrowser(self):
        headers = {'Sec-CH-UA': '"Chromium";v="120", "YaBrowser";v="24"'}
        assert is_yandex_client_hints(headers) is True

    def test_sec_ch_ua_full(self):
        headers = {'Sec-CH-UA-Full-Version-List': '"Chromium";v="120", "YaBrowser";v="24.1"'}
        assert is_yandex_client_hints(headers) is True

    def test_chrome_only(self):
        headers = {'Sec-CH-UA': '"Chromium";v="120", "Google Chrome";v="120"'}
        assert is_yandex_client_hints(headers) is False

    def test_empty(self):
        assert is_yandex_client_hints({}) is False


class TestDetect:
    def test_yabrowser_detected(self):
        r = detect({'User-Agent': 'YaBrowser/24.1'})
        assert r.detected is True
        assert r.browser is True
        assert r.reason == 'yandex_browser'

    def test_bot_detected(self):
        r = detect({'User-Agent': 'YandexBot/3.0'})
        assert r.detected is True
        assert r.bot is True
        assert r.reason == 'yandex_bot'

    def test_referrer_detected(self):
        r = detect({'Referer': 'https://yandex.ru/search?q=test'})
        assert r.detected is True
        assert r.referrer is True
        assert r.reason == 'yandex_referrer'

    def test_client_hints_detected(self):
        r = detect({'Sec-CH-UA': '"YaBrowser";v="24"'})
        assert r.detected is True
        assert r.client_hints is True
        assert r.reason == 'yandex_client_hints'

    def test_normal_user(self):
        r = detect({'User-Agent': 'Chrome/120', 'Referer': 'https://google.com'})
        assert r.detected is False
        assert r.reason is None
        assert bool(r) is False

    def test_multiple_signals(self):
        r = detect({
            'User-Agent': 'YaBrowser/24.1',
            'Referer': 'https://yandex.ru/search',
        })
        assert r.browser is True
        assert r.referrer is True
        assert r.reason == 'yandex_browser'  # browser приоритетнее

    def test_bot_priority_over_browser(self):
        r = detect({'User-Agent': 'YandexBot/3.0 YaBrowser/24.1'})
        assert r.reason == 'yandex_bot'  # bot приоритетнее

    def test_repr(self):
        r = detect({'User-Agent': 'YaBrowser/24'})
        assert 'DetectResult' in repr(r)
        assert 'yandex_browser' in repr(r)
