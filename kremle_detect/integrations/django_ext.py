# -*- coding: utf-8 -*-
"""
Django-интеграция KremleDetect (middleware).

Использование в settings.py:
    MIDDLEWARE = [
        'django.contrib.sessions.middleware.SessionMiddleware',   # должен идти раньше
        ...
        'kremle_detect.integrations.django_ext.KremleDjangoMiddleware',
    ]

    KREMLE_CATEGORIES = ['math', 'physics', 'russian', 'literature']
    KREMLE_QUESTION_COUNT = 15
    KREMLE_MAX_ERRORS = 3

Также нужно подключить URL-ы в urls.py:
    from kremle_detect.integrations.django_ext import kremle_urls
    urlpatterns = [
        path('kremle/', kremle_urls()),
        ...
    ]

Настройки (все необязательные):
    KREMLE_SECRET = '...'
    KREMLE_SKIP_PATHS = ['/admin/', '/static/']
    KREMLE_WHITELIST = ['127.0.0.1', '10.0.0.0/8']
    KREMLE_TRUSTED_PROXIES = None    # None → loopback+приватные, [] → никому
    KREMLE_RATE_LIMIT = 10
    KREMLE_RATE_WINDOW = 600
    KREMLE_CHALLENGE_RATE_LIMIT = 60
    KREMLE_TEMPLATE = None
    KREMLE_STORAGE = None
    KREMLE_EXTRA_QUESTIONS = None
    KREMLE_ONLY_EXTRA = False
    KREMLE_FAIL_THRESHOLD = 0
    KREMLE_BLACKLIST_TTL = 86400
    KREMLE_POLICY = None   # None → все сигналы требуют капчу (challenge)
    KREMLE_SAMPLE_RATE = 1.0
    KREMLE_METRICS_ENABLED = True
    KREMLE_VERIFIED_TTL = 86400
    KREMLE_BIND_IP = False
    KREMLE_BIND_UA = False
    KREMLE_QUESTIONS_SOURCE = 'auto'
    KREMLE_QUESTIONS_IMAGES = False   # задания с рисунком из «Решу ЕГЭ»
    KREMLE_JSON_API = True        # JSON-ответ вместо редиректа для fetch/SPA
    KREMLE_HEADLESS = False       # всегда JSON (весь сайт — API)
    KREMLE_ENABLE_OPS_ROUTES = True
"""

from __future__ import annotations

import json
import os
from typing import Callable

from .. import __version__
from ..captcha import CaptchaEngine
from ..detector import detect_from_request
from ..ip import client_ip, ip_matches
from ..metrics import health_payload
from ..session import (
    NEXT_KEY, SESSION_KEY, TOKEN_KEY, build_verification, is_verified, remaining_seconds,
)
from ..storage import MemoryStorage, RedisStorage
from ._common import (
    accepts_json, blocked_payload, challenge_payload, no_store_headers, wants_json,
)

_engine_cache = {}
_ENGINE_CACHE_MAX = 8

# Значения этих настроек влияют на движок — меняются (в тестах, например),
# значит движок надо пересобрать.
_ENGINE_SETTINGS = (
    'KREMLE_CATEGORIES', 'KREMLE_QUESTION_COUNT', 'KREMLE_MAX_ERRORS',
    'KREMLE_SECRET', 'KREMLE_STORAGE', 'KREMLE_RATE_LIMIT', 'KREMLE_RATE_WINDOW',
    'KREMLE_CHALLENGE_RATE_LIMIT', 'KREMLE_ON_DETECT', 'KREMLE_ON_PASS',
    'KREMLE_ON_FAIL', 'KREMLE_EXTRA_QUESTIONS', 'KREMLE_ONLY_EXTRA',
    'KREMLE_FAIL_THRESHOLD', 'KREMLE_BLACKLIST_TTL', 'KREMLE_POLICY',
    'KREMLE_SAMPLE_RATE', 'KREMLE_METRICS_ENABLED', 'KREMLE_VERIFIED_TTL',
    'KREMLE_BIND_IP', 'KREMLE_BIND_UA', 'KREMLE_QUESTIONS_SOURCE',
    'KREMLE_QUESTIONS_IMAGES',
)


