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
    KREMLE_QUESTIONS_SOURCE = 'auto'  # auto | own | sdamgia | own+sdamgia
    KREMLE_MIXED_RATIO = 0.5          # доля портала для own+sdamgia
    KREMLE_QUESTIONS_IMAGES = False   # задания с рисунком из «Решу ЕГЭ»
    KREMLE_ADAPTIVE = True            # строже после серии провалов с IP
    KREMLE_ADAPTIVE_THRESHOLD = 3     # сколько провалов подряд включают ступень
    KREMLE_ADAPTIVE_EXTRA_QUESTIONS = 2   # +вопросов на каждой ступени
    KREMLE_STICKY_REFERRER = True  # держать капчу по Referer, пока не пройдена
    KREMLE_STICKY_TTL = 900        # сколько секунд помнить этот «долг капчи»
    KREMLE_OVERLAY = False         # капча поверх страницы (окно из виджета)
    KREMLE_JSON_API = True        # JSON-ответ вместо редиректа для fetch/SPA
    KREMLE_HEADLESS = False       # всегда JSON (весь сайт — API)
    KREMLE_ENABLE_OPS_ROUTES = True
    KREMLE_CSP_POLICY = None      # своя CSP; "" — не отправлять заголовок
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
    DEFAULT_PENDING_TTL, NEXT_KEY, SESSION_KEY, TOKEN_KEY, build_verification,
    clear_pending, is_verified, mark_pending, pending_reason, remaining_seconds,
)
from ..storage import MemoryStorage, RedisStorage
from ..widget import headers as widget_headers, read_bundle
from ._common import (
    accepts_json, blocked_payload, challenge_payload, no_store_headers, wants_json,
    captcha_headers,
    is_document_request,
    render_captcha_html,
)

_engine_cache: dict = {}
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
    'KREMLE_QUESTIONS_IMAGES', 'KREMLE_IMAGES_CACHE_DIR', 'KREMLE_IMAGES_PREFIX',
    'KREMLE_MIXED_RATIO', 'KREMLE_ADAPTIVE', 'KREMLE_ADAPTIVE_THRESHOLD',
    'KREMLE_ADAPTIVE_EXTRA_QUESTIONS', 'KREMLE_STICKY_REFERRER',
    'KREMLE_STICKY_TTL',
)


def _engine_cache_key(settings) -> tuple:
    key: list = [id(settings)]
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
            mixed_ratio=getattr(settings, 'KREMLE_MIXED_RATIO', 0.5),
            adaptive=getattr(settings, 'KREMLE_ADAPTIVE', True),
            adaptive_threshold=getattr(settings, 'KREMLE_ADAPTIVE_THRESHOLD', 3),
            adaptive_extra_questions=getattr(
                settings, 'KREMLE_ADAPTIVE_EXTRA_QUESTIONS', 2
            ),
            questions_images=getattr(settings, 'KREMLE_QUESTIONS_IMAGES', False),
            images_cache_dir=getattr(settings, 'KREMLE_IMAGES_CACHE_DIR', None),
            images_prefix=getattr(
                settings, 'KREMLE_IMAGES_PREFIX', '/kremle/img/',
            ),
        )
    return _engine_cache[cache_key]


