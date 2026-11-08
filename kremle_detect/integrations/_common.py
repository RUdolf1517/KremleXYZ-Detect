# -*- coding: utf-8 -*-
"""
Общие помощники интеграций (Flask, Django, FastAPI).

Здесь только то, что не зависит от фреймворка: разбор ``Accept``, формат
JSON-ответов для API-клиентов и заголовки, запрещающие кеширование капчи.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

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


# ── Вставка JSON в HTML ──────────────────────────────────────────────────────

#: Символы, которыми можно вырваться из ``<script>`` или сломать разбор строки.
_JSON_ESCAPES = {
    '<': '\\u003c',
    '>': '\\u003e',
    '&': '\\u0026',
    '\u2028': '\\u2028',
    '\u2029': '\\u2029',
}


def escape_json_for_html(text: str) -> str:
    """
    Экранировать JSON так, чтобы его нельзя было вставить в ``<script>`` безопасно.

    ``json.dumps`` экранирует кавычки, но не ``</script>``: строка
    ``"</script><script>alert(1)</script>"`` внутри JSON закрывает скрипт и
    открывает новый. Замена ``<``/``>``/``&`` на ``\\u003c`` и т.д. сохраняет
    JSON валидным (``JSON.parse`` вернёт исходный текст), но лишает возможности
    вырваться из тега. U+2028/U+2029 в старых движках ломали строковый литерал.

    Пример:
        escape_json_for_html('{"q": "</script>"}')  # '{"q": "\\u003c/script\\u003e"}'
    """
    for char, escaped in _JSON_ESCAPES.items():
        text = text.replace(char, escaped)
    return text


def json_for_script(data: Any) -> str:
    """JSON, готовый к подстановке внутрь ``<script>`` (см. escape_json_for_html)."""
    return escape_json_for_html(json.dumps(data, ensure_ascii=False))


def render_captcha_html(template_text: str, data: Any) -> str:
    """
    Подставить данные челленджа в шаблон капчи.

    Один и тот же код для Flask, Django и FastAPI: шаблон читается как текст
    (не Jinja2), подстановка — только ``{{ questions_json }}``, JSON экранирован.

    Пример:
        html = render_captcha_html(template, challenge.to_dict())
    """
    return template_text.replace('{{ questions_json }}', json_for_script(data))


# ── Заголовки безопасности ───────────────────────────────────────────────────

#: Политика по умолчанию: шаблон использует inline-стили и inline-скрипт,
#: рисунки приходят из своего роута, data-URI или горячей ссылки на портал.
DEFAULT_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def captcha_headers(csp_policy: Optional[str] = None) -> Dict[str, str]:
    """
    Заголовки ответов капчи: не кешировать + защитные заголовки.

    Одна функция на все три интеграции — чтобы набор не разъехался.

    Пример:
        headers = captcha_headers()
        'no-store' in headers['Cache-Control']
        headers['X-Frame-Options']  # 'DENY'
    """
    headers = no_store_headers()
    headers.update(security_headers(csp_policy))
    return headers


def security_headers(csp_policy: Optional[str] = None) -> Dict[str, str]:
    """
    Заголовки для страниц капчи: нельзя встроить в iframe, нельзя угадать тип.

    Args:
        csp_policy: своя политика CSP. ``None`` — политика по умолчанию,
            пустая строка — не отправлять CSP вообще (свои шаблоны со внешними
            скриптами), остальное — как есть.

    Пример:
        security_headers()['X-Frame-Options']  # 'DENY'
        'Content-Security-Policy' in security_headers('')
    """
    headers = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'no-referrer',
    }
    policy = DEFAULT_CSP if csp_policy is None else csp_policy
    if policy:
        headers['Content-Security-Policy'] = policy
    return headers


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


def is_document_request(
    accept: Optional[str] = None,
    xhr: Optional[str] = None,
    method: str = 'GET',
    fetch_dest: Optional[str] = None,
) -> bool:
    """
    Это переход по ссылке (браузер грузит страницу), а не вызов из кода?

    Нужен режиму «капча поверх страницы» (``overlay=True``): оболочку сайта
    отдаём, чтобы модальное окно было поверх него, а данные — нет. Отличить
    одно от другого можно только по заголовкам, поэтому правило
    консервативное: всё непонятное считается API и получает капчу как раньше.

    Пример:
        is_document_request('text/html,application/xhtml+xml')   # True
        is_document_request('application/json')                 # False
        is_document_request('*/*')                              # False
    """
    if method and method.upper() not in ('GET', 'HEAD'):
        return False
    if xhr and xhr.strip().lower() == 'xmlhttprequest':
        return False
    if fetch_dest:
        # Браузер сам говорит, зачем пришёл: document — переход, пустой/иной
        # (empty, script, image) — подзагрузка, её пропускать нельзя.
        return fetch_dest.strip().lower() == 'document'
    if not accept:
        return False
    for part in accept.split(','):
        mime = part.split(';')[0].strip().lower()
        if mime in ('text/html', 'application/xhtml+xml'):
            return True
        if mime == 'application/json' or mime.endswith('+json'):
            return False
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
