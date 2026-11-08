# -*- coding: utf-8 -*-
"""Края FastAPI-интеграции: whitelist, block/monitor, флаги, шаблон.

Эти ветки не встречаются в «счастливом пути», и раньше их не проверял никто.
Гейт покрытия по модулям (`fastapi_ext.py` ≥ 90 %) держит их на виду: если
ветка отвалится при рефакторинге, тест покраснеет, а не тихо умрёт.
"""

import pytest

pytest.importorskip('fastapi', reason='fastapi not installed')
pytest.importorskip('httpx', reason='httpx not installed (нужен TestClient)')

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from kremle_detect.integrations.fastapi_ext import KremleFastAPI, _storage_name  # noqa: E402
from kremle_detect.storage import MemoryStorage, RedisStorage  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
CHROME_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def make_app(**kwargs):
    app = FastAPI()
    params = dict(secret='test', question_count=3, max_errors=1,
                  challenge_rate_limit=0, rate_limit=0)
    params.update(kwargs)
    # как в демо: расширение кладём в state, чтобы тест видел движок
    app.state.kremle = KremleFastAPI(app, **params)

    @app.get('/')
    async def index():
        return {'ok': True}

    return app


def client_for(app, peer='127.0.0.1'):
    """Клиент с известным peer-адресом: иначе IP-логику не проверить.

    Заголовки передаём в каждом запросе: у клиента Starlette свой
    ``user-agent: testclient``, и смешивать их — значит проверять не то.
    """
    return TestClient(app, follow_redirects=False, client=(peer, 50000))


class TestWhitelistAndBlocklist:
    def test_whitelisted_ip_skips_the_guard(self):
        app = make_app(whitelist=['127.0.0.1'])
        response = client_for(app).get('/', headers={'User-Agent': YANDEX_UA})
        assert response.status_code == 200

    def test_persistent_whitelist_skips_the_guard(self):
        storage = MemoryStorage()
        storage.whitelist_add('127.0.0.1')
        app = make_app(storage=storage)
        response = client_for(app).get('/', headers={'User-Agent': YANDEX_UA})
        assert response.status_code == 200

    def test_blacklisted_ip_gets_plain_text_for_browsers(self):
        storage = MemoryStorage()
        storage.blacklist_add('127.0.0.1', ttl=3600)
        app = make_app(storage=storage)
        response = client_for(app).get('/', headers={'User-Agent': CHROME_UA})
        assert response.status_code == 403
        assert 'заблокирован' in response.text


class TestPolicyActions:
    def test_monitor_lets_the_request_through(self):
        app = make_app(policy={'yandex_browser': 'monitor'})
        assert client_for(app).get('/', headers={'User-Agent': YANDEX_UA}).status_code == 200

    def test_block_returns_text_for_browsers(self):
        app = make_app(policy={'yandex_browser': 'block'})
        response = client_for(app).get('/', headers={'User-Agent': YANDEX_UA})
        assert response.status_code == 403
        assert 'заблокирован' in response.text

    def test_block_returns_json_for_api_clients(self):
        app = make_app(policy={'yandex_browser': 'block'})
        response = client_for(app).get('/', headers={'User-Agent': YANDEX_UA,
                                                     'Accept': 'application/json'})
        assert response.status_code == 403
        assert response.json()['error'] == 'blocked'


class TestFlags:
    def test_json_api_false_keeps_redirects_for_fetch(self):
        app = make_app(json_api=False)
        response = client_for(app).get('/', headers={'User-Agent': YANDEX_UA,
                                                     'Accept': 'application/json'})
        assert response.status_code == 302
        assert response.headers['location'].endswith('/kremle/challenge')

    def test_async_offload_false_runs_inline(self):
        app = make_app(async_offload=False)
        client = client_for(app)
        response = client.get('/', headers={'User-Agent': CHROME_UA,
                                            'Referer': 'https://yandex.ru/search/?text=x'})
        assert response.status_code == 302
        # второй заход без сигнала: долг капчи всё равно держит
        assert client.get('/', headers={'User-Agent': CHROME_UA}).status_code == 302

    def test_headless_always_answers_json(self):
        app = make_app(headless=True)
        response = client_for(app).get('/', headers={'User-Agent': YANDEX_UA})
        assert response.status_code == 403
        assert response.json()['error'] == 'captcha_required'


class TestStorageName:
    def test_known_backends(self):
        assert _storage_name(MemoryStorage()) == 'memory'
        assert _storage_name(RedisStorage(redis_client=object())) == 'redis'

    def test_custom_backend_falls_back_to_class_name(self):
        from kremle_detect.storage import BaseStorage

        class MyStorage(BaseStorage):
            def set(self, key, value, ttl=None):
                pass

            def get(self, key):
                return None

            def delete(self, key):
                pass

            def increment(self, key, ttl=None):
                return 1

        assert _storage_name(MyStorage()) == 'MyStorage'


class TestVerificationRecord:
    def test_stale_record_is_dropped_not_kept(self):
        """Привязка не сошлась — отметку выбрасываем, а не храним до срока.

        Иначе `bind_ua`/`bind_ip` были бы бесполезны: неверная отметка
        оставалась бы в сессии и могла «ожить», если UA вернут обратно.
        """
        app = make_app(bind_ua=True)
        engine = app.state.kremle.engine
        client = client_for(app)

        challenge = client.get('/kremle/challenge', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json'}).json()
        stored = engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
        client.post('/kremle/verify', json={'token': challenge['token'],
                                            'answers': answers},
                    headers={'User-Agent': YANDEX_UA})
        assert client.get('/kremle/status', headers={
            'User-Agent': YANDEX_UA}).json()['verified'] is True

        # UA сменился — guard видит несоответствие и стирает отметку
        client.get('/', headers={'User-Agent': CHROME_UA})
        assert client.get('/kremle/status', headers={
            'User-Agent': YANDEX_UA}).json()['verified'] is False

    def test_status_after_broken_record(self):
        app = make_app()
        engine = app.state.kremle.engine
        client = client_for(app)
        challenge = client.get('/kremle/challenge', headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json'}).json()
        stored = engine.get_challenge(challenge['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
        client.post('/kremle/verify', json={'token': challenge['token'],
                                            'answers': answers},
                    headers={'User-Agent': YANDEX_UA})
        assert client.get('/kremle/status',
                          headers={'User-Agent': YANDEX_UA}).json()['verified'] is True
        client.post('/kremle/logout')
        assert client.get('/kremle/status',
                          headers={'User-Agent': YANDEX_UA}).json()['verified'] is False


class TestCustomTemplate:
    def test_missing_template_is_an_explicit_error(self):
        app = make_app(template='/nonexistent/kremle-template.html')
        with pytest.raises(RuntimeError) as exc:
            client_for(app).get('/kremle/challenge',
                                headers={'User-Agent': YANDEX_UA, 'Accept': 'text/html'})
        assert 'шаблон' in str(exc.value)
