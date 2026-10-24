# -*- coding: utf-8 -*-
"""
Общие куски интеграций: определение JSON-клиента и ответы гарда.

Держим их отдельно, чтобы Flask/Django/FastAPI вели себя одинаково:
один и тот же Accept-заголовок должен давать один и тот же JSON.
"""

from __future__ import annotations

from typing import Optional

CHALLENGE_ERROR = 'captcha_required'


def accepts_json(accept: Optional[str]) -> bool:
    """
    True, если клиент ждёт JSON (fetch/XHR/SPA), а не HTML-страницу.

    Пример:
        accepts_json('application/json')                  # True
        accepts_json('text/html,application/xhtml+xml')   # False
        accepts_json('*/*')                               # False (браузер)
    """
    if not accept:
        return False
    for part in accept.split(','):
        mime = part.split(';')[0].strip().lower()
        if mime in ('application/json', 'application/problem+json'):
            return True
    return False


def wants_json(accept: Optional[str], xhr: Optional[str] = None) -> bool:
    """
    JSON нужен, если клиент просит JSON или это XHR-запрос.

    ``Accept: */*`` (обычный переход в браузере) JSON не считается.
    """
    if accepts_json(accept):
        return True
    return (xhr or '').strip().lower() == 'xmlhttprequest'


def challenge_payload(reason: Optional[str], action: str = 'challenge') -> dict:
    """
    Тело JSON-ответа гарда. Формат совпадает во всех интеграциях.

    Пример:
        challenge_payload('yandex_browser')
        # → {'error': 'captcha_required', 'reason': 'yandex_browser',
        #    'challenge_url': '/kremle/challenge'}
    """
    return {
        'error': CHALLENGE_ERROR,
        'reason': reason,
        'action': action,
        'challenge_url': '/kremle/challenge',
    }


def blocked_payload(reason: str) -> dict:
    """Тело ответа для действия ``block`` (без капчи)."""
    return {
        'error': 'blocked',
        'reason': reason,
        'action': 'block',
        'challenge_url': None,
    }


def no_store_headers() -> dict:
    """Заголовки для ответов, содержащих токен."""
    return {
        'Cache-Control': 'no-store, no-cache, must-revalidate',
        'Pragma': 'no-cache',
    }
