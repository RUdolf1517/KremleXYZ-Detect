# -*- coding: utf-8 -*-
"""Тесты CLI-подкоманд работы с вопросами (show / sync / cache)."""

import sys

import pytest

from kremle_detect import cli
from kremle_detect.questions import sdamgia


def run_cli(argv, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['kremle-detect'] + argv)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


def run_cli_ok(argv, monkeypatch):
    """Команда без sys.exit()."""
    monkeypatch.setattr(sys, 'argv', ['kremle-detect'] + argv)
    cli.main()


class TestShow:
    def test_builtin_questions(self, monkeypatch, capsys):
        run_cli_ok(['questions', 'show', '-c', 'math', '-n', '2', '--source', 'builtin'],
                   monkeypatch)
        out = capsys.readouterr().out
        assert '[1] [math]' in out
        assert '[2] [math]' in out

    def test_legacy_flags(self, monkeypatch, capsys):
        run_cli_ok(['questions', '-c', 'math', '--count', '1'], monkeypatch)
        assert '[1] [math]' in capsys.readouterr().out

    def test_sdamgia_without_cache_exits_1(self, monkeypatch, capsys):
        assert run_cli(['questions', 'show', '-c', 'math', '--source', 'sdamgia'],
                       monkeypatch) == 1
        assert 'questions sync' in capsys.readouterr().err

    def test_shows_attribution(self, monkeypatch, capsys, tmp_path, write_sdamgia_cache):
        write_sdamgia_cache('math', count=3)
        monkeypatch.setenv('KREMLE_CACHE_DIR', str(tmp_path))
        run_cli_ok(['questions', 'show', '-c', 'math', '-n', '1'], monkeypatch)
        assert 'РешуЕГЭ' in capsys.readouterr().out


class TestSync:
    def test_dry_run_does_not_write(self, monkeypatch, capsys, tmp_path):
        html = ('<div class="prob_maindiv"><div class="pbody">Сколько будет 2+2?</div>'
                '<div class="answer">Ответ: 4</div></div>')
        monkeypatch.setattr(sdamgia, 'http_get', lambda url: html)

        run_cli_ok(['questions', 'sync', '-c', 'math', '-n', '1',
                    '--ids', '1001', '--cache-dir', str(tmp_path), '--dry-run'], monkeypatch)
        out = capsys.readouterr().out
        assert 'задания: 1001' in out
        assert '1 вопрос(ов) — кеш не записан' in out
        assert sdamgia.read_cache('math', str(tmp_path)) is None

    def test_sync_writes_cache(self, monkeypatch, capsys, tmp_path):
        html = ('<div class="prob_maindiv"><div class="pbody">Сколько будет 2+2?</div>'
                '<div class="answer">Ответ: 4</div></div>')
        monkeypatch.setattr(sdamgia, 'http_get', lambda url: html)

        run_cli_ok(['questions', 'sync', '-c', 'math', '-n', '2',
                    '--ids', '1001,1002', '--cache-dir', str(tmp_path)], monkeypatch)
        out = capsys.readouterr().out
        assert '2 вопрос(ов) записано в кеш' in out
        data = sdamgia.read_cache('math', str(tmp_path))
        assert len(data['questions']) == 2
        assert data['questions'][0]['source']['name'] == 'РешуЕГЭ'

    def test_sync_failure_exits_1(self, monkeypatch, capsys, tmp_path):
        def broken(url):
            from urllib.error import URLError
            raise URLError('offline')

        monkeypatch.setattr(sdamgia, 'http_get', broken)
        code = run_cli(['questions', 'sync', '-c', 'math', '-n', '1',
                        '--cache-dir', str(tmp_path)], monkeypatch)
        assert code == 1
        assert 'Ничего не скачано' in capsys.readouterr().err


class TestCacheCommand:
    def test_empty_cache(self, monkeypatch, capsys, tmp_path):
        run_cli_ok(['questions', 'cache', '--cache-dir', str(tmp_path)], monkeypatch)
        out = capsys.readouterr().out
        assert 'Кеш вопросов' in out
        assert 'пусто' in out

    def test_filled_cache(self, monkeypatch, capsys, tmp_path, write_sdamgia_cache):
        write_sdamgia_cache('math', count=3)
        run_cli_ok(['questions', 'cache', '--cache-dir', str(tmp_path)], monkeypatch)
        out = capsys.readouterr().out
        assert 'math' in out
        assert '3 вопрос' in out
        assert 'только что' in out


