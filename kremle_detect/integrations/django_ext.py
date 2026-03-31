# -*- coding: utf-8 -*-
"""
Django-интеграция KremleDetect (middleware).

Использование в settings.py:
    MIDDLEWARE = [
        ...
        'kremle_detect.integrations.django_ext.KremleDjangoMiddleware',
    ]

    # Опционально:
    KREMLE_CATEGORIES = ['math', 'physics', 'russian', 'literature']
    KREMLE_QUESTION_COUNT = 15
    KREMLE_MAX_ERRORS = 3
    KREMLE_SECRET = 'your-secret'
    KREMLE_SKIP_PATHS = ['/admin/', '/static/']

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

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'

# Ленивая инициализация engine — создаётся при первом запросе
_engine_cache = {}


def _get_engine(settings) -> CaptchaEngine:
    cache_key = id(settings)
    if cache_key not in _engine_cache:
        _engine_cache[cache_key] = CaptchaEngine(
            categories=getattr(settings, 'KREMLE_CATEGORIES', None),
            question_count=getattr(settings, 'KREMLE_QUESTION_COUNT', 15),
            max_errors=getattr(settings, 'KREMLE_MAX_ERRORS', 3),
            secret=getattr(settings, 'KREMLE_SECRET', getattr(settings, 'SECRET_KEY', 'kremle')),
        )
    return _engine_cache[cache_key]


class KremleDjangoMiddleware:
    """Django middleware — перенаправляет яндекс-пользователей на капчу."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        skip_paths = getattr(settings, 'KREMLE_SKIP_PATHS', ['/admin/', '/static/'])

        # Пропускаем kremle-пути и настроенные исключения
        path = request.path
        if path.startswith('/kremle/') or any(path.startswith(s) for s in skip_paths):
            return self.get_response(request)

        # Уже прошёл капчу
        if request.session.get(SESSION_KEY):
            return self.get_response(request)

        # Проверяем детекцию
        result = detect_from_request(request)
        if result:
            from django.shortcuts import redirect
            request.session[NEXT_KEY] = request.get_full_path()
            return redirect('/kremle/challenge/')

        return self.get_response(request)


def kremle_urls():
    """Возвращает список URL-паттернов для Django."""
    from django.http import JsonResponse
    from django.template.response import TemplateResponse
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

        # Читаем шаблон вручную (не зависим от TEMPLATES Django)
        tpl_path = os.path.join(template_dir, 'kremle_captcha.html')
        with open(tpl_path, encoding='utf-8') as f:
            html = f.read()

        # Простая подстановка данных
        html = html.replace('{{ questions_json }}', json.dumps(ch.to_dict(), ensure_ascii=False))

        from django.http import HttpResponse
        return HttpResponse(html, content_type='text/html; charset=utf-8')

    @csrf_exempt
    @require_POST
    def verify(request):
        from django.conf import settings
        engine = _get_engine(settings)

        data = json.loads(request.body)
        token = data.get('token') or request.session.get('kremle_token', '')
        answers = data.get('answers', {})

        result = engine.verify(token, answers)

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
