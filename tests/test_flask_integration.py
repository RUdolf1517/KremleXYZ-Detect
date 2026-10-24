# -*- coding: utf-8 -*-
"""Тесты Flask-интеграции (раньше их не было вообще)."""

import pytest

flask = pytest.importorskip('flask', reason='flask not installed')

from flask import Flask  # noqa: E402

from kremle_detect.integrations.flask_ext import KremleFlask  # noqa: E402
from kremle_detect.storage import MemoryStorage  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def make_app(**kwargs):
    app = Flask(__name__)
    app.secret_key = 'test-secret'
    app.config['TESTING'] = True
    storage = kwargs.pop('storage', None) or MemoryStorage()
    params = dict(
        categories=['math'],
        question_count=5,
        max_errors=1,
        storage=storage,
        secret='test',
    )
    params.update(kwargs)
    kremle = KremleFlask(app, **params)

    @app.route('/')
    def index():
        return 'ok'

    @app.route('/api')
    def api():
        return {'ok': True}

    return app, kremle


class TestGuard:
    def test_yandex_browser_redirected(self):
        app, _ = make_app()
        r = app.test_client().get('/', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 302
        assert '/kremle/challenge' in r.headers['Location']

    def test_normal_user_passes(self):
        app, _ = make_app()
        r = app.test_client().get('/', headers={'User-Agent': NORMAL_UA})
        assert r.status_code == 200
        assert r.data == b'ok'

    def test_yandex_referrer_redirected(self):
        app, _ = make_app()
        r = app.test_client().get(
            '/', headers={'User-Agent': NORMAL_UA, 'Referer': 'https://yandex.ru/search?q=x'}
        )
        assert r.status_code == 302

    def test_static_like_endpoints_skipped(self):
        app, _ = make_app(skip_endpoints=['api'])
        r = app.test_client().get('/api', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 200

    def test_whitelist_cidr_allows_yandex(self):
        app, _ = make_app(whitelist=['127.0.0.0/8'])
        r = app.test_client().get('/', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 200

    def test_blacklist_redirects_to_challenge(self):
        storage = MemoryStorage()
        storage.blacklist_add('127.0.0.1', ttl=3600)
        app, _ = make_app(storage=storage)
        r = app.test_client().get('/', headers={'User-Agent': NORMAL_UA})
        assert r.status_code == 302
        assert '/kremle/challenge' in r.headers['Location']

    def test_persistent_whitelist_allows_yandex(self):
        storage = MemoryStorage()
        storage.whitelist_add('127.0.0.1')
        app, _ = make_app(storage=storage)
        r = app.test_client().get('/', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 200


class TestSpoofedForwardedFor:
    def test_public_peer_cannot_spoof_xff(self):
        """Публичный клиент не обойдёт rate limit сменой X-Forwarded-For."""
        app, kremle = make_app(max_errors=0, rate_limit=1, rate_window=600)
        client = app.test_client()
        for spoof in ('1.1.1.1', '2.2.2.2', '3.3.3.3'):
            ch = kremle.engine.create_challenge()
            wrong = {str(i): 99 for i in range(len(ch.questions))}
            r = client.post(
                '/kremle/verify', json={'token': ch.token, 'answers': wrong},
                headers={'X-Forwarded-For': spoof},
                environ_base={'REMOTE_ADDR': '203.0.113.5'},
            )
        assert r.get_json()['error'] == 'rate_limited'

    def test_loopback_proxy_trusted_by_default(self):
        """nginx на том же хосте — работает без единой настройки."""
        app, kremle = make_app(max_errors=0, rate_limit=1, rate_window=600)
        client = app.test_client()
        for spoof in ('1.1.1.1', '2.2.2.2', '3.3.3.3'):
            ch = kremle.engine.create_challenge()
            wrong = {str(i): 99 for i in range(len(ch.questions))}
            r = client.post(
                '/kremle/verify', json={'token': ch.token, 'answers': wrong},
                headers={'X-Forwarded-For': spoof},
                environ_base={'REMOTE_ADDR': '127.0.0.1'},
            )
            assert r.get_json().get('error') != 'rate_limited'

    def test_explicit_empty_list_disables_trust(self):
        app, kremle = make_app(
            max_errors=0, rate_limit=1, rate_window=600, trusted_proxies=[],
        )
        client = app.test_client()
        for spoof in ('1.1.1.1', '2.2.2.2'):
            ch = kremle.engine.create_challenge()
            wrong = {str(i): 99 for i in range(len(ch.questions))}
            r = client.post(
                '/kremle/verify', json={'token': ch.token, 'answers': wrong},
                headers={'X-Forwarded-For': spoof},
                environ_base={'REMOTE_ADDR': '127.0.0.1'},
            )
        assert r.get_json()['error'] == 'rate_limited'

    def test_xff_honored_from_trusted_public_proxy(self):
        app, kremle = make_app(
            max_errors=0, rate_limit=1, rate_window=600,
            trusted_proxies=['203.0.113.10'],
        )
        client = app.test_client()
        for spoof in ('1.1.1.1', '2.2.2.2', '3.3.3.3'):
            ch = kremle.engine.create_challenge()
            wrong = {str(i): 99 for i in range(len(ch.questions))}
            r = client.post(
                '/kremle/verify', json={'token': ch.token, 'answers': wrong},
                headers={'X-Forwarded-For': spoof},
                environ_base={'REMOTE_ADDR': '203.0.113.10'},
            )
            assert r.get_json().get('error') != 'rate_limited'


class TestChallengeEndpoint:
    def test_returns_html_with_token(self):
        app, _ = make_app()
        r = app.test_client().get('/kremle/challenge')
        assert r.status_code == 200
        assert 'text/html' in r.headers['Content-Type']
        assert b'"token"' in r.data
        assert b'"questions"' in r.data
        assert 'no-store' in r.headers.get('Cache-Control', '')

    def test_questions_do_not_leak_answers(self):
        app, _ = make_app()
        body = app.test_client().get('/kremle/challenge').data
        assert b'"ans"' not in body

    def test_challenge_rate_limit(self):
        app, _ = make_app(challenge_rate_limit=1)
        client = app.test_client()
        assert client.get('/kremle/challenge').status_code == 200
        assert client.get('/kremle/challenge').status_code == 429

    def test_custom_template_missing_file(self):
        app, _ = make_app(template='/nonexistent/kremle.html')
        with pytest.raises(RuntimeError, match='шаблон'):
            app.test_client().get('/kremle/challenge')


class TestVerifyFlow:
    def test_correct_answers_set_session(self):
        app, kremle = make_app(max_errors=0)
        client = app.test_client()
        ch = kremle.engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}

        r = client.post('/kremle/verify', json={'token': ch.token, 'answers': answers})
        assert r.get_json()['passed'] is True
        assert r.get_json()['redirect']

        # сессия помечена — Яндекс-браузер теперь проходит
        r2 = client.get('/', headers={'User-Agent': YANDEX_UA})
        assert r2.status_code == 200

    def test_wrong_answers_keep_user_out(self):
        app, kremle = make_app(max_errors=0)
        client = app.test_client()
        ch = kremle.engine.create_challenge()
        wrong = {str(i): 99 for i in range(len(ch.questions))}

        result = client.post('/kremle/verify', json={'token': ch.token, 'answers': wrong}).get_json()
        assert result['passed'] is False
        assert result['errors'] == len(ch.questions)
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 302

    def test_status_endpoint(self):
        app, _ = make_app()
        client = app.test_client()
        assert client.get('/kremle/status').get_json()['verified'] is False

    def test_broken_json_does_not_crash(self):
        app, _ = make_app()
        r = app.test_client().post(
            '/kremle/verify', data='not json',
            headers={'Content-Type': 'application/json'},
        )
        assert r.status_code == 200
        assert r.get_json()['passed'] is False

    def test_token_reuse_rejected(self):
        app, kremle = make_app(max_errors=0)
        client = app.test_client()
        ch = kremle.engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        assert client.post('/kremle/verify', json={'token': ch.token, 'answers': answers}).get_json()['passed']
        second = client.post('/kremle/verify', json={'token': ch.token, 'answers': answers}).get_json()
        assert second['passed'] is False
        assert second['error'] == 'invalid_token'


class TestProtectDecorator:
    def test_protects_single_route(self):
        app = Flask(__name__)
        app.secret_key = 'test'
        kremle = KremleFlask(
            app, auto_guard=False, categories=['math'],
            question_count=5, max_errors=1, secret='test',
        )

        @app.route('/secret')
        @kremle.protect
        def secret():
            return 'secret'

        @app.route('/public')
        def public():
            return 'public'

        client = app.test_client()
        assert client.get('/public', headers={'User-Agent': YANDEX_UA}).status_code == 200
        assert client.get('/secret', headers={'User-Agent': YANDEX_UA}).status_code == 302
        assert client.get('/secret', headers={'User-Agent': NORMAL_UA}).status_code == 200
