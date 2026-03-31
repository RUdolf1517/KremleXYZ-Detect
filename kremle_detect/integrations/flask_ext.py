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

import ipaddress
import json
import os
from typing import Callable, List, Optional, Sequence

from flask import (
    Blueprint, Flask, request, session,
    jsonify, redirect, url_for,
)

from ..captcha import CaptchaEngine
from ..detector import detect_from_request
from ..storage import BaseStorage

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'

# Эндпоинты, которые не надо защищать
_SKIP_ENDPOINTS = frozenset({
    'kremle.challenge',
    'kremle.verify',
    'kremle.status',
    'static',
})


def _get_client_ip(request) -> str:
    """Извлекает реальный IP с учётом прокси/nginx (X-Forwarded-For)."""
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or ''


def _ip_in_whitelist(ip: str, whitelist: list) -> bool:
    """Проверяет, входит ли IP в whitelist (поддержка CIDR)."""
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
        rate_limit: макс. попыток /verify с одного IP (0 — отключить)
        rate_window: окно rate limit в секундах
        whitelist: список IP/CIDR, которые не проверяются
        template: путь к кастомному HTML-шаблону капчи
        on_detect: callback(detect_result, ip) — при детекции
        on_pass: callback(ip, errors, total) — при прохождении
        on_fail: callback(ip, errors, total) — при провале
        extra_questions: свои вопросы
        only_extra: только свои вопросы
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
        self.engine: Optional[CaptchaEngine] = None

        if app is not None:
            self.init_app(app)

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
        )

        bp = self._create_blueprint()
        app.register_blueprint(bp)

        if self.auto_guard:
            app.before_request(self._guard)

        app.extensions['kremle'] = self

    def _create_blueprint(self) -> Blueprint:
        default_tpl_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'templates', 'kremle_captcha.html'
        )
        bp = Blueprint('kremle', __name__, url_prefix='/kremle')

        engine = self.engine
        custom_template = self.custom_template

        @bp.route('/challenge')
        def challenge():
            ch = engine.create_challenge()
            session['kremle_token'] = ch.token

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
            html = html.replace(
                '{{ questions_json }}',
                json.dumps(ch.to_dict(), ensure_ascii=False),
            )
            return html

        @bp.route('/verify', methods=['POST'])
        def verify():
            data = request.get_json(force=True, silent=True) or {}
            token = data.get('token') or session.get('kremle_token', '')
            answers = data.get('answers', {})
            fingerprint = data.get('fingerprint')
            ip = _get_client_ip(request)

            result = engine.verify(token, answers, ip=ip, fingerprint=fingerprint)

            if result['passed']:
                session[SESSION_KEY] = True
                session.permanent = True
                next_url = session.pop(NEXT_KEY, '/')
                result['redirect'] = next_url
            else:
                result['redirect'] = None

            return jsonify(result)

        @bp.route('/status')
        def status():
            return jsonify({'verified': bool(session.get(SESSION_KEY))})

        return bp

    def _guard(self):
        """before_request хук — перенаправляет яндекс-пользователей на капчу."""
        if request.endpoint in (_SKIP_ENDPOINTS | self.skip_endpoints):
            return None
        if session.get(SESSION_KEY):
            return None

        # IP whitelist
        ip = request.remote_addr
        if self.whitelist and _ip_in_whitelist(ip, self.whitelist):
            return None

        # IP blacklist
        if self.engine.is_blacklisted(ip):
            return redirect(url_for('kremle.challenge'))

        result = detect_from_request(request)
        if result:
            self.engine.notify_detect(result, ip=ip)
            session[NEXT_KEY] = request.url
            return redirect(url_for('kremle.challenge'))
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
            if session.get(SESSION_KEY):
                return f(*args, **kwargs)

            ip = _get_client_ip(request)
            if self.whitelist and _ip_in_whitelist(ip, self.whitelist):
                return f(*args, **kwargs)

            result = detect_from_request(request)
            if result:
                self.engine.notify_detect(result, ip=ip)
                session[NEXT_KEY] = request.url
                return redirect(url_for('kremle.challenge'))

            return f(*args, **kwargs)

        return wrapper
