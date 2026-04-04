# -*- coding: utf-8 -*-
"""
Тесты FastAPI headless-режима.

Проверяем, что при headless=True:
- middleware возвращает JSON 403 (не редирект) при детекции Яндекс-браузера
- GET /kremle/challenge возвращает JSON с вопросами (не HTML)
- POST /kremle/verify возвращает JSON с passed/errors/total
- обычный (не-Яндекс) запрос проходит насквозь

При headless=False (по умолчанию) — прежнее поведение с редиректом.
"""

import pytest

# Skip the entire module if fastapi is not installed (optional dependency)
pytest.importorskip('fastapi', reason='fastapi not installed')
pytest.importorskip('httpx', reason='httpx not installed (required by TestClient)')

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from kremle_detect.integrations.fastapi_ext import KremleFastAPI  # noqa: E402
from kremle_detect.storage import MemoryStorage  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36'


def make_app(headless: bool = True) -> FastAPI:
    app = FastAPI()
    storage = MemoryStorage()
    KremleFastAPI(
        app,
        secret='test-secret',
        storage=storage,
        headless=headless,
        question_count=3,
        max_errors=1,
    )

    @app.get('/protected')
    async def protected():
        return {'ok': True}

    return app


# ── Headless=True ─────────────────────────────────────────────────────────────

class TestHeadlessMiddleware:
    def setup_method(self):
        self.client = TestClient(make_app(headless=True), raise_server_exceptions=True)

    def test_yandex_browser_gets_json_403(self):
        """Яндекс-браузер → 403 JSON, не редирект."""
        r = self.client.get('/protected', headers={'User-Agent': YANDEX_UA}, follow_redirects=False)
        assert r.status_code == 403
        body = r.json()
        assert body['error'] == 'captcha_required'
        assert 'challenge_url' in body

    def test_yandex_referer_gets_json_403(self):
        """Реферер с Яндекса → 403 JSON."""
        r = self.client.get(
            '/protected',
            headers={'User-Agent': NORMAL_UA, 'Referer': 'https://yandex.ru/search?q=test'},
            follow_redirects=False,
        )
        assert r.status_code == 403
        body = r.json()
        assert body['error'] == 'captcha_required'

    def test_normal_user_passes_through(self):
        """Обычный пользователь проходит без капчи."""
        r = self.client.get('/protected', headers={'User-Agent': NORMAL_UA})
        assert r.status_code == 200
        assert r.json() == {'ok': True}

    def test_kremle_paths_not_intercepted(self):
        """/kremle/* не перехватывается middleware."""
        r = self.client.get('/kremle/challenge', headers={'User-Agent': YANDEX_UA})
        # Роут существует, middleware его пропускает — должен вернуть данные (не 403)
        assert r.status_code != 403

    def test_blacklisted_ip_gets_json_403(self):
        """Забаненный IP → 403 JSON с reason blacklisted."""
        storage = MemoryStorage()
        storage.blacklist_add('10.0.0.99', ttl=3600)

        app = FastAPI()
        KremleFastAPI(app, secret='test-secret', storage=storage, headless=True, question_count=3)

        @app.get('/protected')
        async def protected():
            return {'ok': True}

        client = TestClient(app)
        r = client.get(
            '/protected',
            headers={'User-Agent': NORMAL_UA, 'X-Forwarded-For': '10.0.0.99'},
        )
        assert r.status_code == 403
        body = r.json()
        assert body['error'] == 'captcha_required'
        assert body['reason'] == 'blacklisted'


