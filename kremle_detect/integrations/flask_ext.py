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

import os
from typing import Optional, Sequence

from flask import (
    Blueprint, Flask, render_template, request, session,
    jsonify, redirect, url_for,
)

from ..captcha import CaptchaEngine
from ..detector import detect_from_request

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'

# Эндпоинты, которые не надо защищать
_SKIP_ENDPOINTS = frozenset({
    'kremle.challenge',
    'kremle.verify',
    'kremle.status',
    'static',
})


class KremleFlask:
    """
    Flask-расширение для защиты от Яндекс-пользователей.

    Args:
        app: Flask-приложение (или None для отложенной инициализации через init_app)
        categories: категории вопросов
        question_count: количество вопросов
        max_errors: допустимое число ошибок
        secret: секрет для подписи токенов (по умолчанию — app.secret_key)
        skip_endpoints: дополнительные эндпоинты, которые не защищать
        auto_guard: автоматически ставить before_request guard
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
    ):
        self.categories = categories
        self.question_count = question_count
        self.max_errors = max_errors
        self._secret = secret
        self.skip_endpoints = set(skip_endpoints or set())
        self.auto_guard = auto_guard
        self.engine: Optional[CaptchaEngine] = None

        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Инициализация с Flask-приложением (поддержка паттерна app factory)."""
        secret = self._secret or app.secret_key or 'kremle-default-secret'

        self.engine = CaptchaEngine(
            categories=self.categories,
            question_count=self.question_count,
            max_errors=self.max_errors,
            secret=secret,
        )

        bp = self._create_blueprint()
        app.register_blueprint(bp)

        if self.auto_guard:
            app.before_request(self._guard)

        # Сохраняем ссылку на расширение в app
        app.extensions['kremle'] = self

    def _create_blueprint(self) -> Blueprint:
        bp = Blueprint(
            'kremle',
            __name__,
            template_folder=os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 'templates'
            ),
            url_prefix='/kremle',
        )

        engine = self.engine

        @bp.route('/challenge')
        def challenge():
            ch = engine.create_challenge()
            session['kremle_token'] = ch.token
            return render_template(
                'kremle_captcha.html',
                questions_json=ch.to_dict(),
            )

        @bp.route('/verify', methods=['POST'])
        def verify():
            data = request.get_json(force=True, silent=True) or {}
            token = data.get('token') or session.get('kremle_token', '')
            answers = data.get('answers', {})

            result = engine.verify(token, answers)

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
        result = detect_from_request(request)
        if result:
            session[NEXT_KEY] = request.url
            return redirect(url_for('kremle.challenge'))
        return None

    def is_detected(self) -> bool:
        """Проверяет текущий запрос (вызывать из обработчиков)."""
        return bool(detect_from_request(request))
