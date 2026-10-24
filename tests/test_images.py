# -*- coding: utf-8 -*-
"""Тесты локального кеша картинок и роутов /kremle/img/<key>."""

import os

import pytest

from kremle_detect import images
from kremle_detect.images import (
    KEY_RE, ImageError, cache_questions, clear, download_image, has_image,
    image_key, local_url, localize_image, read_image, rewrite_questions,
    stats, store_image,
)

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 32
URL = 'https://math-ege.sdamgia.ru/img/graph.png'


def fake_fetcher(payload=PNG, content_type='image/png', calls=None):
    def _get(url):
        if calls is not None:
            calls.append(url)
        return payload, content_type
    return _get


class TestKey:
    def test_key_is_stable_and_short(self):
        key = image_key(URL)
        assert KEY_RE.match(key)
        assert len(key) == 32
        assert key == image_key(URL)

    def test_different_urls_differ(self):
        assert image_key(URL) != image_key(URL + '?v=2')

    def test_local_url(self):
        assert local_url('abc') == '/kremle/img/abc'
        assert local_url('abc', '/media/kremle') == '/media/kremle/abc'


class TestStoreAndRead:
    def test_roundtrip(self, tmp_path):
        stored = store_image(URL, PNG, 'image/png', cache_dir=str(tmp_path))
        assert stored['size'] == len(PNG)
        assert has_image(URL, str(tmp_path))
        entry = read_image(stored['key'], str(tmp_path))
        assert entry['bytes'] == PNG
        assert entry['content_type'] == 'image/png'
        assert entry['url'] == URL

    def test_content_type_with_charset(self, tmp_path):
        stored = store_image(URL, PNG, 'image/png; charset=binary', str(tmp_path))
        assert read_image(stored['key'], str(tmp_path))['content_type'] == 'image/png'

    def test_sniff_when_type_missing_or_wrong(self, tmp_path):
        stored = store_image(URL, JPEG, 'application/octet-stream', str(tmp_path))
        assert read_image(stored['key'], str(tmp_path))['content_type'] == 'image/jpeg'

    def test_svg_without_type(self, tmp_path):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        stored = store_image(URL, svg, None, str(tmp_path))
        assert read_image(stored['key'], str(tmp_path))['content_type'] == 'image/svg+xml'

    def test_rejects_non_image(self, tmp_path):
        with pytest.raises(ImageError):
            store_image(URL, b'<html>not an image</html>', 'text/html', str(tmp_path))
        assert not has_image(URL, str(tmp_path))

    def test_rejects_too_large(self, tmp_path):
        with pytest.raises(ImageError):
            store_image(URL, PNG + b'x' * 100, 'image/png', str(tmp_path), max_bytes=10)
        assert not has_image(URL, str(tmp_path))

    def test_no_temp_files_left(self, tmp_path):
        store_image(URL, PNG, 'image/png', str(tmp_path))
        names = os.listdir(images.images_dir(str(tmp_path)))
        assert not [n for n in names if n.endswith('.tmp')]


class TestReadGuards:
    @pytest.mark.parametrize('key', ['', '../etc/passwd', 'x' * 32, '/etc/passwd',
                                     'ABC', '0' * 33])
    def test_bad_key_rejected(self, key, tmp_path):
        assert read_image(key, str(tmp_path)) is None

    def test_unknown_key_404(self, tmp_path):
        assert read_image('0' * 32, str(tmp_path)) is None

    def test_missing_meta_still_served(self, tmp_path):
        key = image_key(URL)
        os.makedirs(images.images_dir(str(tmp_path)), exist_ok=True)
        with open(os.path.join(images.images_dir(str(tmp_path)), key), 'wb') as f:
            f.write(PNG)
        entry = read_image(key, str(tmp_path))
        assert entry['content_type'] == 'image/png'

    def test_oversized_cached_file_not_served(self, tmp_path, monkeypatch):
        stored = store_image(URL, PNG, 'image/png', str(tmp_path))
        monkeypatch.setattr(images, 'MAX_IMAGE_BYTES', 4)
        assert read_image(stored['key'], str(tmp_path)) is None


