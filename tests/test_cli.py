# -*- coding: utf-8 -*-
"""
Тесты CLI (кроме вопросов — они в test_cli_questions.py).

CLI — то, чем реально пользуются в проде (блоклист, логи, диагностика),
поэтому покрываем и коды возврата, и цветной/бесцветный вывод.
"""

import sys

import pytest

from kremle_detect import cli
from kremle_detect.storage import MemoryStorage

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


def run(argv, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['kremle-detect'] + argv)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


def run_ok(argv, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['kremle-detect'] + argv)
    cli.main()


@pytest.fixture
def storage(monkeypatch):
    """Подменяем хранилище: CLI по умолчанию работал бы с Redis."""
    storage = MemoryStorage()
    monkeypatch.setattr(cli, '_get_storage', lambda args: storage)
    return storage


class TestCheckCommands:
    def test_check_ua_detected(self, monkeypatch, capsys):
        assert run(['check-ua', YANDEX_UA], monkeypatch) == 1
        out = capsys.readouterr().out
        assert 'DETECTED' in out
        assert 'Reason:  yandex_browser' in out
        assert 'Signals: browser' in out

    def test_check_ua_clean(self, monkeypatch, capsys):
        run_ok(['check-ua', NORMAL_UA], monkeypatch)
        assert 'clean' in capsys.readouterr().out

    def test_check_ua_all_signals(self, monkeypatch, capsys):
        run(['check-ua', 'YandexBot YaBrowser'], monkeypatch)
        out = capsys.readouterr().out
        assert 'bot' in out and 'browser' in out

    def test_check_ref(self, monkeypatch, capsys):
        assert run(['check-ref', 'https://yandex.ru/search?q=x'], monkeypatch) == 1
        assert 'Reason:  yandex_referrer' in capsys.readouterr().out

    def test_check_hints(self, monkeypatch, capsys):
        assert run(['check-hints', '"YaBrowser";v="24"'], monkeypatch) == 1
        assert 'yandex_client_hints' in capsys.readouterr().out

    def test_long_value_truncated(self, monkeypatch, capsys):
        run_ok(['check-ua', 'x' * 200], monkeypatch)
        line = [row for row in capsys.readouterr().out.splitlines()
                if row.startswith('User-Agent')][0]
        assert len(line) < 120

    def test_help(self, monkeypatch, capsys):
        run_ok(['help'], monkeypatch)
        out = capsys.readouterr().out
        assert 'kremle-detect' in out
        assert 'blacklist' in out
        assert 'questions check' in out


class TestBlacklist:
    def test_empty(self, storage, monkeypatch, capsys):
        run_ok(['blacklist', 'list'], monkeypatch)
        assert 'пуст' in capsys.readouterr().out.lower()

    def test_add_list_remove(self, storage, monkeypatch, capsys):
        run_ok(['blacklist', 'add', '1.2.3.4', '--ttl', '60'], monkeypatch)
        assert '1.2.3.4' in capsys.readouterr().out
        assert storage.blacklist_check('1.2.3.4') is True

        run_ok(['blacklist', 'list'], monkeypatch)
        assert '1.2.3.4' in capsys.readouterr().out

        run_ok(['blacklist', 'remove', '1.2.3.4'], monkeypatch)
        assert storage.blacklist_check('1.2.3.4') is False

    def test_add_forever(self, storage, monkeypatch, capsys):
        run_ok(['blacklist', 'add', '5.6.7.8', '--ttl', '0'], monkeypatch)
        run_ok(['blacklist', 'list'], monkeypatch)
        out = capsys.readouterr().out
        assert '5.6.7.8' in out
        assert 'навсегда' in out.lower()

    def test_add_without_ttl_uses_default(self, storage, monkeypatch, capsys):
        run_ok(['blacklist', 'add', '9.9.9.9'], monkeypatch)
        assert storage.blacklist_check('9.9.9.9') is True

    def test_remove_missing(self, storage, monkeypatch, capsys):
        assert run(['blacklist', 'remove', '9.9.9.9'], monkeypatch) == 1
        assert 'не найден' in capsys.readouterr().err.lower()

    def test_list_with_ttl(self, storage, monkeypatch, capsys):
        storage.blacklist_add('1.1.1.1', ttl=0)
        storage.blacklist_add('2.2.2.2', ttl=3600)
        run_ok(['blacklist', 'list'], monkeypatch)
        out = capsys.readouterr().out
        assert '1.1.1.1' in out and '2.2.2.2' in out


class TestWhitelist:
    def test_add_list_remove(self, storage, monkeypatch, capsys):
        run_ok(['whitelist', 'add', '10.0.0.1'], monkeypatch)
        assert storage.whitelist_check('10.0.0.1') is True

        run_ok(['whitelist', 'list'], monkeypatch)
        assert '10.0.0.1' in capsys.readouterr().out

        run_ok(['whitelist', 'remove', '10.0.0.1'], monkeypatch)
        assert storage.whitelist_check('10.0.0.1') is False

    def test_empty_list(self, storage, monkeypatch, capsys):
        run_ok(['whitelist', 'list'], monkeypatch)
        assert 'пуст' in capsys.readouterr().out.lower()

    def test_remove_missing(self, storage, monkeypatch, capsys):
        assert run(['whitelist', 'remove', '10.0.0.9'], monkeypatch) == 1
        assert 'не найден' in capsys.readouterr().err.lower()


