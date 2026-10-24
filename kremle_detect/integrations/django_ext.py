# -*- coding: utf-8 -*-
"""
Django-интеграция KremleDetect (middleware).

Использование в settings.py:
    MIDDLEWARE = [
        ...
        'kremle_detect.integrations.django_ext.KremleDjangoMiddleware',
    ]

    # Настройки:
    KREMLE_CATEGORIES = ['math', 'physics', 'russian', 'literature']
    KREMLE_QUESTION_COUNT = 15
    KREMLE_MAX_ERRORS = 3
    KREMLE_SECRET = 'your-secret'
    KREMLE_SKIP_PATHS = ['/admin/', '/static/']
    KREMLE_WHITELIST = ['127.0.0.1', '10.0.0.0/8']
    KREMLE_RATE_LIMIT = 10
    KREMLE_RATE_WINDOW = 600
    KREMLE_TEMPLATE = None          # путь к кастомному шаблону
    KREMLE_STORAGE = None           # BaseStorage instance (RedisStorage и т.д.)
    KREMLE_EXTRA_QUESTIONS = None
    KREMLE_ONLY_EXTRA = False
    KREMLE_FAIL_THRESHOLD = 0
    KREMLE_BLACKLIST_TTL = 86400
    KREMLE_TRUSTED_PROXIES = None   # None → loopback+приватные, [] → никому, список → только он
    KREMLE_CHALLENGE_RATE_LIMIT = 60                       # выдач челленджа с IP за окно

Также нужно подключить URL-ы в urls.py:
    from kremle_detect.integrations.django_ext import kremle_urls
    urlpatterns = [
        path('kremle/', kremle_urls()),
        ...
    ]
"""

from __future__ import annotations

import json
import os
from typing import Callable

from ..captcha import CaptchaEngine
from ..detector import detect_from_request
from ..ip import client_ip, ip_matches
from ..storage import BaseStorage

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'

_engine_cache = {}
_ENGINE_CACHE_MAX = 8

# Значения этих настроек влияют на движок — меняются (в тестах, например)
# значит движок надо пересобрать.
_ENGINE_SETTINGS = (
    'KREMLE_CATEGORIES', 'KREMLE_QUESTION_COUNT', 'KREMLE_MAX_ERRORS',
    'KREMLE_SECRET', 'KREMLE_STORAGE', 'KREMLE_RATE_LIMIT', 'KREMLE_RATE_WINDOW',
    'KREMLE_CHALLENGE_RATE_LIMIT', 'KREMLE_ON_DETECT', 'KREMLE_ON_PASS',
    'KREMLE_ON_FAIL', 'KREMLE_EXTRA_QUESTIONS', 'KREMLE_ONLY_EXTRA',
    'KREMLE_FAIL_THRESHOLD', 'KREMLE_BLACKLIST_TTL',
)


def _engine_cache_key(settings) -> tuple:
    key = [id(settings)]
    for name in _ENGINE_SETTINGS:
        value = getattr(settings, name, None)
        if isinstance(value, (list, dict, tuple, set)):
            key.append(repr(value))
        elif value is None or isinstance(value, (str, int, float, bool)):
            key.append(value)
        else:
            key.append(id(value))  # storage, callbacks
    return tuple(key)


def _get_engine(settings) -> CaptchaEngine:
    cache_key = _engine_cache_key(settings)
    if cache_key not in _engine_cache:
        if len(_engine_cache) >= _ENGINE_CACHE_MAX:
            _engine_cache.clear()
        _engine_cache[cache_key] = CaptchaEngine(
            categories=getattr(settings, 'KREMLE_CATEGORIES', None),
            question_count=getattr(settings, 'KREMLE_QUESTION_COUNT', 15),
            max_errors=getattr(settings, 'KREMLE_MAX_ERRORS', 3),
            secret=getattr(settings, 'KREMLE_SECRET', getattr(settings, 'SECRET_KEY', 'kremle')),
            storage=getattr(settings, 'KREMLE_STORAGE', None),
            rate_limit=getattr(settings, 'KREMLE_RATE_LIMIT', 10),
            rate_window=getattr(settings, 'KREMLE_RATE_WINDOW', 600),
            on_detect=getattr(settings, 'KREMLE_ON_DETECT', None),
            on_pass=getattr(settings, 'KREMLE_ON_PASS', None),
            on_fail=getattr(settings, 'KREMLE_ON_FAIL', None),
            extra_questions=getattr(settings, 'KREMLE_EXTRA_QUESTIONS', None),
            only_extra=getattr(settings, 'KREMLE_ONLY_EXTRA', False),
            fail_threshold=getattr(settings, 'KREMLE_FAIL_THRESHOLD', 0),
            blacklist_ttl=getattr(settings, 'KREMLE_BLACKLIST_TTL', 86400),
            challenge_rate_limit=getattr(settings, 'KREMLE_CHALLENGE_RATE_LIMIT', 60),
        )
    return _engine_cache[cache_key]


def _ip_in_whitelist(ip: str, whitelist: list) -> bool:
    return ip_matches(ip, whitelist)


