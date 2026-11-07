# -*- coding: utf-8 -*-
"""Безопасность страницы капчи: экранирование JSON и защитные заголовки.

Проверки #27 и #28 роадмапа 2.10 одинаково важны для всех трёх интеграций:
шаблон у них общий, поэтому и регрессия была бы общей.
"""

import json
import re

import pytest

from kremle_detect.integrations._common import (
    DEFAULT_CSP,
    json_for_script,
    render_captcha_html,
    security_headers,
)

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'

# Вопрос, который раньше вырывался из <script> и выполнял чужой код.
EVIL_QUESTION = {
    'q': '</script><script>alert(1)</script>',
    'opts': ['A & B', '<img src=x onerror=alert(2)>', 'C', 'D'],
    'ans': 0,
}


def _script_json(html):
    """Достаёт данные из скрипта шаблона так, как это сделал бы браузер.

    В шаблоне `var DATA = {...};`, а `\u003c` разворачивается парсером JS —
    `json.loads` здесь его честно повторяет.
    """
    match = re.search(r'var DATA = (\{.*?\});', html, re.S)
    assert match is not None, 'в шаблоне не нашёлся JSON с вопросами'
    return json.loads(match.group(1))


class TestJsonEscapingHelpers:
    def test_angle_brackets_escaped(self):
        payload = json_for_script({'q': '</script>'})
        assert '</script>' not in payload
        assert '\\u003c/script\\u003e' in payload

    def test_round_trip_keeps_text(self):
        data = {'q': '</script><b>&amp;</b>', 'sep': '\u2028\u2029'}
        assert json.loads(json_for_script(data)) == data

    def test_render_replaces_placeholder(self):
        html = render_captcha_html('<script>var DATA = {{ questions_json }};</script>',
                                   {'questions': ['<x>']})
        assert '{{ questions_json }}' not in html
        assert json.loads(re.search(r'var DATA = (\{.*?\});', html).group(1)) == {'questions': ['<x>']}


class TestFingerprintMinimal:
    """Клиент отправляет пять сигналов, а не четырнадцать (#30)."""

    ALLOWED = {'yaBrands', 'yandexApi', 'webdriver', 'timezone', 'honeypot', 'error'}

    def test_template_collects_only_allowed_fields(self):
        from pathlib import Path

        template = (
            Path(__file__).resolve().parent.parent
            / 'kremle_detect' / 'templates' / 'kremle_captcha.html'
        ).read_text(encoding='utf-8')
        collected = set(re.findall(r'fingerprint\.([A-Za-z_]+)\s*=', template))
        assert collected <= self.ALLOWED, sorted(collected - self.ALLOWED)
        assert {'yaBrands', 'yandexApi', 'honeypot'} <= collected

    def test_template_does_not_send_user_agent(self):
        from pathlib import Path

        template = (
            Path(__file__).resolve().parent.parent
            / 'kremle_detect' / 'templates' / 'kremle_captcha.html'
        ).read_text(encoding='utf-8')
        assert 'fingerprint.ua' not in template
        assert 'screenRes' not in template


class TestSecurityHeadersHelper:
    def test_defaults(self):
        headers = security_headers()
        assert headers['X-Content-Type-Options'] == 'nosniff'
        assert headers['X-Frame-Options'] == 'DENY'
        assert headers['Referrer-Policy'] == 'no-referrer'
        assert headers['Content-Security-Policy'] == DEFAULT_CSP

    def test_empty_policy_disables_csp(self):
        assert 'Content-Security-Policy' not in security_headers('')

    def test_custom_policy(self):
        headers = security_headers("default-src 'self'; frame-ancestors 'none'")
        assert headers['Content-Security-Policy'] == "default-src 'self'; frame-ancestors 'none'"


# ---------------------------------------------------------------- Flask

flask = pytest.importorskip('flask', reason='flask not installed')