class TestLogs:
    def test_no_events(self, storage, monkeypatch, capsys):
        run_ok(['logs'], monkeypatch)
        assert 'Событий нет' in capsys.readouterr().out

    def test_events_rendered(self, storage, monkeypatch, capsys):
        storage.log_event({'ts': 1700000000, 'event': 'detect',
                           'ip': '1.2.3.4', 'reason': 'yandex_browser'})
        storage.log_event({'ts': 1700000001, 'event': 'shadow',
                           'ip': '1.2.3.5', 'reason': 'yandex_referrer',
                           'action': 'monitor'})
        storage.log_event({'ts': 1700000002, 'event': 'pass',
                           'ip': '1.2.3.6', 'errors': 1, 'total': 5})
        storage.log_event({'ts': 1700000003, 'event': 'fail',
                           'ip': '1.2.3.7', 'errors': 4, 'total': 5})
        storage.log_event({'ts': 1700000004, 'event': 'blocked',
                           'ip': '1.2.3.8', 'reason': 'blacklisted'})

        run_ok(['logs', '--no-color', '-n', '10'], monkeypatch)
        out = capsys.readouterr().out
        assert 'ДЕТЕКТ' in out and 'ТЕНЬ' in out
        assert 'ПРОШЁЛ' in out and 'ПРОВАЛ' in out and 'ЗАБЛОК' in out
        assert 'действие: monitor' in out
        assert 'ошибок: 1/5' in out

    def test_limit(self, storage, monkeypatch, capsys):
        for i in range(5):
            storage.log_event({'ts': i, 'event': 'pass', 'ip': f'10.0.0.{i}'})
        run_ok(['logs', '-n', '2', '--no-color'], monkeypatch)
        assert len(capsys.readouterr().out.strip().splitlines()) == 2


class TestStorageSelection:
    def test_redis_url_from_flag(self, monkeypatch):
        captured = {}

        class FakeRedisStorage:
            def __init__(self, url=None, redis_client=None, prefix='kremle:'):
                captured['url'] = url

        monkeypatch.setattr('kremle_detect.storage.RedisStorage', FakeRedisStorage)
        cli._get_storage(type('A', (), {'redis': 'redis://localhost:6379/1'})())
        assert captured['url'] == 'redis://localhost:6379/1'

    def test_redis_url_from_env(self, monkeypatch):
        captured = {}

        class FakeRedisStorage:
            def __init__(self, url=None, redis_client=None, prefix='kremle:'):
                captured['url'] = url

        monkeypatch.setattr('kremle_detect.storage.RedisStorage', FakeRedisStorage)
        monkeypatch.setenv('KREMLE_REDIS_URL', 'redis://example.test:6379/2')
        cli._get_storage(type('A', (), {'redis': None})())
        assert captured['url'] == 'redis://example.test:6379/2'

    def test_memory_fallback(self, monkeypatch):
        monkeypatch.delenv('KREMLE_REDIS_URL', raising=False)
        from kremle_detect.storage import MemoryStorage as RealMemory
        assert isinstance(cli._get_storage(type('A', (), {'redis': None})()), RealMemory)


class TestArgParsing:
    def test_requires_command(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['kremle-detect'])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2

    def test_unknown_command(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['kremle-detect', 'nope'])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2

    def test_questions_help_lists_check(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['kremle-detect', 'questions', '--help'])
        with pytest.raises(SystemExit):
            cli.main()
        out = capsys.readouterr().out
        assert 'check' in out and 'sync' in out and 'cache' in out

    def test_version_flag(self, monkeypatch, capsys):
        from kremle_detect import __version__

        monkeypatch.setattr(sys, 'argv', ['kremle-detect', '--version'])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        assert __version__ in capsys.readouterr().out


class TestServe:
    """`kremle-detect serve` — демо; флаги картинок должны доезжать до приложения."""

    def test_flags_reach_demo(self, monkeypatch):
        from kremle_detect import demo

        calls = {}
        monkeypatch.setattr(demo, 'main', lambda **kwargs: calls.update(kwargs))
        run_ok(['serve', '--port', '8123', '--images', '--sample-image'], monkeypatch)

        assert calls['port'] == 8123
        assert calls['questions_images'] is True
        assert calls['sample_image'] is True

    def test_defaults_leave_env_in_charge(self, monkeypatch):
        from kremle_detect import demo

        calls = {}
        monkeypatch.setattr(demo, 'main', lambda **kwargs: calls.update(kwargs))
        run_ok(['serve'], monkeypatch)

        assert calls['questions_images'] is None
        assert calls['sample_image'] is None