class TestCheck:
    """`questions check` — самая простая проверка задания и его картинок."""

    def _patch(self, monkeypatch, html):
        monkeypatch.setattr(sdamgia, 'http_get', lambda url: html)

    def test_plain_task_is_usable(self, monkeypatch, capsys, sdamgia_html):
        self._patch(monkeypatch, sdamgia_html)
        run_cli_ok(['questions', 'check', '1001'], monkeypatch)
        out = capsys.readouterr().out
        assert 'Картинок в условии: 0' in out
        assert 'В капчу пойдёт' in out
        assert 'Ответ:   0,95' in out

    def test_task_with_image_skipped_without_flag(self, monkeypatch, capsys,
                                                 sdamgia_html_with_image):
        self._patch(monkeypatch, sdamgia_html_with_image)
        code = run_cli(['questions', 'check', '1001'], monkeypatch)
        out = capsys.readouterr().out
        assert code == 3
        assert 'Картинок в условии: 2' in out
        assert 'есть картинка' in out

    def test_task_with_image_usable_with_flag(self, monkeypatch, capsys,
                                             sdamgia_html_with_image):
        self._patch(monkeypatch, sdamgia_html_with_image)
        run_cli_ok(['questions', 'check', '1001', '--images'], monkeypatch)
        out = capsys.readouterr().out
        assert 'В капчу пойдёт' in out
        assert 'img/graph.png' in out

    def test_json_output(self, monkeypatch, capsys, sdamgia_html_with_image):
        self._patch(monkeypatch, sdamgia_html_with_image)
        run_cli_ok(['questions', 'check', '1001', '--images', '--json'], monkeypatch)
        import json as _json
        data = _json.loads(capsys.readouterr().out)
        assert data['problem_id'] == '1001'
        assert len(data['images']) == 2
        # без --images задание с рисунком не годится для капчи
        assert data['usable'] is True
        assert data['question']['opts'][data['question']['ans']] == '3'

    def test_network_error(self, monkeypatch, capsys):
        def boom(url):
            raise OSError('network down')

        monkeypatch.setattr(sdamgia, 'http_get', boom)
        assert run_cli(['questions', 'check', '1'], monkeypatch) == 1
        assert 'Не удалось скачать' in capsys.readouterr().err

    def test_unparsable_page(self, monkeypatch, capsys):
        self._patch(monkeypatch, '<html><body>ничего</body></html>')
        assert run_cli(['questions', 'check', '1'], monkeypatch) == 2
        assert 'не разобрались' in capsys.readouterr().err

    def test_text_answer_not_usable(self, monkeypatch, capsys):
        html = ('<div class="prob_maindiv"><div class="pbody">Назовите город</div>'
                '<div class="answer">Ответ: Москва</div></div>')
        self._patch(monkeypatch, html)
        assert run_cli(['questions', 'check', '1'], monkeypatch) == 3
        assert 'В капчу НЕ пойдёт' in capsys.readouterr().out


class TestSyncImages:
    def test_sync_with_images_flag(self, monkeypatch, capsys, tmp_path,
                                   sdamgia_html_with_image):
        monkeypatch.setattr(sdamgia, 'http_get', lambda url: sdamgia_html_with_image)
        run_cli_ok(['questions', 'sync', '-c', 'math', '-n', '1', '--ids', '5',
                    '--images', '--cache-dir', str(tmp_path)], monkeypatch)
        data = sdamgia.read_cache('math', str(tmp_path))
        assert data['questions'][0]['images']

    def test_sync_without_flag_skips_images(self, monkeypatch, capsys, tmp_path,
                                            sdamgia_html_with_image):
        monkeypatch.setattr(sdamgia, 'http_get', lambda url: sdamgia_html_with_image)
        code = run_cli(['questions', 'sync', '-c', 'math', '-n', '1', '--ids', '5',
                        '--cache-dir', str(tmp_path)], monkeypatch)
        assert code == 1
        assert sdamgia.read_cache('math', str(tmp_path)) is None


class TestSyncDownloadImages:
    """`questions sync --download` — картинки в локальный кеш."""

    def _fake_download(self, monkeypatch, cache_dir):
        from kremle_detect import images

        calls = []

        def fake(url, **kwargs):
            calls.append(url)
            stored = images.store_image(url, b'\x89PNG\r\n\x1a\n' + b'\x00' * 8,
                                        'image/png', cache_dir=cache_dir)
            stored['cached'] = False
            return stored

        monkeypatch.setattr(images, 'download_image', fake)
        return calls

    def test_download_stores_images(self, monkeypatch, capsys, tmp_path,
                                    sdamgia_html_with_image):
        monkeypatch.setattr(sdamgia, 'http_get', lambda url: sdamgia_html_with_image)
        calls = self._fake_download(monkeypatch, str(tmp_path))

        run_cli_ok(['questions', 'sync', '-c', 'math', '-n', '1', '--ids', '5',
                    '--download', '--cache-dir', str(tmp_path)], monkeypatch)
        out = capsys.readouterr().out
        assert 'скачано: 2' in out
        assert len(calls) == 2
        # --download включает --images: задание с рисунком попало в кеш
        assert sdamgia.read_cache('math', str(tmp_path))['questions'][0]['images']

    def test_download_reports_failures_without_failing(self, monkeypatch, capsys,
                                                       tmp_path, sdamgia_html_with_image):
        from kremle_detect import images

        monkeypatch.setattr(sdamgia, 'http_get', lambda url: sdamgia_html_with_image)

        def boom(url, **kwargs):
            raise images.ImageError('404')

        monkeypatch.setattr(images, 'download_image', boom)
        run_cli_ok(['questions', 'sync', '-c', 'math', '-n', '1', '--ids', '5',
                    '--download', '--cache-dir', str(tmp_path)], monkeypatch)
        captured = capsys.readouterr()
        assert 'ошибок: 2' in captured.out
        assert '404' in captured.err

    def test_without_download_mentions_hotlinks(self, monkeypatch, capsys, tmp_path):
        html = ('<div class="prob_maindiv"><div class="pbody">Сколько будет 2+2?</div>'
                '<div class="answer">Ответ: 4</div></div>')
        monkeypatch.setattr(sdamgia, 'http_get', lambda url: html)
        run_cli_ok(['questions', 'sync', '-c', 'math', '-n', '1', '--ids', '1',
                    '--cache-dir', str(tmp_path)], monkeypatch)
        assert '--download' in capsys.readouterr().out


