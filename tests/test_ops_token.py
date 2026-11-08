# -*- coding: utf-8 -*-
"""Опс-роуты за токеном: `Authorization: Bearer <token>`.

Раньше `/kremle/health`, `/kremle/stats` и `/kremle/metrics` были открыты всем,
кто знает адрес: цифры по трафику — не секрет, но и не для всех. Токен
включается одной настройкой, а без неё поведение остаётся прежним (2.x не
ломаем) — только предупреждение в лог.
"""

import pytest

from kremle_detect.integrations._common import (
    OPS_TOKEN_ENV,
    OPS_UNAUTHORIZED,
    ops_authorized,
    ops_token_from_env,
)

TOKEN = 's3cret-ops-token'
BEARER = {'Authorization': f'Bearer {TOKEN}'}
JSON = {'Accept': 'application/json'}


class TestOpsAuthorized:
    def test_no_token_configured_means_open(self):
        assert ops_authorized(None, None) is True
        assert ops_authorized('мусор', None) is True

    def test_token_configured_requires_header(self):
        assert ops_authorized(None, TOKEN) is False
        assert ops_authorized('', TOKEN) is False
        assert ops_authorized('Bearer wrong', TOKEN) is False

    def test_bearer_and_bare_both_work(self):
        assert ops_authorized(f'Bearer {TOKEN}', TOKEN) is True
        assert ops_authorized(f'bearer {TOKEN}', TOKEN) is True
        assert ops_authorized(TOKEN, TOKEN) is True

    def test_env_is_the_fallback(self, monkeypatch):
        monkeypatch.delenv(OPS_TOKEN_ENV, raising=False)
        assert ops_token_from_env() is None
        monkeypatch.setenv(OPS_TOKEN_ENV, '  из-окружения  ')
        assert ops_token_from_env() == 'из-окружения'
        monkeypatch.setenv(OPS_TOKEN_ENV, '   ')
        assert ops_token_from_env() is None


# ── Flask ────────────────────────────────────────────────────────────────────

flask = pytest.importorskip('flask', reason='flask not installed')


def make_flask(**kwargs):
    from kremle_detect.integrations.flask_ext import KremleFlask

    app = flask.Flask(__name__)
    app.secret_key = 'test'
    params = dict(categories=['math'], question_count=3, max_errors=1, secret='test')
    params.update(kwargs)
    KremleFlask(app, **params)

    @app.route('/')
    def index():
        return 'ok'

    return app


class TestFlaskOpsToken:
    @pytest.mark.parametrize('path', ['/kremle/health', '/kremle/stats', '/kremle/metrics'])
    def test_without_token_is_401(self, path):
        client = make_flask(ops_token=TOKEN).test_client()
        response = client.get(path)
        assert response.status_code == 401
        assert response.get_json() == OPS_UNAUTHORIZED
        assert response.headers['WWW-Authenticate'] == 'Bearer'
        assert 'no-store' in response.headers['Cache-Control']

    @pytest.mark.parametrize('path', ['/kremle/health', '/kremle/stats', '/kremle/metrics'])
    def test_with_token_is_200(self, path):
        client = make_flask(ops_token=TOKEN).test_client()
        assert client.get(path, headers=BEARER).status_code == 200

    def test_captcha_routes_stay_open(self):
        """Токен закрывает только опс-роуты: капча должна работать всем."""
        client = make_flask(ops_token=TOKEN).test_client()
        assert client.get('/kremle/challenge', headers=JSON).status_code == 200
        assert client.get('/kremle/status').status_code == 200

    def test_env_variable_works(self, monkeypatch):
        monkeypatch.setenv(OPS_TOKEN_ENV, TOKEN)
        client = make_flask().test_client()
        assert client.get('/kremle/stats').status_code == 401
        assert client.get('/kremle/stats', headers=BEARER).status_code == 200

    def test_without_token_configured_nothing_changes(self, monkeypatch):
        monkeypatch.delenv(OPS_TOKEN_ENV, raising=False)
        assert make_flask().test_client().get('/kremle/stats').status_code == 200

    def test_disabled_ops_routes_stay_404(self):
        client = make_flask(ops_token=TOKEN, enable_ops_routes=False).test_client()
        assert client.get('/kremle/stats', headers=BEARER).status_code == 404


# ── FastAPI ──────────────────────────────────────────────────────────────────

pytest.importorskip('fastapi', reason='fastapi not installed')
pytest.importorskip('httpx', reason='httpx not installed')


