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

Также нужно подключить URL-ы в urls.py:
    from kremle_detect.integrations.django_ext import kremle_urls
    urlpatterns = [
        path('kremle/', kremle_urls()),
        ...
    ]
"""

from __future__ import annotations

import ipaddress
import json
import os
from typing import Callable

from ..captcha import CaptchaEngine
from ..detector import detect_from_request
from ..storage import BaseStorage

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'

_engine_cache = {}


def _get_engine(settings) -> CaptchaEngine:
    cache_key = id(settings)
    if cache_key not in _engine_cache:
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
        )
    return _engine_cache[cache_key]


def _ip_in_whitelist(ip: str, whitelist: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in whitelist:
        try:
            if '/' in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if addr == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False


def _get_client_ip(request) -> str:
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


class KremleDjangoMiddleware:
    """Django middleware — перенаправляет яндекс-пользователей на капчу."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        skip_paths = getattr(settings, 'KREMLE_SKIP_PATHS', ['/admin/', '/static/'])
        whitelist = getattr(settings, 'KREMLE_WHITELIST', [])

        path = request.path
        if path.startswith('/kremle/') or any(path.startswith(s) for s in skip_paths):
            return self.get_response(request)

        if request.session.get(SESSION_KEY):
            return self.get_response(request)

        # IP whitelist
        ip = _get_client_ip(request)
        if whitelist and _ip_in_whitelist(ip, whitelist):
            return self.get_response(request)

        engine = _get_engine(settings)

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
        ch = engine.create_challenge()
        request.session['kremle_token'] = ch.token

        custom_tpl = getattr(settings, 'KREMLE_TEMPLATE', None)
        tpl_path = custom_tpl or os.path.join(template_dir, 'kremle_captcha.html')

        with open(tpl_path, encoding='utf-8') as f:
            html = f.read()

        html = html.replace('{{ questions_json }}', json.dumps(ch.to_dict(), ensure_ascii=False))
        return HttpResponse(html, content_type='text/html; charset=utf-8')

    @csrf_exempt
    @require_POST
    def verify(request):
        from django.conf import settings
        engine = _get_engine(settings)

        data = json.loads(request.body)
        token = data.get('token') or request.session.get('kremle_token', '')
        answers = data.get('answers', {})
        fingerprint = data.get('fingerprint')
        ip = _get_client_ip(request)

        result = engine.verify(token, answers, ip=ip, fingerprint=fingerprint)

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

    return [
        path('challenge/', challenge, name='kremle_challenge'),
        path('verify/', verify, name='kremle_verify'),
        path('status/', status, name='kremle_status'),
    ]
