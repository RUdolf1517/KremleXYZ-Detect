# -*- coding: utf-8 -*-
"""Демо-приложение: то, что видит пользователь после `kremle-detect serve`."""

import pytest

pytest.importorskip('fastapi', reason='fastapi not installed')
pytest.importorskip('httpx', reason='httpx not installed')

from fastapi.testclient import TestClient  # noqa: E402

from kremle_detect.demo import build_app  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def client(policy=None):
    return TestClient(build_app(policy))


class TestPages:
    def test_index(self):
        response = client().get('/')
        assert response.status_code == 200
        assert 'kremle-detect demo' in response.text
        assert '/api/me' in response.text

    def test_stats_page(self):
        response = client().get('/stats')
        assert response.status_code == 200
        assert '/kremle/stats' in response.text

    def test_stats_page_shows_counters(self):
        c = client()
        c.get('/', headers={'User-Agent': NORMAL_UA})
        body = c.get('/kremle/stats').json()
        assert body['requests_total'] >= 1


class TestGuard:
    def test_normal_user_passes(self):
        c = client()
        assert c.get('/api/me', headers={'User-Agent': NORMAL_UA}).json() == {
            'ok': True, 'user': 'not-a-yandex-browser',
        }

    def test_yandex_browser_gets_json_403(self):
        c = client()
        response = c.get('/api/me', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json',
        })
        assert response.status_code == 403
        assert response.json()['error'] == 'captcha_required'

    def test_yandex_browser_redirected_on_html(self):
        c = client()
        response = c.get('/', headers={'User-Agent': YANDEX_UA, 'Accept': 'text/html'},
                         follow_redirects=False)
        # middleware отрабатывает раньше роута: навигация → редирект на капчу
        assert response.status_code == 302
        assert response.headers['location'] == '/kremle/challenge'

    def test_shadow_mode_blocks_nothing(self):
        c = client({signal: 'monitor' for signal in (
            'yandex_bot', 'yandex_browser', 'yandex_client_hints', 'yandex_referrer',
        )})
        response = c.get('/api/me', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json',
        })
        assert response.status_code == 200
        stats = c.get('/kremle/stats').json()
        assert stats['actions']['monitor'] >= 1
        assert stats['actions']['challenge'] == 0


class TestOps:
    def test_health(self):
        body = client().get('/kremle/health').json()
        assert body['status'] == 'ok'
        assert body['version']
        assert body['verified_ttl'] == 300

    def test_metrics(self):
        response = client().get('/kremle/metrics')
        assert response.status_code == 200
        assert 'kremle_requests_total' in response.text

    def test_challenge_payload_has_attribution(self):
        body = client().get('/kremle/challenge',
                            headers={'Accept': 'application/json'}).json()
        assert 'token' in body and body['questions']
        assert 'attribution' in body


class TestFullCycleOnDemo:
    def test_pass_then_logout(self):
        c = client()
        challenge = c.get('/kremle/challenge',
                          headers={'Accept': 'application/json'}).json()
        engine = c.app.state.kremle.engine
        stored = engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}

        assert c.post('/kremle/verify', json={
            'token': challenge['token'], 'answers': answers,
        }).json()['passed'] is True

        # пройдено — Яндекс-UA пропускается
        assert c.get('/api/me', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json',
        }).status_code == 200

        assert c.post('/kremle/logout').status_code == 200
        assert c.get('/api/me', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json',
        }).status_code == 403


class TestEntrypoint:
    def test_main_runs_uvicorn_with_env_port(self, monkeypatch):
        import uvicorn

        from kremle_detect import demo

        calls = {}

        def fake_run(app, host, port, log_level):
            calls.update(host=host, port=port, log_level=log_level)

        monkeypatch.setattr(uvicorn, 'run', fake_run)
        monkeypatch.setenv('KREMLE_DEMO_PORT', '8123')
        monkeypatch.delenv('KREMLE_DEMO_POLICY', raising=False)
        demo.main()
        assert calls == {'host': '0.0.0.0', 'port': 8123, 'log_level': 'info'}

    def test_main_monitor_env_enables_shadow(self, monkeypatch):
        import uvicorn

        from kremle_detect import demo

        captured = {}
        monkeypatch.setattr(uvicorn, 'run', lambda app, **kw: captured.update(app=app))
        monkeypatch.setenv('KREMLE_DEMO_POLICY', 'monitor')
        demo.main(port=9000)
        # в shadow-режиме движок не блокирует, но решение всё равно принимает
        assert captured['app'].state.kremle.engine.policy.get('yandex_browser') == 'monitor'

    def test_explicit_port_wins_over_env(self, monkeypatch):
        import uvicorn

        from kremle_detect import demo

        ports = []
        monkeypatch.setattr(uvicorn, 'run',
                            lambda app, host, port, log_level: ports.append(port))
        monkeypatch.setenv('KREMLE_DEMO_PORT', '8123')
        demo.main(port=7000)
        assert ports == [7000]

    def test_pages_have_expected_hooks(self):
        from kremle_detect import demo

        assert 'fetch(' in demo._INDEX_HTML
        assert '/kremle/stats' in demo._STATS_HTML
        assert 'Яндекс' in demo._INDEX_HTML


class TestSessionDependency:
    """Без itsdangerous Starlette не даёт SessionMiddleware — сообщение должно быть внятным."""

    def test_missing_itsdangerous_gives_clear_error(self, monkeypatch):
        from kremle_detect.integrations import fastapi_ext

        monkeypatch.setattr(fastapi_ext, 'SessionMiddleware', None)
        with pytest.raises(RuntimeError) as exc:
            build_app()
        assert 'itsdangerous' in str(exc.value)
