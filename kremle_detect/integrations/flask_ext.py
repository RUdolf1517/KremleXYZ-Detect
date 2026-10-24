# -*- coding: utf-8 -*-
"""
Flask-интеграция KremleDetect.

Использование:
    from flask import Flask
    from kremle_detect.integrations.flask_ext import KremleFlask

    app = Flask(__name__)
    app.secret_key = 'your-secret'

    kremle = KremleFlask(app, categories=['math', 'physics'], question_count=10)
    # Готово — защита работает автоматически.
"""

from __future__ import annotations

import json
import os
from typing import Callable, List, Optional, Sequence

from flask import (
    Blueprint, Flask, jsonify, redirect, request, session, url_for,
)

from .. import __version__
from ..captcha import CaptchaEngine
from ..detector import detect_from_request
from ..ip import client_ip, ip_matches
from ..metrics import health_payload
from ..session import (
    NEXT_KEY, SESSION_KEY, TOKEN_KEY, build_verification, is_verified, remaining_seconds,
)
from ..storage import BaseStorage, MemoryStorage, RedisStorage
from ._common import (
    accepts_json, blocked_payload, challenge_payload, no_store_headers, wants_json,
)

# Эндпоинты, которые не надо защищать
_SKIP_ENDPOINTS = frozenset({
    'kremle.challenge',
    'kremle.verify',
    'kremle.status',
    'kremle.logout',
    'kremle.health',
    'kremle.stats',
    'kremle.metrics',
    'static',
})


def _get_client_ip(request, trusted_proxies=None) -> str:
    """
    Реальный IP клиента. X-Forwarded-For учитывается только от доверенных
    прокси (``trusted_proxies``) — иначе его можно подделать.
    """
    return client_ip(
        request.remote_addr,
        request.headers.get('X-Forwarded-For', ''),
        trusted_proxies,
    )


def _ip_in_whitelist(ip: str, whitelist: list) -> bool:
    """Проверяет, входит ли IP в whitelist (поддержка CIDR)."""
    return ip_matches(ip, whitelist)


def _storage_name(storage: BaseStorage) -> str:
    if isinstance(storage, RedisStorage):
        return 'redis'
    if isinstance(storage, MemoryStorage):
        return 'memory'
    return type(storage).__name__