def _captcha_headers(settings) -> dict:
    """Заголовки ответов капчи: не кешировать + защитные заголовки."""
    return captcha_headers(getattr(settings, 'KREMLE_CSP_POLICY', None))


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

        detection = detect_from_request(request)
        decision = engine.decide(detection)
        engine.record_decision(decision, ip=ip)

        sticky = getattr(settings, 'KREMLE_STICKY_REFERRER', True)
        sticky_ttl = getattr(settings, 'KREMLE_STICKY_TTL', DEFAULT_PENDING_TTL)
        overlay = getattr(settings, 'KREMLE_OVERLAY', False)

        if decision.action == 'monitor':
            return self.get_response(request)
        if decision.action == 'block':
            if _wants_json(request, settings):
                return JsonResponse(blocked_payload(decision.reason or 'blocked'),
                                    status=403, headers=no_store_headers())
            return self._plain_blocked()
        if decision.action == 'challenge':
            if overlay:
                # «Поверх страницы»: долг ставим при любом сигнале, а переход
                # по ссылке пропускаем — модальное окно покажет капчу, данные
                # останутся за ней.
                mark_pending(request.session, decision.reason, sticky_ttl)
                if self._is_document(request):
                    return self.get_response(request)
            elif sticky and detection.referrer:
                # Referer поисковика приходит только с первым запросом: без
                # записи в сессии капча обходится стиранием её адреса.
                mark_pending(request.session, decision.reason, sticky_ttl)
            return self._challenge(request, redirect, JsonResponse, settings,
                                   decision.reason)

        sticky = sticky or overlay
        reason = pending_reason(request.session, sticky_ttl) if sticky else None
        if reason:
            engine.metrics.count_detect(reason, 'challenge')
            if overlay and self._is_document(request):
                return self.get_response(request)
            return self._challenge(request, redirect, JsonResponse, settings, reason)

        return self.get_response(request)

    @staticmethod
    def _is_document(request) -> bool:
        """Переход по ссылке, а не подзагрузка и не API-вызов."""
        return is_document_request(
            request.META.get('HTTP_ACCEPT'),
            request.META.get('HTTP_X_REQUESTED_WITH'),
            request.method,
            request.META.get('HTTP_SEC_FETCH_DEST'),
        )

    @staticmethod
    def _challenge(request, redirect, JsonResponse, settings, reason):
        """Показать капчу: JSON для API-клиента, редирект для браузера."""
        request.session[NEXT_KEY] = request.get_full_path()
        if _wants_json(request, settings):
            return JsonResponse(challenge_payload(reason), status=403,
                                headers=no_store_headers())
        return redirect('/kremle/challenge/')

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
            # окно лимита известно — говорим клиенту, когда пробовать снова
            return HttpResponse('Слишком много запросов. Попробуйте позже.',
                                status=429, content_type='text/plain; charset=utf-8',
                                headers={'Retry-After': str(engine.rate_window)})
        engine.track_challenge(ip)

        ch = engine.create_challenge(ip=ip)
        request.session[TOKEN_KEY] = ch.token

        data = ch.to_dict(verify_url=reverse('kremle_verify'),
                          max_errors=ch.max_errors)

        if _wants_json(request, settings) or accepts_json(request.META.get('HTTP_ACCEPT', '')):
            response = JsonResponse(data)
            for name, value in _captcha_headers(settings).items():
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

        # `</script>` в тексте вопроса вырывался из шаблона — экранируем
        html = render_captcha_html(html, data)
        response = HttpResponse(html, content_type='text/html; charset=utf-8')
        for name, value in _captcha_headers(settings).items():
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
            clear_pending(request.session)
            request.session[SESSION_KEY] = build_verification(
                ip=ip,
                ua=request.META.get('HTTP_USER_AGENT'),
                ttl=engine.verified_ttl,
            )
            next_url = request.session.pop(NEXT_KEY, '/')
            result['redirect'] = next_url
        else:
            result['redirect'] = None

        response = JsonResponse(result)
        for name, value in _captcha_headers(settings).items():
            response[name] = value
        return response

    @require_GET
    def status(request):
        from django.conf import settings
        engine = _get_engine(settings)
        state = request.session.get(SESSION_KEY)
        verified = is_verified(
            state,
            ua=request.META.get('HTTP_USER_AGENT'),
            bind_ua=engine.bind_ua,
        )
        sticky = getattr(settings, 'KREMLE_STICKY_REFERRER', True)
        overlay = getattr(settings, 'KREMLE_OVERLAY', False)
        pending = None if verified else pending_reason(
            request.session,
            getattr(settings, 'KREMLE_STICKY_TTL', DEFAULT_PENDING_TTL)
            if (sticky or overlay) else None,
        )
        response = JsonResponse({
            'verified': verified,
            'expires_in': remaining_seconds(state),
            'pending': bool(pending),
            'reason': pending,
            'challenge_url': '/kremle/challenge/' if pending else None,
            'overlay': overlay,
        })
        for name, value in _captcha_headers(settings).items():
            response[name] = value
        return response

    @csrf_exempt
    @require_POST
    def logout(request):
        from django.conf import settings

        request.session.pop(SESSION_KEY, None)
        request.session.pop(TOKEN_KEY, None)
        request.session.pop(NEXT_KEY, None)
        # Долг капчи переживает выход: иначе /kremle/logout = «отмени капчу».
        response = JsonResponse({'verified': False})
        for name, value in _captcha_headers(settings).items():
            response[name] = value
        return response

    @require_GET
    def health(request):
        from django.conf import settings
        engine = _get_engine(settings)
        storage = engine.storage
        payload = health_payload(
            version=__version__,
            storage=storage,
            storage_name=_storage_name(storage),
            questions=engine.questions_health(),
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

    @require_GET
    def widget(request, name):
        """Собранный виджет без React: один файл, один <script>."""
        payload = read_bundle(name)
        if payload is None:
            return HttpResponse(
                'Виджет не собран. В исходниках: cd kremle-widget && npm run build',
                status=404, content_type='text/plain; charset=utf-8',
                headers={'Cache-Control': 'no-store'},
            )
        return HttpResponse(payload, headers=widget_headers())

    @require_GET
    def image(request, key):
        """Картинка задания из локального кеша (см. ``kremle_detect.images``)."""
        from django.conf import settings
        from ..images import RESPONSE_HEADERS as image_headers, read_image

        engine = _get_engine(settings)
        entry = read_image(key, engine.images_cache_dir)
        if entry is None:
            return HttpResponse('', status=404, headers={'Cache-Control': 'no-store'})
        response = HttpResponse(entry['bytes'], content_type=entry['content_type'])
        for name, value in image_headers.items():
            response[name] = value
        return response

    patterns = [
        path('challenge/', challenge, name='kremle_challenge'),
        path('verify/', verify, name='kremle_verify'),
        path('status/', status, name='kremle_status'),
        path('logout/', logout, name='kremle_logout'),
        # без завершающего слэша: images_prefix по умолчанию '/kremle/img/'
        path('img/<str:key>', image, name='kremle_image'),
        path('widget/<str:name>', widget, name='kremle_widget'),
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