class TestHeadlessChallenge:
    def setup_method(self):
        self.client = TestClient(make_app(headless=True), raise_server_exceptions=True)

    def test_challenge_returns_json(self):
        """GET /kremle/challenge в headless режиме → JSON."""
        r = self.client.get('/kremle/challenge')
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('application/json')
        body = r.json()
        assert 'questions' in body
        assert 'token' in body
        assert 'verify_url' in body
        assert isinstance(body['questions'], list)
        assert len(body['questions']) == 3

    def test_challenge_questions_have_no_answers(self):
        """Вопросы в challenge не содержат правильных ответов."""
        r = self.client.get('/kremle/challenge')
        for q in r.json()['questions']:
            assert 'ans' not in q
            assert 'q' in q
            assert 'opts' in q
            assert len(q['opts']) >= 2

    def test_verify_correct_answers(self):
        """Верные ответы → passed: true."""
        # Сначала создаём challenge через engine напрямую, чтобы знать ответы.
        # В headless-режиме клиент получает вопросы из /kremle/challenge
        # и отправляет ответы. Эмулируем полный flow.
        storage = MemoryStorage()
        app = FastAPI()
        KremleFastAPI(app, secret='test-secret', storage=storage,
                      headless=True, question_count=3, max_errors=0)
        client = TestClient(app)

        # Получаем challenge
        r = client.get('/kremle/challenge')
        assert r.status_code == 200
        data = r.json()
        token = data['token']

        # Правильные ответы — берём из storage (engine создал challenge с ответами)
        from kremle_detect.captcha import CaptchaEngine
        # challenge хранится в storage под ключом challenge:{token}
        ch_data = storage.get(f'challenge:{token}')
        assert ch_data is not None
        answers = {str(i): q['ans'] for i, q in enumerate(ch_data['questions'])}

        r2 = client.post('/kremle/verify', json={'token': token, 'answers': answers})
        assert r2.status_code == 200
        result = r2.json()
        assert result['passed'] is True
        assert result['errors'] == 0

    def test_verify_wrong_answers(self):
        """Неверные ответы → passed: false."""
        storage = MemoryStorage()
        app = FastAPI()
        KremleFastAPI(app, secret='test-secret', storage=storage,
                      headless=True, question_count=3, max_errors=0)
        client = TestClient(app)

        r = client.get('/kremle/challenge')
        token = r.json()['token']
        answers = {str(i): 99 for i in range(3)}

        r2 = client.post('/kremle/verify', json={'token': token, 'answers': answers})
        result = r2.json()
        assert result['passed'] is False
        assert result['errors'] == 3

    def test_status_endpoint(self):
        """GET /kremle/status → JSON с полем verified."""
        r = self.client.get('/kremle/status')
        assert r.status_code == 200
        body = r.json()
        assert 'verified' in body
        assert body['verified'] is False


# ── Headless=False (режим по умолчанию) ──────────────────────────────────────

class TestDefaultMode:
    def setup_method(self):
        self.client = TestClient(make_app(headless=False), raise_server_exceptions=False)

    def test_yandex_browser_gets_redirect(self):
        """В обычном режиме Яндекс-браузер получает редирект, не JSON."""
        r = self.client.get('/protected', headers={'User-Agent': YANDEX_UA}, follow_redirects=False)
        assert r.status_code == 302
        assert '/kremle/challenge' in r.headers.get('location', '')

    def test_challenge_returns_html(self):
        """В обычном режиме GET /kremle/challenge → HTML."""
        r = self.client.get('/kremle/challenge')
        assert r.status_code == 200
        assert 'text/html' in r.headers['content-type']
        assert b'<html' in r.content or b'<!DOCTYPE' in r.content or b'kremle' in r.content.lower()


# ── Сквозной headless flow ─────────────────────────────────────────────────────

class TestHeadlessFullFlow:
    """
    Полный headless flow:
    1. Яндекс-браузер → 403 {error: captcha_required}
    2. Фронт запрашивает GET /kremle/challenge → JSON вопросы
    3. Пользователь отвечает, фронт POST /kremle/verify → {passed: true}
    4. Повторный запрос к /protected — уже через сессию (verified=True)
    """

    def test_full_flow_correct(self):
        storage = MemoryStorage()
        app = FastAPI()
        KremleFastAPI(app, secret='headless-test', storage=storage,
                      headless=True, question_count=2, max_errors=0)

        @app.get('/protected')
        async def protected():
            return {'ok': True}

        client = TestClient(app, raise_server_exceptions=True)

        # Шаг 1: Яндекс-браузер блокируется
        r = client.get('/protected', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 403

        # Шаг 2: Получить вопросы
        r = client.get('/kremle/challenge')
        assert r.status_code == 200
        token = r.json()['token']

        # Шаг 3: Ответить правильно
        ch_data = storage.get(f'challenge:{token}')
        answers = {str(i): q['ans'] for i, q in enumerate(ch_data['questions'])}
        r = client.post('/kremle/verify', json={'token': token, 'answers': answers})
        assert r.json()['passed'] is True

        # Шаг 4: Теперь /protected доступен (сессия установлена)
        r = client.get('/protected', headers={'User-Agent': YANDEX_UA})
        assert r.status_code == 200
        assert r.json() == {'ok': True}
