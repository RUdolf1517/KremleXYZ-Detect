# -*- coding: utf-8 -*-
"""Капча поверх страницы.

Режим ``overlay`` меняет только то, **что** отдаётся без капчи: переход по
ссылке (оболочка сайта) проходит, а данные — подзагрузки и API — нет. Иначе
говоря, окно рисуется поверх живой страницы, но сама страница не становится
бесплатной: без прохождения из неё не уедет ни одного байта данных.

Правило консервативное: непонятный ``Accept`` считается API.
"""

import pytest

from kremle_detect.integrations._common import is_document_request

CHROME_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 YaBrowser/24.1.0'
YANDEX_REFERER = 'https://yandex.ru/search/?text=test'
DOC = {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
JSON = {'Accept': 'application/json'}


# ── единицы: что считается переходом по ссылке ───────────────────────────────

class TestIsDocumentRequest:
    def test_html_navigation(self):
        assert is_document_request('text/html,application/xhtml+xml') is True

    def test_xhtml(self):
        assert is_document_request('application/xhtml+xml') is True

    def test_json_is_api(self):
        assert is_document_request('application/json') is False

    def test_any_json_suffix_is_api(self):
        assert is_document_request('application/ld+json') is False

    def test_wildcard_is_api(self):
        """`*/*` — это fetch, а не переход: непонятное трактуем как API."""
        assert is_document_request('*/*') is False

    def test_missing_accept_is_api(self):
        assert is_document_request(None) is False

    def test_post_is_never_a_document(self):
        assert is_document_request('text/html', method='POST') is False

    def test_head_is_a_document(self):
        assert is_document_request('text/html', method='HEAD') is True

    def test_xhr_is_api(self):
        assert is_document_request('text/html', xhr='XMLHttpRequest') is False

    def test_fetch_dest_document(self):
        assert is_document_request(None, fetch_dest='document') is True

    def test_fetch_dest_empty_is_subresource(self):
        assert is_document_request('text/html', fetch_dest='empty') is False

    def test_fetch_dest_script_is_subresource(self):
        assert is_document_request('*/*', fetch_dest='script') is False


# ── Flask ────────────────────────────────────────────────────────────────────

flask = pytest.importorskip('flask', reason='flask not installed')


def make_flask(**kwargs):
    from kremle_detect.integrations.flask_ext import KremleFlask

    app = flask.Flask(__name__)
    app.secret_key = 'test'
    params = dict(categories=['math'], question_count=3, max_errors=1, secret='test',
                  challenge_rate_limit=0, rate_limit=0)
    params.update(kwargs)
    KremleFlask(app, **params)

    @app.route('/')
    def index():
        return 'оболочка'

    @app.route('/api/data')
    def data():
        return {'secret': 42}

    return app


def solve(client, engine):
    challenge = client.get('/kremle/challenge', headers=JSON).get_json()
    stored = engine.get_challenge(challenge['token'])
    answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
    return client.post('/kremle/verify',
                       json={'token': challenge['token'], 'answers': answers}).get_json()


class TestFlaskOverlay:
    def test_navigation_is_let_through(self):
        app = make_flask(overlay=True)
        client = app.test_client()
        response = client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        assert response.status_code == 200
        assert response.get_data(as_text=True) == 'оболочка'

    def test_api_is_challenged(self):
        app = make_flask(overlay=True)
        client = app.test_client()
        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        assert client.get('/api/data', headers=JSON).status_code == 403

    def test_unknown_accept_is_challenged(self):
        """Без Accept и Sec-Fetch-Dest спасать нечего — капча, как раньше."""
        app = make_flask(overlay=True)
        client = app.test_client()
        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        assert client.get('/api/data', headers={'User-Agent': CHROME_UA}).status_code == 403

    def test_subresource_is_challenged(self):
        app = make_flask(overlay=True)
        client = app.test_client()
        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        response = client.get('/api/data', headers={'Accept': '*/*', 'Sec-Fetch-Dest': 'empty'})
        assert response.status_code == 403

    def test_status_tells_the_widget_to_open(self):
        app = make_flask(overlay=True)
        client = app.test_client()
        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})

        data = client.get('/kremle/status').get_json()
        assert data['pending'] is True
        assert data['reason'] == 'yandex_browser'
        assert data['challenge_url'] == '/kremle/challenge'
        assert data['overlay'] is True
        assert data['verified'] is False

    def test_status_is_quiet_without_detection(self):
        app = make_flask(overlay=True)
        data = app.test_client().get('/kremle/status').get_json()
        assert data['pending'] is False
        assert data['reason'] is None
        assert data['challenge_url'] is None

    def test_after_passing_the_data_is_unlocked(self):
        app = make_flask(overlay=True)
        engine = app.extensions['kremle'].engine
        client = app.test_client()

        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        assert solve(client, engine)['passed'] is True

        assert client.get('/api/data', headers=JSON).status_code == 200
        assert client.get('/kremle/status').get_json()['pending'] is False

    def test_old_behaviour_without_the_flag(self):
        """Без overlay оболочка тоже под капчей — обратная совместимость."""
        app = make_flask()
        client = app.test_client()
        response = client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        assert response.status_code == 302
        assert client.get('/kremle/status').get_json()['overlay'] is False

    def test_login_wall_stays_for_api_even_on_navigation(self):
        """Переход отдаёт оболочку, но не данные: JSON — всегда 403."""
        app = make_flask(overlay=True)
        client = app.test_client()
        client.get('/', headers={**DOC, 'Referer': YANDEX_REFERER})
        assert client.get('/api/data', headers={**JSON, 'Referer': YANDEX_REFERER}).status_code == 403

    def test_protect_lets_the_shell_through(self):
        import flask as flask_mod

        from kremle_detect.integrations.flask_ext import KremleFlask

        app = flask_mod.Flask(__name__)
        app.secret_key = 'test'
        kremle = KremleFlask(app, categories=['math'], question_count=3, max_errors=1,
                             secret='test', challenge_rate_limit=0, rate_limit=0,
                             auto_guard=False, overlay=True)

        @app.route('/secret')
        @kremle.protect
        def secret():
            return 'оболочка'

        client = app.test_client()
        assert client.get('/secret', headers={**DOC, 'User-Agent': YANDEX_UA}).status_code == 200
        assert client.get('/secret', headers={'User-Agent': YANDEX_UA}).status_code == 302


