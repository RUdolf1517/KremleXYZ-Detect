# -*- coding: utf-8 -*-
"""Виджет без React: бандл, роут и сниппет.

Виджет — это обычный JS-файл, который интеграции отдают своим роутом. Тесты
проверяют три вещи: файл действительно есть в пакете, роут отдаёт его с
правильными заголовками, а имена вне белого списка не открывают файловую систему.
"""

import pytest

from kremle_detect import widget as widget_module
from kremle_detect.widget import (
    BUNDLES,
    CONTENT_TYPE,
    bundle_path,
    headers,
    read_bundle,
    widget_snippet,
)

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'


class TestBundleFiles:
    def test_minified_bundle_shipped(self):
        """Файл лежит в пакете — иначе wheel обманет пользователя."""
        path = bundle_path('kremle-widget.min.js')
        assert path is not None, 'kremle-widget.min.js не собран и не попал в пакет'
        assert path.endswith('static/widget/kremle-widget.min.js')

    def test_bundle_is_real_javascript(self):
        payload = read_bundle('kremle-widget.min.js')
        assert payload and b'KremleWidget' in payload
        assert b'function' in payload

    def test_all_bundles_readable(self):
        for name in BUNDLES:
            assert read_bundle(name) is not None, name

    def test_unknown_names_rejected(self):
        for name in ('../../etc/passwd', 'index.js', '../templates/kremle_captcha.html', ''):
            assert bundle_path(name) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert read_bundle('kremle-widget.min.js', static_dir=str(tmp_path)) is None

    def test_headers(self):
        result = headers()
        assert result['Content-Type'] == CONTENT_TYPE
        assert result['X-Content-Type-Options'] == 'nosniff'
        assert 'max-age' in result['Cache-Control']


class TestSnippet:
    def test_snippet_has_container_and_mount(self):
        html = widget_snippet()
        assert '<div id="kremle" data-kremle></div>' in html
        assert 'src="/kremle/widget/kremle-widget.min.js"' in html
        assert 'KremleWidget.mount("#kremle"' in html

    def test_snippet_custom_urls_and_title(self):
        html = widget_snippet(challenge_url='/c', verify_url='/v', title='[ стоп ]',
                              redirect_on_pass=True)
        assert 'challengeUrl: \'/c\'' in html
        assert 'verifyUrl: \'/v\'' in html
        assert "title: '[ стоп ]'" in html
        assert 'redirectOnPass: true' in html

    def test_snippet_selector_without_hash(self):
        html = widget_snippet(selector='kremle')
        assert '<div id="kremle"' in html


class TestFlaskRoute:
    @pytest.fixture
    def client(self):
        pytest.importorskip('flask')
        from flask import Flask

        from kremle_detect.integrations.flask_ext import KremleFlask

        app = Flask(__name__)
        app.secret_key = 'test'
        KremleFlask(app, secret='test', categories=['math'])
        return app.test_client()

    def test_bundle_served(self, client):
        response = client.get('/kremle/widget/kremle-widget.min.js')
        assert response.status_code == 200
        assert 'javascript' in response.headers['Content-Type']
        assert b'KremleWidget' in response.data

    def test_unknown_bundle_404(self, client):
        response = client.get('/kremle/widget/../../../etc/passwd')
        assert response.status_code == 404

    def test_plain_name_404(self, client):
        assert client.get('/kremle/widget/index.js').status_code == 404

    def test_widget_not_blocked_by_guard(self, client):
        """Роут виджета не должен требовать прохождения капчи."""
        response = client.get('/kremle/widget/kremle-widget.min.js',
                              headers={'User-Agent': YANDEX_UA})
        assert response.status_code == 200


class TestFastapiRoute:
    @pytest.fixture
    def client(self):
        pytest.importorskip('fastapi')
        pytest.importorskip('httpx')
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from kremle_detect.integrations.fastapi_ext import KremleFastAPI

        app = FastAPI()
        KremleFastAPI(app, secret='test', categories=['math'])
        return TestClient(app)

    def test_bundle_served(self, client):
        response = client.get('/kremle/widget/kremle-widget.min.js')
        assert response.status_code == 200
        assert 'javascript' in response.headers['content-type']
        assert 'KremleWidget' in response.text

    def test_unknown_bundle_404(self, client):
        assert client.get('/kremle/widget/index.js').status_code == 404


