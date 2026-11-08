# -*- coding: utf-8 -*-
"""Нагрузочный смоук: считает то, что обещает, и не врёт про хранилище.

Скрипт живёт вне пакета (``scripts/loadtest.py``), но именно он даёт цифры в
summary PR — поэтому его арифметика проверяется тестами, а не глазами.
"""

import importlib.util
import json
import os
import sys

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'scripts', 'loadtest.py',
)


def load_module():
    spec = importlib.util.spec_from_file_location('loadtest_script', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['loadtest_script'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def loadtest():
    return load_module()


class TestStats:
    def test_percentiles_and_rps(self, loadtest):
        stats = loadtest.Stats('тест')
        for seconds in (0.01, 0.02, 0.03, 0.04):
            stats.add(seconds, 200)
        stats.wall_time = 2.0

        assert stats.count == 4
        assert stats.percentile(0.5) == 0.03
        assert stats.percentile(0.95) == 0.04
        assert 'rps' in stats.report() or '→' in stats.report()

    def test_empty_stats_do_not_divide_by_zero(self, loadtest):
        stats = loadtest.Stats('пусто')
        assert stats.percentile(0.5) == 0.0
        assert 'нет данных' in stats.report()

    def test_errors_are_counted_by_zero_status(self, loadtest, monkeypatch):
        monkeypatch.setattr(loadtest, 'http', lambda *a, **kw: (0, 'нет сети'.encode()))
        stats = loadtest.run_workers('[t]', 4, 2, lambda: loadtest.http('GET', 'x')[0])
        assert stats.errors == 4


class TestWaitForServer:
    def test_dead_server_is_reported_not_measured(self, loadtest, monkeypatch, capsys):
        monkeypatch.setattr(loadtest, 'http', lambda *a, **kw: (0, b''))
        code = loadtest.main(['--url', 'http://127.0.0.1:1', '-n', '1',
                              '--health-timeout', '0.2'])
        assert code == 2
        assert 'не отвечает' in capsys.readouterr().err

    def test_closed_ops_routes_still_count_as_alive(self, loadtest, monkeypatch, tmp_path):
        """401 на /kremle/health — сервер жив, просто просит токен."""
        calls = {'n': 0}

        def fake_http(method, url, **kwargs):
            calls['n'] += 1
            if url.endswith('/kremle/health'):
                return 401, b'{}'
            return 200, b'{}'

        monkeypatch.setattr(loadtest, 'http', fake_http)
        out = tmp_path / 'summary.json'
        code = loadtest.main(['--url', 'http://127.0.0.1:9', '-n', '2', '--endpoint',
                              'normal', '--json-out', str(out), '--label', 'redis'])

        assert code == 0
        assert json.loads(out.read_text(encoding='utf-8'))['normal']['count'] == 2


class TestScenarios:
    def test_full_captcha_sends_token_and_answers(self, loadtest, monkeypatch):
        seen = {}

        def fake_http(method, url, data=None, **kwargs):
            if method == 'GET':
                return 200, json.dumps({
                    'token': 'tok', 'questions': [{'opts': ['a', 'b']}, {'opts': ['c']}],
                }).encode()
            seen.update(data)
            return 200, b'{"passed": false}'

        monkeypatch.setattr(loadtest, 'http', fake_http)
        assert loadtest.scenario_full_captcha('http://x')() == 200

        assert seen['token'] == 'tok'
        assert set(seen['answers']) == {'0', '1'}

    def test_bad_challenge_json_is_an_error(self, loadtest, monkeypatch):
        monkeypatch.setattr(loadtest, 'http', lambda *a, **kw: (200, 'не json'.encode()))
        assert loadtest.scenario_full_captcha('http://x')() == 0
