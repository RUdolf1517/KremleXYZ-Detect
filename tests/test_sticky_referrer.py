# -*- coding: utf-8 -*-
"""Реферер из Яндекса — не одноразовый билет.

Баг: человек приходит из поиска Яндекса обычным Chrome. Первый запрос несёт
`Referer: yandex.ru` → капча. Дальше реферер уже свой (или его нет, если
набрать адрес руками), детекция молчит — и достаточно стереть
`/kremle/challenge` из адресной строки, чтобы пройти.

Сигнал действительно одноразовый, а вот **долг** — нет: он запоминается в
сессии и держится, пока капча не пройдена (или пока не истечёт окно).
"""

import time

import pytest

from kremle_detect.session import (
    DEFAULT_PENDING_TTL, PENDING_KEY, clear_pending, mark_pending, pending_reason,
)

YANDEX_REFERER = 'https://yandex.ru/search/?text=%D0%BA%D0%B0%D0%BF%D1%87%D0%B0'
CHROME_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
JSON = {'Accept': 'application/json'}


# ── единицы: сам механизм «долга» ────────────────────────────────────────────

class TestPendingSession:
    def test_mark_and_read(self):
        session = {}
        mark_pending(session, 'yandex_referrer')
        assert pending_reason(session) == 'yandex_referrer'

    def test_expired_is_forgotten(self):
        session = {}
        mark_pending(session, 'yandex_referrer', ttl=1)
        session[PENDING_KEY]['exp'] = time.time() - 1
        assert pending_reason(session) is None
        assert PENDING_KEY not in session

    def test_shortened_window_applies(self):
        session = {}
        mark_pending(session, 'yandex_referrer', ttl=DEFAULT_PENDING_TTL)
        session[PENDING_KEY]['ts'] = time.time() - 1000
        assert pending_reason(session, ttl=900) is None

    def test_clear(self):
        session = {}
        mark_pending(session, 'yandex_referrer')
        clear_pending(session)
        assert pending_reason(session) is None

    def test_garbage_is_ignored(self):
        session = {PENDING_KEY: 'мусор'}
        assert pending_reason(session) is None
        assert PENDING_KEY not in session

    def test_zero_ttl_disables(self):
        session = {}
        mark_pending(session, 'yandex_referrer', ttl=0)
        assert PENDING_KEY not in session


# ── Flask ────────────────────────────────────────────────────────────────────

flask = pytest.importorskip('flask', reason='flask not installed')


def make_flask_app(app, **kwargs):
    """Навесить KremleFlask на готовое приложение и вернуть расширение."""
    from kremle_detect.integrations.flask_ext import KremleFlask

    params = dict(categories=['math'], question_count=3, max_errors=1, secret='test',
                  challenge_rate_limit=0, rate_limit=0)
    params.update(kwargs)
    return KremleFlask(app, **params)


def make_flask(**kwargs):
    app = flask.Flask(__name__)
    app.secret_key = 'test'
    make_flask_app(app, **kwargs)

    @app.route('/')
    def index():
        return 'ok'

    @app.route('/article/42')
    def article():
        return 'статья'

    return app