class KremleFlask:
    """
    Flask-расширение для защиты от Яндекс-пользователей.

    Args:
        app: Flask-приложение (или None для init_app)
        categories: категории вопросов
        question_count: количество вопросов
        max_errors: допустимое число ошибок
        secret: секрет для подписи токенов
        skip_endpoints: эндпоинты, которые не защищать
        auto_guard: автоматический before_request guard
        storage: бэкенд хранения (MemoryStorage/RedisStorage)
        rate_limit: макс. НЕУДАЧНЫХ проверок с одного IP (0 — отключить)
        rate_window: окно rate limit в секундах
        whitelist: список IP/CIDR, которые не проверяются
        template: путь к кастомному HTML-шаблону капчи
        on_detect: callback(detect_result, ip) — при детекции
        on_pass: callback(ip, errors, total) — при прохождении
        on_fail: callback(ip, errors, total) — при провале
        extra_questions: свои вопросы
        only_extra: только свои вопросы
        trusted_proxies: IP/CIDR прокси, которым доверяем X-Forwarded-For;
                         None — loopback и приватные сети, [] — никому
        challenge_rate_limit: макс. выдач челленджа с одного IP за rate_window (0 — off)
        policy: действия по сегментам, ``{'yandex_bot': 'block'}``
        sample_rate: доля детектированных запросов, которым показывается капча
        metrics_enabled: вести счётчики (``/kremle/stats``)
        verified_ttl: срок действия «капча пройдена» в секундах (0 — бессрочно)
        bind_ip / bind_ua: переспрашивать капчу при смене IP / User-Agent
        questions_source: ``auto`` (кеш РешуЕГЭ → встроенный банк), ``builtin``,
                          ``sdamgia``
        json_api: отвечать JSON клиентам, которые просят JSON (fetch/SPA),
                  вместо редиректа на HTML-капчу
        headless: всегда отвечать JSON (весь сайт — API)
        enable_ops_routes: отдавать ``/kremle/health``, ``/stats``, ``/metrics``
    """

    def __init__(
        self,
        app: Optional[Flask] = None,
        categories: Optional[Sequence[str]] = None,
        question_count: int = 15,
        max_errors: int = 3,
        secret: Optional[str] = None,
        skip_endpoints: Optional[Sequence[str]] = None,
        auto_guard: bool = True,
        storage: Optional[BaseStorage] = None,
        rate_limit: int = 10,
        rate_window: int = 600,
        whitelist: Optional[List[str]] = None,
        template: Optional[str] = None,
        on_detect: Optional[Callable] = None,
        on_pass: Optional[Callable] = None,
        on_fail: Optional[Callable] = None,
        extra_questions: Optional[list] = None,
        only_extra: bool = False,
        fail_threshold: int = 0,
        blacklist_ttl: int = 86400,
        trusted_proxies: Optional[Sequence[str]] = None,
        challenge_rate_limit: int = 60,
        policy: Optional[dict] = None,
        sample_rate: float = 1.0,
        metrics_enabled: bool = True,
        verified_ttl: int = 86400,
        bind_ip: bool = False,
        bind_ua: bool = False,
        questions_source: str = 'auto',
        json_api: bool = True,
        headless: bool = False,
        enable_ops_routes: bool = True,
    ):
        self.categories = categories
        self.question_count = question_count
        self.max_errors = max_errors
        self._secret = secret
        self.skip_endpoints = set(skip_endpoints or set())
        self.auto_guard = auto_guard
        self._storage = storage
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self.whitelist = whitelist or []
        self.custom_template = template
        self.on_detect = on_detect
        self.on_pass = on_pass
        self.on_fail = on_fail
        self.extra_questions = extra_questions
        self.only_extra = only_extra
        self.fail_threshold = fail_threshold
        self.blacklist_ttl = blacklist_ttl
        # None → авто (loopback + приватные сети), [] → не доверять никому
        self.trusted_proxies = None if trusted_proxies is None else list(trusted_proxies)
        self.challenge_rate_limit = challenge_rate_limit
        self.policy = policy
        self.sample_rate = sample_rate
        self.metrics_enabled = metrics_enabled
        self.verified_ttl = verified_ttl
        self.bind_ip = bind_ip
        self.bind_ua = bind_ua
        self.questions_source = questions_source
        self.json_api = json_api
        self.headless = headless
        self.enable_ops_routes = enable_ops_routes
        self.engine: Optional[CaptchaEngine] = None

        if app is not None:
            self.init_app(app)

    # ── инициализация ────────────────────────────────────────────────────────

    def init_app(self, app: Flask) -> None:
        """Инициализация с Flask-приложением (паттерн app factory)."""
        secret = self._secret or app.secret_key or 'kremle-default-secret'

        self.engine = CaptchaEngine(
            categories=self.categories,
            question_count=self.question_count,
            max_errors=self.max_errors,
            secret=secret,
            storage=self._storage,
            rate_limit=self.rate_limit,
            rate_window=self.rate_window,
            on_detect=self.on_detect,
            on_pass=self.on_pass,
            on_fail=self.on_fail,
            extra_questions=self.extra_questions,
            only_extra=self.only_extra,
            fail_threshold=self.fail_threshold,
            blacklist_ttl=self.blacklist_ttl,
            challenge_rate_limit=self.challenge_rate_limit,
            policy=self.policy,
            sample_rate=self.sample_rate,
            metrics_enabled=self.metrics_enabled,
            verified_ttl=self.verified_ttl,
            bind_ip=self.bind_ip,
            bind_ua=self.bind_ua,
            questions_source=self.questions_source,
        )

        bp = self._create_blueprint()
        app.register_blueprint(bp)

        if self.auto_guard:
            app.before_request(self._guard)

        app.extensions['kremle'] = self

    # ── ответы гарда ─────────────────────────────────────────────────────────

    def _wants_json(self) -> bool:
        """Клиент ждёт JSON, а не HTML-страницу."""
        if self.headless:
            return True
        if not self.json_api:
            return False
        return wants_json(
            request.headers.get('Accept'),
            request.headers.get('X-Requested-With'),
        )

    def _challenge_response(self, reason: Optional[str]):
        """403 JSON для API или редирект на HTML-капчу для браузера."""
        if self._wants_json():
            return jsonify(challenge_payload(reason)), 403, no_store_headers()
        return redirect(url_for('kremle.challenge'))

    def _blocked_response(self, reason: Optional[str], action: str = 'block'):
        """Ответ для действия ``block`` — без капчи."""
        if self._wants_json():
            return jsonify(blocked_payload(reason or 'blocked')), 403, no_store_headers()
        return 'Доступ заблокирован.', 403

    def _is_verified(self, ip: str) -> bool:
        """Проверяет сессию с учётом TTL и привязки к клиенту."""
        state = session.get(SESSION_KEY)
        if is_verified(
            state,
            ip=ip,
            ua=request.headers.get('User-Agent'),
            bind_ip=self.bind_ip,
            bind_ua=self.bind_ua,
        ):
            return True
        if state is not None:
            session.pop(SESSION_KEY, None)
        return False

    # ── роуты ────────────────────────────────────────────────────────────────

    def _create_blueprint(self) -> Blueprint:
        default_tpl_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'templates', 'kremle_captcha.html'
        )
        bp = Blueprint('kremle', __name__, url_prefix='/kremle')

        engine = self.engine
        custom_template = self.custom_template
        trusted_proxies = self.trusted_proxies
        enable_ops = self.enable_ops_routes

        @bp.route('/challenge')
        def challenge():
            ip = _get_client_ip(request, trusted_proxies)
            if engine.check_challenge_limit(ip):
                return (
                    'Слишком много запросов. Попробуйте позже.',
                    429,
                    {'Cache-Control': 'no-store', 'Content-Type': 'text/plain; charset=utf-8'},
                )
            engine.track_challenge(ip)

            ch = engine.create_challenge()
            session[TOKEN_KEY] = ch.token
            data = ch.to_dict(verify_url=url_for('kremle.verify'))

            # headless/JSON-клиент получает вопросы сразу, без HTML
            if self.headless or accepts_json(request.headers.get('Accept', '')):
                return jsonify(data), 200, no_store_headers()

            tpl_path = custom_template or default_tpl_path
            try:
                with open(tpl_path, encoding='utf-8') as f:
                    html = f.read()
            except OSError as e:
                raise RuntimeError(
                    f'Не удалось открыть шаблон капчи: {tpl_path!r} — {e}'
                ) from e
            # Простой string-replace — шаблон не зависит от Jinja2 и работает
            # одинаково во Flask, Django и FastAPI без экранирования кавычек.
            html = html.replace('{{ questions_json }}', json.dumps(data, ensure_ascii=False))
            return html, 200, {
                'Content-Type': 'text/html; charset=utf-8',
                **no_store_headers(),
            }

        @bp.route('/verify', methods=['POST'])
        def verify():
            data = request.get_json(force=True, silent=True) or {}
            if not isinstance(data, dict):
                data = {}
            token = data.get('token') or session.get(TOKEN_KEY, '')
            answers = data.get('answers', {})
            fingerprint = data.get('fingerprint')
            ip = _get_client_ip(request, trusted_proxies)

            result = engine.verify(token, answers, ip=ip, fingerprint=fingerprint)
            session.pop(TOKEN_KEY, None)

            if result['passed']:
                session[SESSION_KEY] = build_verification(
                    ip=ip,
                    ua=request.headers.get('User-Agent'),
                    ttl=engine.verified_ttl,
                )
                # cookie живёт не дольше проверки (0 = сессионная)
                session.permanent = engine.verified_ttl > 0
                next_url = session.pop(NEXT_KEY, '/')
                result['redirect'] = next_url
            else:
                result['redirect'] = None

            return jsonify(result)

        @bp.route('/status')
        def status():
            state = session.get(SESSION_KEY)
            return jsonify({
                'verified': is_verified(
                    state,
                    ua=request.headers.get('User-Agent'),
                    bind_ua=self.bind_ua,
                ),
                'expires_in': remaining_seconds(state),
            })

        @bp.route('/logout', methods=['POST'])
        def logout():
            session.pop(SESSION_KEY, None)
            session.pop(TOKEN_KEY, None)
            session.pop(NEXT_KEY, None)
            return jsonify({'verified': False})

        if enable_ops:
            @bp.route('/health')
            def health():
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
                    },
                )
                return jsonify(payload), (200 if payload['storage_ok'] else 503)

            @bp.route('/stats')
            def stats():
                return jsonify(engine.metrics.snapshot())

            @bp.route('/metrics')
            def metrics():
                return engine.metrics.prometheus(), 200, {
                    'Content-Type': 'text/plain; version=0.0.4; charset=utf-8',
                }

        return bp

    # ── гард ─────────────────────────────────────────────────────────────────

    def _guard(self):
        """before_request хук — применяет политику к детектированному трафику."""
        if request.endpoint in (_SKIP_ENDPOINTS | self.skip_endpoints):
            return None

        ip = _get_client_ip(request, self.trusted_proxies)

        if self._is_verified(ip):
            return None

        # IP whitelist (static config + persistent storage)
        if self.whitelist and _ip_in_whitelist(ip, self.whitelist):
            return None
        if self.engine.is_whitelisted(ip):
            return None

        self.engine.metrics.count_request()

        # IP blacklist — блокируем сразу, без капчи
        if self.engine.is_blacklisted(ip):
            self.engine.metrics.count_blocked('blacklisted')
            return self._blocked_response('blacklisted')

        decision = self.engine.decide(detect_from_request(request))
        self.engine.record_decision(decision, ip=ip)

        if decision.action == 'monitor':
            # shadow-режим: пропускаем, но уже посчитали
            return None
        if decision.action == 'block':
            return self._blocked_response(decision.reason)
        if decision.action == 'challenge':
            session[NEXT_KEY] = request.url
            return self._challenge_response(decision.reason)
        return None

    def is_detected(self) -> bool:
        """Проверяет текущий запрос."""
        return bool(detect_from_request(request))

    def protect(self, f):
        """
        Декоратор для защиты отдельного роута.

        Использование:
            @app.route('/secret')
            @kremle.protect
            def secret():
                return 'секретная страница'

        Работает независимо от auto_guard — можно использовать
        вместе с auto_guard=False для точечной защиты.
        """
        import functools

        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            ip = _get_client_ip(request, self.trusted_proxies)
            if self._is_verified(ip):
                return f(*args, **kwargs)

            if self.whitelist and _ip_in_whitelist(ip, self.whitelist):
                return f(*args, **kwargs)
            if self.engine.is_whitelisted(ip):
                return f(*args, **kwargs)

            if self.engine.is_blacklisted(ip):
                return self._blocked_response('blacklisted')

            decision = self.engine.decide(detect_from_request(request))
            self.engine.record_decision(decision, ip=ip)

            if decision.action == 'block':
                return self._blocked_response(decision.reason)
            if decision.action == 'challenge':
                session[NEXT_KEY] = request.url
                return self._challenge_response(decision.reason)
            return f(*args, **kwargs)

        return wrapper
