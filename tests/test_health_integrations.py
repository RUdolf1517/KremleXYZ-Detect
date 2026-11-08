# -*- coding: utf-8 -*-
"""`/kremle/health` одинаково рассказывает про вопросы во всех интеграциях.

Проверяем не «поле есть», а что интеграция действительно спрашивает движок:
кеш «Решу ЕГЭ» состарен, и health обязан сказать `degraded`, а не бодрое `ok`.
"""

import json
import time

import pytest

from kremle_detect.questions.sdamgia import cache_path, clear_cache_memo, write_cache

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'

CACHED = {
    'q': 'Сколько будет 2 + 2?',
    'opts': ['4', '5', '22', '0'],
    'ans': 0,
    'images': [],
}


@pytest.fixture
def aged_cache(tmp_path, monkeypatch):
    """Кеш «Решу ЕГЭ» возрастом 72 часа — старее порога в 48."""
    monkeypatch.setenv('KREMLE_CACHE_DIR', str(tmp_path))
    clear_cache_memo()
    write_cache('math', [CACHED], cache_dir=str(tmp_path))
    path = cache_path('math', cache_dir=str(tmp_path))
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    data['fetched_at'] = time.time() - 72 * 3600
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False)
    clear_cache_memo()
    yield tmp_path
    clear_cache_memo()


@pytest.fixture
def no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('KREMLE_CACHE_DIR', str(tmp_path))
    clear_cache_memo()
    yield tmp_path
    clear_cache_memo()


def check(body, status_code):
    """Общие ожидания для тела health."""
    assert body['questions']['stale'] is True
    assert body['questions']['reason'] == 'stale_cache'
    assert body['questions']['age_hours'] > 48
    assert body['status'] == 'degraded'
    assert body['reasons'] == ['questions:stale_cache']
    # хранилище здорово — значит это не 503
    assert body['storage_ok'] is True
    assert status_code == 200


class TestFlask:
    def test_stale_cache_degrades_health(self, aged_cache):
        flask = pytest.importorskip('flask')
        from kremle_detect.integrations.flask_ext import KremleFlask

        app = flask.Flask(__name__)
        app.secret_key = 'test'
        KremleFlask(app, categories=['math'], question_count=3, max_errors=1,
                    secret='test', questions_source='sdamgia')
        response = app.test_client().get('/kremle/health')
        check(response.get_json(), response.status_code)

    def test_own_source_stays_ok(self, no_cache):
        flask = pytest.importorskip('flask')
        from kremle_detect.integrations.flask_ext import KremleFlask

        app = flask.Flask(__name__)
        app.secret_key = 'test'
        KremleFlask(app, categories=['math'], question_count=3, max_errors=1,
                    secret='test', questions_source='own')
        body = app.test_client().get('/kremle/health').get_json()
        assert body['status'] == 'ok'
        assert body['questions']['source'] == 'own'
        assert body['questions']['count'] > 0


class TestFastAPI:
    def test_stale_cache_degrades_health(self, aged_cache):
        pytest.importorskip('fastapi')
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from kremle_detect.integrations.fastapi_ext import KremleFastAPI

        app = FastAPI()
        KremleFastAPI(app, categories=['math'], question_count=3, max_errors=1,
                      secret='test', questions_source='sdamgia')
        response = TestClient(app).get('/kremle/health')
        check(response.json(), response.status_code)


class TestStarlette:
    def test_stale_cache_degrades_health(self, aged_cache):
        pytest.importorskip('starlette')
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kremle_detect.integrations.asgi_ext import KremleStarlette

        app = Starlette()
        KremleStarlette(app, categories=['math'], question_count=3, max_errors=1,
                        secret='test', questions_source='sdamgia')
        response = TestClient(app).get('/kremle/health')
        check(response.json(), response.status_code)


class TestLitestar:
    def test_stale_cache_degrades_health(self, aged_cache):
        pytest.importorskip('litestar')
        from litestar import Litestar
        from litestar.stores.memory import MemoryStore
        from litestar.testing import TestClient

        from kremle_detect.integrations.asgi_ext import KremleLitestar

        kremle = KremleLitestar(categories=['math'], question_count=3, max_errors=1,
                                secret='test', questions_source='sdamgia')
        app = Litestar(route_handlers=list(kremle.route_handlers),
                       middleware=kremle.middleware,
                       stores={'sessions': MemoryStore()})
        with TestClient(app) as client:
            response = client.get('/kremle/health')
        check(response.json(), response.status_code)


class TestDjango:
    """Django-вьюха вызывается напрямую — как в tests/test_django_ops.py."""

    def test_stale_cache_degrades_health(self, aged_cache):
        pytest.importorskip('django')
        from django.conf import settings as dj_settings
        if not dj_settings.configured:
            import tests.test_django_integration  # noqa: F401 — общая настройка

        from django.test import RequestFactory, override_settings

        from kremle_detect.integrations import django_ext

        # вьюхи живут в замыкании kremle_urls(), по имени их и достаём
        view = {p.name: p.callback for p in django_ext.kremle_urls()[0]}['kremle_health']
        request = RequestFactory().get('/kremle/health/', HTTP_USER_AGENT=YANDEX_UA)
        request.session = {}
        with override_settings(KREMLE_QUESTIONS_SOURCE='sdamgia'):
            response = view(request)
        check(json.loads(response.content), response.status_code)