# ── FastAPI ──────────────────────────────────────────────────────────────────

fastapi = pytest.importorskip('fastapi', reason='fastapi not installed')


def make_fastapi(**kwargs):
    from fastapi import FastAPI

    from kremle_detect.integrations.fastapi_ext import KremleFastAPI

    app = FastAPI()
    params = dict(categories=['math'], question_count=3, max_errors=1, secret='test',
                  challenge_rate_limit=0, rate_limit=0)
    params.update(kwargs)
    # Расширение нужно тесту после прохождения капчи — держим ссылку на нём
    app.kremle_ext = KremleFastAPI(app, **params)

    @app.get('/')
    def index():
        return {'page': 'оболочка'}

    @app.get('/api/data')
    def data():
        return {'secret': 42}

    return app


class TestFastAPIOverlay:
    def test_navigation_and_api_differ(self):
        from fastapi.testclient import TestClient

        client = TestClient(make_fastapi(overlay=True))
        assert client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA}).status_code == 200
        assert client.get('/api/data', headers=JSON).status_code == 403

    def test_status_reports_pending(self):
        from fastapi.testclient import TestClient

        client = TestClient(make_fastapi(overlay=True))
        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        data = client.get('/kremle/status').json()
        assert data['pending'] is True
        assert data['overlay'] is True

    def test_api_unlocked_after_passing(self):
        from fastapi.testclient import TestClient

        app = make_fastapi(overlay=True)
        client = TestClient(app)
        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})

        challenge = client.get('/kremle/challenge',
                               headers={'Accept': 'application/json'}).json()
        extension = app.kremle_ext
        stored = extension.engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
        passed = client.post('/kremle/verify',
                             json={'token': challenge['token'], 'answers': answers}).json()
        assert passed['passed'] is True
        assert client.get('/api/data', headers=JSON).status_code == 200


# ── Starlette (общее ASGI-ядро) ──────────────────────────────────────────────

starlette = pytest.importorskip('starlette', reason='starlette not installed')


def make_starlette(**kwargs):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from kremle_detect.integrations.asgi_ext import KremleStarlette

    async def index(request):
        return PlainTextResponse('оболочка')

    async def data(request):
        return PlainTextResponse('{"secret": 42}')

    app = Starlette(routes=[Route('/', index), Route('/api/data', data)])
    params = dict(categories=['math'], question_count=3, max_errors=1, secret='test',
                  challenge_rate_limit=0, rate_limit=0)
    params.update(kwargs)
    KremleStarlette(app, **params)
    return app


class TestStarletteOverlay:
    def test_navigation_and_api_differ(self):
        from starlette.testclient import TestClient

        client = TestClient(make_starlette(overlay=True))
        assert client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA}).status_code == 200
        assert client.get('/api/data', headers=JSON).status_code == 403

    def test_status_reports_overlay(self):
        from starlette.testclient import TestClient

        client = TestClient(make_starlette(overlay=True))
        client.get('/', headers={**DOC, 'User-Agent': YANDEX_UA})
        data = client.get('/kremle/status').json()
        assert data['pending'] is True
        assert data['overlay'] is True


# ── Django ───────────────────────────────────────────────────────────────────

django = pytest.importorskip('django', reason='django not installed')

from django.conf import settings as dj_settings  # noqa: E402