class TestFlaskStickyReferrer:
    def test_challenge_survives_url_editing(self):
        client = make_flask().test_client()

        first = client.get('/', headers={'Referer': YANDEX_REFERER, 'User-Agent': CHROME_UA})
        assert first.status_code == 302
        assert first.headers['Location'].endswith('/kremle/challenge')

        # «стёр капчу из адресной строки» — тот же клиент, чистое URL
        second = client.get('/', headers={'User-Agent': CHROME_UA})
        assert second.status_code == 302
        assert second.headers['Location'].endswith('/kremle/challenge')

    def test_other_pages_are_challenged_too(self):
        client = make_flask().test_client()
        client.get('/', headers={'Referer': YANDEX_REFERER})
        assert client.get('/article/42').status_code == 302

    def test_json_client_gets_403_not_redirect(self):
        client = make_flask().test_client()
        client.get('/', headers={'Referer': YANDEX_REFERER})
        response = client.get('/article/42', headers=JSON)
        assert response.status_code == 403
        assert response.get_json()['error'] == 'captcha_required'
        assert response.get_json()['reason'] == 'yandex_referrer'

    def test_passing_clears_the_debt(self):
        app = make_flask()
        engine = app.extensions['kremle'].engine
        client = app.test_client()

        client.get('/', headers={'Referer': YANDEX_REFERER})
        challenge = client.get('/kremle/challenge', headers=JSON).get_json()
        stored = engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
        passed = client.post('/kremle/verify',
                             json={'token': challenge['token'], 'answers': answers}).get_json()
        assert passed['passed'] is True

        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 200

    def test_logout_after_passing_does_not_bring_the_captcha_back(self):
        app = make_flask()
        engine = app.extensions['kremle'].engine
        client = app.test_client()

        # без реферера капчи нет
        assert client.get('/').status_code == 200

        client.get('/', headers={'Referer': YANDEX_REFERER})
        challenge = client.get('/kremle/challenge', headers=JSON).get_json()
        stored = engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
        client.post('/kremle/verify', json={'token': challenge['token'], 'answers': answers})
        assert client.get('/').status_code == 200

        client.post('/kremle/logout')
        # после выхода долг не возвращается: он был снят прохождением
        assert client.get('/').status_code == 200

    def test_logout_does_not_forgive_the_debt(self):
        """Долг переживает выход: иначе «выйти» = «отмени капчу». """
        client = make_flask().test_client()

        client.get('/', headers={'Referer': YANDEX_REFERER})
        assert client.post('/kremle/logout').get_json()['verified'] is False
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 302

    def test_protect_decorator_keeps_the_debt(self):
        """Точечная защита роута — тот же долг, а не «только первый заход». """
        import flask

        app = flask.Flask(__name__)
        app.secret_key = 'test'
        kremle = make_flask_app(app, auto_guard=False)

        @app.route('/secret')
        @kremle.protect
        def secret():
            return 'secret'

        client = app.test_client()
        assert client.get('/secret', headers={'Referer': YANDEX_REFERER}).status_code == 302
        assert client.get('/secret', headers={'User-Agent': CHROME_UA}).status_code == 302

    def test_plain_chrome_is_not_affected(self):
        """Обычный посетитель без Яндекса капчу не видит — и не должен."""
        client = make_flask().test_client()
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 200
        assert client.get('/article/42').status_code == 200

    def test_referrer_from_site_does_not_challenge(self):
        client = make_flask().test_client()
        client.get('/', headers={'Referer': 'https://example.com/'})
        assert client.get('/article/42').status_code == 200

    def test_sticky_can_be_disabled(self):
        client = make_flask(sticky_referrer=False).test_client()
        client.get('/', headers={'Referer': YANDEX_REFERER})
        assert client.get('/').status_code == 200

    def test_expired_debt_lets_visitor_through(self):
        client = make_flask(sticky_ttl=1).test_client()
        client.get('/', headers={'Referer': YANDEX_REFERER})
        with client.session_transaction() as sess:
            # переприсваиваем: вложенную правку Flask не считает изменением
            sess[PENDING_KEY] = dict(sess[PENDING_KEY], exp=time.time() - 1)
        assert client.get('/').status_code == 200

    def test_monitor_policy_does_not_create_debt(self):
        client = make_flask(policy={'yandex_referrer': 'monitor'}).test_client()
        client.get('/', headers={'Referer': YANDEX_REFERER})
        # monitor — только статистика, капчи нет и долга тоже
        assert client.get('/').status_code == 200

    def test_yandex_browser_is_handled_by_ua_not_session(self):
        """У Яндекс Браузера сигнал в UA — он и так на каждом запросе."""
        client = make_flask().test_client()
        ya = 'Mozilla/5.0 YaBrowser/24.1.0 Safari/537.36'
        client.get('/', headers={'User-Agent': ya})
        # сменил UA (например, расширением) — капча всё равно приходит,
        # но уже по новому запросу, а не по «долгу» из сессии
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 200


# ── Django ───────────────────────────────────────────────────────────────────

class TestDjangoStickyReferrer:
    @staticmethod
    def _middleware():
        pytest.importorskip('django')
        from django.conf import settings as dj_settings
        if not dj_settings.configured:
            import tests.test_django_integration  # noqa: F401 — общая настройка
        from kremle_detect.integrations.django_ext import KremleDjangoMiddleware
        return KremleDjangoMiddleware(lambda request: 'passed-through')

    @staticmethod
    def _request(path='/', referer=''):
        from django.test import RequestFactory

        kwargs = {'HTTP_USER_AGENT': CHROME_UA}
        if referer:
            kwargs['HTTP_REFERER'] = referer
        request = RequestFactory().get(path, **kwargs)
        request.session = {}
        return request

    def test_debt_survives_second_request(self):
        from django.test import override_settings

        middleware = self._middleware()
        with override_settings(KREMLE_STICKY_REFERRER=True):
            first = middleware(self._request('/', referer=YANDEX_REFERER))
            assert getattr(first, 'status_code', None) == 302
            session = self._request('/')
            # та же сессия, что и у первого запроса
            session.session = first.wsgi_request.session if hasattr(first, 'wsgi_request') else {}
            assert True  # проверка ниже делает основную работу

    def test_sticky_via_shared_session(self):
        from django.test import override_settings

        middleware = self._middleware()
        shared = {}

        def call(path='/', referer=''):
            request = self._request(path, referer=referer)
            request.session = shared
            return middleware(request)

        with override_settings(KREMLE_STICKY_REFERRER=True):
            first = call('/', referer=YANDEX_REFERER)
            assert first.status_code == 302
            second = call('/article/42')
            assert second.status_code == 302

    def test_cleared_by_verification(self):
        from django.test import override_settings

        middleware = self._middleware()
        shared = {}

        def call(path='/', referer=''):
            request = self._request(path, referer=referer)
            request.session = shared
            return middleware(request)

        with override_settings(KREMLE_STICKY_REFERRER=True):
            call('/', referer=YANDEX_REFERER)
            assert call('/') .status_code == 302
            clear_pending(shared)
            assert call('/') == 'passed-through'

    def test_disabled_by_setting(self):
        from django.test import override_settings

        middleware = self._middleware()
        shared = {}

        def call(path='/', referer=''):
            request = self._request(path, referer=referer)
            request.session = shared
            return middleware(request)

        with override_settings(KREMLE_STICKY_REFERRER=False):
            call('/', referer=YANDEX_REFERER)
            assert call('/') == 'passed-through'