def make_fastapi(**kwargs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kremle_detect.integrations.fastapi_ext import KremleFastAPI

    app = FastAPI()
    params = dict(categories=['math'], question_count=3, max_errors=1, secret='test')
    params.update(kwargs)
    KremleFastAPI(app, **params)

    @app.get('/')
    async def index():
        return {'ok': True}

    return TestClient(app)


class TestFastapiOpsToken:
    @pytest.mark.parametrize('path', ['/kremle/health', '/kremle/stats', '/kremle/metrics'])
    def test_without_token_is_401(self, path):
        response = make_fastapi(ops_token=TOKEN).get(path)
        assert response.status_code == 401
        assert response.json() == OPS_UNAUTHORIZED
        assert response.headers['www-authenticate'] == 'Bearer'

    @pytest.mark.parametrize('path', ['/kremle/health', '/kremle/stats', '/kremle/metrics'])
    def test_with_token_is_200(self, path):
        assert make_fastapi(ops_token=TOKEN).get(path, headers=BEARER).status_code == 200

    def test_captcha_routes_stay_open(self):
        client = make_fastapi(ops_token=TOKEN)
        assert client.get('/kremle/challenge', headers=JSON).status_code == 200


# ── Starlette / Litestar (общее ядро) ────────────────────────────────────────


class TestAsgiOpsToken:
    def _call(self, core, name, headers=None):
        import asyncio
        import json as json_mod

        from kremle_detect.integrations.asgi_ext import ASGIRequest

        request = ASGIRequest({
            'type': 'http', 'method': 'GET', 'path': f'/kremle/{name}',
            'headers': [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            'client': ('203.0.113.9', 1),
        })
        response = asyncio.new_event_loop().run_until_complete(core.dispatch(name, request))
        body = None
        if response.body and 'json' in response.headers.get('Content-Type', ''):
            body = json_mod.loads(response.body.decode())
        return response, body

    @pytest.mark.parametrize('name', ['health', 'stats', 'metrics'])
    def test_without_token_is_401(self, name):
        from kremle_detect.integrations.asgi_ext import KremleASGI

        core = KremleASGI(secret='test', categories=['math'], question_count=3,
                          max_errors=1, ops_token=TOKEN)
        response, body = self._call(core, name)
        assert response.status == 401
        assert body == OPS_UNAUTHORIZED
        assert response.headers['WWW-Authenticate'] == 'Bearer'

    @pytest.mark.parametrize('name', ['health', 'stats', 'metrics'])
    def test_with_token_is_200(self, name):
        from kremle_detect.integrations.asgi_ext import KremleASGI

        core = KremleASGI(secret='test', categories=['math'], question_count=3,
                          max_errors=1, ops_token=TOKEN)
        response, _ = self._call(core, name, BEARER)
        assert response.status == 200


# ── Django ───────────────────────────────────────────────────────────────────

django = pytest.importorskip('django', reason='django not installed')

from django.conf import settings as dj_settings  # noqa: E402

if not dj_settings.configured:  # noqa: E402
    import tests.test_django_integration  # noqa: F401  — общая настройка settings

from django.test import RequestFactory, override_settings  # noqa: E402

from kremle_detect.integrations import django_ext  # noqa: E402


def django_view(name):
    urlconf_module = django_ext.kremle_urls()[0]
    return {p.name: p.callback for p in urlconf_module}[name]


def django_request(headers=None):
    factory = RequestFactory()
    meta = {key.upper().replace('-', '_'): value for key, value in (headers or {}).items()}
    meta = {f'HTTP_{key}' if key != 'REMOTE_ADDR' else key: value
            for key, value in meta.items()}
    request = factory.get('/kremle/health/', **meta)
    request.session = {}
    return request


class TestDjangoOpsToken:
    @pytest.mark.parametrize('name', ['kremle_health', 'kremle_stats', 'kremle_metrics'])
    def test_without_token_is_401(self, name):
        with override_settings(KREMLE_OPS_TOKEN=TOKEN):
            response = django_view(name)(django_request())
        assert response.status_code == 401
        assert OPS_UNAUTHORIZED['error'] in response.content.decode()
        assert response['WWW-Authenticate'] == 'Bearer'

    @pytest.mark.parametrize('name', ['kremle_health', 'kremle_stats', 'kremle_metrics'])
    def test_with_token_is_200(self, name):
        with override_settings(KREMLE_OPS_TOKEN=TOKEN):
            response = django_view(name)(django_request(BEARER))
        assert response.status_code == 200

    def test_without_setting_nothing_changes(self):
        with override_settings(KREMLE_OPS_TOKEN=None):
            assert django_view('kremle_stats')(django_request()).status_code == 200