class TestLocalize:
    def test_cached_url_replaced(self, tmp_path):
        store_image(URL, PNG, 'image/png', str(tmp_path))
        item = localize_image(URL, str(tmp_path))
        assert item['url'] == local_url(image_key(URL))
        assert item['remote_url'] == URL

    def test_not_cached_falls_back_to_remote(self, tmp_path):
        item = localize_image(URL, str(tmp_path))
        assert item['url'] == URL

    def test_empty_url(self, tmp_path):
        assert localize_image('', str(tmp_path)) is None

    def test_rewrite_questions_keeps_answers(self, tmp_path):
        store_image(URL, PNG, 'image/png', str(tmp_path))
        questions = [
            {'q': 'График?', 'opts': ['1', '2'], 'ans': 1,
             'images': [{'url': URL, 'alt': 'график'}]},
            {'q': 'Просто текст', 'opts': ['a', 'b'], 'ans': 0},
        ]
        result = rewrite_questions(questions, str(tmp_path))
        assert result[0]['ans'] == 1
        assert result[0]['images'][0]['url'] == local_url(image_key(URL))
        assert result[0]['images'][0]['alt'] == 'график'
        # без картинок — тот же объект, лишних копий нет
        assert result[1] is questions[1]
        # исходный вопрос не испорчен
        assert questions[0]['images'][0]['url'] == URL


class TestDownload:
    def test_downloads_and_caches(self, tmp_path):
        calls = []
        result = download_image(URL, str(tmp_path), get=fake_fetcher(calls=calls))
        assert result['cached'] is False
        assert calls == [URL]
        assert has_image(URL, str(tmp_path))

    def test_second_call_uses_cache(self, tmp_path):
        calls = []
        download_image(URL, str(tmp_path), get=fake_fetcher(calls=calls))
        result = download_image(URL, str(tmp_path), get=fake_fetcher(calls=calls))
        assert result['cached'] is True
        assert calls == [URL]

    def test_force_redownloads(self, tmp_path):
        calls = []
        download_image(URL, str(tmp_path), get=fake_fetcher(calls=calls))
        download_image(URL, str(tmp_path), get=fake_fetcher(calls=calls), force=True)
        assert len(calls) == 2

    def test_network_error_wrapped(self, tmp_path):
        def boom(url):
            raise OSError('нет сети')

        with pytest.raises(ImageError):
            download_image(URL, str(tmp_path), get=boom)

    def test_data_uri_skipped(self, tmp_path):
        with pytest.raises(ImageError):
            download_image('data:image/png;base64,AAAA', str(tmp_path), get=fake_fetcher())

    def test_too_large_response_rejected(self, tmp_path):
        with pytest.raises(ImageError):
            download_image(URL, str(tmp_path), get=fake_fetcher(PNG + b'x' * 100),
                           max_bytes=10)


class TestSsrfGuard:
    @pytest.mark.parametrize('url', [
        'file:///etc/passwd',
        'ftp://example.com/a.png',
        'http://127.0.0.1:8000/admin.png',
        'http://localhost/x.png',
        'http://169.254.169.254/latest/meta-data.png',
        'http://[::1]/x.png',
        'http://10.0.0.5/x.png',
    ])
    def test_internal_and_non_http_rejected(self, url, tmp_path):
        with pytest.raises(ImageError):
            download_image(url, str(tmp_path))

    def test_no_host(self, tmp_path):
        with pytest.raises(ImageError):
            download_image('http:///x.png', str(tmp_path))

    def test_allow_private_opt_in(self, tmp_path):
        result = download_image('http://127.0.0.1/x.png', str(tmp_path),
                                get=fake_fetcher(), allow_private=True)
        assert result['size'] == len(PNG)