class TestDjangoRoute:
    @pytest.fixture
    def views(self):
        django = pytest.importorskip('django')
        from django.conf import settings as dj_settings

        if not dj_settings.configured:
            import tests.test_django_integration  # noqa: F401 — общая настройка

        from kremle_detect.integrations import django_ext

        assert django.VERSION
        return {pattern.name: pattern.callback for pattern in django_ext.kremle_urls()[0]}

    def make_request(self, path):
        from django.test import RequestFactory

        request = RequestFactory().get(path, HTTP_USER_AGENT=YANDEX_UA)
        request.session = {}
        return request

    def test_bundle_served(self, views):
        response = views['kremle_widget'](self.make_request('/kremle/widget/kremle-widget.min.js'),
                                          'kremle-widget.min.js')
        assert response.status_code == 200
        assert 'javascript' in response['Content-Type']
        assert b'KremleWidget' in response.content

    def test_unknown_bundle_404(self, views):
        response = views['kremle_widget'](self.make_request('/kremle/widget/index.js'),
                                          'index.js')
        assert response.status_code == 404
        assert 'npm run build' in response.content.decode()


class TestProtocolParity:
    """Протокол виджета = протокол интеграций (поля, которые он ждёт)."""

    def test_challenge_payload_has_widget_fields(self):
        from kremle_detect.captcha import CaptchaEngine

        engine = CaptchaEngine(secret='test', categories=['math'], question_count=3,
                               max_errors=1)
        payload = engine.create_challenge().to_dict(max_errors=engine.max_errors)
        # ровно то, что читает kremle-widget/src/widget.js
        for key in ('questions', 'token', 'expires_in', 'max_errors', 'sources', 'attribution'):
            assert key in payload, key
        for question in payload['questions']:
            assert 'q' in question and 'opts' in question
            assert 'ans' not in question

    def test_verify_accepts_widget_body(self):
        """Тело, которое отправляет виджет: token + answers + fingerprint."""
        from kremle_detect.captcha import CaptchaEngine

        engine = CaptchaEngine(secret='test', categories=['math'], question_count=2,
                               max_errors=1)
        challenge = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(challenge.questions)}
        result = engine.verify(challenge.token, answers, fingerprint={
            'yaBrands': False, 'yandexApi': False, 'honeypot': False,
            'webdriver': False, 'timezone': 'Europe/Moscow',
        })
        assert result['passed'] is True
        assert result['max_errors'] == engine.max_errors


class TestStaticDirOverride:
    def test_custom_static_dir(self, tmp_path):
        (tmp_path / 'kremle-widget.min.js').write_text('var KremleWidget = {};')
        assert read_bundle('kremle-widget.min.js', static_dir=str(tmp_path))
        assert widget_module.bundle_path('kremle-widget.min.js', static_dir=str(tmp_path))


class TestStaticDemo:
    """docs/demo.html — демонстрация, которую не надо устанавливать."""

    @pytest.fixture
    def demo_html(self):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / 'docs' / 'demo.html').read_text(
            encoding='utf-8'
        )

    def test_demo_references_bundle(self, demo_html):
        assert '<script src="./assets/kremle-widget.min.js"></script>' in demo_html
        assert "KremleWidget.mount('#kremle'" in demo_html

    def test_demo_bundle_exists_and_matches_package(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        demo_bundle = root / 'docs' / 'assets' / 'kremle-widget.min.js'
        assert demo_bundle.is_file()
        assert demo_bundle.read_bytes() == read_bundle('kremle-widget.min.js')

    def test_demo_is_honest_about_embedded_answers(self, demo_html):
        flat = ' '.join(demo_html.split())
        assert 'Правильные ответы лежат в коде страницы' in flat
        assert 'POST /kremle/verify' in flat
