# -*- coding: utf-8 -*-
"""
kremle-detect — защита сайта от пользователей Яндекс Браузера.

Фреймворк-агностичное ядро + интеграции для Flask, Django, FastAPI.

Быстрый старт (Flask):
    from kremle_detect.integrations.flask_ext import KremleFlask
    kremle = KremleFlask(app, categories=['math', 'physics'])

Быстрый старт (Django):
    # settings.py → MIDDLEWARE += ['kremle_detect.integrations.django_ext.KremleDjangoMiddleware']
    # urls.py → path('kremle/', kremle_urls())

Быстрый старт (FastAPI):
    from kremle_detect.integrations.fastapi_ext import KremleFastAPI
    kremle = KremleFastAPI(app, secret='...')

Использование ядра напрямую (любой фреймворк):
    from kremle_detect import detect, CaptchaEngine

    # Детекция
    result = detect({'User-Agent': '...', 'Referer': '...'})
    if result:
        print(result.reason)

    # Капча
    engine = CaptchaEngine(categories=['math', 'russian'], question_count=10)
    challenge = engine.create_challenge()
    verification = engine.verify(challenge.token, user_answers)
"""

__version__ = '2.0.0'

from .detector import (
    detect,
    detect_from_request,
    DetectResult,
    is_yandex_browser,
    is_yandex_bot,
    is_yandex_referrer,
    is_yandex_client_hints,
)
from .captcha import CaptchaEngine, Challenge
from .questions import get_questions, ALL_CATEGORY_NAMES, CATEGORIES

__all__ = [
    # Детекция
    'detect',
    'detect_from_request',
    'DetectResult',
    'is_yandex_browser',
    'is_yandex_bot',
    'is_yandex_referrer',
    'is_yandex_client_hints',
    # Капча
    'CaptchaEngine',
    'Challenge',
    # Вопросы
    'get_questions',
    'ALL_CATEGORY_NAMES',
    'CATEGORIES',
]