def _get_client_ip(request, trusted_proxies=None) -> str:
    """
    IP клиента; X-Forwarded-For учитывается только если запрос пришёл
    от доверенного прокси (KREMLE_TRUSTED_PROXIES).
    """
    return client_ip(
        request.META.get('REMOTE_ADDR', ''),
        request.META.get('HTTP_X_FORWARDED_FOR', ''),
        trusted_proxies,
    )


class KremleDjangoMiddleware:
    """Django middleware — перенаправляет яндекс-пользователей на капчу."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        skip_paths = getattr(settings, 'KREMLE_SKIP_PATHS', ['/admin/', '/static/'])
        whitelist = getattr(settings, 'KREMLE_WHITELIST', [])
        trusted_proxies = getattr(settings, 'KREMLE_TRUSTED_PROXIES', None)

        if not hasattr(request, 'session'):
            from django.core.exceptions import ImproperlyConfigured
            raise ImproperlyConfigured(
                'KremleDjangoMiddleware требует SessionMiddleware. Добавьте '
                "'django.contrib.sessions.middleware.SessionMiddleware' в MIDDLEWARE "
                'до kremle_detect.integrations.django_ext.KremleDjangoMiddleware.'
            )

        path = request.path
        if path.startswith('/kremle/') or any(path.startswith(s) for s in skip_paths):
            return self.get_response(request)

        if request.session.get(SESSION_KEY):
            return self.get_response(request)

        # IP whitelist (static config + persistent storage)
        ip = _get_client_ip(request, trusted_proxies)
        if whitelist and _ip_in_whitelist(ip, whitelist):
            return self.get_response(request)

        engine = _get_engine(settings)

        if engine.is_whitelisted(ip):
            return self.get_response(request)

        # IP blacklist
        if engine.is_blacklisted(ip):
            from django.shortcuts import redirect
            return redirect('/kremle/challenge/')

        result = detect_from_request(request)
        if result:
            engine.notify_detect(result, ip=ip)
            from django.shortcuts import redirect
            request.session[NEXT_KEY] = request.get_full_path()
            return redirect('/kremle/challenge/')

        return self.get_response(request)


def kremle_urls():
    """Возвращает список URL-паттернов для Django."""
    from django.http import HttpResponse, JsonResponse
    from django.urls import path
    from django.views.decorators.csrf import csrf_exempt
    from django.views.decorators.http import require_GET, require_POST

    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

    @require_GET
    def challenge(request):
        from django.conf import settings
        engine = _get_engine(settings)

        trusted_proxies = getattr(settings, 'KREMLE_TRUSTED_PROXIES', None)
        ip = _get_client_ip(request, trusted_proxies)
        if engine.check_challenge_limit(ip):
            return HttpResponse('Слишком много запросов. Попробуйте позже.',
                                status=429, content_type='text/plain; charset=utf-8')
        engine.track_challenge(ip)

        ch = engine.create_challenge()
        request.session['kremle_token'] = ch.token

        custom_tpl = getattr(settings, 'KREMLE_TEMPLATE', None)
        tpl_path = custom_tpl or os.path.join(template_dir, 'kremle_captcha.html')

        try:
            with open(tpl_path, encoding='utf-8') as f:
                html = f.read()
        except OSError as e:
            raise RuntimeError(
                f'Не удалось открыть шаблон капчи: {tpl_path!r} — {e}'
            ) from e

        from django.urls import reverse
        verify_url = reverse('kremle_verify')
        html = html.replace('{{ questions_json }}', json.dumps(ch.to_dict(verify_url=verify_url), ensure_ascii=False))
        response = HttpResponse(html, content_type='text/html; charset=utf-8')
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response['Pragma'] = 'no-cache'
        return response

    @csrf_exempt
    @require_POST
    def verify(request):
        from django.conf import settings
        engine = _get_engine(settings)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'invalid_json'}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({'error': 'invalid_json'}, status=400)

        token = data.get('token') or request.session.get('kremle_token', '')
        answers = data.get('answers', {})
        fingerprint = data.get('fingerprint')
        trusted_proxies = getattr(settings, 'KREMLE_TRUSTED_PROXIES', None)
        ip = _get_client_ip(request, trusted_proxies)

        result = engine.verify(token, answers, ip=ip, fingerprint=fingerprint)
        request.session.pop('kremle_token', None)

        if result['passed']:
            request.session[SESSION_KEY] = True
            next_url = request.session.pop(NEXT_KEY, '/')
            result['redirect'] = next_url
        else:
            result['redirect'] = None

        return JsonResponse(result)

    @require_GET
    def status(request):
        return JsonResponse({'verified': bool(request.session.get(SESSION_KEY))})

    # include() возвращает тройку (urlconf_module, app_name, namespace) —
    # именно её path() умеет распаковывать. Просто список паттернов path()
    # тоже «распакует», но как те же три элемента → URLConf сломан.
    from django.urls import include

    return include([
        path('challenge/', challenge, name='kremle_challenge'),
        path('verify/', verify, name='kremle_verify'),
        path('status/', status, name='kremle_status'),
    ])