class TestCacheQuestions:
    def test_counts(self, tmp_path):
        url2 = 'https://cdn.example.test/extra.png'
        questions = [
            {'images': [{'url': URL, 'alt': ''}, {'url': url2, 'alt': ''}]},
            {'images': [{'url': URL, 'alt': ''}]},          # дубль URL — из кеша
            {'images': [{'url': 'data:image/png;base64,AA', 'alt': ''}]},
            {'images': []},
            {'q': 'без картинок'},
        ]
        result = cache_questions(questions, str(tmp_path), get=fake_fetcher())
        assert result['total'] == 4
        assert result['cached'] == 2
        assert result['skipped'] == 2
        assert result['failed'] == []

    def test_failures_do_not_raise(self, tmp_path):
        def boom(url):
            raise OSError('timeout')

        result = cache_questions([{'images': [{'url': URL}]}], str(tmp_path), get=boom)
        assert result['cached'] == 0
        assert len(result['failed']) == 1
        assert 'timeout' in result['failed'][0]['error']

    def test_question_images_accepts_plain_strings(self):
        assert images.question_images({'images': ['a.png', 'a.png', 'b.png']}) == \
            ['a.png', 'b.png']


class TestMaintenance:
    def test_stats_and_clear(self, tmp_path):
        store_image(URL, PNG, 'image/png', str(tmp_path))
        store_image(URL + '?v=2', PNG, 'image/png', str(tmp_path))
        info = stats(str(tmp_path))
        assert info['count'] == 2
        assert info['bytes'] == 2 * len(PNG)
        assert clear(str(tmp_path)) == 4  # 2 файла + 2 метаданных
        assert stats(str(tmp_path))['count'] == 0

    def test_stats_on_missing_dir(self, tmp_path):
        assert stats(str(tmp_path / 'nope'))['count'] == 0
        assert clear(str(tmp_path / 'nope')) == 0


# ── интеграция: движок и роуты ───────────────────────────────────────────────

class TestEngineLocalization:
    def test_engine_uses_cached_images(self, tmp_path):
        from kremle_detect.captcha import CaptchaEngine

        store_image(URL, PNG, 'image/png', str(tmp_path))
        engine = CaptchaEngine(
            question_count=1, max_errors=0, secret='test',
            extra_questions=[
                {'q': 'График?', 'opts': ['1', '2'], 'ans': 0,
                 'images': [{'url': URL, 'alt': 'график'}]},
            ],
            only_extra=True, questions_images=True,
            images_cache_dir=str(tmp_path),
        )
        challenge = engine.create_challenge()
        image = challenge.safe_questions[0]['images'][0]
        assert image['url'] == local_url(image_key(URL))
        assert image['alt'] == 'график'
        assert image['remote_url'] == URL

    def test_engine_without_cache_keeps_hotlink(self, tmp_path):
        from kremle_detect.captcha import CaptchaEngine

        engine = CaptchaEngine(
            question_count=1, max_errors=0, secret='test',
            extra_questions=[
                {'q': 'График?', 'opts': ['1', '2'], 'ans': 0,
                 'images': [{'url': URL, 'alt': ''}]},
            ],
            only_extra=True, questions_images=True,
            images_cache_dir=str(tmp_path),
        )
        challenge = engine.create_challenge()
        image = challenge.safe_questions[0]['images'][0]
        assert image['url'] == URL
        assert 'remote_url' not in image

    def test_images_flag_off_hides_library_questions(self, tmp_path):
        """Без questions_images задания с рисунком из банка не попадают в капчу."""
        from kremle_detect.questions import get_questions
        from kremle_detect.questions.sdamgia import write_cache

        write_cache('math', [
            {'q': 'График?', 'opts': ['1', '2', '3', '4'], 'ans': 0,
             'images': [{'url': URL, 'alt': ''}]},
            {'q': 'Текст', 'opts': ['1', '2', '3', '4'], 'ans': 1},
        ], str(tmp_path))

        without = get_questions(categories=['math'], source='sdamgia',
                                cache_dir=str(tmp_path), shuffle=False)
        assert [q['q'] for q in without] == ['Текст']

        with_images = get_questions(categories=['math'], source='sdamgia',
                                    cache_dir=str(tmp_path), shuffle=False,
                                    allow_images=True)
        assert [q['q'] for q in with_images] == ['График?', 'Текст']