def _engine_cache_key(settings) -> tuple:
    key = [id(settings)]
    for name in _ENGINE_SETTINGS:
        value = getattr(settings, name, None)
        if isinstance(value, (list, dict, tuple, set)):
            key.append(repr(sorted(value.items()) if isinstance(value, dict) else value))
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
            challenge_rate_limit=getattr(settings, 'KREMLE_CHALLENGE_RATE_LIMIT', 60),
            on_detect=getattr(settings, 'KREMLE_ON_DETECT', None),
            on_pass=getattr(settings, 'KREMLE_ON_PASS', None),
            on_fail=getattr(settings, 'KREMLE_ON_FAIL', None),
            extra_questions=getattr(settings, 'KREMLE_EXTRA_QUESTIONS', None),
            only_extra=getattr(settings, 'KREMLE_ONLY_EXTRA', False),
            fail_threshold=getattr(settings, 'KREMLE_FAIL_THRESHOLD', 0),
            blacklist_ttl=getattr(settings, 'KREMLE_BLACKLIST_TTL', 86400),
            policy=getattr(settings, 'KREMLE_POLICY', None),
            sample_rate=getattr(settings, 'KREMLE_SAMPLE_RATE', 1.0),
            metrics_enabled=getattr(settings, 'KREMLE_METRICS_ENABLED', True),
            verified_ttl=getattr(settings, 'KREMLE_VERIFIED_TTL', 86400),
            bind_ip=getattr(settings, 'KREMLE_BIND_IP', False),
            bind_ua=getattr(settings, 'KREMLE_BIND_UA', False),
            questions_source=getattr(settings, 'KREMLE_QUESTIONS_SOURCE', 'auto'),
            questions_images=getattr(settings, 'KREMLE_QUESTIONS_IMAGES', False),
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


def _settings_flag(settings, name: str, default):
    return getattr(settings, name, default)


def _wants_json(request, settings) -> bool:
    if _settings_flag(settings, 'KREMLE_HEADLESS', False):
        return True
    if not _settings_flag(settings, 'KREMLE_JSON_API', True):
        return False
    return wants_json(
        request.META.get('HTTP_ACCEPT'),
        request.META.get('HTTP_X_REQUESTED_WITH'),
        request.path,
    )


def _storage_name(storage) -> str:
    if isinstance(storage, RedisStorage):
        return 'redis'
    if isinstance(storage, MemoryStorage):
        return 'memory'
    return type(storage).__name__


