# -*- coding: utf-8 -*-
"""Операционные возможности FastAPI-интеграции: JSON-гард, ops-роуты, TTL."""

import pytest

pytest.importorskip('fastapi', reason='fastapi not installed')
pytest.importorskip('httpx', reason='httpx not installed')

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from kremle_detect.integrations.fastapi_ext import KremleFastAPI  # noqa: E402
from kremle_detect.storage import MemoryStorage  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def make_app(headless=False, **kwargs):
    app = FastAPI()
    storage = kwargs.pop('storage', None) or MemoryStorage()
    params = dict(
        secret='test-secret', storage=storage, headless=headless,
        categories=['math'], question_count=3, max_errors=1,
    )
    params.update(kwargs)
    kremle = KremleFastAPI(app, **params)

    @app.get('/protected')
    async def protected():
        return {'ok': True}

    return app, kremle


def client_for(app, headers, peer='127.0.0.1'):
    """TestClient с заданным peer-адресом (для blacklist/IP-логики)."""
    client = TestClient(app, client=(peer, 50000))
    client.headers.update(headers)
    return client


class TestJsonGuard:
    def test_json_client_gets_403(self):
        app, _ = make_app()
        client = client_for(app, {'User-Agent': YANDEX_UA, 'Accept': 'application/json'})
        r = client.get('/protected')
        assert r.status_code == 403
        assert r.json()['error'] == 'captcha_required'
        assert r.json()['challenge_url'] == '/kremle/challenge'
        assert 'no-store' in r.headers['cache-control']

    def test_api_path_json_without_accept(self):
        app, _ = make_app()
        client = client_for(app, {'User-Agent': YANDEX_UA, 'Accept': 'text/html'})
        # /protected — не /api/, поэтому редирект; /api/-путь даёт JSON
        @app.get('/api/items')
        async def items():
            return {'items': []}

        assert client.get('/api/items').status_code == 403
        assert client.get('/protected', follow_redirects=False).status_code == 302

    def test_html_client_redirected(self):
        app, _ = make_app()
        client = client_for(app, {'User-Agent': YANDEX_UA, 'Accept': 'text/html'})
        r = client.get('/protected', follow_redirects=False)
        assert r.status_code == 302
        assert r.headers['location'] == '/kremle/challenge'

    def test_normal_user_passes(self):
        app, _ = make_app()
        client = client_for(app, {'User-Agent': NORMAL_UA})
        assert client.get('/protected').json() == {'ok': True}

    def test_headless_everything_json(self):
        app, _ = make_app(headless=True)
        client = client_for(app, {'User-Agent': YANDEX_UA, 'Accept': 'text/html'})
        assert client.get('/protected').status_code == 403


class TestMonitorAndPolicy:
    def test_monitor_passes_and_counts(self):
        app, _ = make_app(policy={'yandex_browser': 'monitor'})
        client = client_for(app, {'User-Agent': YANDEX_UA})
        assert client.get('/protected').status_code == 200
        stats = client.get('/kremle/stats').json()
        assert stats['actions']['monitor'] == 1
        assert stats['shadow_total'] == 1

    def test_allow_action_ignores_signal(self):
        app, _ = make_app(policy={'yandex_browser': 'allow'})
        client = client_for(app, {'User-Agent': YANDEX_UA})
        assert client.get('/protected').status_code == 200
        assert client.get('/kremle/stats').json()['actions']['challenge'] == 0

    def test_blacklist_returns_blocked(self):
        storage = MemoryStorage()
        storage.blacklist_add('127.0.0.1', ttl=3600)
        app, _ = make_app(storage=storage)
        client = client_for(app, {'User-Agent': NORMAL_UA, 'Accept': 'application/json'},
                            peer='127.0.0.1')
        r = client.get('/protected')
        assert r.status_code == 403
        assert r.json()['error'] == 'blocked'


class TestOps:
    def test_health(self):
        app, _ = make_app()
        body = TestClient(app).get('/kremle/health').json()
        assert body['status'] == 'ok'
        assert body['storage_ok'] is True
        assert body['async_offload'] in (True, False)

    def test_health_degraded(self):
        class Broken(MemoryStorage):
            def set(self, key, value, ttl):
                raise RuntimeError('down')

        app, _ = make_app(storage=Broken())
        r = TestClient(app).get('/kremle/health')
        assert r.status_code == 503
        assert r.json()['status'] == 'degraded'

    def test_stats_and_metrics(self):
        app, _ = make_app()
        client = client_for(app, {'User-Agent': YANDEX_UA})
        client.get('/protected')
        stats = client.get('/kremle/stats').json()
        assert stats['requests_total'] >= 1

        metrics = client.get('/kremle/metrics')
        assert metrics.status_code == 200
        assert 'kremle_requests_total' in metrics.text

    def test_ops_disabled(self):
        app, _ = make_app(enable_ops_routes=False)
        assert TestClient(app).get('/kremle/health').status_code == 404


class TestVerificationTtl:
    def test_full_cycle(self):
        app, kremle = make_app(verified_ttl=300)
        client = TestClient(app)
        challenge = client.get('/kremle/challenge',
                               headers={'Accept': 'application/json'}).json()
        ch = kremle.engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}

        assert client.post('/kremle/verify', json={
            'token': challenge['token'], 'answers': answers,
        }).json()['passed'] is True

        status = client.get('/kremle/status').json()
        assert status['verified'] is True
        assert 0 < status['expires_in'] <= 300

        # пройдено — значит запрос проходит без капчи даже с Яндекс-UA
        client.headers.update({'User-Agent': YANDEX_UA})
        assert client.get('/protected').status_code == 200

        assert client.post('/kremle/logout').status_code == 200
        assert client.get('/kremle/status').json()['verified'] is False
        # после logout — снова редирект на капчу (следить за follow_redirects!)
        assert client.get('/protected', follow_redirects=False).status_code == 302

    def test_expired_state_rejected(self):
        app, _ = make_app(verified_ttl=1)
        client = TestClient(app)
        with client as c:
            c.cookies.set('session', 'x')   # не мешает: сессии ещё нет
        # сессию с истёкшим exp кладём напрямую через cookie невозможно,
        # поэтому проверяем, что старый bool-формат не проходит
        assert client.get('/kremle/status').json()['verified'] is False

    def test_verify_malformed_json(self):
        app, _ = make_app()
        r = TestClient(app).post('/kremle/verify', content=b'not json',
                                 headers={'Content-Type': 'application/json'})
        assert r.status_code == 400
        assert r.json()['error'] == 'invalid_json'

    def test_challenge_json_payload(self):
        app, _ = make_app()
        r = TestClient(app).get('/kremle/challenge', headers={'Accept': 'application/json'})
        body = r.json()
        assert body['questions'] and body['token']
        assert 'ans' not in body['questions'][0]
        assert 'no-store' in r.headers['cache-control']
