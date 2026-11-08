# -*- coding: utf-8 -*-
"""Базовое хранилище и его «умолчания», память с просрочкой, Redis без Redis.

Отдельный файл появился вместе с гейтом покрытия по модулям: `storage.py`
обязан держаться выше 90 %, а непокрытыми оставались как раз ветки, которые
в обычной жизни не выполняются — базовые заглушки, ленивая уборка мусора,
неудачный импорт redis и разбор его `TTL`-ответов (-2 «нет ключа»,
-1 «без срока», N секунд).
"""

import time

import pytest

from kremle_detect.storage import BaseStorage, MemoryStorage, RedisStorage


class TinyStorage(BaseStorage):
    """Свой бэкенд «на минимуме»: только обязательные методы.

    Так и должен выглядеть чужой storage — всё остальное библиотека обязана
    закрыть разумными умолчаниями, а не требовать ещё десять методов.
    """

    def __init__(self):
        self.data = {}

    def set(self, key, value, ttl=None):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)

    def increment(self, key, ttl=None):
        self.data[key] = {'count': self.data.get(key, {'count': 0})['count'] + 1}
        return self.data[key]['count']


class TestBaseDefaults:
    """Подкласс, который не переопределяет необязательное, получает умолчания."""

    def test_counter_and_lists_default_to_empty(self):
        storage = TinyStorage()
        assert storage.get_counter('nope') == 0
        assert storage.blacklist_list() == []
        assert storage.whitelist_list() == []

    def test_event_log_defaults_to_noop(self):
        storage = TinyStorage()
        storage.log_event({'event': 'detect'})     # не падает и ничего не пишет
        assert storage.log_get() == []

    def test_ttl_is_not_implemented_by_default(self):
        with pytest.raises(NotImplementedError):
            TinyStorage().ttl('key')


class TestMemoryTtl:
    def test_expired_key_is_removed_on_ttl_query(self):
        storage = MemoryStorage()
        # просроченную запись кладём мимо set(): тот убирает мусор сразу,
        # а нам нужен именно момент «ключ лежит, но уже мёртв»
        storage._data['key'] = ({'v': 1}, time.time() - 1)
        assert storage.ttl('key') is None
        assert 'key' not in storage._data

    def test_ttl_of_live_and_eternal_keys(self):
        storage = MemoryStorage()
        storage.set('live', {'v': 1}, ttl=60)
        storage.set('forever', {'v': 1}, ttl=None)
        assert 55 <= storage.ttl('live') <= 60
        assert storage.ttl('forever') == 0
        assert storage.ttl('missing') is None

    def test_cleanup_removes_expired_entries(self):
        storage = MemoryStorage()
        storage.set('old', {'v': 1}, ttl=-1)
        # уборка идёт не чаще раза в минуту — сдвигаем отметку в прошлое
        storage._last_cleanup = 0
        storage._cleanup()
        assert storage._data == {}
        assert storage._last_cleanup > 0


class FakeRedis:
    """Ровно те методы, которые нужны `RedisStorage` для проверки TTL."""

    def __init__(self, ttl_value):
        self.ttl_value = ttl_value
        self.calls = []

    def ttl(self, key):
        self.calls.append(key)
        return self.ttl_value


class TestRedisStorageConstruction:
    def test_client_can_be_passed_directly(self):
        client = FakeRedis(-2)
        storage = RedisStorage(redis_client=client)
        assert storage.ttl('missing') is None
        assert client.calls == ['kremle:missing']

    def test_url_creates_lazy_client(self):
        # клиент создаётся, но не соединяется: сети здесь не нужно
        storage = RedisStorage(url='redis://localhost:6379/15')
        assert storage._prefix == 'kremle:'

    def test_missing_redis_library_is_explained(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, 'redis', None)
        with pytest.raises(ImportError) as exc:
            RedisStorage(url='redis://localhost:6379/15')
        assert 'pip install redis' in str(exc.value)

    def test_no_url_and_no_client_is_an_error(self):
        with pytest.raises(ValueError):
            RedisStorage()


class TestRedisTtl:
    @pytest.mark.parametrize('raw, expected', [
        (-2, None),   # ключа нет
        (-1, 0),      # ключ бессрочный
        (42, 42),     # остаток в секундах
    ])
    def test_ttl_maps_redis_answers(self, raw, expected):
        assert RedisStorage(redis_client=FakeRedis(raw)).ttl('k') == expected

    def test_ttl_never_returns_stale_float(self):
        storage = RedisStorage(redis_client=FakeRedis(41.9))
        assert storage.ttl('k') == 41
        assert isinstance(storage.ttl('k'), int)
