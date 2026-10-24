# -*- coding: utf-8 -*-
"""
Тесты эксплуатационных возможностей Flask-интеграции (2.7.0):
JSON-гард, health/stats/metrics, TTL «пройдено», logout, monitor-режим.
"""

import json

import pytest

flask = pytest.importorskip('flask', reason='flask not installed')

from flask import Flask  # noqa: E402

from kremle_detect.integrations.flask_ext import KremleFlask  # noqa: E402
from kremle_detect.storage import MemoryStorage  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'
BOT_UA = 'Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)'


def make_app(**kwargs):
    app = Flask(__name__)
    app.secret_key = 'test-secret'
    app.config['TESTING'] = True
    storage = kwargs.pop('storage', None) or MemoryStorage()
    params = dict(
        categories=['math'], question_count=3, max_errors=1,
        storage=storage, secret='test',
    )
    params.update(kwargs)
    kremle = KremleFlask(app, **params)

    @app.route('/')
    def index():
        return 'ok'

    @app.route('/api/data')
    def api_data():
        return {'ok': True}

    return app, kremle


def solve(client, headers=None):
    """Проходит капчу за клиента и возвращает ответ verify."""
    challenge = client.get('/kremle/challenge', headers=headers or {}).get_json()
    # правильные ответы знает только сервер: берём из сессии через движок
    app = client.application
    engine = app.extensions['kremle'].engine
    token = challenge['token']
    data = engine._memory_get(token) if hasattr(engine, '_memory_get') else None
    answers = {}
    for i, q in enumerate(challenge['questions']):
        match = [o for o in q['opts'] if o == q.get('answer')]
        answers[str(i)] = 0 if not match else q['opts'].index(match[0])
    return client.post('/kremle/verify', json={'token': token, 'answers': answers},
                       headers=headers or {})


class TestJsonGuard:
    def test_accept_json_gets_json_403(self):
        app, _ = make_app()
        r = app.test_client().get(
            '/api/data', headers={'User-Agent': YANDEX_UA, 'Accept': 'application/json'},
        )
        assert r.status_code == 403
        body = r.get_json()
        assert body['error'] == 'captcha_required'
        assert body['action'] == 'challenge'
        assert body['challenge_url'] == '/kremle/challenge'
        assert body['reason'] == 'yandex_browser'
        assert 'no-store' in r.headers['Cache-Control']

    def test_xhr_gets_json_403(self):
        app, _ = make_app()
        r = app.test_client().get(
            '/api/data', headers={'User-Agent': YANDEX_UA, 'X-Requested-With': 'XMLHttpRequest'},
        )
        assert r.status_code == 403
        assert r.get_json()['error'] == 'captcha_required'

    def test_api_path_gets_json_without_accept(self):
        """/api/* считаем API даже без явного Accept: text/html."""
        app, _ = make_app()
        r = app.test_client().get(
            '/api/data', headers={'User-Agent': YANDEX_UA, 'Accept': 'text/html'},
        )
        assert r.status_code == 403
        assert r.get_json()['challenge_url'] == '/kremle/challenge'

    def test_html_request_still_redirected(self):
        app, _ = make_app()
        r = app.test_client().get('/', headers={'User-Agent': YANDEX_UA, 'Accept': 'text/html'})
        assert r.status_code == 302
        assert '/kremle/challenge' in r.headers['Location']

    def test_normal_user_not_affected(self):
        app, _ = make_app()
        r = app.test_client().get('/api/data', headers={'User-Agent': NORMAL_UA,
                                                       'Accept': 'application/json'})
        assert r.status_code == 200
        assert r.get_json() == {'ok': True}

    def test_headless_mode_json_for_html(self):
        app, _ = make_app(headless=True)
        r = app.test_client().get('/', headers={'User-Agent': YANDEX_UA, 'Accept': 'text/html'})
        assert r.status_code == 403
        assert r.get_json()['error'] == 'captcha_required'

    def test_json_api_disabled(self):
        app, _ = make_app(json_api=False)
        r = app.test_client().get(
            '/api/data', headers={'User-Agent': YANDEX_UA, 'Accept': 'application/json'},
        )
        assert r.status_code == 302