class TestCheckDownload:
    def test_download_prints_local_url(self, monkeypatch, capsys, tmp_path,
                                       sdamgia_html_with_image):
        from kremle_detect import images

        monkeypatch.setattr(sdamgia, 'http_get', lambda url: sdamgia_html_with_image)
        monkeypatch.setenv('KREMLE_CACHE_DIR', str(tmp_path))

        def fake(url, **kwargs):
            stored = images.store_image(url, b'\x89PNG\r\n\x1a\n' + b'\x00' * 8,
                                        'image/png', cache_dir=str(tmp_path))
            stored['cached'] = False
            return stored

        monkeypatch.setattr(images, 'download_image', fake)
        run_cli_ok(['questions', 'check', '5', '--download'], monkeypatch)
        out = capsys.readouterr().out
        assert '/kremle/img/' in out
        assert images.stats(str(tmp_path))['count'] == 2

    def test_json_reports_cached_images(self, monkeypatch, capsys, tmp_path,
                                        sdamgia_html_with_image):
        import json as jsonlib

        from kremle_detect import images

        monkeypatch.setattr(sdamgia, 'http_get', lambda url: sdamgia_html_with_image)
        monkeypatch.setenv('KREMLE_CACHE_DIR', str(tmp_path))

        def fake(url, **kwargs):
            stored = images.store_image(url, b'\x89PNG\r\n\x1a\n' + b'\x00' * 8,
                                        'image/png', cache_dir=str(tmp_path))
            stored['cached'] = False
            return stored

        monkeypatch.setattr(images, 'download_image', fake)
        run_cli_ok(['questions', 'check', '5', '--download', '--json'], monkeypatch)
        payload = jsonlib.loads(capsys.readouterr().out)
        assert payload['usable'] is True
        assert all(item['ok'] for item in payload['images_cached'])


class TestImagesCommand:
    """`questions images` — размер и чистка кеша рисунков."""

    def _store(self, tmp_path, name):
        from kremle_detect import images

        return images.store_image(f'https://cdn.example.test/{name}.png',
                                  b'\x89PNG\r\n\x1a\n' + b'\x00' * 64,
                                  'image/png', cache_dir=str(tmp_path))

    def test_empty(self, monkeypatch, capsys, tmp_path):
        run_cli_ok(['questions', 'images', '--cache-dir', str(tmp_path)], monkeypatch)
        out = capsys.readouterr().out
        assert 'пусто' in out
        assert '--download' in out

    def test_stats(self, monkeypatch, capsys, tmp_path):
        self._store(tmp_path, 'a')
        run_cli_ok(['questions', 'images', '--cache-dir', str(tmp_path)], monkeypatch)
        out = capsys.readouterr().out
        assert '1 файл(ов)' in out

    def test_clear(self, monkeypatch, capsys, tmp_path):
        from kremle_detect import images

        self._store(tmp_path, 'a')
        run_cli_ok(['questions', 'images', '--cache-dir', str(tmp_path), '--clear'],
                   monkeypatch)
        assert 'очищен' in capsys.readouterr().out
        assert images.stats(str(tmp_path))['count'] == 0

    def test_prune_zero(self, monkeypatch, capsys, tmp_path):
        from kremle_detect import images

        self._store(tmp_path, 'a')
        self._store(tmp_path, 'b')
        run_cli_ok(['questions', 'images', '--cache-dir', str(tmp_path), '--prune', '0'],
                   monkeypatch)
        out = capsys.readouterr().out
        assert 'Удалено 2 старых рисунков' in out
        assert images.stats(str(tmp_path))['count'] == 0

    def test_prune_nothing_to_do(self, monkeypatch, capsys, tmp_path):
        self._store(tmp_path, 'a')
        run_cli_ok(['questions', 'images', '--cache-dir', str(tmp_path), '--prune', '64'],
                   monkeypatch)
        assert 'Чистить нечего' in capsys.readouterr().out

    def test_prune_and_clear_are_exclusive(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, 'argv', ['kremle-detect', 'questions', 'images',
                                          '--prune', '1', '--clear'])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