class KremleDjangoMiddleware:
    """Django middleware — применяет политику к детектированному трафику."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import JsonResponse
        from django.shortcuts import redirect

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

        ip = _get_client_ip(request, trusted_proxies)
        engine = _get_engine(settings)

        ua = request.META.get('HTTP_USER_AGENT')
        state = request.session.get(SESSION_KEY)
        if is_verified(
            state,
            ip=ip,
            ua=ua,
            bind_ip=engine.bind_ip,
            bind_ua=engine.bind_ua,
        ):
            return self.get_response(request)
        if state is not None:
            request.session.pop(SESSION_KEY, None)

        # IP whitelist (static config + persistent storage)
        if whitelist and _ip_in_whitelist(ip, whitelist):
            return self.get_response(request)
        if engine.is_whitelisted(ip):
            return self.get_response(request)

        engine.metrics.count_request()

        if engine.is_blacklisted(ip):
            engine.metrics.count_blocked('blacklisted')
            if _wants_json(request, settings):
                return JsonResponse(blocked_payload('blacklisted'), status=403,
                                headers=no_store_headers())
            return self._plain_blocked()

        decision = engine.decide(detect_from_request(request))
        engine.record_decision(decision, ip=ip)

        if decision.action == 'monitor':
            return self.get_response(request)
        if decision.action == 'block':
            if _wants_json(request, settings):
                return JsonResponse(blocked_payload(decision.reason or 'blocked'),
                                    status=403, headers=no_store_headers())
            return self._plain_blocked()
        if decision.action == 'challenge':
            request.session[NEXT_KEY] = request.get_full_path()
            if _wants_json(request, settings):
                return JsonResponse(challenge_payload(decision.reason), status=403,
                                    headers=no_store_headers())
            return redirect('/kremle/challenge/')

        return self.get_response(request)

    @staticmethod
    def _plain_blocked():
        from django.http import HttpResponse
        return HttpResponse('Доступ заблокирован.', status=403,
                            content_type='text/plain; charset=utf-8')


def kremle_urls():
    """Возвращает URL-паттерны для Django (обёрнутые в include)."""
    from django.http import HttpResponse, JsonResponse
    from django.urls import include, path, reverse
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
        request.session[TOKEN_KEY] = ch.token

        data = ch.to_dict(verify_url=reverse('kremle_verify'))

        if _wants_json(request, settings) or accepts_json(request.META.get('HTTP_ACCEPT', '')):
            response = JsonResponse(data)
            for name, value in no_store_headers().items():
                response[name] = value
            return response

        custom_tpl = getattr(settings, 'KREMLE_TEMPLATE', None)
        tpl_path = custom_tpl or os.path.join(template_dir, 'kremle_captcha.html')

        try:
            with open(tpl_path, encoding='utf-8') as f:
                html = f.read()
        except OSError as e:
            raise RuntimeError(
                f'Не удалось открыть шаблон капчи: {tpl_path!r} — {e}'
            ) from e

        html = html.replace('{{ questions_json }}', json.dumps(data, ensure_ascii=False))
        response = HttpResponse(html, content_type='text/html; charset=utf-8')
        for name, value in no_store_headers().items():
            response[name] = value
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

        token = data.get('token') or request.session.get(TOKEN_KEY, '')
        answers = data.get('answers', {})
        fingerprint = data.get('fingerprint')
        trusted_proxies = getattr(settings, 'KREMLE_TRUSTED_PROXIES', None)
        ip = _get_client_ip(request, trusted_proxies)

        result = engine.verify(token, answers, ip=ip, fingerprint=fingerprint)
        request.session.pop(TOKEN_KEY, None)

        if result['passed']:
            request.session[SESSION_KEY] = build_verification(
                ip=ip,
                ua=request.META.get('HTTP_USER_AGENT'),
                ttl=engine.verified_ttl,
            )
            next_url = request.session.pop(NEXT_KEY, '/')
            result['redirect'] = next_url
        else:
            result['redirect'] = None

        return JsonResponse(result)

    @require_GET
    def status(request):
        from django.conf import settings
        engine = _get_engine(settings)
        state = request.session.get(SESSION_KEY)
        return JsonResponse({
            'verified': is_verified(
                state,
                ua=request.META.get('HTTP_USER_AGENT'),
                bind_ua=engine.bind_ua,
            ),
            'expires_in': remaining_seconds(state),
        })

    @csrf_exempt
    @require_POST
    def logout(request):
        request.session.pop(SESSION_KEY, None)
        request.session.pop(TOKEN_KEY, None)
        request.session.pop(NEXT_KEY, None)
        return JsonResponse({'verified': False})

    @require_GET
    def health(request):
        from django.conf import settings
        engine = _get_engine(settings)
        storage = engine.storage
        payload = health_payload(
            version=__version__,
            storage=storage,
            storage_name=_storage_name(storage),
            extra={
                'sample_rate': engine.sample_rate,
                'policy': dict(engine.policy),
                'verified_ttl': engine.verified_ttl,
                'questions_source': engine.questions_source,
                'questions_images': engine.questions_images,
            },
        )
        return JsonResponse(payload, status=200 if payload['storage_ok'] else 503)

    @require_GET
    def stats(request):
        from django.conf import settings
        engine = _get_engine(settings)
        return JsonResponse(engine.metrics.snapshot())

    @require_GET
    def metrics(request):
        from django.conf import settings
        engine = _get_engine(settings)
        return HttpResponse(
            engine.metrics.prometheus(),
            content_type='text/plain; version=0.0.4; charset=utf-8',
        )

    patterns = [
        path('challenge/', challenge, name='kremle_challenge'),
        path('verify/', verify, name='kremle_verify'),
        path('status/', status, name='kremle_status'),
        path('logout/', logout, name='kremle_logout'),
    ]

    # Эксплуатационные роуты можно выключить целиком (KREMLE_ENABLE_OPS_ROUTES)
    from django.conf import settings as django_settings
    if getattr(django_settings, 'KREMLE_ENABLE_OPS_ROUTES', True):
        patterns += [
            path('health/', health, name='kremle_health'),
            path('stats/', stats, name='kremle_stats'),
            path('metrics/', metrics, name='kremle_metrics'),
        ]

    # include() возвращает тройку (urlconf_module, app_name, namespace) —
    # именно её path() умеет распаковывать.
    return include(patterns)