@pytest.fixture
def flask_app():
    from flask import Flask

    from kremle_detect.integrations.flask_ext import KremleFlask
    from kremle_detect.storage import MemoryStorage

    def build(**kwargs):
        app = Flask(__name__)
        app.secret_key = 'test'
        app.config['TESTING'] = True
        params = dict(
            secret='test', storage=MemoryStorage(), categories=['math'],
            question_count=1, max_errors=1, extra_questions=[dict(EVIL_QUESTION)],
            only_extra=True, challenge_rate_limit=0,
        )
        params.update(kwargs)
        KremleFlask(app, **params)

        @app.route('/')
        def index():
            return 'ok'

        return app

    return build


class TestFlaskChallengeSecurity:
    def test_question_cannot_break_out_of_script(self, flask_app):
        client = flask_app().test_client()
        html = client.get('/kremle/challenge').get_data(as_text=True)
        assert '</script><script>alert(1)' not in html
        assert html.count('alert(1)') == 1  # ровно в экранированном JSON
        data = _script_json(html)
        assert data['questions'][0]['q'] == EVIL_QUESTION['q']
        # варианты перемешиваются, поэтому сверяем состав
        assert sorted(data['questions'][0]['opts']) == sorted(EVIL_QUESTION['opts'])

    def test_headers_on_challenge(self, flask_app):
        response = flask_app().test_client().get('/kremle/challenge')
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        assert response.headers['Content-Security-Policy'] == DEFAULT_CSP
        assert 'no-store' in response.headers['Cache-Control']

    def test_headers_on_verify_and_status(self, flask_app):
        client = flask_app().test_client()
        challenge = client.get('/kremle/challenge', headers={'Accept': 'application/json'})
        token = challenge.get_json()['token']
        verify = client.post('/kremle/verify', json={'token': token, 'answers': {'0': 0}})
        assert verify.headers['X-Frame-Options'] == 'DENY'
        assert verify.headers['Content-Security-Policy'] == DEFAULT_CSP
        status = client.get('/kremle/status')
        assert status.headers['X-Frame-Options'] == 'DENY'

    def test_custom_and_disabled_csp(self, flask_app):
        client = flask_app(csp_policy="default-src 'self'").test_client()
        assert client.get('/kremle/challenge').headers['Content-Security-Policy'] == (
            "default-src 'self'"
        )
        client = flask_app(csp_policy='').test_client()
        response = client.get('/kremle/challenge')
        assert 'Content-Security-Policy' not in response.headers
        assert response.headers['X-Frame-Options'] == 'DENY'


# ---------------------------------------------------------------- FastAPI

pytest.importorskip('fastapi', reason='fastapi not installed')
pytest.importorskip('httpx', reason='httpx not installed')


@pytest.fixture
def fastapi_app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kremle_detect.integrations.fastapi_ext import KremleFastAPI
    from kremle_detect.storage import MemoryStorage

    def build(**kwargs):
        app = FastAPI()
        params = dict(
            secret='test', storage=MemoryStorage(), categories=['math'],
            question_count=1, max_errors=1, extra_questions=[dict(EVIL_QUESTION)],
            only_extra=True, challenge_rate_limit=0,
        )
        params.update(kwargs)
        KremleFastAPI(app, **params)

        @app.get('/')
        async def index():
            return {'ok': True}

        return TestClient(app)

    return build


class TestFastapiChallengeSecurity:
    def test_question_cannot_break_out_of_script(self, fastapi_app):
        html = fastapi_app().get('/kremle/challenge').text
        assert '</script><script>alert(1)' not in html
        data = _script_json(html)
        assert data['questions'][0]['q'] == EVIL_QUESTION['q']

    def test_headers_on_challenge(self, fastapi_app):
        response = fastapi_app().get('/kremle/challenge')
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['referrer-policy'] == 'no-referrer'
        assert response.headers['content-security-policy'] == DEFAULT_CSP

    def test_headers_on_verify_and_status(self, fastapi_app):
        client = fastapi_app()
        challenge = client.get('/kremle/challenge', headers={'Accept': 'application/json'})
        token = challenge.json()['token']
        verify = client.post('/kremle/verify', json={'token': token, 'answers': {'0': 0}})
        assert verify.headers['x-frame-options'] == 'DENY'
        assert verify.headers['content-security-policy'] == DEFAULT_CSP
        assert client.get('/kremle/status').headers['x-frame-options'] == 'DENY'

    def test_custom_and_disabled_csp(self, fastapi_app):
        client = fastapi_app(csp_policy='')
        response = client.get('/kremle/challenge')
        assert 'content-security-policy' not in response.headers
        assert response.headers['x-frame-options'] == 'DENY'


