# -*- coding: utf-8 -*-
"""Starlette и Litestar: та же капча, тот же протокол, те же заголовки.

Обе интеграции — тонкие адаптеры над ``KremleASGI``, поэтому тесты проверяют
и общее ядро (таблица роутов, guard), и то, что результат действительно
доезжает до клиента через каждую библиотеку.
"""

import pytest

from kremle_detect.integrations.asgi_ext import ASGIRequest, KremleASGI

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'
JSON_HEADERS = {'Accept': 'application/json'}


def make_core(**kwargs):
    params = dict(secret='test', categories=['math'], question_count=3, max_errors=1,
                  challenge_rate_limit=0)
    params.update(kwargs)
    return KremleASGI(**params)


class TestRoutesTable:
    """Паритет роутов с FastAPI — проверяется сравнением, а не обещанием."""

    def test_table_has_all_routes(self):
        core = make_core()
        table = {path: methods for path, methods, _ in core.routes_table()}
        assert table == {
            '/kremle/challenge': ('GET',),
            '/kremle/verify': ('POST',),
            '/kremle/status': ('GET',),
            '/kremle/logout': ('POST',),
            '/kremle/widget/{name}': ('GET',),
            '/kremle/img/{key}': ('GET',),
            '/kremle/health': ('GET',),
            '/kremle/stats': ('GET',),
            '/kremle/metrics': ('GET',),
        }

    def test_ops_routes_can_be_disabled(self):
        table = {path for path, _, _ in make_core(enable_ops_routes=False).routes_table()}
        assert '/kremle/health' not in table
        assert '/kremle/challenge' in table

    def test_parity_with_fastapi(self):
        pytest.importorskip('fastapi')
        from fastapi import FastAPI

        from kremle_detect.integrations.fastapi_ext import KremleFastAPI

        app = FastAPI()
        KremleFastAPI(app, secret='test', categories=['math'])
        fastapi_paths = {route.path for route in app.routes if '/kremle/' in getattr(route, 'path', '')}
        core_paths = {
            path.replace('{name}', '{name}') for path, _, _ in make_core().routes_table()
        }
        # у Starlette/Litestar путь параметра пишется так же — сравниваем как есть
        assert core_paths == fastapi_paths


