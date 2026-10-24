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
