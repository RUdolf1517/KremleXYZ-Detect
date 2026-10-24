# -*- coding: utf-8 -*-
"""
Паритет Django-интеграции с Flask/FastAPI (2.7.0): JSON-гард, ops-роуты,
monitor-режим, TTL «пройдено» и logout.
"""

import json

import pytest

django = pytest.importorskip('django', reason='django not installed')

from django.conf import settings as dj_settings  # noqa: E402

if not dj_settings.configured:  # noqa: E402
    import tests.test_django_integration  # noqa: F401  — общая настройка settings

from django.test import RequestFactory, override_settings  # noqa: E402

from kremle_detect.integrations import django_ext  # noqa: E402
from kremle_detect.storage import MemoryStorage  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def make_request(path='/secret', ua=NORMAL_UA, accept=None, xhr=False, method='get'):
    factory = RequestFactory()
    kwargs = {'HTTP_USER_AGENT': ua, 'REMOTE_ADDR': '203.0.113.5'}
    if accept:
        kwargs['HTTP_ACCEPT'] = accept
    if xhr:
        kwargs['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
    request = getattr(factory, method)(path, **kwargs)
    request.session = {}
    return request


def run_middleware(request):
    called = {}

    def get_response(req):
        called['ok'] = True
        return 'response'

    return django_ext.KremleDjangoMiddleware(get_response)(request), called


def views():
    urlconf_module = django_ext.kremle_urls()[0]
    return {p.name: p.callback for p in urlconf_module}


class TestJsonGuard:
    def test_accept_json_gets_403(self):
        result, called = run_middleware(make_request(ua=YANDEX_UA, accept='application/json'))
        assert not called
        assert result.status_code == 403
        body = json.loads(result.content)
        assert body['error'] == 'captcha_required'
        assert body['challenge_url'] == '/kremle/challenge'
        assert result['Cache-Control'].startswith('no-store')

    def test_xhr_gets_json(self):
        result, _ = run_middleware(make_request(ua=YANDEX_UA, xhr=True))
        assert result.status_code == 403
        assert json.loads(result.content)['error'] == 'captcha_required'

    def test_api_path_gets_json_without_accept(self):
        result, called = run_middleware(
            make_request(path='/api/orders', ua=YANDEX_UA, accept='text/html')
        )
        assert not called
        assert result.status_code == 403
        assert json.loads(result.content)['error'] == 'captcha_required'

    def test_html_redirect(self):
        result, _ = run_middleware(make_request(ua=YANDEX_UA, accept='text/html'))
        assert result.status_code == 302

    def test_headless_setting(self):
        with override_settings(KREMLE_HEADLESS=True):
            result, _ = run_middleware(make_request(ua=YANDEX_UA, accept='text/html'))
        assert result.status_code == 403
        assert json.loads(result.content)['error'] == 'captcha_required'

    def test_json_api_disabled(self):
        with override_settings(KREMLE_JSON_API=False):
            result, _ = run_middleware(make_request(ua=YANDEX_UA, accept='application/json'))
        assert result.status_code == 302


class TestMonitor:
    def test_monitor_passes(self):
        with override_settings(KREMLE_POLICY={'yandex_browser': 'monitor'}):
            result, called = run_middleware(make_request(ua=YANDEX_UA))
            assert called and result == 'response'
            stats = json.loads(views()['kremle_stats'](make_request('/kremle/stats/')).content)
        assert stats['actions']['monitor'] >= 1

    def test_sample_rate_zero_shadow(self):
        with override_settings(KREMLE_SAMPLE_RATE=0.0):
            result, called = run_middleware(make_request(ua=YANDEX_UA))
        assert called


class TestOps:
    def test_health(self):
        response = views()['kremle_health'](make_request('/kremle/health/'))
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body['status'] == 'ok'
        assert body['storage_ok'] is True

    def test_health_degraded(self):
        class Broken(MemoryStorage):
            def set(self, key, value, ttl):
                raise RuntimeError('down')

        with override_settings(KREMLE_STORAGE=Broken()):
            response = views()['kremle_health'](make_request('/kremle/health/'))
        assert response.status_code == 503
        assert json.loads(response.content)['status'] == 'degraded'

    def test_stats_and_metrics(self):
        run_middleware(make_request(ua=YANDEX_UA))
        stats_v = views()['kremle_stats']
        body = json.loads(stats_v(make_request('/kremle/stats/')).content)
        assert body['requests_total'] >= 1

        metrics = views()['kremle_metrics'](make_request('/kremle/metrics/'))
        assert b'kremle_requests_total' in metrics.content

    def test_ops_can_be_disabled(self):
        with override_settings(KREMLE_ENABLE_OPS_ROUTES=False):
            names = views().keys()
        assert 'kremle_health' not in names
        assert 'kremle_challenge' in names


class TestVerificationTtl:
    def test_legacy_true_flag_does_not_bypass(self):
        request = make_request(ua=YANDEX_UA)
        request.session['kremle_ok'] = True   # формат 2.6
        result, called = run_middleware(request)
        assert not called
        assert result.status_code == 302

    def test_verify_then_status_then_logout(self):
        v = views()
        challenge = v['kremle_challenge'](make_request('/kremle/challenge/',
                                                       accept='application/json'))
        data = json.loads(challenge.content)
        engine = django_ext._get_engine(dj_settings)
        ch = engine.get_challenge(data['token'])
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}

        request = make_request('/kremle/verify/', method='post')
        request._body = json.dumps({'token': data['token'], 'answers': answers}).encode()
        verify = v['kremle_verify'](request)
        assert json.loads(verify.content)['passed'] is True

        status_request = make_request(ua=YANDEX_UA)
        status_request.session = request.session
        status = json.loads(v['kremle_status'](status_request).content)
        assert status['verified'] is True
        assert status['expires_in'] > 0

        # сессия пройдена — Яндекс-UA пропускается
        verified_request = make_request(ua=YANDEX_UA)
        verified_request.session = request.session
        result, called = run_middleware(verified_request)
        assert called

        logout_request = make_request('/kremle/logout/', method='post')
        logout_request.session = request.session
        logout = v['kremle_logout'](logout_request)
        assert json.loads(logout.content)['verified'] is False

        after_request = make_request(ua=YANDEX_UA)
        after_request.session = request.session
        result, called = run_middleware(after_request)
        assert not called
        assert result.status_code == 302

    def test_challenge_json_payload_in_django(self):
        v = views()
        with override_settings(KREMLE_QUESTION_COUNT=3):
            response = v['kremle_challenge'](make_request('/kremle/challenge/',
                                                          accept='application/json'))
        body = json.loads(response.content)
        assert body['questions']
        assert 'ans' not in body['questions'][0]
        assert 'attribution' in body