def guard(core, path, headers, method='GET'):
    """Прогнать guard на синтетическом ASGI-запросе."""
    import asyncio

    request = ASGIRequest({
        'type': 'http', 'method': method, 'path': path,
        'headers': [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        'client': ('203.0.113.9', 1234),
    })
    return asyncio.new_event_loop().run_until_complete(core.guard(request))


class TestGuardCore:
    def test_normal_user_passes(self):
        assert guard(make_core(), '/secret', {'User-Agent': NORMAL_UA}) is None

    def test_own_paths_are_skipped(self):
        core = make_core()
        for path in ('/kremle/challenge', '/kremle/verify', '/kremle/widget/x.js'):
            assert core.is_own_path(path)
            assert guard(core, path, {'User-Agent': YANDEX_UA}) is None

    def test_json_client_gets_403_payload(self):
        response = guard(make_core(), '/api/data',
                         {'User-Agent': YANDEX_UA, 'Accept': 'application/json'})
        assert response is not None
        assert response.status == 403
        assert b'captcha_required' in response.body

    def test_html_client_gets_redirect(self):
        response = guard(make_core(), '/', {'User-Agent': YANDEX_UA})
        assert response.status == 302
        assert response.headers['Location'] == '/kremle/challenge'


class TestGuardDecisions:
    """Три исхода guard: пропустить, отдать капчу, отказать."""

    def test_block_policy_is_403_text(self):
        response = guard(make_core(policy={'yandex_browser': 'block'}), '/',
                         {'User-Agent': YANDEX_UA})
        assert response.status == 403
        assert 'Доступ заблокирован' in response.body.decode('utf-8')

    def test_block_policy_is_403_json_for_api(self):
        response = guard(make_core(policy={'yandex_browser': 'block'}), '/api/data',
                         {'User-Agent': YANDEX_UA, 'Accept': 'application/json'})
        assert response.status == 403
        assert b'access_denied' in response.body or b'blocked' in response.body

    def test_blacklist_is_403(self):
        core = make_core()
        import asyncio

        asyncio.new_event_loop().run_until_complete(
            core._run(core.engine.blacklist_add, '203.0.113.9')
        )
        response = guard(core, '/', {'User-Agent': NORMAL_UA})
        assert response.status == 403

    def test_json_client_after_block_keeps_no_store(self):
        response = guard(make_core(policy={'yandex_browser': 'block'}), '/api',
                         {'User-Agent': YANDEX_UA, 'Accept': 'application/json'})
        assert 'no-store' in response.headers['Cache-Control']

    def test_whitelisted_ip_passes(self):
        assert guard(make_core(whitelist=['203.0.113.9']), '/', {'User-Agent': YANDEX_UA}) is None

    def test_trusted_proxy_ip_is_used(self):
        core = make_core(whitelist=['10.1.1.1'], trusted_proxies=['203.0.113.9'])
        request = ASGIRequest({
            'type': 'http', 'method': 'GET', 'path': '/',
            'headers': [(b'user-agent', YANDEX_UA.encode()),
                        (b'x-forwarded-for', b'10.1.1.1')],
            'client': ('203.0.113.9', 1),
        })
        import asyncio

        assert asyncio.new_event_loop().run_until_complete(core.guard(request)) is None

    def test_untrusted_forwarded_for_is_ignored(self):
        core = make_core(whitelist=['10.1.1.1'])
        request = ASGIRequest({
            'type': 'http', 'method': 'GET', 'path': '/',
            'headers': [(b'user-agent', YANDEX_UA.encode()),
                        (b'x-forwarded-for', b'10.1.1.1')],
            'client': ('203.0.113.9', 1),
        })
        import asyncio

        response = asyncio.new_event_loop().run_until_complete(core.guard(request))
        assert response.status == 302

    def test_challenge_rate_limit_is_429(self):
        core = make_core(challenge_rate_limit=1)
        import asyncio

        loop = asyncio.new_event_loop()
        request = ASGIRequest({'type': 'http', 'method': 'GET', 'path': '/kremle/challenge',
                               'headers': [], 'client': ('203.0.113.9', 1)})
        first = loop.run_until_complete(core.challenge(request))
        second = loop.run_until_complete(core.challenge(request))
        assert first.status == 200
        assert second.status == 429
        assert second.headers['Retry-After']

    def test_non_http_scope_passes_through(self):
        import asyncio

        core = make_core()
        called = {}

        async def next_app(scope, receive, send):
            called['yes'] = True

        asyncio.new_event_loop().run_until_complete(
            core({'type': 'websocket'}, None, None, next_app)
        )
        assert called['yes'] is True

    def test_missing_custom_template_is_runtime_error(self):
        import asyncio

        core = make_core(template='/nonexistent/kremle.html')
        request = ASGIRequest({'type': 'http', 'method': 'GET', 'path': '/kremle/challenge',
                               'headers': [], 'client': ('203.0.113.9', 1)})
        with pytest.raises(RuntimeError, match='шаблон'):
            asyncio.new_event_loop().run_until_complete(core.challenge(request))


class TestStatusBindIp:
    def test_status_checks_ip_like_the_guard(self):
        import asyncio

        from kremle_detect.session import SESSION_KEY, build_verification

        core = make_core(bind_ip=True)

        def status_for(ip):
            scope = {
                'type': 'http', 'method': 'GET', 'path': '/kremle/status',
                'headers': [], 'client': (ip, 1234),
                'session': {SESSION_KEY: build_verification(ip='203.0.113.9')},
            }
            response = asyncio.new_event_loop().run_until_complete(
                core.status(ASGIRequest(scope))
            )
            import json as json_mod
            return json_mod.loads(response.body.decode())

        assert status_for('203.0.113.9')['verified'] is True
        assert status_for('203.0.113.50')['verified'] is False


# ── Starlette ────────────────────────────────────────────────────────────────

starlette = pytest.importorskip('starlette', reason='starlette not installed')


@pytest.fixture
def starlette_app():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from kremle_detect.integrations.asgi_ext import KremleStarlette

    def build(**kwargs):
        async def index(request):
            return PlainTextResponse('ok')

        app = Starlette(routes=[Route('/', index)])
        params = dict(secret='test', categories=['math'], question_count=3, max_errors=1,
                      challenge_rate_limit=0)
        params.update(kwargs)
        KremleStarlette(app, **params)
        return app

    return build


class TestStarlette:
    @pytest.fixture
    def client(self, starlette_app):
        from starlette.testclient import TestClient

        return TestClient(starlette_app(), follow_redirects=False)

    def test_normal_user_passes(self, client):
        assert client.get('/', headers={'User-Agent': NORMAL_UA}).status_code == 200

    def test_yandex_json_is_403(self, client):
        response = client.get('/', headers={'User-Agent': YANDEX_UA, **JSON_HEADERS})
        assert response.status_code == 403
        assert response.json()['error'] == 'captcha_required'
        assert response.json()['challenge_url'] == '/kremle/challenge'

    def test_yandex_html_is_redirect(self, client):
        response = client.get('/', headers={'User-Agent': YANDEX_UA})
        assert response.status_code == 302
        assert response.headers['location'] == '/kremle/challenge'

    def test_challenge_json_headers(self, client):
        response = client.get('/kremle/challenge',
                              headers={'User-Agent': YANDEX_UA, **JSON_HEADERS})
        assert response.status_code == 200
        assert response.json()['max_errors'] == 1
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert "frame-ancestors 'none'" in response.headers['content-security-policy']
        assert 'no-store' in response.headers['cache-control']

    def test_challenge_html_renders_template(self, client):
        response = client.get('/kremle/challenge', headers={'User-Agent': YANDEX_UA})
        assert response.status_code == 200
        assert 'text/html' in response.headers['content-type']
        assert 'var DATA = ' in response.text
        assert '__KR' not in response.text

    def test_verify_pass_then_status_and_logout(self, client):
        challenge = client.get('/kremle/challenge',
                               headers={'User-Agent': YANDEX_UA, **JSON_HEADERS}).json()
        token = challenge['token']

        # ответы берём у сервера: клиенту правильные не отдаются
        engine = client.app.state.kremle.engine
        stored = engine.get_challenge(token)
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}

        passed = client.post('/kremle/verify', json={'token': token, 'answers': answers},
                             headers={'User-Agent': YANDEX_UA})
        assert passed.status_code == 200
        assert passed.json()['passed'] is True
        assert passed.json()['redirect'] == '/'

        status = client.get('/kremle/status', headers={'User-Agent': YANDEX_UA})
        assert status.json()['verified'] is True
        assert status.headers['x-frame-options'] == 'DENY'

        # сессия пройдена — guard пропускает
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 200

        assert client.post('/kremle/logout').json()['verified'] is False
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 302

    def test_invalid_json_is_400(self, client):
        response = client.post('/kremle/verify', content='{не json'.encode(),
                               headers={'Content-Type': 'application/json'})
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_json'

    def test_widget_and_unknown_widget(self, client):
        bundle = client.get('/kremle/widget/kremle-widget.min.js')
        assert bundle.status_code == 200
        assert b'KremleWidget' in bundle.content
        assert client.get('/kremle/widget/index.js').status_code == 404

    def test_unknown_image_is_404(self, client):
        assert client.get('/kremle/img/' + 'a' * 32).status_code == 404

    def test_image_from_cache_is_served(self, starlette_app, tmp_path):
        from starlette.testclient import TestClient

        from kremle_detect.images import image_key, store_image

        png = (b'\x89PNG\r\n\x1a\n' + b'\x00' * 32)
        url = 'https://example.invalid/task.png'
        store_image(url, png, cache_dir=str(tmp_path))

        app = starlette_app(images_cache_dir=str(tmp_path))
        client = TestClient(app)
        response = client.get('/kremle/img/' + image_key(url))
        assert response.status_code == 200
        assert response.content == png
        assert response.headers['content-type'] == 'image/png'
        assert response.headers['x-content-type-options'] == 'nosniff'

    def test_own_session_middleware_is_reused_and_wrapped(self):
        """Своя SessionMiddleware не дублируется, а guard встаёт под неё."""
        from starlette.applications import Starlette
        from starlette.middleware.sessions import SessionMiddleware
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from kremle_detect.integrations.asgi_ext import KremleStarlette

        async def index(request):
            return PlainTextResponse('ok')

        app = Starlette(routes=[Route('/', index)])
        app.add_middleware(SessionMiddleware, secret_key='own-key')
        kremle = KremleStarlette(app, secret='test', categories=['math'],
                                 max_errors=1, challenge_rate_limit=0)

        names = [mw.cls.__name__ for mw in app.user_middleware]
        assert names.count('SessionMiddleware') == 1
        assert names.index('SessionMiddleware') == names.index('KremleGuardMiddleware') - 1

        client = TestClient(app, follow_redirects=False)
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 302

        challenge = client.get('/kremle/challenge',
                               headers={'User-Agent': YANDEX_UA,
                                        'Accept': 'application/json'}).json()
        stored = kremle.engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
        client.post('/kremle/verify', json={'token': challenge['token'], 'answers': answers},
                    headers={'User-Agent': YANDEX_UA})
        # прохождение запомнилось в чужой сессии — значит guard видит session
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 200

    def test_ops_routes(self, client):
        client.get('/', headers={'User-Agent': NORMAL_UA})   # один запрос под фильтром
        health = client.get('/kremle/health')
        assert health.status_code == 200
        assert health.json()['status'] == 'ok'
        assert client.get('/kremle/stats').json()['requests_total'] >= 1
        assert 'kremle_requests_total' in client.get('/kremle/metrics').text

    def test_monitor_mode_blocks_nothing(self, starlette_app):
        from starlette.testclient import TestClient

        client = TestClient(starlette_app(policy={'yandex_browser': 'monitor'}))
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 200

    def test_whitelist_passes(self, starlette_app):
        from starlette.testclient import TestClient

        client = TestClient(starlette_app(whitelist=['127.0.0.1']))
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).status_code == 200

    def test_headless_always_json(self, starlette_app):
        from starlette.testclient import TestClient

        client = TestClient(starlette_app(headless=True))
        assert client.get('/', headers={'User-Agent': YANDEX_UA}).json()['error'] == (
            'captcha_required'
        )