class TestFlaskRoute:
    def make_app(self, cache_dir):
        flask = pytest.importorskip('flask')
        from kremle_detect.integrations.flask_ext import KremleFlask

        app = flask.Flask(__name__)
        app.secret_key = 'test'
        KremleFlask(app, categories=['math'], question_count=2, max_errors=0,
                    secret='test', images_cache_dir=cache_dir,
                    challenge_rate_limit=0)
        return app

    def test_serves_cached_image(self, tmp_path):
        stored = store_image(URL, PNG, 'image/png', str(tmp_path))
        app = self.make_app(str(tmp_path))
        response = app.test_client().get(f'/kremle/img/{stored["key"]}')
        assert response.status_code == 200
        assert response.data == PNG
        assert response.headers['Content-Type'] == 'image/png'
        assert 'immutable' in response.headers['Cache-Control']
        assert response.headers['X-Content-Type-Options'] == 'nosniff'

    def test_unknown_key_is_404(self, tmp_path):
        app = self.make_app(str(tmp_path))
        assert app.test_client().get('/kremle/img/' + '0' * 32).status_code == 404

    def test_invalid_key_is_404(self, tmp_path):
        app = self.make_app(str(tmp_path))
        assert app.test_client().get('/kremle/img/not-a-key').status_code == 404


class TestFastapiRoute:
    def make_app(self, cache_dir):
        pytest.importorskip('fastapi')
        pytest.importorskip('httpx', reason='TestClient требует httpx')
        from fastapi import FastAPI
        from kremle_detect.integrations.fastapi_ext import KremleFastAPI

        app = FastAPI()
        KremleFastAPI(app, categories=['math'], question_count=2, max_errors=0,
                      secret='test', images_cache_dir=cache_dir,
                      challenge_rate_limit=0)
        return app

    def test_serves_cached_image(self, tmp_path):
        from starlette.testclient import TestClient

        stored = store_image(URL, PNG, 'image/png', str(tmp_path))
        app = self.make_app(str(tmp_path))
        response = TestClient(app).get(f'/kremle/img/{stored["key"]}')
        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers['content-type'] == 'image/png'

    def test_unknown_key_is_404(self, tmp_path):
        from starlette.testclient import TestClient

        app = self.make_app(str(tmp_path))
        assert TestClient(app).get('/kremle/img/' + '0' * 32).status_code == 404


class TestDjangoRoute:
    def test_serves_cached_image(self, tmp_path):
        django = pytest.importorskip('django')
        from django.conf import settings as dj_settings
        from django.test import override_settings

        if not dj_settings.configured:  # pragma: no cover - тесты django идут первыми
            pytest.skip('django settings не настроены')

        from django.test import RequestFactory
        from kremle_detect.integrations.django_ext import kremle_urls

        stored = store_image(URL, PNG, 'image/png', str(tmp_path))
        patterns = kremle_urls()[0]  # include() → (urlconf_module, app_name, namespace)
        view = next(p.callback for p in patterns if p.name == 'kremle_image')

        with override_settings(KREMLE_IMAGES_CACHE_DIR=str(tmp_path)):
            response = view(RequestFactory().get('/kremle/img/x'), key=stored['key'])
            assert response.status_code == 200
            assert response.content == PNG

            missing = view(RequestFactory().get('/kremle/img/y'), key='0' * 32)
            assert missing.status_code == 404


class TestRealHttp:
    """Скачивание по-настоящему: локальный сервер вместо портала."""

    @pytest.fixture
    def server(self):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/big.png':
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/png')
                    self.send_header('Content-Length', str(len(PNG) * 2))
                    self.end_headers()
                    self.wfile.write(PNG * 2)
                    return
                if self.path == '/missing.png':
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(PNG)))
                self.end_headers()
                self.wfile.write(PNG)

            def log_message(self, *args):  # тишина в выводе тестов
                pass

        httpd = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{httpd.server_port}'
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_downloads_from_server(self, server, tmp_path):
        result = download_image(f'{server}/graph.png', str(tmp_path), allow_private=True)
        assert result['content_type'] == 'image/png'
        assert read_image(result['key'], str(tmp_path))['bytes'] == PNG

    def test_http_error_wrapped(self, server, tmp_path):
        with pytest.raises(ImageError):
            download_image(f'{server}/missing.png', str(tmp_path), allow_private=True)

    def test_does_not_read_past_limit(self, server, tmp_path):
        with pytest.raises(ImageError):
            download_image(f'{server}/big.png', str(tmp_path), allow_private=True,
                           max_bytes=len(PNG) + 8)