# ---------------------------------------------------------------- Django

django = pytest.importorskip('django', reason='django not installed')

from django.conf import settings as dj_settings  # noqa: E402

if not dj_settings.configured:  # noqa: E402
    import tests.test_django_integration  # noqa: F401  — общая настройка settings

from django.test import RequestFactory, override_settings  # noqa: E402

from kremle_detect.integrations import django_ext  # noqa: E402
from kremle_detect.storage import MemoryStorage  # noqa: E402


def _django_views():
    """{имя маршрута: view} — как в остальных Django-тестах."""
    return {pattern.name: pattern.callback for pattern in django_ext.kremle_urls()[0]}


def _request(path='/kremle/challenge/', ua=YANDEX_UA, method='get', accept=None):
    kwargs = {'HTTP_USER_AGENT': ua, 'REMOTE_ADDR': '203.0.113.7'}
    if accept:
        kwargs['HTTP_ACCEPT'] = accept
    request = getattr(RequestFactory(), method)(path, **kwargs)
    request.session = {}
    return request


class TestDjangoChallengeSecurity:
    def test_question_cannot_break_out_of_script(self):
        with override_settings(KREMLE_STORAGE=MemoryStorage(),
                               KREMLE_EXTRA_QUESTIONS=[dict(EVIL_QUESTION)],
                               KREMLE_ONLY_EXTRA=True,
                               KREMLE_QUESTION_COUNT=1,
                               KREMLE_CHALLENGE_RATE_LIMIT=0):
            response = _django_views()['kremle_challenge'](_request())
        html = response.content.decode()
        assert '</script><script>alert(1)' not in html
        assert _script_json(html)['questions'][0]['q'] == EVIL_QUESTION['q']

    def test_headers_on_challenge(self):
        with override_settings(KREMLE_STORAGE=MemoryStorage()):
            response = _django_views()['kremle_challenge'](_request())
        assert response['X-Content-Type-Options'] == 'nosniff'
        assert response['X-Frame-Options'] == 'DENY'
        assert response['Referrer-Policy'] == 'no-referrer'
        assert response['Content-Security-Policy'] == DEFAULT_CSP

    def test_headers_on_verify_status_logout(self):
        views = _django_views()
        with override_settings(KREMLE_STORAGE=MemoryStorage()):
            challenge = views['kremle_challenge'](
                _request('/kremle/challenge/', accept='application/json'))
            token = json.loads(challenge.content)['token']
            request = _request('/kremle/verify/', method='post')
            request._body = json.dumps({'token': token, 'answers': {'0': 0}}).encode()
            verify = views['kremle_verify'](request)
            assert verify['X-Frame-Options'] == 'DENY'
            assert verify['Content-Security-Policy'] == DEFAULT_CSP
            assert views['kremle_status'](_request('/kremle/status/'))['X-Frame-Options'] == 'DENY'
            assert views['kremle_logout'](_request('/kremle/logout/', method='post'))[
                'X-Frame-Options'
            ] == 'DENY'

    def test_custom_policy_from_settings(self):
        views = _django_views()
        with override_settings(KREMLE_STORAGE=MemoryStorage(),
                               KREMLE_CSP_POLICY="default-src 'self'"):
            response = views['kremle_challenge'](_request())
        assert response['Content-Security-Policy'] == "default-src 'self'"
        with override_settings(KREMLE_STORAGE=MemoryStorage(), KREMLE_CSP_POLICY=''):
            response = views['kremle_challenge'](_request())
        assert 'Content-Security-Policy' not in response
        assert response['X-Frame-Options'] == 'DENY'