# ── Litestar ─────────────────────────────────────────────────────────────────

pytest.importorskip('litestar', reason='litestar not installed')


@pytest.fixture
def litestar_app():
    from litestar import Litestar, get
    from litestar.stores.memory import MemoryStore

    from kremle_detect.integrations.asgi_ext import KremleLitestar

    def build(**kwargs):
        @get('/')
        async def index() -> dict:
            return {'ok': True}

        params = dict(secret='test', categories=['math'], question_count=3, max_errors=1,
                      challenge_rate_limit=0)
        params.update(kwargs)
        kremle = KremleLitestar(**params)
        app = Litestar(
            route_handlers=[index, *kremle.route_handlers],
            middleware=kremle.middleware,
            stores={'sessions': MemoryStore()},
        )
        # как в Flask/FastAPI-интеграциях: движок доступен из приложения
        app.state.kremle = kremle
        return app

    return build


class TestLitestar:
    @pytest.fixture
    def client(self, litestar_app):
        from litestar.testing import TestClient

        with TestClient(litestar_app()) as client:
            yield client

    def test_normal_user_passes(self, client):
        assert client.get('/', headers={'User-Agent': NORMAL_UA}).status_code == 200

    def test_yandex_json_is_403(self, client):
        response = client.get('/', headers={'User-Agent': YANDEX_UA, **JSON_HEADERS})
        assert response.status_code == 403
        assert response.json()['error'] == 'captcha_required'

    def test_challenge_json_headers(self, client):
        response = client.get('/kremle/challenge',
                              headers={'User-Agent': YANDEX_UA, **JSON_HEADERS})
        assert response.status_code == 200
        assert response.json()['max_errors'] == 1
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['x-content-type-options'] == 'nosniff'

    def test_verify_pass_then_status(self, client):
        challenge = client.get('/kremle/challenge',
                               headers={'User-Agent': YANDEX_UA, **JSON_HEADERS}).json()
        token = challenge['token']

        engine = client.app.state.kremle.engine
        stored = engine.get_challenge(token)
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}

        passed = client.post('/kremle/verify', json={'token': token, 'answers': answers},
                             headers={'User-Agent': YANDEX_UA})
        assert passed.json()['passed'] is True
        assert client.get('/kremle/status').json()['verified'] is True

        # Именно 200 без единого редиректа: TestClient Litestar идёт по
        # редиректу сам, и «200 после 302» — это страница капчи, а не
        # пройденный guard. Так однажды уже спрятался баг с порядком
        # middleware, когда сессия стояла внутри guard.
        response = client.get('/', headers={'User-Agent': YANDEX_UA})
        assert response.history == []
        assert response.status_code == 200

    def test_widget_served(self, client):
        response = client.get('/kremle/widget/kremle-widget.min.js')
        assert response.status_code == 200
        assert b'KremleWidget' in response.content

    def test_ops_routes(self, client):
        assert client.get('/kremle/health').status_code == 200
        assert 'kremle_requests_total' in client.get('/kremle/metrics').text

    def test_init_app_on_existing_app(self):
        from litestar import Litestar, get
        from litestar.stores.memory import MemoryStore
        from litestar.testing import TestClient

        from kremle_detect.integrations.asgi_ext import KremleLitestar

        @get('/')
        async def index() -> dict:
            return {'ok': True}

        kremle = KremleLitestar(secret='test', categories=['math'])
        app = Litestar(route_handlers=[index, *kremle.route_handlers],
                       middleware=kremle.middleware, stores={'sessions': MemoryStore()})
        with TestClient(app) as client:
            assert client.get('/kremle/challenge').status_code == 200
            assert client.get('/kremle/health').json()['status'] == 'ok'

    def test_no_ops_routes(self, litestar_app):
        from litestar.testing import TestClient

        with TestClient(litestar_app(enable_ops_routes=False)) as client:
            assert client.get('/kremle/health').status_code == 404
            assert client.get('/kremle/challenge').status_code == 200
