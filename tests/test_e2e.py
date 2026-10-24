# -*- coding: utf-8 -*-
"""
Настоящий e2e: живой HTTP-сервер (uvicorn в потоке) и реальные сокеты.

TestClient не проверяет то, что ломается в проде: middleware-стек Starlette,
cookie сессии между запросами, заголовки, реальный редирект. Здесь всё это есть.

Сценарий: Яндекс Браузер → 403 JSON → GET /kremle/challenge → решаем →
/protected 200 → POST /kremle/logout → снова 403.
"""

import socket
import threading
import time

import pytest

pytest.importorskip('fastapi', reason='fastapi not installed')
pytest.importorskip('httpx', reason='httpx not installed')
uvicorn = pytest.importorskip('uvicorn', reason='uvicorn not installed (pip install kremle-detect[demo])')

import httpx  # noqa: E402

from kremle_detect.demo import build_app  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture(scope='module')
def server():
    """Поднимает демо на свободном порту и отдаёт базовый URL."""
    port = free_port()
    app = build_app()
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning')
    instance = uvicorn.Server(config)

    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()

    base = f'http://127.0.0.1:{port}'
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f'{base}/kremle/health', timeout=0.5)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.05)
    else:  # pragma: no cover
        pytest.fail('сервер не поднялся за 15 секунд')

    yield base, app

    instance.should_exit = True
    thread.join(timeout=10)


class TestLiveServer:
    def test_health_over_http(self, server):
        base, _ = server
        response = httpx.get(f'{base}/kremle/health')
        assert response.status_code == 200
        assert response.json()['status'] == 'ok'

    def test_normal_user_passes(self, server):
        base, _ = server
        response = httpx.get(f'{base}/api/me', headers={'User-Agent': NORMAL_UA})
        assert response.status_code == 200
        assert response.json()['ok'] is True

    def test_yandex_json_guard(self, server):
        base, _ = server
        response = httpx.get(f'{base}/api/me', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json',
        })
        assert response.status_code == 403
        assert response.json()['error'] == 'captcha_required'
        assert 'no-store' in response.headers['cache-control']

    def test_yandex_html_redirect(self, server):
        base, _ = server
        response = httpx.get(f'{base}/', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'text/html',
        }, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'] == '/kremle/challenge'

    def test_full_captcha_cycle(self, server):
        base, app = server
        engine = app.state.kremle.engine

        with httpx.Client(base_url=base, headers={'User-Agent': YANDEX_UA}) as client:
            # 1. до капчи — 403
            assert client.get('/api/me', headers={'Accept': 'application/json'}).status_code == 403

            # 2. берём вопросы (куки сессии сохраняет клиент)
            challenge = client.get('/kremle/challenge',
                                   headers={'Accept': 'application/json'}).json()
            assert challenge['questions']

            # 3. решаем так, как это сделал бы сервер (ответы знает только он)
            stored = engine.get_challenge(challenge['token'])
            answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}

            verify = client.post('/kremle/verify', json={
                'token': challenge['token'], 'answers': answers,
            })
            assert verify.status_code == 200
            assert verify.json()['passed'] is True

            # 4. теперь пускают
            allowed = client.get('/api/me', headers={'Accept': 'application/json'})
            assert allowed.status_code == 200

            # 5. logout — и снова 403 (без новых кук)
            assert client.post('/kremle/logout').status_code == 200
            assert client.get('/api/me', headers={
                'Accept': 'application/json',
            }, follow_redirects=False).status_code == 403

    def test_wrong_answers_fail(self, server):
        base, app = server
        with httpx.Client(base_url=base, headers={'User-Agent': YANDEX_UA}) as client:
            challenge = client.get('/kremle/challenge',
                                   headers={'Accept': 'application/json'}).json()
            stored = app.state.kremle.engine.get_challenge(challenge['token'])
            wrong = {str(i): (q['ans'] + 1) % len(q['opts'])
                     for i, q in enumerate(stored.questions)}
            result = client.post('/kremle/verify', json={
                'token': challenge['token'], 'answers': wrong,
            }).json()
            assert result['passed'] is False

    def test_token_is_single_use_over_http(self, server):
        base, app = server
        with httpx.Client(base_url=base, headers={'User-Agent': YANDEX_UA}) as client:
            challenge = client.get('/kremle/challenge',
                                   headers={'Accept': 'application/json'}).json()
            stored = app.state.kremle.engine.get_challenge(challenge['token'])
            answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}

            first = client.post('/kremle/verify', json={
                'token': challenge['token'], 'answers': answers,
            }).json()
            second = client.post('/kremle/verify', json={
                'token': challenge['token'], 'answers': answers,
            }).json()

            assert first['passed'] is True
            assert second['error'] == 'invalid_token'

    def test_stats_reflect_traffic(self, server):
        base, _ = server
        httpx.get(f'{base}/', headers={'User-Agent': YANDEX_UA, 'Accept': 'application/json'})
        body = httpx.get(f'{base}/kremle/stats').json()
        assert body['requests_total'] >= 1
        assert body['detected_by_reason']['yandex_browser'] >= 1