class TestMonitor:
    def test_monitor_does_not_block(self):
        app, kremle = make_app(policy={'yandex_browser': 'monitor'})
        r = app.test_client().get('/api/data', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 200
        stats = app.test_client().get('/kremle/stats').get_json()
        assert stats['actions']['monitor'] == 1
        assert stats['detected_by_reason']['yandex_browser'] == 1
        assert stats['shadow_total'] == 1

    def test_shadow_event_visible_in_events(self):
        app, kremle = make_app(policy={'yandex_browser': 'monitor'})
        client = app.test_client()
        client.get('/', headers={'User-Agent': YANDEX_UA})
        events = kremle.engine.storage.log_get(10)
        assert events[0]['event'] == 'shadow'
        assert events[0]['action'] == 'monitor'

    def test_sample_rate_zero_is_full_shadow(self):
        app, _ = make_app(sample_rate=0.0)
        client = app.test_client()
        for _ in range(5):
            assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 200
        assert client.get('/kremle/stats').get_json()['actions']['challenge'] == 0

    def test_block_policy_returns_403_json(self):
        app, _ = make_app()
        storage = app.extensions['kremle']._storage
        storage.blacklist_add('127.0.0.1', ttl=3600)
        r = app.test_client().get('/api/data', headers={'User-Agent': NORMAL_UA,
                                                       'Accept': 'application/json'})
        assert r.status_code == 403
        assert r.get_json()['error'] == 'blocked'


class TestOpsRoutes:
    def test_health_ok(self):
        app, _ = make_app()
        r = app.test_client().get('/kremle/health')
        assert r.status_code == 200
        body = r.get_json()
        assert body['status'] == 'ok'
        assert body['storage_ok'] is True
        assert body['version']

    def test_health_degraded(self):
        class Broken(MemoryStorage):
            def set(self, key, value, ttl):
                raise RuntimeError('redis down')

        app, _ = make_app(storage=Broken())
        r = app.test_client().get('/kremle/health')
        assert r.status_code == 503
        assert r.get_json()['status'] == 'degraded'

    def test_stats_json(self):
        app, _ = make_app()
        client = app.test_client()
        client.get('/', headers={'User-Agent': NORMAL_UA})
        client.get('/', headers={'User-Agent': YANDEX_UA})
        body = client.get('/kremle/stats').get_json()
        assert body['requests_total'] >= 1
        assert body['actions']['challenge'] >= 1
        assert body['actions']['allow'] >= 1

    def test_metrics_prometheus(self):
        app, _ = make_app()
        client = app.test_client()
        client.get('/', headers={'User-Agent': YANDEX_UA})
        r = client.get('/kremle/metrics')
        assert r.status_code == 200
        assert r.headers['Content-Type'].startswith('text/plain')
        assert 'kremle_requests_total' in r.data.decode()
        assert 'kremle_detected_total{reason="yandex_browser"}' in r.data.decode()

    def test_ops_can_be_disabled(self):
        app, _ = make_app(enable_ops_routes=False)
        assert app.test_client().get('/kremle/health').status_code == 404


class TestVerificationTtl:
    def test_status_not_verified(self):
        app, _ = make_app()
        body = app.test_client().get('/kremle/status').get_json()
        assert body == {'verified': False, 'expires_in': None}

    def test_verify_sets_ttl(self):
        app, kremle = make_app(verified_ttl=120)
        client = app.test_client()
        engine = kremle.engine
        challenge = client.get('/kremle/challenge',
                               headers={'Accept': 'application/json'}).get_json()
        ch = engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        r = client.post('/kremle/verify', json={'token': challenge['token'], 'answers': answers})
        assert r.get_json()['passed'] is True

        status = client.get('/kremle/status').get_json()
        assert status['verified'] is True
        assert 0 < status['expires_in'] <= 120

    def test_logout_clears(self):
        app, kremle = make_app(verified_ttl=120)
        client = app.test_client()
        engine = kremle.engine
        challenge = client.get('/kremle/challenge',
                               headers={'Accept': 'application/json'}).get_json()
        ch = engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        client.post('/kremle/verify', json={'token': challenge['token'], 'answers': answers})
        assert client.get('/kremle/status').get_json()['verified'] is True

        assert client.post('/kremle/logout').status_code == 200
        assert client.get('/kremle/status').get_json()['verified'] is False

    def test_legacy_session_flag_is_expired(self):
        """Сессия, записанная версией 2.6 (True), больше не даёт проход."""
        app, _ = make_app()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['kremle_ok'] = True
        r = client.get('/', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 302


class TestChallengePayload:
    def test_json_payload_fields(self):
        app, _ = make_app()
        r = app.test_client().get('/kremle/challenge', headers={'Accept': 'application/json'})
        body = r.get_json()
        assert set(body) >= {'questions', 'token', 'verify_url', 'attribution'}
        assert len(body['questions']) <= 3
        assert 'ans' not in body['questions'][0]
        assert 'no-store' in r.headers['Cache-Control']

    def test_html_payload(self):
        app, _ = make_app()
        r = app.test_client().get('/kremle/challenge')
        assert r.status_code == 200
        assert b'<html' in r.data.lower()
        assert 'no-store' in r.headers['Cache-Control']

    def test_verify_rejects_bad_token(self):
        app, _ = make_app()
        r = app.test_client().post('/kremle/verify', json={'token': 'nope', 'answers': {}})
        assert r.status_code == 200
        assert r.get_json()['error'] == 'invalid_token'

    def test_verify_malformed_body_is_invalid_token(self):
        """Тело не JSON — не 500, а штатная ошибка токена."""
        app, _ = make_app()
        r = app.test_client().post('/kremle/verify', data='not json')
        assert r.status_code == 200
        assert r.get_json()['error'] == 'invalid_token'