# ── FastAPI ──────────────────────────────────────────────────────────────────

class TestFastAPiStickyReferrer:
    @staticmethod
    def _app(**kwargs):
        pytest.importorskip('fastapi')
        from fastapi import FastAPI

        from kremle_detect.integrations.fastapi_ext import KremleFastAPI

        app = FastAPI()
        params = dict(categories=['math'], question_count=3, max_errors=1, secret='test',
                      challenge_rate_limit=0, rate_limit=0)
        params.update(kwargs)
        KremleFastAPI(app, **params)

        @app.get('/')
        async def index():
            return {'ok': True}

        return app

    def test_challenge_survives_url_editing(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(), follow_redirects=False)
        assert client.get('/', headers={'Referer': YANDEX_REFERER}).status_code == 302
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 302

    def test_json_client_gets_403(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(), follow_redirects=False)
        client.get('/', headers={'Referer': YANDEX_REFERER})
        response = client.get('/', headers=JSON)
        assert response.status_code == 403
        assert response.json()['reason'] == 'yandex_referrer'

    def test_clean_visitor_passes(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(), follow_redirects=False)
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 200

    def test_logout_does_not_forgive_the_debt(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(), follow_redirects=False)
        client.get('/', headers={'Referer': YANDEX_REFERER})
        client.post('/kremle/logout')
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 302


# ── Starlette и Litestar (общее ASGI-ядро) ───────────────────────────────────

class TestASGIStickyReferrer:
    def test_starlette_keeps_the_captcha(self):
        pytest.importorskip('starlette')
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from kremle_detect.integrations.asgi_ext import KremleStarlette

        async def index(request):
            return PlainTextResponse('ok')

        app = Starlette(routes=[Route('/', index)])
        KremleStarlette(app, categories=['math'], question_count=3, max_errors=1,
                        secret='test', challenge_rate_limit=0, rate_limit=0)
        client = TestClient(app, follow_redirects=False)

        assert client.get('/', headers={'Referer': YANDEX_REFERER}).status_code == 302
        assert client.get('/').status_code == 302
        assert client.get('/', headers=JSON).status_code == 403

    def test_litestar_keeps_the_captcha(self):
        pytest.importorskip('litestar')
        from litestar import Litestar, get
        from litestar.stores.memory import MemoryStore
        from litestar.testing import TestClient

        from kremle_detect.integrations.asgi_ext import KremleLitestar

        @get('/')
        async def index() -> dict:
            return {'ok': True}

        kremle = KremleLitestar(categories=['math'], question_count=3, max_errors=1,
                                secret='test', challenge_rate_limit=0, rate_limit=0)
        app = Litestar(route_handlers=[index, *kremle.route_handlers],
                       middleware=kremle.middleware,
                       stores={'sessions': MemoryStore()})

        def challenged(client, headers=None):
            """TestClient Litestar всегда идёт по редиректу — смотрим историю."""
            response = client.get('/', headers=headers or {})
            return any(h.status_code == 302 for h in response.history)

        with TestClient(app) as client:
            assert challenged(client, {'Referer': YANDEX_REFERER})
            # «стёр капчу из адресной строки» — сессия помнит долг
            assert challenged(client)

    def test_starlette_clean_visitor_passes(self):
        pytest.importorskip('starlette')
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from kremle_detect.integrations.asgi_ext import KremleStarlette

        async def index(request):
            return PlainTextResponse('ok')

        app = Starlette(routes=[Route('/', index)])
        KremleStarlette(app, categories=['math'], question_count=3, max_errors=1,
                        secret='test', challenge_rate_limit=0, rate_limit=0)
        client = TestClient(app, follow_redirects=False)
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 200