if not dj_settings.configured:
    dj_settings.configure(
        DEBUG=True,
        SECRET_KEY='test-secret',
        ROOT_URLCONF='tests.django_urls',
        INSTALLED_APPS=[
            'django.contrib.sessions',
            'django.contrib.contenttypes',
            'django.contrib.auth',
        ],
        MIDDLEWARE=['django.contrib.sessions.middleware.SessionMiddleware'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        USE_TZ=True,
        KREMLE_CATEGORIES=['math'],
        KREMLE_QUESTION_COUNT=5,
        KREMLE_MAX_ERRORS=1,
        KREMLE_SECRET='test',
        KREMLE_CHALLENGE_RATE_LIMIT=0,
        KREMLE_SKIP_PATHS=['/admin/', '/static/'],
    )
    django.setup()

from django.test import RequestFactory, override_settings  # noqa: E402

from kremle_detect.integrations import django_ext  # noqa: E402


def django_request(path='/page', ua=CHROME_UA, accept=None, dest=None, xhr=False):
    factory = RequestFactory()
    headers = {'HTTP_USER_AGENT': ua, 'REMOTE_ADDR': '127.0.0.1'}
    if accept:
        headers['HTTP_ACCEPT'] = accept
    if dest:
        headers['HTTP_SEC_FETCH_DEST'] = dest
    if xhr:
        headers['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
    request = factory.get(path, **headers)
    request.session = {}
    return request


def run_django_middleware(request):
    called = {}

    def get_response(req):
        called['ok'] = True
        return 'response'

    return django_ext.KremleDjangoMiddleware(get_response)(request), called


def django_status(request):
    import json

    from django.urls import resolve

    response = resolve('/kremle/status/').func(request)
    return json.loads(response.content)


class TestDjangoOverlay:
    def test_navigation_is_let_through(self):
        with override_settings(KREMLE_OVERLAY=True):
            result, called = run_django_middleware(
                django_request(ua=YANDEX_UA, accept='text/html', dest='document'))
        assert called and result == 'response'

    def test_api_is_challenged(self):
        with override_settings(KREMLE_OVERLAY=True):
            result, called = run_django_middleware(
                django_request(ua=YANDEX_UA, accept='application/json'))
        assert not called
        assert result.status_code == 403

    def test_subresource_is_challenged(self):
        """`*/*` — не переход: документ не отдаём (у Django это HTML-редирект)."""
        with override_settings(KREMLE_OVERLAY=True):
            result, called = run_django_middleware(
                django_request(ua=YANDEX_UA, accept='*/*', dest='empty'))
        assert not called
        assert result.status_code == 302
        assert '/kremle/challenge/' in result['Location']

    def test_status_reports_pending_and_overlay(self):
        request = django_request(ua=YANDEX_UA, accept='text/html', dest='document')
        with override_settings(KREMLE_OVERLAY=True):
            run_django_middleware(request)
            data = django_status(request)
        assert data['pending'] is True
        assert data['overlay'] is True

    def test_status_is_quiet_without_detection(self):
        with override_settings(KREMLE_OVERLAY=True):
            data = django_status(django_request())
        assert data['pending'] is False
        assert data['overlay'] is True

    def test_old_behaviour_without_the_flag(self):
        with override_settings(KREMLE_OVERLAY=False):
            result, called = run_django_middleware(
                django_request(ua=YANDEX_UA, accept='text/html', dest='document'))
            data = django_status(django_request())
        assert not called
        assert result.status_code == 302
        assert data['overlay'] is False


# ── демо ─────────────────────────────────────────────────────────────────────

class TestDemoOverlay:
    def _client(self, **kwargs):
        from fastapi.testclient import TestClient

        from kremle_detect.demo import build_app

        return TestClient(build_app(**kwargs))

    def test_demo_puts_the_debt_on_request(self):
        client = self._client(overlay=True)
        response = client.get('/demo/pending', follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['Location'] == '/'
        assert client.get('/kremle/status').json()['pending'] is True
        # страница остаётся на месте, данные — нет
        assert client.get('/', headers={'Accept': 'text/html',
                                        'Sec-Fetch-Dest': 'document'}).status_code == 200
        assert client.get('/api/me', headers={'Accept': 'application/json'}).status_code == 403

    def test_demo_page_has_overlay_button_always(self):
        """Кнопка «открыть капчу поверх страницы» есть в любом режиме демо."""
        for flag in (False, True):
            body = self._client(overlay=flag).get('/').text
            assert 'id="overlay-demo"' in body
            assert 'guardOverlay' in body
            assert '<!-- OVERLAY' not in body
            assert 'kremle-widget.min.js' in body

    def test_demo_page_tells_about_server_mode(self):
        assert 'в режиме окна: включён' in self._client(overlay=True).get('/').text
        assert 'в режиме окна выключен' in self._client(overlay=False).get('/').text

    def test_demo_offers_the_debt_link(self):
        body = self._client(overlay=True).get('/').text
        assert '/demo/pending' in body
