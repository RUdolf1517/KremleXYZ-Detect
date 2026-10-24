# -*- coding: utf-8 -*-
"""Тесты Django-интеграции (раньше их не было вообще)."""

import json

import pytest

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

from django.core.exceptions import ImproperlyConfigured  # noqa: E402
from django.test import RequestFactory, override_settings  # noqa: E402

from kremle_detect.integrations import django_ext  # noqa: E402
from kremle_detect.storage import MemoryStorage  # noqa: E402

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def make_request(path='/secret', ua=NORMAL_UA, xff=None, remote='127.0.0.1', method='get'):
    factory = RequestFactory()
    kwargs = {'HTTP_USER_AGENT': ua, 'REMOTE_ADDR': remote}
    if xff:
        kwargs['HTTP_X_FORWARDED_FOR'] = xff
    request = getattr(factory, method)(path, **kwargs)
    request.session = {}  # вместо SessionStore — тестам хватает dict
    return request


def run_middleware(request):
    called = {}

    def get_response(req):
        called['ok'] = True
        return 'response'

    result = django_ext.KremleDjangoMiddleware(get_response)(request)
    return result, called


class TestMiddleware:
    def test_yandex_browser_redirected(self):
        result, called = run_middleware(make_request(ua=YANDEX_UA))
        assert not called
        assert result.status_code == 302
        assert '/kremle/challenge/' in result['Location']

    def test_normal_user_passes(self):
        result, called = run_middleware(make_request(ua=NORMAL_UA))
        assert called and result == 'response'

    def test_yandex_referer_redirected(self):
        request = make_request(ua=NORMAL_UA)
        request.META['HTTP_REFERER'] = 'https://yandex.ru/search?q=x'
        result, called = run_middleware(request)
        assert not called
        assert result.status_code == 302

    def test_skip_paths(self):
        result, called = run_middleware(make_request(path='/admin/', ua=YANDEX_UA))
        assert called

    def test_verified_session_passes(self):
        app, _ = make_request(), None
        app.session['kremle_ok'] = True
        result, called = run_middleware(app)
        assert called

    def test_whitelist(self):
        with override_settings(KREMLE_WHITELIST=['127.0.0.0/8']):
            result, called = run_middleware(make_request(ua=YANDEX_UA))
        assert called

    def test_spoofed_xff_does_not_whitelist(self):
        """X-Forwarded-For от недоверенного peer не должен обходить детекцию."""
        with override_settings(KREMLE_WHITELIST=['198.51.100.7'], KREMLE_TRUSTED_PROXIES=[]):
            result, called = run_middleware(
                make_request(ua=YANDEX_UA, xff='198.51.100.7', remote='203.0.113.5')
            )
        assert not called
        assert result.status_code == 302

    def test_xff_from_trusted_proxy_whitelists(self):
        with override_settings(
            KREMLE_WHITELIST=['198.51.100.7'],
            KREMLE_TRUSTED_PROXIES=['127.0.0.1'],
        ):
            result, called = run_middleware(
                make_request(ua=YANDEX_UA, xff='198.51.100.7', remote='127.0.0.1')
            )
        assert called

    def test_blacklisted_redirected(self):
        storage = MemoryStorage()
        storage.blacklist_add('203.0.113.5', ttl=3600)
        with override_settings(KREMLE_STORAGE=storage):
            result, called = run_middleware(
                make_request(ua=NORMAL_UA, remote='203.0.113.5')
            )
        assert not called
        assert result.status_code == 302

    def test_missing_session_middleware_raises_clear_error(self):
        request = make_request(ua=NORMAL_UA)
        del request.session
        with pytest.raises(ImproperlyConfigured, match='SessionMiddleware'):
            run_middleware(request)


class TestViews:
    @staticmethod
    def patterns():
        # kremle_urls() → include(...) → (urlconf_module, app_name, namespace)
        urlconf_module = django_ext.kremle_urls()[0]
        return {p.name: p.callback for p in urlconf_module}

    def test_urls_are_reversible(self):
        """Регрессия: список из 3 паттернов path() распаковывал как include-тройку."""
        from django.urls import resolve, reverse

        assert reverse('kremle_challenge') == '/kremle/challenge/'
        assert reverse('kremle_verify') == '/kremle/verify/'
        assert resolve('/kremle/status/').url_name == 'kremle_status'


    def test_challenge_html(self):
        view = self.patterns()['kremle_challenge']
        response = view(make_request(path='/kremle/challenge/'))
        assert response.status_code == 200
        body = response.content.decode()
        assert '"questions"' in body
        assert '"token"' in body
        assert response['Cache-Control'].startswith('no-store')

    def test_challenge_rate_limit(self):
        view = self.patterns()['kremle_challenge']
        with override_settings(KREMLE_CHALLENGE_RATE_LIMIT=1):
            assert view(make_request(path='/kremle/challenge/')).status_code == 200
            assert view(make_request(path='/kremle/challenge/')).status_code == 429

    def test_verify_correct(self):
        engine = django_ext._get_engine(dj_settings)
        views = self.patterns()
        challenge = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(challenge.questions)}

        request = make_request(path='/kremle/verify/', method='post')
        request._body = json.dumps({'token': challenge.token, 'answers': answers}).encode()
        response = views['kremle_verify'](request)
        assert response.status_code == 200
        assert json.loads(response.content)['passed'] is True

    def test_verify_broken_json(self):
        request = make_request(path='/kremle/verify/', method='post')
        request._body = b'not json'
        response = self.patterns()['kremle_verify'](request)
        assert response.status_code == 400

    def test_verify_json_array(self):
        request = make_request(path='/kremle/verify/', method='post')
        request._body = b'[1, 2, 3]'
        response = self.patterns()['kremle_verify'](request)
        assert response.status_code == 400

    def test_status(self):
        response = self.patterns()['kremle_status'](make_request(path='/kremle/status/'))
        assert json.loads(response.content) == {'verified': False}


class TestEngineCache:
    def test_settings_override_rebuilds_engine(self):
        """Раньше кеш по id(settings) не замечал изменения настроек."""
        with override_settings(KREMLE_QUESTION_COUNT=3, KREMLE_MAX_ERRORS=1):
            engine = django_ext._get_engine(dj_settings)
            assert engine.question_count == 3

        with override_settings(KREMLE_QUESTION_COUNT=7, KREMLE_MAX_ERRORS=2):
            engine = django_ext._get_engine(dj_settings)
            assert engine.question_count == 7
