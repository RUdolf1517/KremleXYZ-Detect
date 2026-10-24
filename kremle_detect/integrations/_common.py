# -*- coding: utf-8 -*-
"""
Общие помощники интеграций (Flask, Django, FastAPI).

Здесь только то, что не зависит от фреймворка: разбор ``Accept``, формат
JSON-ответов для API-клиентов и заголовки, запрещающие кеширование капчи.
"""

from __future__ import annotations

from typing import Optional

#: Префиксы путей, которые считаем API по умолчанию (если запрос не сказал иначе).
API_PATH_PREFIXES = ('/api/', '/api', '/v1/', '/v2/', '/graphql')

CAPTCHA_ERROR = 'captcha_required'
BLOCKED_ERROR = 'blocked'
CHALLENGE_URL = '/kremle/challenge'

NO_STORE_HEADERS = {
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    'Pragma': 'no-cache',
}


def no_store_headers() -> dict:
    """Заголовки для ответов, содержащих токен капчи (кешировать нельзя)."""
    return dict(NO_STORE_HEADERS)


def accepts_json(accept: Optional[str]) -> bool:
    """
    Приоритет отдан JSON?

    ``application/json`` в начале списка — да; ``text/html`` раньше JSON — нет;
    ``*/*`` (curl, fetch по умолчанию) — нет, чтобы не ломать навигацию.

    Пример:
        accepts_json('application/json, text/plain, */*')  # True
        accepts_json('text/html,application/xhtml+xml')    # False
    """
    if not accept:
        return False
    for part in accept.split(','):
        mime = part.split(';')[0].strip().lower()
        if not mime:
            continue
        if mime in ('text/html', 'application/xhtml+xml'):
            return False
        if mime == 'application/json' or mime.endswith('+json'):
            return True
    return False


def wants_json(
    accept: Optional[str],
    xhr: Optional[str] = None,
    path: Optional[str] = None,
    api_prefixes: tuple = API_PATH_PREFIXES,
) -> bool:
    """
    Определяет, ждёт ли клиент JSON, а не HTML-страницу.

    Args:
        accept: заголовок ``Accept``.
        xhr: заголовок ``X-Requested-With`` (jQuery/axios).
        path: путь запроса — для эвристики по префиксу ``/api/``.
        api_prefixes: префиксы, которые считаем API.

    Пример:
        wants_json('application/json', None, '/api/orders')  # True
        wants_json('text/html', None, '/')                   # False
    """
    if accepts_json(accept):
        return True
    if xhr and xhr.strip().lower() == 'xmlhttprequest':
        return True
    if path and api_prefixes and any(path.startswith(p) for p in api_prefixes):
        return True
    return False


def challenge_payload(reason: Optional[str] = None) -> dict:
    """
    Тело ответа (403) для API-клиента, которому нужно пройти капчу.

    Пример:
        {'error': 'captcha_required', 'action': 'challenge',
         'challenge_url': '/kremle/challenge', 'reason': 'yandex_browser'}
    """
    payload = {
        'error': CAPTCHA_ERROR,
        'action': 'challenge',
        'challenge_url': CHALLENGE_URL,
    }
    if reason:
        payload['reason'] = reason
    return payload


def blocked_payload(reason: Optional[str] = None) -> dict:
    """Тело ответа (403) для заблокированного клиента: капча не поможет."""
    payload = {
        'error': BLOCKED_ERROR,
        'action': 'block',
        'challenge_url': None,
    }
    if reason and reason != BLOCKED_ERROR:
        payload['reason'] = reason
    return payload
